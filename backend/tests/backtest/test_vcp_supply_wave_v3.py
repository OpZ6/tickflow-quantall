from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from vcp_supply_wave_v3 import _downside_pressure, represent_supply_waves


def test_downside_pressure_falls_when_later_selloff_has_lighter_volume() -> None:
    close = np.array([10.0, 9.0, 9.5, 10.0])
    heavy = _downside_pressure(close, np.array([1.0, 10.0, 1.0, 1.0]), 0, 3)
    light = _downside_pressure(close, np.array([1.0, 1.0, 10.0, 10.0]), 0, 3)

    assert heavy is not None and light is not None
    assert heavy > light


def test_signal_bar_is_used_only_for_breakout_demand() -> None:
    close = np.array(
        [8, 9, 10, 11, 12, 11, 10, 9, 10, 11, 12, 11.5, 11, 10.5, 11, 11.7, 12, 11.8,
         11.6, 11.7, 11.8, 11.9, 11.8, 11.9, 11.85, 11.9, 11.95, 11.9, 11.95, 12.2],
        dtype=float,
    )
    high = close + 0.1
    low = close - 0.1
    volume = np.array([30] * 10 + [24] * 7 + [18] * 12 + [40], dtype=float)
    dates = np.array([f"D{index:02d}" for index in range(len(close))])
    baseline = represent_supply_waves(high, low, close, volume, dates)

    changed_high, changed_low, changed_close, changed_volume = (values.copy() for values in (high, low, close, volume))
    changed_high[-1], changed_low[-1], changed_close[-1], changed_volume[-1] = 99, 0.1, 50, 999
    changed = represent_supply_waves(changed_high, changed_low, changed_close, changed_volume, dates)

    assert changed["waves"] == baseline["waves"]
    assert changed.get("pivot") == baseline.get("pivot")
