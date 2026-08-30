from __future__ import annotations

import math
from datetime import date, timedelta

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.market_lab import router
from app.market_facts.registry import DatasetId
from app.services.market_lab import (
    build_etf_momentum,
    calculate_drawdown,
    calculate_pit,
    calculate_position,
    compute_dispersion,
    macro_dispersion_from_repo,
    monte_carlo,
    sector_flow_from_repo,
    sector_members_from_repo,
    sector_radar_from_repo,
)


def _etf_frame(symbol: str = "510300.SH", n: int = 70) -> pl.DataFrame:
    start = date(2026, 1, 1)
    closes = [100.0 + i for i in range(n)]
    return pl.DataFrame({
        "symbol": [symbol] * n,
        "date": [start + timedelta(days=i) for i in range(n)],
        "open": closes,
        "high": [v + 1 for v in closes],
        "low": [v - 1 for v in closes],
        "close": closes,
        "volume": [1000.0 + i * 10 for i in range(n)],
        "amount": [100_000.0 + i * 1000 for i in range(n)],
    })


def test_etf_momentum_exposes_reference_metrics_and_units() -> None:
    rows = build_etf_momentum({"510300.SH": _etf_frame()}, {"510300.SH": "沪深300ETF"})
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "沪深300ETF"
    assert row["return_1d_pct"] > 0
    assert row["return_50d_pct"] > row["return_5d_pct"]
    expected = (
        row["return_1d_pct"] * 0.4
        + row["return_5d_pct"] * 0.3
        + row["return_20d_pct"] * 0.2
        + row["return_50d_pct"] * 0.1
    )
    assert abs(row["weighted_momentum_pct"] - expected) < 1e-8
    assert row["slope_momentum_pct"] > 0
    assert row["volume_ratio_5_20"] > 1


def test_dispersion_matches_onchart_definition() -> None:
    result = compute_dispersion({"A": 1.0, "B": -1.0, "C": 0.0})
    assert abs(result["mean_pct"]) < 1e-12
    assert abs(result["dispersion"] - (2**0.5)) < 1e-12
    assert result["contributions"][0]["share"] == 0.5
    assert result["contributions"][-1]["share"] == 0.0


def test_position_calculator_uses_board_lots_and_risk_cap() -> None:
    result = calculate_position(
        balance=100_000, risk_pct=0.01, entry=10, stop=9, target=12
    )
    assert result["shares"] == 1000
    assert result["planned_loss"] == 1000
    assert result["capital_usage_pct"] == 10
    assert result["reward_risk"] == 2
    assert result["risk_level"] == "保守"
    assert result["stop_pct"] == 10
    assert result["warnings"] == []


def test_position_presets_match_onechart_b1_b2_modes() -> None:
    result = calculate_position(
        balance=100_000, risk_pct=0.01, entry=10, stop=9,
        mode="sensitive", trade_type="B2",
    )
    assert result["target_r"] == 3
    assert result["target_price"] == 13
    assert result["breakeven_r"] == 2
    assert result["breakeven_price"] == 12


def test_pit_and_drawdown_match_onechart_formulas() -> None:
    pit = calculate_pit(top=10, bottom=8, current=9)
    assert pit["target"] == 12
    assert pit["depth_pct"] == 20
    draw = calculate_drawdown(entry=10, stop=9, high=20, target_r=10, drawdown_pct=0.1)
    assert draw["actual_r"] == 10
    assert draw["draw_amount"] == 1
    assert draw["exit_price"] == 19
    assert draw["target_achieved"] is True


