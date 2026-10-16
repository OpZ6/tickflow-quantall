import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_cup_entry_kind import ordered_retest


def test_breakout_must_be_before_current_retest():
    high = np.array([10, 10.2, 10.1])
    low = np.array([9.8, 10, 9.9])
    close = np.array([10, 10.1, 10])
    assert ordered_retest(high, low, close, 0, 10, 10.15)
    assert not ordered_retest(np.array([10, 10.1, 10.2]), low, close, 0, 10, 10.15)


def test_old_retest_does_not_make_today_a_retest():
    assert not ordered_retest(np.array([10, 10.3, 10.4]), np.array([9.8, 9.9, 10.2]),
                              np.array([10, 10.2, 10.3]), 0, 10, 10.15)


def test_today_must_hold_left_rim():
    assert not ordered_retest(np.array([10, 10.3, 10.1]), np.array([9.8, 10, 9.8]),
                              np.array([10, 10.2, 9.9]), 0, 10, 10.15)
