import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_cup_armed_ma20 import armed_ma20_exit


def test_waits_until_first_close_above_then_never_resets():
    close = np.array([9., 9., 10., 9., np.nan, 9.])[:, None]
    exits = armed_ma20_exit(close, np.full_like(close, 10.))
    assert np.flatnonzero(exits[:, 0]).tolist() == [3, 5]


def test_signal_day_can_arm_but_cannot_exit():
    close = np.array([10., 9., 8.])[:, None]
    assert armed_ma20_exit(close, np.full_like(close, 10.)).ravel().tolist() == [False, True, True]


def test_future_cross_does_not_change_prior_exits():
    close = np.array([9., 8., 9., 11., 9.])[:, None]
    ma = np.full_like(close, 10.)
    full = armed_ma20_exit(close, ma)
    np.testing.assert_array_equal(full[:3], armed_ma20_exit(close[:3], ma[:3]))
    assert not full[:4].any()


def test_missing_ma_cannot_arm_and_assets_are_independent():
    close = np.array([[11., 9.], [9., 9.], [9., 9.]])
    ma = np.array([[10., np.nan], [np.nan, 10.], [10., 10.]])
    assert armed_ma20_exit(close, ma).tolist() == [[False, False], [False, False], [True, False]]
