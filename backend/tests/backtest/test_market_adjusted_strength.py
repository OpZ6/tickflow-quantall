import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "market_adjusted", Path(__file__).resolve().parents[3] / "scripts/research_market_adjusted_strength.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_market_adjustment_preserves_alpha_and_removes_known_beta():
    market_log = np.array([0., .01, .02, -.01, 0., .03, -.02])
    returns = np.column_stack([.005 + 2 * market_log[1:], 3 * market_log[1:]])
    close = 10 * np.exp(np.vstack([np.zeros(2), np.cumsum(returns, axis=0)]))
    score, beta, count = module.market_adjusted_scores(close, market_log, 6, 6, 1, 3)
    np.testing.assert_allclose(beta, [2, 3], atol=1e-12)
    np.testing.assert_allclose(score, [.025, 0.], atol=1e-12)
    np.testing.assert_array_equal(count, [6, 6])
    assert score[0] > score[1]
    # Perturb everything after the signal: estimates and ranking must not move.
    changed = module.market_adjusted_scores(
        np.vstack([close, [1e9, .001]]), np.append(market_log, .4), 6, 6, 1, 3,
    )
    for a, b in zip((score, beta, count), changed, strict=True):
        np.testing.assert_array_equal(a, b)


def test_missing_pairs_use_the_same_observations_for_both_means():
    market_log = np.array([0., .01, .02, -.01, .015, .03, -.02, .025, .005])
    close = 10 * np.exp(np.r_[0., np.cumsum(.002 + 1.5 * market_log[1:])])[:, None]
    close[3, 0] = np.nan
    score, beta, count = module.market_adjusted_scores(close, market_log, 8, 8, 1, 3)
    np.testing.assert_allclose(beta, [1.5], atol=1e-12)
    np.testing.assert_allclose(score, [.014], atol=1e-12)
    np.testing.assert_array_equal(count, [6])


def test_degenerate_market_or_insufficient_pairs_is_unavailable():
    close = np.arange(10., 19.)[:, None]
    score, beta, _ = module.market_adjusted_scores(close, np.zeros(9), 8, 8, 1, 3)
    assert np.isnan(score).all() and np.isnan(beta).all()


def test_residual_volatility_removes_market_and_intercept_and_matches_lstsq():
    x = np.array([.01, .02, -.01, .015, .03, -.02, .025, .005])
    noise = np.array([.004, -.003, .002, -.005, .003, .006, -.002, -.001])
    y = np.column_stack([.002 + 2*x, .002 + 2*x + noise])
    close = 10*np.exp(np.vstack([np.zeros(2), np.cumsum(y, axis=0)]))
    market = np.r_[0., x]
    beta, counts, total, residual = module.market_model_statistics(close, market, 8, 8, 3)
    assert residual[0] < 1e-14
    assert residual[1] > residual[0]
    for i in range(2):
        design = np.column_stack([np.ones(8), x])
        fitted = np.linalg.lstsq(design, y[:, i], rcond=None)[0]
        expected = np.sqrt(np.sum((y[:, i] - design @ fitted)**2) / 6)
        np.testing.assert_allclose(residual[i], expected, atol=1e-14)
        np.testing.assert_allclose(beta[i], fitted[1], atol=1e-12)
        np.testing.assert_allclose(total[i], np.std(y[:, i], ddof=1), atol=1e-14)
    np.testing.assert_array_equal(counts, [8, 8])
    future = module.market_model_statistics(np.vstack([close, [999., .01]]), np.r_[market, .4], 8, 8, 3)
    for a, b in zip((beta, counts, total, residual), future, strict=True):
        np.testing.assert_array_equal(a, b)


def test_missing_pair_residual_volatility_matches_common_sample_regression():
    x = np.array([.01, .02, -.01, .015, .03, -.02, .025, .005])
    y = .002 + 1.5*x + np.array([.004, -.003, .002, -.005, .003, .006, -.002, -.001])
    close = 10*np.exp(np.r_[0., np.cumsum(y)])[:, None]
    close[3, 0] = np.nan
    beta, counts, total, residual = module.market_model_statistics(close, np.r_[0., x], 8, 8, 3)
    keep = np.array([True, True, False, False, True, True, True, True])
    design = np.column_stack([np.ones(6), x[keep]])
    fitted = np.linalg.lstsq(design, y[keep], rcond=None)[0]
    np.testing.assert_allclose(beta, [fitted[1]], atol=1e-12)
    np.testing.assert_allclose(total, [np.std(y[keep], ddof=1)], atol=1e-14)
    np.testing.assert_allclose(residual, [np.sqrt(np.sum((y[keep]-design@fitted)**2)/4)], atol=1e-14)
    np.testing.assert_array_equal(counts, [6])
    score, beta, _ = module.market_adjusted_scores(close, np.arange(9.) / 1000, 8, 8, 1, 9)
    assert np.isnan(score).all() and np.isnan(beta).all()
