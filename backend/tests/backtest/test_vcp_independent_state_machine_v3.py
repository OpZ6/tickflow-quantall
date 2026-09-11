from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from vcp_independent_state_machine_v3 import _mean_down_volume, represent_independent_vcp


def test_down_volume_uses_only_declining_sessions() -> None:
    result = _mean_down_volume(
        np.array([10.0, 9.0, 9.5, 9.2]),
        np.array([1.0, 10.0, 100.0, 20.0]),
        0,
        3,
    )

    assert result == 15.0


def test_signal_bar_cannot_change_prebreakout_state() -> None:
    first = np.linspace(8.0, 12.0, 70)
    base = np.r_[np.linspace(12.0, 9.5, 10), np.linspace(9.5, 11.5, 10),
                 np.linspace(11.5, 10.5, 8), np.linspace(10.5, 11.8, 12), np.full(19, 11.7)]
    close = np.r_[first, base, 12.3]
    high, low = close + 0.1, close - 0.1
    volume = np.r_[np.full(90, 30.0), np.full(len(close) - 91, 15.0), 40.0]
    dates = np.array([f"D{index:03d}" for index in range(len(close))])
    baseline = represent_independent_vcp(high, low, close, volume, dates)
    high[-1], low[-1], close[-1], volume[-1] = 99.0, 0.1, 50.0, 999.0
    changed = represent_independent_vcp(high, low, close, volume, dates)

    for field in ("pivot", "pivot_date", "prior_advance", "base_depth", "reversal", "waves"):
        assert changed.get(field) == baseline.get(field)
