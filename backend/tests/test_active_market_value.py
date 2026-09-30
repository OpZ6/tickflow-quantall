import math
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.kline import router as kline_router
from app.custom.amv import router
from app.indicators.active_market_value import (
    compute_active_market_value,
    compute_stock_amv,
    resolve_float_shares,
)
from app.services.active_market_value import analyze_active_market_value, list_sector_activity
from app.services.chart_data import ChartQuery, build_chart_response


def sample(n=180):
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(n)]
    rows = [{"symbol": s, "date": d, "raw_close": 10., "close": 5., "amount": 2e7,
             "float_shares": f, "share_basis": "historical_reconstructed"}
            for s, f in [("000001.SZ", 1e8), ("000002.SZ", 2e8)] for d in days]
    return pl.DataFrame(rows), days


def test_fixed_numeric_value_and_weighted_additive_aggregation():
    rows, days = sample()
    out = compute_active_market_value(rows, days, ["000001.SZ", "000002.SZ"], {})
    first = next(x for x in out["members"] if x["symbol"] == "000001.SZ")
    # Independent closed form for constant q=.02, H=8, KF=1.15, gamma=1.
    u = 1 - math.exp(-.023)
    retention = 2 ** (-1 / 8) * (1 - u)
    expected = u * (1 - retention ** len(days)) / (1 - retention)
    assert first["active_share_pct"] == pytest.approx(expected * 100)
    assert first["amv_yi"] == pytest.approx(expected * 10)
    assert out["latest"]["amv_yi"] == pytest.approx(sum(x["amv_yi"] for x in out["members"]))
    assert out["latest"]["active_share_pct"] == pytest.approx(out["latest"]["amv_yi"] / 30 * 100)
    assert out["latest"]["percentile_250"] is None
    assert out["covered_members"] == 2


def test_no_trade_decay_and_unknown_observation_are_distinct():
    rows, days = sample(180)
    rows = rows.with_columns(pl.when(pl.col("date") > days[-11]).then(0.).otherwise(pl.col("amount")).alias("amount"))
    out = compute_active_market_value(rows, days, ["000001.SZ"], {})
    assert out["series"][-1]["amv_yi"] / out["series"][-11]["amv_yi"] == pytest.approx(2 ** (-10 / 8))
    broken = rows.with_columns(pl.when(pl.col("date") == days[-2]).then(None).otherwise(pl.col("amount")).alias("amount"))
    out = compute_active_market_value(broken, days, ["000001.SZ"], {})
    assert out["status"] == "unavailable"
    assert out["latest"] is None


def test_state_is_bounded_even_with_multiple_cap_turnover():
    rows, days = sample()
    rows = rows.with_columns(pl.lit(1e12).alias("amount"))
    out = compute_active_market_value(rows, days, ["000001.SZ", "000002.SZ"], {})
    assert 0 <= out["latest"]["amv_yi"] <= out["latest"]["float_mv_yi"]
    assert all(0 <= x["active_share_pct"] <= 100 for x in out["members"])


def test_future_rows_ignored_and_missing_target_not_replaced():
    rows, days = sample()
    out = compute_active_market_value(rows, days[:100], ["000001.SZ"], {})
    trimmed = compute_active_market_value(rows.filter(pl.col("date") <= days[99]), days[:100], ["000001.SZ"], {})
    assert out == trimmed
    out = compute_active_market_value(rows.filter(pl.col("date") != days[-1]), days, ["000001.SZ"], {})
    assert out["status"] == "unavailable"


def test_fixed_cohort_excludes_missing_member_throughout_curve():
    rows, days = sample()
    rows = rows.filter(~((pl.col("symbol") == "000002.SZ") & (pl.col("date") == days[-10])))
    out = compute_active_market_value(rows, days, ["000001.SZ", "000002.SZ"], {})
    assert out["status"] == "partial"
    assert out["covered_members"] == 1
    assert all(x["float_mv_yi"] == 10 for x in out["series"])


