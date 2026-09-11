"""Controlled entries isolate VCP exit signals and the production account rules."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.engine import BacktestEngine, MatcherConfig, SimulationOptions
from app.backtest.matrix import (
    build_market_data_matrix,
    build_market_matrix_from_signals,
    make_signal_matrix,
)
from app.strategy.builtin._quants_vcp import build_breakout_bar_failure_exits
from app.strategy.engine import StrategyEngine


def simulate(close, *, stop=None, max_hold=None, opens=None, lows=None, profit_lock_steps=None):
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
    days = [day for day in days if day.weekday() < 5][: len(close)]
    opens = opens or close
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(close),
            "date": days,
            "open": opens,
            "close": close,
            "high": [max(o, c) + 0.1 for o, c in zip(opens, close, strict=True)],
            "low": lows or [min(o, c) - 0.1 for o, c in zip(opens, close, strict=True)],
            "volume": [100000.0] * len(close),
        }
    )
    market = build_market_data_matrix(frame)
    builtin = Path(__file__).resolve().parents[2] / "app/strategy/builtin"
    strategy = StrategyEngine([builtin]).get("quants_vcp_legacy_v1").matrix_strategy
    actual = strategy.compute_signals(market, {"trend_filter": False, "rs_min": 0})
    entry = np.zeros(market.shape, np.uint8)
    entry[20, 0] = 1
    signals = make_signal_matrix(
        market.shape,
        entry=entry,
        exit=actual.exit,
        exit_signal_ids=actual.exit_signal_ids,
        exit_signal_code=actual.exit_signal_code,
    )
    matrix = build_market_matrix_from_signals(
        market, signals, entry_delay_bars=1, exit_delay_bars=1
    )
    result = BacktestEngine(None).simulate_market_matrix(
        matrix,
        MatcherConfig(
            matching="open_t+1",
            stop_loss_pct=stop,
            profit_lock_steps=profit_lock_steps,
            max_hold_days=max_hold,
            commission_pct=0.0003,
            stamp_tax_pct=0.0005,
            slippage_bps=10,
        ),
        options=SimulationOptions(include_monte_carlo=False),
    )
    return result.trades, days


def test_vcp_ma20_exit_fills_after_crossing():
    prices = [10.0] * 23 + [9.8, 9.7, 9.7]
    trades, days = simulate(prices)
    assert len(trades) == 1
    assert trades[0].exit_reason == "signal"
    assert trades[0].exit_signal_date == str(days[23])
    assert str(trades[0].exit_date) == str(days[24])


def test_account_stop_honors_t1_and_gap_price():
    prices = [10.0] * 22 + [9.3, 9.4, 9.4]
    lows = [9.9] * 21 + [9.0, 9.2, 9.3, 9.3]
    trades, days = simulate(prices, stop=-0.05, lows=lows)
    assert len(trades) == 1
    assert trades[0].exit_reason == "stop_loss"
    assert str(trades[0].entry_date) == str(days[21])
    assert str(trades[0].exit_date) == str(days[22])
    assert trades[0].exit_price == pytest.approx(9.3)
    assert trades[0].pnl_pct < -0.07  # Costs worsen the unadjusted gap loss.


def test_maximum_holding_uses_trading_bars():
    trades, days = simulate([10.0] * 30, max_hold=3)
    assert len(trades) == 1
    assert trades[0].exit_reason == "max_hold"
    assert trades[0].duration == 3
    assert str(trades[0].exit_date) > str(days[21])


def test_staged_profit_lock_protects_entry_after_ten_percent_gain():
    prices = [10.0] * 22 + [11.2, 10.5, 10.5]
    lows = [9.9] * 22 + [11.1, 9.9, 10.4]
    trades, days = simulate(
        prices,
        lows=lows,
        profit_lock_steps=[
            {"activate_pct": 0.10, "floor_return_pct": 0.0},
            {"activate_pct": 0.20, "trailing_drawdown_pct": 0.10},
        ],
    )
    assert len(trades) == 1
    assert trades[0].exit_reason == "staged_profit_lock"
    assert str(trades[0].exit_date) == str(days[23])
    assert trades[0].exit_price == pytest.approx(10.0)


def test_breakout_bar_low_exit_uses_only_later_completed_closes():
    close = [10.0, 9.7, 9.4, 9.8]
    low = [9.5, 9.2, 9.3, 9.7]
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 4,
            "date": [date(2024, 1, 2) + timedelta(days=i) for i in range(4)],
            "open": close,
            "high": [value + 0.2 for value in close],
            "low": low,
            "close": close,
            "volume": [100000.0] * 4,
        }
    )
    market = build_market_data_matrix(frame)
    entry = np.zeros(market.shape, np.uint8)
    base_exit = np.zeros(market.shape, np.uint8)
    entry[0, 0] = 1

    exits = build_breakout_bar_failure_exits(market, entry, base_exit)

    assert exits[:, 0].tolist() == [0, 0, 1, 0]
