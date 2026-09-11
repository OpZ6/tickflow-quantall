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


def test_shrink_pullback_buys_next_open_after_quiet_dip() -> None:
    days = _weekdays(25)
    sessions = []
    for i, day in enumerate(days):
        volume = 50.0 if i == 21 else 100.0
        close = 10.5 if i == 20 else (10.2 if i == 21 else 10.4)
        low = 10.3 if i == 20 else (10.3 if i == 21 else 10.2)
        open_px = 10.4 if i != 22 else 10.25
        sessions.append(
            {"date": day, "open": open_px, "high": 10.6, "low": low, "close": close, "volume": volume}
        )
    found = MODULE.find_shrink_pullback_entry(
        signal_date=days[20],
        exit_date=days[24],
        sessions=sessions,
        market_calendar=days,
        lookback=20,
        window=8,
    )
    assert found["filled"] is True
    assert found["entry_date"] == days[22].isoformat()
    pnl = MODULE.pullback_round_trip(
        new_entry_price=10.25,
        exit_price=11.0,
        exit_date=days[24],
        config=CONFIG,
    )
    gross = 11.0 / 10.25 - 1.0
    assert pnl == pytest.approx(
        MODULE.net_round_trip(gross, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[24]))
    )
    assert pnl < gross


def test_volume_not_shrunk_does_not_fill() -> None:
    days = _weekdays(25)
    sessions = [
        {"date": day, "open": 10.4, "high": 10.6, "low": 10.3, "close": 10.4 if i != 21 else 10.2, "volume": 100.0}
        for i, day in enumerate(days)
    ]
    sessions[20]["close"] = 10.5
    found = MODULE.find_shrink_pullback_entry(
        signal_date=days[20],
        exit_date=days[24],
        sessions=sessions,
        market_calendar=days,
        lookback=20,
        window=8,
    )
    assert found["filled"] is False


def test_stabilize_buys_next_open_after_yang_above_prior_close() -> None:
    days = _weekdays(6)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.4, "volume": 1e6},
        {"date": days[1], "open": 10.3, "high": 10.4, "low": 10.0, "close": 10.1, "volume": 1e6},
        {"date": days[2], "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4, "volume": 1e6},
        {"date": days[3], "open": 10.35, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1e6},
        {"date": days[4], "open": 10.4, "high": 10.6, "low": 10.3, "close": 10.5, "volume": 1e6},
        {"date": days[5], "open": 10.5, "high": 10.7, "low": 10.4, "close": 10.6, "volume": 1e6},
    ]
    found = MODULE.find_stabilize_entry(
        signal_date=days[0],
        exit_date=days[5],
        sessions=sessions,
        market_calendar=days,
        window=3,
    )
    assert found["filled"] is True
    assert found["entry_date"] == days[3].isoformat()


def test_stock_hole_does_not_roll_pullback() -> None:
    days = _weekdays(25)
    sessions = [
        {"date": day, "open": 10.4, "high": 10.6, "low": 10.3, "close": 10.4, "volume": 50.0 if i == 21 else 100.0}
        for i, day in enumerate(days)
    ]
    sessions[20]["close"] = 10.5
    sessions[20]["low"] = 10.3
    stock = [row for row in sessions if row["date"] != days[21]]
    found = MODULE.find_shrink_pullback_entry(
        signal_date=days[20],
        exit_date=days[24],
        sessions=stock,
        market_calendar=days,
        lookback=20,
        window=8,
    )
    assert found["filled"] is False
    assert found["reason"] == "missing_bar"
