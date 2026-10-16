import json
import runpy
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.review import build_review


def test_exact_source_combinations_and_result_denominators(tmp_path):
    days = [date(2026, 9, i) for i in (16, 17, 18)]
    for day in days:
        folder = tmp_path / "stock_pools" / f"date={day}"
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(json.dumps({"trade_date": str(day), "status": "complete", "rule_version": "stock-pools-v2", "source_quality": {}}))
        rows = [{"symbol": "A.SZ", "name": "A", "primary_stage": "突破启动", "source_ids": ["breakthrough", "liquidity_trend"], "sources": ["breakthrough", "liquidity_trend"], "topics": []},
                {"symbol": "B.SZ", "name": "B", "primary_stage": "趋势延续", "source_ids": ["liquidity_trend"], "sources": ["liquidity_trend"], "topics": []}]
        (folder / "candidates.json").write_text(json.dumps(rows), encoding="utf-8")

    class Klines:
        def get_daily_batch(self, symbols, start, end, columns):
            return pl.DataFrame([{"symbol": symbol, "date": day, "close": price, "open": price - 2,
                                  "high": price + 2, "low": price - 5}
                                 for symbol, values in [("A.SZ", [100., 110., 120.]), ("B.SZ", [100., 90., 80.])]
                                 for day, price in zip(days, values, strict=True)])
    result = build_review(StockPoolRepository(tmp_path), Klines(), days[-1], 3, 1)
    combo = result["attribution"]["combinations"]["breakthrough+liquidity_trend"]
    assert combo["matured_count"] == 1
    assert combo["pending_count"] == 1
    assert combo["up_rate_pct"] == 100
    assert combo["priced_dates"] == 1
    assert combo["adverse_count"] == 1
    assert combo["mean_adverse_pct"] == -2.54
    assert result["groups"]["all"]["up_rate_pct"] == 50
    assert result["attribution"]["sources"]["liquidity_trend"]["matured_count"] == 2


def test_signal_outcomes_use_exact_sessions_and_block_intervals_are_reproducible():
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "analyze_market_signal_efficacy.py"))
    days = [date(2026, 9, i) for i in (16, 17, 18, 21)]
    prices = {day: {"close": price, "low": price - 2} for day, price in zip(days, [100, 110, 120, 130], strict=True)}
    value = module["outcome"](prices, days, days[0], 3)
    assert value["return_pct"] == pytest.approx(30)
    assert value["worst_pct"] == pytest.approx(8)
    assert module["outcome"](prices, days, days[-1], 1) is None
    assert module["outcome"]({day: bar for day, bar in prices.items() if day != days[1]}, days, days[0], 3) is None
    rows = [{"return_pct": -1 if i % 2 else 1, "selected": bool(i % 2), "baseline": not i % 2} for i in range(30)]
    assert module["block_interval"](rows, repeats=50) == [-2, -2]
