import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_pullback_reclaim import reclaim_after_touch


def inputs():
    close = np.array([10.5, 10.1, 9.9, 10.2, 9.9, 10.3])[:, None]
    touch = np.array([False, True, False, False, False, False])[:, None]
    launch = np.zeros_like(touch)
    support = np.full_like(close, 10.0)
    return close, touch, launch, support


def test_waits_for_cross_after_touch_and_only_enters_once():
    close, touch, launch, support = inputs()
    entries = reclaim_after_touch(close, touch, launch, support, 0.02)
    assert np.flatnonzero(entries[:, 0]).tolist() == [3]


def test_close_above_support_without_cross_is_not_reclaim():
    close, touch, launch, support = inputs()
    close[:] = 10.2
    assert not reclaim_after_touch(close, touch, launch, support, 0.02).any()


def test_touch_day_cross_is_not_a_later_reclaim():
    close, touch, launch, support = inputs()
    close[:] = 10.2
    close[0] = 9.9
    assert not reclaim_after_touch(close, touch, launch, support, 0.02).any()


def test_missing_market_bar_cancels_instead_of_rolling():
    close, touch, launch, support = inputs()
    close[2] = np.nan
    assert not reclaim_after_touch(close, touch, launch, support, 0.02).any()


def test_existing_failure_level_or_expiry_cancels():
    close, touch, launch, support = inputs()
    close[2] = 9.7
    assert not reclaim_after_touch(close, touch, launch, support, 0.02).any()
    close[2] = 9.9
    support[2] = np.nan
    assert not reclaim_after_touch(close, touch, launch, support, 0.02).any()


def test_new_launch_cancels_old_opportunity():
    close, touch, launch, support = inputs()
    launch[3] = True
    assert not reclaim_after_touch(close, touch, launch, support, 0.02).any()


def test_future_data_does_not_change_earlier_signals():
    close, touch, launch, support = inputs()
    full = reclaim_after_touch(close, touch, launch, support, 0.02)
    prefix = reclaim_after_touch(close[:4], touch[:4], launch[:4], support[:4], 0.02)
    np.testing.assert_array_equal(full[:4], prefix)
