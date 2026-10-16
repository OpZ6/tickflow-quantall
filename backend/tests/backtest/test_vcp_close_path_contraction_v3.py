from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from vcp_close_path_contraction_v3 import _persistent_leg, represent_close_path_vcp


def test_persistent_leg_rejects_one_bar_repricing() -> None:
    close = np.array([10.0, 10.1, 10.0, 8.0, 7.9])

    assert not _persistent_leg(close, 0, 4)


def test_signal_bar_cannot_change_prebreakout_state() -> None:
    first = np.linspace(8.0, 12.0, 70)
    base = np.r_[np.linspace(12.0, 9.5, 10), np.linspace(9.5, 11.5, 10),
                 np.linspace(11.5, 10.5, 8), np.linspace(10.5, 11.8, 12), np.full(19, 11.7)]
    close = np.r_[first, base, 12.3]
    high, low = close + 0.1, close - 0.1
    volume = np.r_[np.full(90, 30.0), np.full(len(close) - 91, 15.0), 40.0]
    dates = np.array([f"D{index:03d}" for index in range(len(close))])
    baseline = represent_close_path_vcp(high, low, close, volume, dates)
    high[-1], low[-1], close[-1], volume[-1] = 99.0, 0.1, 50.0, 999.0
    changed = represent_close_path_vcp(high, low, close, volume, dates)

    for field in ("pivot", "pivot_date", "prior_advance", "reversal", "waves"):
        assert changed.get(field) == baseline.get(field)