def test_monte_carlo_is_seeded_and_reports_drawdown() -> None:
    args = dict(
        balance=100_000, win_rate=0.55, win_r=1.5, loss_r=1.0,
        risk_pct=0.01, trades=50, paths=200, seed=7,
    )
    a = monte_carlo(**args)
    b = monte_carlo(**args)
    assert a == b
    assert a["kelly_pct"] > 0
    assert a["p50_final"] > 0
    assert 0 <= a["p95_max_drawdown_pct"] <= 100
    assert len(a["sample_paths"]) <= 12
    assert a["reverse"]["recommended_risk_pct"] > 0
    assert len(a["strategies"]) == 13
    assert {row["basis"] for row in a["strategies"]} == {"decision", "theory"}
    assert all(len(row["median_path"]) == args["trades"] + 1 for row in a["strategies"])
    assert a["distribution"]["bins"]


def test_monte_carlo_recommends_zero_risk_for_negative_expectancy() -> None:
    result = monte_carlo(
        balance=100_000, win_rate=0.3, win_r=1, loss_r=1,
        risk_pct=0.01, trades=30, paths=100, seed=3,
        target_return_pct=50, max_drawdown_pct=20, annual_trades=50,
    )
    assert result["expectancy_r"] < 0
    assert result["reverse"]["recommended_risk_pct"] == 0
    assert result["reverse"]["limiting_factor"] == "negative_expectancy"


def test_sector_radar_marks_ohlcv_flow_as_proxy() -> None:
    start = date(2026, 1, 1)
    rows = []
    for day in range(35):
        for symbol, industry, drift in (("A", "芯片", 0.6), ("B", "银行", -0.1)):
            close = 10 + day * drift / 10
            rows.append({
                "symbol": symbol, "industry": industry, "date": start + timedelta(days=day),
                "open": close - 0.1, "high": close + 0.2, "low": close - 0.2,
                "close": close, "amount": 1_000_000.0,
            })
    frame = pl.DataFrame(rows)

    class RadarRepo:
        def get_enriched_latest(self):
            latest = frame.filter(pl.col("date") == frame["date"].max())
            return latest, frame["date"].max()

        def get_enriched_range(self, start_date, end_date, symbols=None, columns=None):
            return frame.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

    result = sector_radar_from_repo(RadarRepo())
    assert result["available"] is True
    assert result["quality"] == "proxy"
    assert result["rows"][0]["rank"] == 1
    assert {row["sector"] for row in result["rows"]} == {"芯片", "银行"}


def test_sector_radar_matches_onechart_money_flow_ema_and_scores() -> None:
    start = date(2026, 1, 1)
    flow_by_sector = {
        "半导体": [100, 200, 300, 400, 500, 600],
        "银行": [50, 40, 30, 20, 10, 0],
        "煤炭": [-20, -40, -60, -80, -100, -120],
        "地产": [-100, -200, -300, -400, -500, -600],
    }
    records = []
    for index, (industry, flows) in enumerate(flow_by_sector.items()):
        for day, flow in enumerate(flows):
            records.append({
                "symbol": f"S{index}", "industry": industry,
                "date": start + timedelta(days=day), "close": 10 + day * (index + 1) / 100,
                "amount": 1_000.0, "main_net_inflow": float(flow),
            })
    frame = pl.DataFrame(records)

    class RadarRepo:
        def get_enriched_latest(self):
            latest_date = frame["date"].max()
            return frame.filter(pl.col("date") == latest_date), latest_date

        def get_enriched_range(self, start_date, end_date, symbols=None, columns=None):
            return frame.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

    result = sector_radar_from_repo(RadarRepo(), as_of=start + timedelta(days=5))
    semiconductor = next(row for row in result["rows"] if row["sector"] == "半导体")

    expected_ratio = 10.0
    expected_amount = 100.0
    for raw_ratio, raw_amount in zip([20, 30, 40, 50, 60], [200, 300, 400, 500, 600], strict=True):
        expected_ratio = 0.24 * raw_ratio + 0.76 * expected_ratio
        expected_amount = 0.22 * raw_amount + 0.78 * expected_amount

    assert result["available"] is True
    assert result["quality"] == "observed"
    assert result["as_of"] == "2026-01-06"
    assert result["available_dates"][-1] == "2026-01-06"
    assert result["universe_size"] == 4
    assert semiconductor["swing_ratio_pct"] == pytest.approx(expected_ratio)
    assert semiconductor["swing_amount_yuan"] == pytest.approx(expected_amount)
    assert semiconductor["swing_rank_pct"] == 100.0
    assert semiconductor["swing_score"] == pytest.approx(977.53)
    assert semiconductor["rank"] == semiconductor["swing_rank"]
    assert "swing_rank_change_1d" in semiconductor
    assert "swing_top_30d" in semiconductor
    assert result["rows"][-1]["swing_rank"] == 4
    assert result["rank_history"]["半导体"][-1]["swing_rank"] == 1


