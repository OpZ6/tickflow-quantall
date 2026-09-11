import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "low_turnover", Path(__file__).resolve().parents[3] / "scripts/research_low_turnover.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_turnover_window_uses_market_sessions_and_preserves_missing_values():
    history = np.array([[99., 99., 99.], [1., np.nan, np.nan], [2., 0., -1.], [3., 6., np.inf], [999., 999., 999.]])
    score, count = module.turnover_scores(history, 3, 3, 2)
    np.testing.assert_allclose(score, [-2., -3., np.nan])
    np.testing.assert_array_equal(count, [3, 2, 0])
    # Missing sessions are not replaced with zero or older observations; zero turnover is valid.
    assert score[0] > score[1]
    history[4] = [-999., np.nan, 0.]
    changed, _ = module.turnover_scores(history, 3, 3, 2)
    np.testing.assert_array_equal(score, changed)


def test_turnover_minimum_coverage_and_boundaries():
    history = np.array([[1., 2.], [2., np.nan], [3., 4.]])
    score, _ = module.turnover_scores(history, 2, 3, 3)
    np.testing.assert_allclose(score, [-2., np.nan])
    for t, lookback, minimum in [(1, 3, 2), (3, 3, 2), (2, 3, 0), (2, 3, 4)]:
        with pytest.raises(ValueError, match="causal turnover window"):
            module.turnover_scores(history, t, lookback, minimum)
