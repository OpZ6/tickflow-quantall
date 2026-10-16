from datetime import date, timedelta

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.market_lab import router
from app.services.market_lab import build_etf_momentum
from app.services.sector_research import concept_overlap, forward_outcomes, industry_daily


def test_overlap_reports_directional_coverage_and_never_merges_concepts():
    result = concept_overlap({"1": {"A", "B"}, "2": {"A", "B"}, "3": {"B", "C"}}, "A")
    row = next(r for r in result["rows"] if r["sector"] == "B")
    assert row["common_codes"] == ["1", "2"]
    assert row["coverage_pct"] == 100
    assert row["other_coverage_pct"] == pytest.approx(200 / 3)
    assert row["jaccard_pct"] == pytest.approx(200 / 3)
    assert result["concepts"] == ["A", "B", "C"]
    assert concept_overlap({}, "missing")["available"] is False


def test_industry_breadth_pressure_and_gaps():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(40)]
    rows = [{"symbol": symbol, "date": day, "close": 100 + direction * i,
             "high": 101 + direction * i, "low": 97 + direction * i, "amount": 100.0}
            for symbol, direction in [("000001.SZ", 1), ("000002.SZ", -1)] for i, day in enumerate(days)]
    mapping = {"000001": {"A"}, "000002": {"A"}}
    daily = industry_daily(pl.DataFrame(rows), mapping, days)
    last = daily.row(-1, named=True)
    assert last["breadth_pct"] == 50
    assert last["breadth_change_5d_pp"] == 0
    assert last["pressure_5d_pct"] == 50
    assert last["member_count"] == 2
    broken = [r for r in rows if not (r["symbol"] == "000002.SZ" and r["date"] == days[-3])]
    last = industry_daily(pl.DataFrame(broken), mapping, days).row(-1, named=True)
    assert last["breadth_change_5d_pp"] is None
    assert last["pressure_5d_pct"] is None
    invalid = pl.DataFrame(rows).with_columns(
        pl.when((pl.col("symbol") == "000002.SZ") & (pl.col("date") == days[-1]))
        .then(float("nan")).otherwise(pl.col("amount")).alias("amount"))
    assert industry_daily(invalid, mapping, days).row(-1, named=True)["pressure_5d_pct"] is None


def test_forward_outcomes_compound_exact_future_sessions_and_exclude_missing():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(5)]
    frame = pl.DataFrame([{"sector": "A", "date": day, "return": .1, "market_return": .02,
                           "return_members": 1, "member_count": 1, "breadth_pct": 70.,
                           "breadth_change_5d_pp": 10.} for day in days])
    result = forward_outcomes(frame, days, 3)
    assert result["matured_count"] == 2
    assert result["pending_count"] == 3
    row = result["sectors"][0]
    assert row["median_return_pct"] == pytest.approx((1.1 ** 3 - 1) * 100)
    assert row["mean_excess_pct"] == pytest.approx((1.1 ** 3 - 1.02 ** 3) * 100)
    gap = forward_outcomes(frame.filter(pl.col("date") != days[2]), days, 3)
    assert gap["matured_count"] == 0
    assert gap["missing_count"] == 2
    assert forward_outcomes(frame, days, 10)["matured_count"] == 0


def test_research_api_routes_validate_and_delegate(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.repo = object()
    monkeypatch.setattr("app.api.market_lab.sector_research", lambda *args: {"available": True, "horizon": args[3]})
    monkeypatch.setattr("app.api.market_lab.concept_overlap_from_repo", lambda *args: {"available": False})
    client = TestClient(app)
    assert client.get("/api/market-lab/sector-research?horizon=3").json()["horizon"] == 3
    assert client.get("/api/market-lab/sector-research?horizon=2").status_code == 422
    assert client.get("/api/market-lab/sector-research?dimension=concept").status_code == 422
    assert client.get("/api/market-lab/concept-overlap").json()["available"] is False
    assert client.get("/api/market-lab/concept-overlap?limit=100").status_code == 422
    assert client.get("/api/market-lab/etf-momentum?symbols=oops").status_code == 422


def test_etf_previous_values_and_missing_close_preserve_date_alignment():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    frame = pl.DataFrame({"date": days, "close": [100. + i for i in range(60)], "volume": [100.] * 60})
    row = build_etf_momentum({"510300.SH": frame})[0]
    assert row["momentum_change_pct"] == pytest.approx(row["weighted_momentum_pct"] - row["previous_metrics"]["weighted_momentum_pct"])
    assert row["previous_metrics"]["return_1d_pct"] == pytest.approx((158 / 157 - 1) * 100)
    broken = frame.with_columns(pl.when(pl.col("date") == days[-6]).then(None).otherwise(pl.col("close")).alias("close"))
    assert build_etf_momentum({"510300.SH": broken}) == []