def test_macro_dispersion_uses_daily_industry_cross_section_and_seven_indices() -> None:
    start = date(2026, 2, 1)
    sector_returns = {
        "成长-电子-半导体": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        "价值-银行-股份制": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "周期-煤炭-焦煤": [-1.0, -1.5, -2.0, -2.5, -3.0, -3.5, -4.0],
    }
    records = []
    for index, (industry, returns) in enumerate(sector_returns.items()):
        close = 100.0
        records.append({"symbol": f"S{index}", "industry": industry, "date": start, "close": close})
        for day, daily_return in enumerate(returns, 1):
            close *= 1 + daily_return / 100
            records.append({
                "symbol": f"S{index}", "industry": industry,
                "date": start + timedelta(days=day), "close": close,
            })
    frame = pl.DataFrame(records)
    index_symbols = (
        "000001.SH", "399006.SZ", "000688.SH", "000016.SH",
        "000300.SH", "000852.SH", "932000.CSI",
    )

    class MacroRepo:
        def get_enriched_latest(self):
            latest_date = frame["date"].max()
            return frame.filter(pl.col("date") == latest_date), latest_date

        def get_enriched_range(self, start_date, end_date, symbols=None, columns=None):
            return frame.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

        def get_index_daily(self, symbol, start_date, end_date, columns=None):
            offset = index_symbols.index(symbol)
            return pl.DataFrame({
                "date": [start + timedelta(days=day) for day in range(8)],
                "close": [100.0 + offset + day for day in range(8)],
            })

    result = macro_dispersion_from_repo(MacroRepo())

    assert result["available"] is True
    assert result["window"] == "daily industry cross-section"
    assert result["industry_level"] == 2
    assert result["industry_count"] == 3
    assert result["dispersion"] == pytest.approx(math.sqrt(32), rel=1e-6)
    assert result["ma3"] == pytest.approx(
        sum(point["dispersion"] for point in result["history"][-3:]) / 3
    )
    assert result["zone"] == "低位趋同"
    assert len(result["indices"]) == 7
    assert all(series["points"][0]["normalized"] == 0 for series in result["indices"])
    assert set(result["contribution_windows"]) == {"1", "3", "5", "10"}
    assert result["contribution_windows"]["1"]["high"][0]["name"] in {"电子", "煤炭"}
    assert "同花顺二级" in result["basis"]
    assert "当前成分快照回看历史" in result["basis"]


def test_sector_flow_keeps_strongest_inflow_and_outflow_sides() -> None:
    end_date = date(2026, 8, 21)
    records = []
    for offset in range(3):
        trade_date = end_date - timedelta(days=2 - offset)
        for index in range(40):
            daily_flow = (35 - index) * 1_000_000.0
            records.append({
                "symbol": f"S{index:02d}",
                "industry": f"板块{index:02d}",
                "date": trade_date,
                "main_net_inflow": daily_flow,
            })
    frame = pl.DataFrame(records)

    class FlowRepo:
        def get_enriched_latest(self):
            return frame.filter(pl.col("date") == end_date), end_date

        def get_enriched_range(self, start_date, end_date, symbols=None, columns=None):
            return frame.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

    result = sector_flow_from_repo(FlowRepo())
    totals = {row["sector"]: row["total_flow_yuan"] for row in result["rows"]}

    assert len(result["rows"]) == 30
    assert totals["板块00"] == 105_000_000.0
    assert totals["板块39"] == -12_000_000.0
    assert any(value > 0 for value in totals.values())
    assert any(value < 0 for value in totals.values())


