import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.engine import MatcherConfig
from app.backtest.matrix import build_market_data_matrix

spec = importlib.util.spec_from_file_location(
    "high52", Path(__file__).resolve().parents[3] / "scripts/research_high52_cross_section.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_high_anchor_distinguishes_equal_momentum_and_is_prefix_causal():
    close = np.array([[10., 10.], [11., 11.], [15., 15.], [20., 20.], [20., 20.]])
    high = close.copy()
    high[2, 0] = 30
    anchor, momentum, count = module.scores(close, high, 4, lookback=4, skip=1)
    np.testing.assert_allclose(anchor, [2/3, 1])
    np.testing.assert_allclose(momentum, [1, 1])
    np.testing.assert_array_equal(count, [4, 4])
    for old, changed in zip((anchor, momentum, count), module.scores(
        np.vstack([close, [999., 1.]]), np.vstack([high, [999., 1.]]), 4,
        lookback=4, skip=1,
    ), strict=True):
        np.testing.assert_array_equal(old, changed)


def test_signal_groups_keep_ties_and_do_not_depend_on_future_fill():
    assert module.deciles(np.array([1., 1., 2., 3.])).tolist() == [4, 4, 8, 10]


def test_cash_missing_entry_and_censored_sale_are_retained():
    rows = []
    for symbol in ('600000.SH', '600001.SH', '600002.SH', '600003.SH'):
        for i, price in enumerate([10., 10., 11., 12., 13.]):
            if symbol == '600003.SH' and i == 1:
                continue
            rows.append({
                'date': date(2016, 1, 4) + timedelta(days=i), 'symbol': symbol,
                **{c: price for c in ('open', 'high', 'low', 'close')},
                'volume': 1000.,
                'signal_limit_up': symbol == '600001.SH' and i == 1,
                'signal_limit_down': symbol == '600002.SH' and i == 4,
            })
    market = build_market_data_matrix(pl.DataFrame(rows))
    config = MatcherConfig(matching='open_t+1', commission_pct=.001, slippage_bps=0)
    rows, execution = module.replay_cohort(market, np.ones(4, dtype=bool), config)
    by_symbol = {r['symbol']: r for r in rows}
    assert by_symbol['600000.SH']['status'] == 'sold'
    assert by_symbol['600000.SH']['net_return'] == pytest.approx(1.3 * .999 / 1.001 - 1)
    for symbol in ('600001.SH', '600003.SH'):
        assert by_symbol[symbol]['status'] == 'unfilled'
        assert by_symbol[symbol]['net_return'] == 0
    assert by_symbol['600002.SH']['status'] == 'censored'
    assert by_symbol['600002.SH']['net_return'] == pytest.approx(1.3 / 1.001 - 1)
    assert execution['buy_limit_up'] == 1
    assert execution['buy_suspended'] == 1


def test_early_engine_end_liquidation_is_a_stale_mark_not_a_sale():
    rows = []
    for symbol in ('600000.SH', '600001.SH'):
        for i, price in enumerate([10., 10., 11., 12., 13.]):
            if symbol == '600001.SH' and i >= 3:
                continue
            rows.append({
                'date': date(2016, 1, 4) + timedelta(days=i), 'symbol': symbol,
                **{c: price for c in ('open', 'high', 'low', 'close')}, 'volume': 1000.,
            })
    market = build_market_data_matrix(pl.DataFrame(rows))
    config = MatcherConfig(matching='open_t+1', commission_pct=.001, slippage_bps=0)
    rows, _ = module.replay_cohort(market, np.ones(2, dtype=bool), config)
    stale = rows[1]
    assert stale['status'] == 'censored'
    assert stale['stale_mark']
    assert stale['exit_date'] is None
    assert stale['mark_date'] == '2016-01-06'
    assert stale['net_return'] == pytest.approx(1.1 / 1.001 - 1)
