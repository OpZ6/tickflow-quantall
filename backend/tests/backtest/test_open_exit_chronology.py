from datetime import date, timedelta

import polars as pl
import pytest

from app.backtest.engine import BacktestEngine, MatcherConfig


@pytest.mark.parametrize("method", [
    "simulate_independent_candidates", "simulate_independent_candidates_legacy",
    "simulate_portfolio", "simulate_portfolio_legacy",
])
@pytest.mark.parametrize("case,opening,expected_price,expected_reason", [
    ("signal", 9.5, 9.5, "signal"),
    ("expiry", 9.5, 9.5, "max_hold"),
    ("gap", 8.5, 8.5, "stop_loss"),
    ("close", 9.5, 9.0, "stop_loss"),
    ("no_signal", 9.5, 9.0, "stop_loss"),
    ("profit", 9.5, 9.5, "signal"),
])
def test_open_exit_precedes_later_intraday_risk(method, case, opening, expected_price, expected_reason):
    panel = pl.DataFrame([
        {"symbol": "A", "name": "A", "date": date(2020, 1, 6) + timedelta(days=i),
         "open": opening if i == 2 else 10., "high": 12. if case == "profit" and i == 2 else 10.,
         "low": 8.5 if i == 2 else 10., "close": 9.6 if i == 2 else 10.,
         "volume": 100_000, "score": 1.}
        for i in range(4)
    ])
    result = getattr(BacktestEngine(repo=None), method)(
        panel, pl.Series([True, False, False, False]),
        pl.Series([False, case in {"signal", "gap", "close", "profit"}, False, False]),
        MatcherConfig(entry_fill="open_t+1", exit_fill="close_t" if case == "close" else "open_t+1",
                      fees_pct=0, slippage_bps=0, stop_loss_pct=None if case == "profit" else .1,
                      take_profit_pct=.1 if case == "profit" else None,
                      max_hold_days=1 if case == "expiry" else 30, max_positions=1))
    assert len(result.trades) == 1
    assert result.trades[0].exit_price == expected_price
    assert result.trades[0].exit_reason == expected_reason
