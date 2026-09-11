from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from vcp_stage2_context_v3 import represent_stage2_context


def _series(concentrated: bool = False):
    early = np.linspace(10.0, 11.0, 50)
    middle = np.linspace(11.0, 15.0, 50)
    if concentrated:
        middle = np.r_[np.full(25, 11.0), np.full(25, 15.0)]
    late = np.linspace(14.2, 15.3, 50) + np.sin(np.arange(50)) * 0.08
    signal = np.array([16.0])
    close = np.r_[early, middle, late, signal]
    high = close * 1.006
    low = close * 0.994
    volume = np.r_[np.full(150, 10.0), 20.0]
    return high, low, close, volume


def test_signal_bar_changes_demand_but_not_context_metrics() -> None:
    high, low, close, volume = _series()
    baseline = represent_stage2_context(high, low, close, volume)
    high[-1], low[-1], close[-1], volume[-1] = 99.0, 0.1, 50.0, 999.0
    changed = represent_stage2_context(high, low, close, volume)

    for field in ("early_median", "middle_median", "late_median", "retained_floor",
                  "leading_to_remaining_positive_return_ratio", "middle_to_late_range_ratio"):
        assert changed[field] == baseline[field]


def test_few_bar_repricing_fails_continuous_advance() -> None:
    smooth = represent_stage2_context(*_series())
    concentrated = represent_stage2_context(*_series(concentrated=True))

    assert smooth["checks"]["continuous_advance"] is True
    assert concentrated["checks"]["continuous_advance"] is False
