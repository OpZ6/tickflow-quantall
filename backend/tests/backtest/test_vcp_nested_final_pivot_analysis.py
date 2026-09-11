import importlib.util
from datetime import date, timedelta
from pathlib import Path

import polars as pl

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "analyze_vcp_nested_final_pivot.py"
SPEC = importlib.util.spec_from_file_location("analyze_vcp_nested_final_pivot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_nested_pivot_does_not_use_signal_day_high_or_low() -> None:
    start = date(2026, 1, 1)
    bars = pl.DataFrame({
        "date": [start + timedelta(days=index) for index in range(6)],
        "high": [10.0, 11.0, 10.5, 10.8, 10.4, 99.0],
        "low": [9.0, 9.5, 9.8, 9.9, 10.0, 1.0],
        "close": [9.5, 10.5, 10.1, 10.4, 10.2, 11.5],
    })

    result = MODULE._nested_pivot(
        bars,
        signal_date=start + timedelta(days=5),
        last_low_date=start,
        signal_close=11.5,
    )
    changed = bars.with_columns(
        pl.when(pl.col("date") == start + timedelta(days=5))
        .then(1_000.0)
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.col("date") == start + timedelta(days=5))
        .then(0.01)
        .otherwise(pl.col("low"))
        .alias("low"),
    )

    assert MODULE._nested_pivot(
        changed,
        signal_date=start + timedelta(days=5),
        last_low_date=start,
        signal_close=11.5,
    ) == result
    assert result["nested_pivot_date"] == start + timedelta(days=3)
    assert result["nested_structure_low"] == 10.0