def test_sector_members_exposes_stock_level_evidence() -> None:
    latest = date(2026, 8, 21)
    frame = pl.DataFrame({
        "symbol": ["A", "A", "B", "B"],
        "name": ["甲", "甲", "乙", "乙"],
        "industry": ["电子", "电子", "电子", "电子"],
        "date": [latest - timedelta(days=1), latest] * 2,
        "close": [10.0, 11.0, 10.0, 9.0],
        "amount": [100.0, 120.0, 100.0, 80.0],
        "main_net_inflow": [0.0, 50.0, 0.0, -30.0],
    })

    class Repo:
        def get_enriched_latest(self):
            return frame.filter(pl.col("date") == latest), latest

        def get_enriched_range(self, start_date, end_date, symbols=None, columns=None):
            return frame.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

    result = sector_members_from_repo(Repo(), dimension="industry", sector="电子", as_of=latest)
    assert result["available"] is True
    assert result["member_count"] == 2
    assert result["metrics"]["return_pct"]["top"][0]["symbol"] == "A"
    assert result["metrics"]["main_net_amount"]["bottom"][0]["symbol"] == "B"


def test_sector_members_matches_industry_path_component() -> None:
    latest = date(2026, 8, 21)
    frame = pl.DataFrame({
        "symbol": ["A", "A", "B", "B"],
        "industry": ["信息技术-电子-半导体"] * 2 + ["金融-银行-股份制银行"] * 2,
        "date": [latest - timedelta(days=1), latest] * 2,
        "close": [10.0, 11.0, 10.0, 10.5],
    })

    class Repo:
        def get_enriched_latest(self):
            return frame.filter(pl.col("date") == latest), latest

        def get_enriched_range(self, start_date, end_date, symbols=None, columns=None):
            return frame.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

    result = sector_members_from_repo(
        Repo(), dimension="industry", sector="电子", as_of=latest,
    )

    assert result["available"] is True
    assert result["member_count"] == 1
    assert result["metrics"]["return_pct"]["top"][0]["symbol"] == "A"


def test_sector_flow_prefers_canonical_observed_facts() -> None:
    rows = pl.DataFrame({
        "trade_date": [date(2026, 8, 20), date(2026, 8, 21)],
        "sector_name": ["AI", "AI"],
        "dimension": ["industry", "industry"],
        "net_inflow_yi": [2.0, 3.0],
        "source": ["sector_fund_flow_s4", "sector_fund_flow_s4"],
        "is_fallback": [False, False],
    })

    class FactRepo:
        def available_dates(self, dataset_id):
            assert dataset_id == DatasetId.SECTOR_FLOW_DAILY
            return [date(2026, 8, 20), date(2026, 8, 21)]

        def get_range(self, dataset_id, start, end):
            assert dataset_id == DatasetId.SECTOR_FLOW_DAILY
            return rows.filter((pl.col("trade_date") >= start) & (pl.col("trade_date") <= end))

    class LegacyRepo:
        def get_enriched_latest(self):
            raise AssertionError("canonical facts should avoid proxy fallback")

    result = sector_flow_from_repo(LegacyRepo(), fact_repo=FactRepo())

    assert result["quality"] == "observed"
    assert result["basis"] == "sector_flow_daily.net_inflow_yi"
    assert result["rows"][0]["total_flow_yuan"] == 500_000_000.0