def test_share_availability_announcement_and_latest_proxy():
    rows, days = sample(3)
    rows = rows.drop("float_shares", "share_basis")
    inst = pl.DataFrame({"symbol": ["000001.SZ", "000002.SZ"], "float_shares": [1e8, 2e8]})
    shares = pl.DataFrame({"symbol": ["000001.SZ"], "period_end": [days[0]],
                           "effective_date": [days[0]], "announce_date": [days[2]], "float_shares": [3e8]})
    resolved = resolve_float_shares(rows, inst, shares).filter(pl.col("symbol") == "000001.SZ")
    assert resolved["float_shares"].to_list() == [1e8, 1e8, 3e8]
    assert resolved["share_basis"].to_list() == ["latest_float_proxy", "latest_float_proxy", "historical_reconstructed"]
    no_dates = resolve_float_shares(rows, inst, shares.drop("announce_date", "effective_date"))
    assert no_dates.filter(pl.col("symbol") == "000001.SZ")["float_shares"].to_list() == [1e8] * 3


class Repo:
    def __init__(self, data_dir):
        self.store = SimpleNamespace(data_dir=data_dir)
        self.rows, self.days = sample()
        self.generation = "test-1"
        self.batch_calls = 0

    def get_matrix_data_generation(self, asset_type):
        return self.generation

    def latest_enriched_date(self, asset_type):
        return self.days[-1]

    def get_instruments(self):
        return pl.DataFrame({"symbol": ["000001.SZ", "000002.SZ"], "name": ["A", "B"], "float_shares": [1e8, 2e8]})

    def get_historical_shares(self):
        return pl.DataFrame()

    def get_daily_batch(self, symbols, start, end, columns=None):
        self.batch_calls += 1
        return self.rows.filter(pl.col("symbol").is_in(symbols) & pl.col("date").is_between(start, end)).drop("float_shares", "share_basis")

    def get_index_daily(self, symbol, *args, **kwargs):
        return pl.DataFrame({"date": self.days})


def test_sector_batch_shared_values_cache_and_invalidation(monkeypatch, tmp_path):
    repo = Repo(tmp_path)
    mapping = {"concept": {"000001": {"PCB", "芯片"}, "000002": {"PCB"}},
               "industry_level1": {"000001": {"电子"}, "000002": {"电子"}}}
    monkeypatch.setattr("app.services.active_market_value.load_security_memberships", lambda _: mapping)
    kernel_calls = []
    def kernel(observations, **kwargs):
        kernel_calls.append(1)
        return compute_stock_amv(observations, **kwargs)
    monkeypatch.setattr("app.indicators.active_market_value.compute_stock_amv", kernel)
    date = repo.days[-1]
    boards = list_sector_activity(repo, date)
    pcb = analyze_active_market_value(repo, date, [], sector="PCB")
    list_sector_activity(repo, date, dimension="industry_level1")
    assert len(kernel_calls) == 2  # Shared stocks are not recomputed for overlapping boards or pages.
    individual = analyze_active_market_value(repo, date, ["000001.SZ", "000002.SZ"])
    assert pcb["series"] == individual["series"]
    assert pcb["latest"] == individual["latest"]
    assert pcb["market_cap_coverage_pct"] == 100
    assert next(x for x in boards["rows"] if x["sector"] == "PCB")["latest"] == pcb["latest"]
    assert repo.batch_calls == 2  # One global read plus the explicit selected-member analysis.
    repo.generation = "test-2"
    list_sector_activity(repo, date)
    assert repo.batch_calls == 3
    mapping["concept"]["000002"].add("芯片")
    changed = list_sector_activity(repo, date)
    assert repo.batch_calls == 4
    assert next(x for x in changed["rows"] if x["sector"] == "芯片")["requested_members"] == 2
    repo.get_instruments = lambda: pl.DataFrame({"symbol": ["000001.SZ", "000002.SZ"],
        "name": ["A", "B"], "float_shares": [2e8, 2e8]})
    capital_changed = analyze_active_market_value(repo, date, [], sector="PCB")
    assert repo.batch_calls == 5
    assert capital_changed["latest"]["float_mv_yi"] == 40


