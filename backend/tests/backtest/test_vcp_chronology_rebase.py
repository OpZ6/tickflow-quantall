import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_vcp_chronology_rebase import breakeven_close_exits


def test_preentry_gain_cannot_arm_held_protection():
    close = np.array([11., 10., 9.9])[:, None]
    assert not breakeven_close_exits(close, 10.).any()


def test_held_close_arms_at_five_percent_and_exit_is_strictly_below_cost():
    close = np.array([10., 10.5, 10., 9.9])[:, None]
    assert breakeven_close_exits(close, 10.).ravel().tolist() == [False, False, False, True]


def test_missing_close_cannot_trigger_and_future_cannot_change_prefix():
    close = np.array([10., 10.5, np.nan, 9.9, 11.])[:, None]
    exits = breakeven_close_exits(close, 10.)
    assert exits.ravel().tolist() == [False, False, False, True, False]
    np.testing.assert_array_equal(exits[:3], breakeven_close_exits(close[:3], 10.))