def test_sector_radar_prefers_canonical_observed_facts() -> None:
    rows = pl.DataFrame({
        "trade_date": [date(2026, 8, 20), date(2026, 8, 20), date(2026, 8, 21), date(2026, 8, 21)],
        "sector_name": ["AI", "Bank", "AI", "Bank"],
        "dimension": ["industry"] * 4,
        "net_inflow_yi": [2.0, -1.0, 3.0, -2.0],
        "amount_yi": [20.0, 20.0, 25.0, 25.0],
        "pct_chg": [1.0, -0.5, 2.0, -1.0],
        "source": ["sector_fund_flow_s4"] * 4,
        "is_fallback": [False] * 4,
    })

    class FactRepo:
        def available_dates(self, _dataset_id):
            return [date(2026, 8, 20), date(2026, 8, 21)]

        def get_range(self, _dataset_id, start, end):
            return rows.filter((pl.col("trade_date") >= start) & (pl.col("trade_date") <= end))

    class LegacyRepo:
        def get_enriched_latest(self):
            raise AssertionError("canonical facts should avoid proxy fallback")

    result = sector_radar_from_repo(LegacyRepo(), fact_repo=FactRepo())

    assert result["quality"] == "observed"
    assert result["basis"] == "sector_flow_daily.net_inflow_yi"
    assert result["as_of"] == "2026-08-21"
    assert result["rows"][0]["sector"] == "AI"


def test_dimension_map_cache_keeps_dataframe_and_count_contract(monkeypatch) -> None:
    import time

    from app.services import rps_rotation

    mapping = pl.DataFrame({"_sym_up": ["600519.SH"], "industry": ["白酒"]})
    monkeypatch.setitem(rps_rotation._map_cache, "industry", (mapping, 1))
    monkeypatch.setitem(rps_rotation._map_ts, "industry", time.time())
    cached, count = rps_rotation._load_concept_map_df(object(), "industry")
    assert isinstance(cached, pl.DataFrame)
    assert cached.equals(mapping)
    assert count == 1


class _Repo:
    def get_etf_instruments(self):
        return pl.DataFrame({"symbol": ["510300.SH"], "name": ["沪深300ETF"]})

    def get_etf_daily(self, symbol, start, end, columns=None):
        return _etf_frame(symbol)

    def get_enriched_latest(self):
        return pl.DataFrame(), None

    def get_enriched_range(self, start, end, symbols=None, columns=None):
        return pl.DataFrame()

    def get_index_daily(self, symbol, start, end, columns=None):
        return pl.DataFrame()


def test_market_lab_api_success_and_empty_states() -> None:
    app = FastAPI()
    app.state.repo = _Repo()
    app.include_router(router)
    client = TestClient(app)

    etf = client.get("/api/market-lab/etf-momentum").json()
    assert etf["available"] is True
    assert etf["unit"] == "percent"
    assert etf["rows"][0]["symbol"] == "510300.SH"

    sectors = client.get("/api/market-lab/sector-flow").json()
    assert sectors["available"] is False
    assert sectors["quality"] == "unavailable"
    radar = client.get("/api/market-lab/sector-radar").json()
    assert radar["available"] is False
    members = client.get("/api/market-lab/sector-members", params={"sector": "电子"}).json()
    assert members["available"] is False
    assert client.get(
        "/api/market-lab/sector-members", params={"sector": "A" * 121}
    ).status_code == 422
    assert client.get(
        "/api/market-lab/sector-members", params={"sector": "电子", "dimension": "invalid"}
    ).status_code == 422

    sim = client.post("/api/market-lab/simulate", json={
        "balance": 100_000, "win_rate": 0.55, "win_r": 1.5,
        "loss_r": 1, "risk_pct": 0.01, "trades": 30, "paths": 100, "seed": 9,
    })
    assert sim.status_code == 200
    assert sim.json()["paths"] == 100
    invalid_sim = client.post("/api/market-lab/simulate", json={
        "balance": 100_000, "win_rate": 0.55, "win_r": 1.5,
        "loss_r": 1, "risk_pct": 0.01, "trades": 30, "paths": 2_001,
    })
    assert invalid_sim.status_code == 422
    assert client.post("/api/market-lab/pit", json={"top": 10, "bottom": 8, "current": 9}).json()["target"] == 12
    assert client.post("/api/market-lab/drawdown", json={"entry": 10, "stop": 9, "high": 20}).json()["target_achieved"] is True
