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


def _flat(days: list[date], close: float = 10.0) -> list[dict]:
    return [
        {"date": day, "open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 1e6}
        for day in days
    ]


def test_close_cross_below_ma10_sells_next_market_open() -> None:
    days = _weekdays(14)
    sessions = _flat(days, 10.0)
    sessions[11]["close"] = 9.0
    sessions[11]["low"] = 8.9
    sessions[12]["open"] = 9.1
    applied = MODULE.apply_ma_cross_exit_to_fill(
        entry_date=days[10],
        exit_date=days[13],
        entry_price=10.0,
        baseline_pnl=0.12,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
        ma_days=10,
    )
    assert applied["shortened"] is True
    assert applied["early_exit_date"] == days[12].isoformat()
    gross = 9.1 / 10.0 - 1.0
    expected = MODULE.net_round_trip(gross, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[12]))
    assert applied["pnl"] == pytest.approx(expected)
    assert applied["pnl"] < gross


def test_staying_above_ma10_keeps_baseline() -> None:
    days = _weekdays(14)
    sessions = _flat(days, 10.0)
    applied = MODULE.apply_ma_cross_exit_to_fill(
        entry_date=days[10],
        exit_date=days[13],
        entry_price=10.0,
        baseline_pnl=0.04,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
        ma_days=10,
    )
    assert applied["shortened"] is False
    assert applied["pnl"] == 0.04


def test_stock_hole_on_market_session_does_not_roll() -> None:
    days = _weekdays(14)
    sessions = _flat(days, 10.0)
    hole = days[11]
    stock = [row for row in sessions if row["date"] != hole]
    sessions[12]["close"] = 9.0
    applied = MODULE.apply_ma_cross_exit_to_fill(
        entry_date=days[10],
        exit_date=days[13],
        entry_price=10.0,
        baseline_pnl=0.06,
        sessions=stock,
        market_calendar=days,
        config=CONFIG,
        ma_days=10,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "missing_bar"
    assert applied["pnl"] == 0.06


def test_breakout_bullish_bar_is_close_above_open() -> None:
    days = _weekdays(2)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 10.5, "low": 9.5, "close": 9.8, "volume": 1e6},
        {"date": days[1], "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 1e6},
    ]
    yin = MODULE.breakout_bullish_bar(signal_date=days[0], sessions=sessions, market_calendar=days)
    yang = MODULE.breakout_bullish_bar(signal_date=days[1], sessions=sessions, market_calendar=days)
    assert yin["bullish"] is False
    assert yang["bullish"] is True


def test_incomplete_ma10_keeps_baseline() -> None:
    days = _weekdays(8)
    sessions = _flat(days, 10.0)
    sessions[-2]["close"] = 9.0
    applied = MODULE.apply_ma_cross_exit_to_fill(
        entry_date=days[0],
        exit_date=days[-1],
        entry_price=10.0,
        baseline_pnl=0.02,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
        ma_days=10,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "incomplete_ma"
    assert applied["pnl"] == 0.02