def test_long_history_aggregated_percentile_and_target_cutoff(monkeypatch, tmp_path):
    repo = Repo(tmp_path)
    repo.rows, repo.days = sample(420)
    repo.rows = repo.rows.with_columns(((pl.col("date") - repo.days[0]).dt.total_days() + 1).cast(pl.Float64).mul(1e6).alias("amount"))
    monkeypatch.setattr("app.services.active_market_value.load_security_memberships", lambda _: {
        "concept": {"000001": {"PCB"}, "000002": {"PCB"}}})
    out = analyze_active_market_value(repo, repo.days[-1], [], sector="PCB")
    # Strictly increasing occupation: current observation is uniquely highest.
    assert out["latest"]["percentile_250"] == pytest.approx(99.8)
    past = analyze_active_market_value(repo, repo.days[380], [], sector="PCB")
    assert past["series"][-1]["date"] == repo.days[380].isoformat()
    assert past["latest"]["amv_yi"] < out["latest"]["amv_yi"]


def test_sector_coverage_missing_and_unmapped_never_filled(monkeypatch, tmp_path):
    repo = Repo(tmp_path)
    repo.rows = repo.rows.filter(~((pl.col("symbol") == "000002.SZ") & (pl.col("date") == repo.days[-10])))
    monkeypatch.setattr("app.services.active_market_value.load_security_memberships", lambda _: {
        "concept": {"000001": {"完整", "缺映射"}, "000002": {"完整"}, "999999": {"缺映射"}}})
    out = analyze_active_market_value(repo, repo.days[-1], [], sector="完整")
    assert out["covered_members"] == 1
    assert out["requested_members"] == 2
    assert out["market_cap_coverage_pct"] == pytest.approx(100 / 3)
    assert all(x["float_mv_yi"] == 10 for x in out["series"])
    missing = analyze_active_market_value(repo, repo.days[-1], [], sector="缺映射")
    assert missing["requested_members"] == 2
    assert missing["unmapped_members"] == 1
    assert missing["market_cap_coverage_pct"] is None
    assert missing["status"] == "partial"


def test_sector_api_default_date_and_classification(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.active_market_value.load_security_memberships", lambda _: {
        "concept": {"000001": {"PCB"}}, "industry_level2": {"000002": {"元件"}}})
    app = FastAPI()
    app.state.repo = Repo(tmp_path)
    app.include_router(router)
    with TestClient(app) as client:
        out = client.get("/api/amv/sectors")
        assert out.status_code == 200
        assert out.json()["trade_date"] == app.state.repo.days[-1].isoformat()
        assert out.json()["rows"][0]["sector"] == "PCB"
        out = client.get("/api/amv/sectors", params={"dimension": "industry_level2"})
        assert out.json()["rows"][0]["sector"] == "元件"
        assert client.get("/api/amv/sectors?dimension=industry").status_code == 422
        assert client.get("/api/amv/sectors?trade_date=bad").status_code == 422


def test_exact_sector_expansion_and_missing_mapping_error(monkeypatch):
    repo = Repo(Path(__file__).resolve().parents[2] / "data/amv-test-empty")
    monkeypatch.setattr("app.services.active_market_value.load_security_memberships", lambda _: {
        "concept": {"000001": {"PCB"}, "000002": {"PCB"}}})
    out = analyze_active_market_value(repo, repo.days[-1], ["000001.SZ"], sector="PCB")
    assert out["requested_members"] == 2
    assert out["scope"] == "sector_latest_mapping"
    with pytest.raises(ValueError):
        analyze_active_market_value(repo, repo.days[-1], ["000001.SZ"], sector="unknown")


def test_api_contract_input_validation_and_empty_result():
    app = FastAPI()
    app.state.repo = Repo(Path(__file__).resolve().parents[2] / "data/amv-test-empty")
    app.include_router(router)
    with TestClient(app) as client:
        good = client.post("/api/amv/analyze", json={"trade_date": "2026-04-20", "symbols": ["000001.SZ"]})
        assert good.status_code == 200
        assert good.json()["algorithm_version"] == "1amv-float-state-v2"
        assert good.json()["official_0amv_verified"] is False
        assert client.post("/api/amv/analyze", json={"trade_date": "2026-04-20"}).status_code == 422
        assert client.post("/api/amv/analyze", json={"trade_date": "2026-04-20", "symbols": ["../bad"]}).status_code == 422
        empty = client.post("/api/amv/analyze", json={"trade_date": "2026-04-20", "symbols": ["600000.SH"]})
        assert empty.status_code == 200
        assert empty.json()["status"] == "unavailable"


