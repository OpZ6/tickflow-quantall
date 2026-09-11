import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.engine import MatcherConfig
from app.backtest.matrix import build_market_data_matrix

spec = importlib.util.spec_from_file_location(
    "pivot_replay", Path(__file__).resolve().parents[3] / "scripts/replay_vcp_pivot_exit.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_rising_support_protects_profit_without_replacing_initial_pivot():
    # Initially, losing the pivot exits even while price is above MA20.
    # Later, losing a higher MA20 exits even while the original pivot holds.
    close = np.array([9.4, 9.7, 11.0, 10.5, 10.1])
    average = np.array([9.0, 9.0, 10.5, 10.8, 9.8])
    actual = module.pivot_ma20_exit(close, average, 9.5)
    np.testing.assert_array_equal(actual, [True, False, False, True, False])
    for end in range(1, len(close) + 1):
        np.testing.assert_array_equal(
            module.pivot_ma20_exit(close[:end], average[:end], 9.5), actual[:end]
        )
    assert module.pivot_ma20_exit(np.array([9.4]), np.array([9.0]), 9.5)[0]


def test_fixed_pivots_are_event_local_and_censored_marks_are_not_sales():
    prices = [10., 9., 8., 11.]
    market = build_market_data_matrix(pl.DataFrame({
        "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(4)],
        "symbol": ["600000.SH"] * 4,
        **{name: prices for name in ("open", "high", "low", "close")},
        "volume": [1000.] * 4,
    }))
    config = MatcherConfig(matching="open_t+1", commission_pct=.001, slippage_bps=0)
    lost = module.replay_event(market, 0, 3, 9.5, config)["original_entry_pivot_loss"]
    held = module.replay_event(market, 0, 3, 7., config)["original_entry_pivot_loss"]
    assert lost["trade"]["exit_signal_date"] == "2020-01-02"
    assert lost["trade"]["exit_date"] == "2020-01-03"
    assert lost["trade"]["exit_price"] == 8
    assert not lost["censored"]
    assert held["censored"]
    assert held["endpoint_wealth"] == pytest.approx(11 / (9 * 1.001))


def test_limit_down_defers_pivot_sale_and_preserves_signal_date():
    prices = [10., 9., 8., 8.5]
    market = build_market_data_matrix(pl.DataFrame({
        "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(4)],
        "symbol": ["600000.SH"] * 4,
        **{name: prices for name in ("open", "high", "low", "close")},
        "volume": [1000.] * 4,
        "signal_limit_down": [False, False, True, False],
    }))
    result = module.replay_event(
        market, 0, 3, 9.5, MatcherConfig(matching="open_t+1")
    )["original_entry_pivot_loss"]
    assert result["trade"]["exit_date"] == "2020-01-04"
    assert result["trade"]["exit_signal_date"] == "2020-01-02"
    assert result["execution"]["sell_limit_down"] == 1
