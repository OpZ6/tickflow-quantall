import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backfill_strategy_minute_samples.py"
SPEC = importlib.util.spec_from_file_location("backfill_strategy_minute_samples", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_plan = MODULE._plan
_select_signals = MODULE._select_signals


def test_signal_selection_keeps_all_provenance_at_limit_boundary(tmp_path) -> None:
    target = tmp_path / "strategy_signal_events" / "date=2026-09-01"
    target.mkdir(parents=True)
    pl.DataFrame({
        "strategy_id": ["vcp_breakout", "vcp_breakout", "vcp_breakout"],
        "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
        "event_date": [date(2026, 9, 1)] * 3,
        "event_type": ["candidate", "entry", "candidate"],
        "source_run_id": ["run-a", "run-a", "run-b"],
        "score": [80.0, 80.0, 70.0],
    }).write_parquet(target / "part.parquet")

    selected = _select_signals(
        tmp_path, date(2026, 9, 1), ["vcp_breakout"], limit=1
    )

    assert selected == [{
        "symbol": "000001.SZ",
        "score": 80.0,
        "strategy_ids": ["vcp_breakout"],
        "event_types": ["candidate", "entry"],
        "source_run_ids": ["run-a"],
    }]


def test_minute_sample_plan_counts_complete_and_missing_sessions() -> None:
    start = datetime(2026, 9, 2, 9, 31)
    frame = pl.DataFrame({
        "symbol": ["000001.SZ"] * 240,
        "datetime": [start + timedelta(minutes=index) for index in range(240)],
        "open": [10.0] * 240,
        "high": [10.1] * 240,
        "low": [9.9] * 240,
        "close": [10.0] * 240,
        "volume": [100.0] * 240,
        "amount": [1000.0] * 240,
    })
    signals = [
        {
            "symbol": symbol,
            "score": 1.0,
            "strategy_ids": ["vcp_breakout"],
            "event_types": ["candidate"],
            "source_run_ids": ["run-a"],
        }
        for symbol in ("000001.SZ", "000002.SZ")
    ]

    result = _plan(
        signals,
        frame,
        date(2026, 9, 1),
        date(2026, 9, 2),
        ["vcp_breakout"],
    )

    assert result["complete_session_candidates"] == 1
    assert result["missing_symbols"] == ["000002.SZ"]
    assert result["rows"] == 240
    assert result["duplicate_keys"] == 0
    assert result["null_ohlc_rows"] == 0