@pytest.mark.parametrize("p", [{"h": 8, "gamma": 1., "kf": 1.15}, {"h": 10, "gamma": 1.15, "kf": 1.}])
def test_literal_tdx_dma_agrees_with_shared_kernel(p):
    rows, _ = sample(420)
    data = rows.filter(pl.col("symbol") == "000001.SZ").with_row_index().with_columns(
        ((pl.col("index") % 21 + 1) * 1e6).alias("amount")).to_dicts()
    result = compute_stock_amv(data, params=p)
    state = None
    d = 2 ** (-1 / p["h"])
    for row, calculated in zip(data, result, strict=True):
        u = 1 - math.exp(-p["kf"] * row["amount"] / (row["raw_close"] * row["float_shares"]))
        w = 1 - d * (1 - u)
        x = u if state is None else u / w
        state = x if state is None else w * x + (1 - w) * state
        if calculated:
            assert calculated["active_share_pct"] == pytest.approx(state ** p["gamma"] * 100, abs=1e-12)


class ChartRepo(Repo):
    def __init__(self):
        super().__init__(Path(__file__).resolve().parents[2] / "data/amv-test-empty")
        self.rows, self.days = sample(600)
        self.rows = self.rows.filter(pl.col("symbol") == "000001.SZ").with_columns(
            pl.col("raw_close").alias("open"), (pl.col("raw_close") + 1).alias("high"),
            (pl.col("raw_close") - 1).alias("low"), pl.col("raw_close").alias("close"), pl.lit(10000.).alias("volume"))

    def get_raw_daily_asset(self, asset, symbol, start, end):
        return self.rows.filter(pl.col("date").is_between(start, end)).drop("raw_close", "float_shares", "share_basis")

    def get_daily_asset(self, *args, **kwargs):
        return pl.DataFrame()

    def get_adjustment_factors(self, *args):
        return pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [self.days[450]], "ex_factor": [2.]})

    def get_name_map(self, symbols):
        return {"000001.SZ": "A"}

    def resolve_asset_type(self, symbol):
        return "stock"


def test_chart_amv_adjustment_invariance_params_and_causal_percentile():
    repo = ChartRepo()
    def run(adjustment="none", params=None, end=None):
        return build_chart_response(repo, ChartQuery(symbol="000001.SZ", asset_type="stock", interval="1d",
            adjustment=adjustment, range_name="custom", start_date=repo.days[420], end_date=end or repo.days[-1],
            indicator_warmups=(("amv", 131), ("amvchg", 121), ("amvpct", 369)),
            indicator_params=params or {}))
    none, qfq, hfq = run(), run("qfq"), run("hfq")
    assert none["rows"][0]["close"] != qfq["rows"][0]["close"]
    assert hfq["rows"][-1]["close"] != none["rows"][-1]["close"]
    for key in ("amv_yi", "amv_ma10", "amv_bbi", "amvchg_pct", "amvpct_value"):
        assert [x[key] for x in none["rows"]] == [x[key] for x in qfq["rows"]] == [x[key] for x in hfq["rows"]]
    assert all(x["amvpct_value"] is not None for x in none["rows"])
    other = run(params={"amv": {"h": 10, "gamma": 1.15, "kf": 1}})
    assert other["rows"][-1]["amv_yi"] != none["rows"][-1]["amv_yi"]
    shorter = run(end=repo.days[480])
    assert shorter["rows"] == none["rows"][:len(shorter["rows"])]
    assert none["meta"]["indicator_metadata"]["amv"]["capital_basis"] == "ordinary_float"


def test_chart_api_rejects_bad_parameters_and_supports_presets():
    app = FastAPI()
    app.state.repo = ChartRepo()
    app.include_router(kline_router)
    with TestClient(app) as client:
        base = {"symbol": "000001.SZ", "indicator_warmups": "amv:131"}
        for bad in ('[]', '{"amv":{"kf":0}}', '{"amv":{"gamma":true}}', '{"amv":{"h":8.5}}', '{"amv":{"extra":1}}', '{"bogus":{}}'):
            assert client.get("/api/kline/chart", params={**base, "indicator_params": bad}).status_code == 422
        good = client.get("/api/kline/chart", params={**base, "end_date": "2027-08-23", "indicator_params": '{"amv":{"h":8,"gamma":1,"kf":1.15}}'})
        assert good.status_code == 200
        assert good.json()["meta"]["indicator_metadata"]["amv"]["parameters"]["kf"] == 1.15
