import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_vcp import trend_context

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_launch_pullback_rs.py"
SPEC = importlib.util.spec_from_file_location("research_launch_pullback_rs", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_lookup_gate_reads_dual_regime_day() -> None:
    GATE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_launch_pullback_gate.py"
    spec = importlib.util.spec_from_file_location("research_launch_pullback_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    gate_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate_mod)
    days = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]
    gate = np.array([False, True, False])
    assert gate_mod.lookup_gate(date(2020, 1, 3), days, gate) is True
    assert gate_mod.lookup_gate(date(2020, 1, 2), days, gate) is False
    assert gate_mod.lookup_gate(date(2020, 1, 7), days, gate) is None


def test_lookup_rs_uses_trend_context_ranks() -> None:
    days = []
    cursor = date(2020, 1, 2)
    while len(days) < 260:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    rows = []
    for t, day in enumerate(days):
        for asset, symbol in enumerate(("600000.SH", "600001.SH", "000001.SZ")):
            close = 10.0 + (0.05 * t if asset == 0 else 0.0)
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000.0,
                    "amount": 30_000_000.0,
                    "raw_close": close,
                }
            )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    _mask, ranks = trend_context(market, {"trend_filter": False, "rs_min": 85.0})
    symbols = list(market.symbols)
    dates = [MODULE._as_date(label) for label in market.timestamp_labels]
    leader = MODULE.lookup_rs("600000.SH", dates[-1], symbols, dates, ranks)
    laggard = MODULE.lookup_rs("600001.SH", dates[-1], symbols, dates, ranks)
    assert leader is not None and leader >= 85.0
    assert laggard is not None and laggard < 85.0
    trades = [
        {"symbol": "600000.SH", "entry_signal_date": dates[-1].isoformat(), "pnl_pct": 0.02},
        {"symbol": "600001.SH", "entry_signal_date": dates[-1].isoformat(), "pnl_pct": -0.01},
    ]
    kept, skipped = MODULE.filter_rs(trades, symbols, dates, ranks, 85.0)
    assert [t["symbol"] for t in kept] == ["600000.SH"]
    assert skipped == 1
    missing = MODULE.lookup_rs("999999.SH", dates[-1], symbols, dates, ranks)
    assert missing is None
