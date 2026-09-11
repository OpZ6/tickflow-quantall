import importlib.util
from pathlib import Path

import numpy as np
import pytest

from app.strategy.builtin._quants_high_tight_flag import detect

spec = importlib.util.spec_from_file_location(
    "flag_balance", Path(__file__).resolve().parents[3] / "scripts/research_flag_volume_balance.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_precheck_never_discards_exact_detector_candidate():
    rng = np.random.default_rng(12)
    paths = [np.r_[np.linspace(10, 22, 20), np.full(39, 20.6), 20.8]]
    paths.extend(10 * np.exp(np.cumsum(rng.normal(.005, .07, 280))) for _ in range(4))
    executable = 0
    for close in paths:
        high, low = close + .1, close - .1
        volume = np.full(len(close), 100.)
        volume[-1] = 300.
        possible = module.possible_poles(high, low)
        for t in range(11, len(close)):
            left = max(0, t - 219)
            c = detect(high[left:t + 1], low[left:t + 1], close[left:t + 1], volume[left:t + 1], {})
            if c and c.get("status") == "executable":
                executable += 1
                assert possible[t]
        np.testing.assert_array_equal(possible[:40], module.possible_poles(high[:40], low[:40]))
    assert executable > 0


def test_balance_excludes_signal_volume_and_uses_original_pole_boundary():
    high = np.array([10, 11, 12, 20, 18, 18, 18, 18, 18, 18, 18, 18, 18, 99.])
    close = np.array([9, 10, 11, 19, 18, 17, 18, 18, 17, 18, 17, 18, 17, 99.])
    volume = np.arange(1., 15.)
    score, length = module.flag_balance(high, close, volume, "short")
    expected = (-5 - 6 + 7 - 9 + 10 - 11 + 12 - 13) / sum(range(5, 14))
    assert score == pytest.approx(expected)
    assert length == 9
    volume[-1] = 1e12
    close[-1] = .01
    assert module.flag_balance(high, close, volume, "short") == pytest.approx((score, length))
    volume[5] = np.nan
    assert np.isnan(module.flag_balance(high, close, volume, "short")[0])
