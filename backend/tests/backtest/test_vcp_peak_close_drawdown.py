import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.backtest.engine import MatcherConfig

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_two_bar_no_demand.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_two_bar_no_demand", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CONFIG = MatcherConfig(
    matching="open_t+1",
    commission_pct=0.0003,
    slippage_bps=10.0,
    stamp_tax_policy="a_share_historical",
)


def _weekdays(n: int, start: date = date(2020, 1, 2)) -> list[date]:
    days = []
    cursor = start
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_eight_percent_close_retrace_sells_next_market_open() -> None:
    days = _weekdays(4)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 11.2, "low": 9.9, "close": 11.0, "volume": 1e6},
        {"date": days[1], "open": 11.0, "high": 11.1, "low": 10.0, "close": 10.12, "volume": 1e6},
        {"date": days[2], "open": 10.05, "high": 10.2, "low": 10.0, "close": 10.1, "volume": 1e6},
        {"date": days[3], "open": 12.0, "high": 12.2, "low": 11.8, "close": 12.0, "volume": 1e6},
    ]
    applied = MODULE.apply_peak_close_drawdown_to_fill(
        entry_date=days[0],
        exit_date=days[3],
        entry_price=10.0,
        baseline_pnl=0.18,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is True
    assert applied["early_exit_date"] == days[2].isoformat()
    gross = 10.05 / 10.0 - 1.0
    expected = MODULE.net_round_trip(gross, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[2]))
    assert applied["pnl"] == pytest.approx(expected)
    assert applied["pnl"] < gross


def test_shallower_retrace_keeps_baseline() -> None:
    days = _weekdays(3)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 11.2, "low": 9.9, "close": 11.0, "volume": 1e6},
        {"date": days[1], "open": 11.0, "high": 11.1, "low": 10.2, "close": 10.13, "volume": 1e6},
        {"date": days[2], "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1e6},
    ]
    applied = MODULE.apply_peak_close_drawdown_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=0.03,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["pnl"] == 0.03


def test_stock_hole_on_market_session_does_not_roll() -> None:
    market = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8), date(2020, 1, 9)]
    sessions = [
        {"date": date(2020, 1, 6), "open": 10.0, "high": 11.2, "low": 9.9, "close": 11.0, "volume": 1e6},
        {"date": date(2020, 1, 8), "open": 10.0, "high": 10.1, "low": 9.0, "close": 9.5, "volume": 1e6},
        {"date": date(2020, 1, 9), "open": 9.4, "high": 9.5, "low": 9.3, "close": 9.4, "volume": 1e6},
    ]
    applied = MODULE.apply_peak_close_drawdown_to_fill(
        entry_date=date(2020, 1, 6),
        exit_date=date(2020, 1, 9),
        entry_price=10.0,
        baseline_pnl=0.04,
        sessions=sessions,
        market_calendar=market,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "missing_bar"
    assert applied["pnl"] == 0.04


def test_breakout_close_upper_half_uses_high_low_range() -> None:
    days = _weekdays(2)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 11.0, "low": 9.0, "close": 9.9, "volume": 1e6},
        {"date": days[1], "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.1, "volume": 1e6},
    ]
    low = MODULE.breakout_close_upper_half(
        signal_date=days[0], sessions=sessions, market_calendar=days
    )
    high = MODULE.breakout_close_upper_half(
        signal_date=days[1], sessions=sessions, market_calendar=days
    )
    assert low["upper"] is False
    assert high["upper"] is True


def test_one_price_limit_down_on_fill_does_not_roll() -> None:
    days = _weekdays(4)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 11.2, "low": 9.9, "close": 11.0, "volume": 1e6},
        {"date": days[1], "open": 11.0, "high": 11.1, "low": 10.0, "close": 10.12, "volume": 1e6},
        {"date": days[2], "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 1e6},
        {"date": days[3], "open": 12.0, "high": 12.1, "low": 11.9, "close": 12.0, "volume": 1e6},
    ]
    applied = MODULE.apply_peak_close_drawdown_to_fill(
        entry_date=days[0],
        exit_date=days[3],
        entry_price=10.0,
        baseline_pnl=0.15,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "early_exit_blocked"
    assert applied["pnl"] == 0.15
