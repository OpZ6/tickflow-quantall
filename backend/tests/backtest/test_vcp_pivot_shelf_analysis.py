import importlib.util
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "analyze_vcp_pivot_shelf.py"
SPEC = importlib.util.spec_from_file_location("analyze_vcp_pivot_shelf", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_shelf_metrics_exclude_breakout_bar() -> None:
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(41)]
    bars = pl.DataFrame(
        {
            "date": dates,
            "high": [10.1] * 40 + [99.0],
            "low": [9.9] * 40 + [1.0],
            "close": [10.0] * 40 + [50.0],
            "volume": [100.0] * 40 + [10000.0],
        }
    )

    metrics = MODULE.compute_shelf_metrics(
        bars,
        signal_date=dates[-1],
        pivot=10.0,
        entry_price=10.2,
    )

    assert metrics["range_5"] == pytest.approx(0.02, abs=1e-6)
    assert metrics["volume_5_to_20"] == pytest.approx(1.0)
    assert metrics["support_risk_5"] == pytest.approx(1 - 9.9 / 10.2, abs=1e-6)
