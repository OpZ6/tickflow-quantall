from datetime import date, timedelta

import polars as pl
import pytest

from app.backtest.engine import BacktestEngine, MatcherConfig


@pytest.mark.parametrize("method", [
    "simulate_independent_candidates", "simulate_independent_candidates_legacy",
    "simulate_portfolio", "simulate_portfolio_legacy",
])
@pytest.mark.parametrize("exit_fill", ["open_t+1", "close_t"])
def test_close_breakeven_waits_for_close_then_next_open(method, exit_fill):
    closes = [10., 10.5, 10., 9.9, 9.7, 10.]
    panel = pl.DataFrame([
        {"symbol": "A", "name": "A", "date": date(2020, 1, 6) + timedelta(days=i),
         "open": 9.8 if i == 4 else 10., "high": 10.6, "low": 9.5,
         "close": c, "volume": 100_000, "score": 1.}
        for i, c in enumerate(closes)
    ])
    result = getattr(BacktestEngine(repo=None), method)(
        panel, pl.Series([True, False, False, False, False, False]), pl.Series([False] * 6),
        MatcherConfig(entry_fill="open_t+1", exit_fill=exit_fill, fees_pct=0, slippage_bps=0,
                      close_breakeven_activate_pct=.05, max_positions=1))
    trade = result.trades[0]
    assert trade.exit_reason == "close_breakeven"
    assert str(trade.exit_signal_date) == "2020-01-09"
    assert str(trade.exit_date) == "2020-01-10"
    assert trade.exit_price == 9.8


@pytest.mark.parametrize("method", ["simulate_independent_candidates", "simulate_portfolio"])
def test_intraday_high_does_not_arm_close_breakeven(method):
    panel = pl.DataFrame([
        {"symbol": "A", "date": date(2020, 1, 6) + timedelta(days=i),
         "open": 10., "high": 11., "low": 9., "close": 10.1 if i == 1 else 9.8,
         "volume": 100_000}
        for i in range(5)
    ])
    result = getattr(BacktestEngine(repo=None), method)(
        panel, pl.Series([True, False, False, False, False]), pl.Series([False] * 5),
        MatcherConfig(matching="open_t+1", close_breakeven_activate_pct=.05))
    assert result.trades[0].exit_reason == "end"


@pytest.mark.parametrize("method", [
    "simulate_independent_candidates", "simulate_independent_candidates_legacy",
    "simulate_portfolio", "simulate_portfolio_legacy",
])
def test_blocked_open_keeps_original_close_signal_and_sells_later(method):
    prices = [(10., 10.), (10., 10.5), (10., 9.9), (9., 9.), (9.4, 9.6), (10., 10.)]
    panel = pl.DataFrame([
        {"symbol": "A", "date": date(2020, 1, 6) + timedelta(days=i),
         "open": opening, "high": 9. if i == 3 else 11., "low": 9., "close": close,
         "volume": 100_000, "signal_limit_down": i == 3}
        for i, (opening, close) in enumerate(prices)
    ])
    result = getattr(BacktestEngine(repo=None), method)(
        panel, pl.Series([True, False, False, False, False, False]), pl.Series([False] * 6),
        MatcherConfig(matching="open_t+1", close_breakeven_activate_pct=.05))
    trade = result.trades[0]
    assert trade.exit_reason == "close_breakeven"
    assert str(trade.exit_signal_date) == "2020-01-08"
    assert str(trade.exit_date) == "2020-01-10"
    assert trade.exit_price == 9.4
    assert trade.blocked_exit_days == 1
