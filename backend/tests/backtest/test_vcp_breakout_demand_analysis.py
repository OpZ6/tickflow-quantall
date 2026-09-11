import importlib.util
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "analyze_vcp_breakout_demand.py"
SPEC = importlib.util.spec_from_file_location("analyze_vcp_breakout_demand", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_demand_metrics_end_on_signal_bar_and_ignore_future() -> None:
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(22)]
    bars = pl.DataFrame(
        {
            "date": dates,
            "open": [10.0] * 20 + [10.2, 50.0],
            "high": [10.1] * 20 + [10.8, 99.0],
            "low": [9.9] * 20 + [10.1, 1.0],
            "close": [10.0] * 20 + [10.7, 50.0],
            "volume": [100.0] * 20 + [200.0, 10000.0],
        }
    )

    metrics = MODULE.compute_demand_metrics(
        bars, signal_date=dates[-2], pivot=10.5
    )

    assert metrics["close_return"] == pytest.approx(0.07, abs=1e-6)
    assert metrics["volume_ratio_20"] == pytest.approx(2.0)
    assert metrics["pivot_clearance"] == pytest.approx(10.7 / 10.5 - 1, abs=1e-6)
