import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.backtest.engine import MatcherConfig

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_cup_breakeven.py"
SPEC = importlib.util.spec_from_file_location("research_cup_breakeven", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VCP_MAIN_RUN = "20260909T030431101979Z"
CUP_ALL_MARKET_N = 98489
CUP_LEADER_OPEN_N = 3750

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


def test_breakeven_after_5pct_shortens_when_close_falls_back_through_entry() -> None:
    days = _weekdays(5)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 1e6},
        {"date": days[1], "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6, "volume": 1e6},
        {"date": days[2], "open": 10.5, "high": 10.6, "low": 9.8, "close": 9.9, "volume": 1e6},
        {"date": days[3], "open": 9.95, "high": 10.1, "low": 9.8, "close": 10.0, "volume": 1e6},
        {"date": days[4], "open": 11.0, "high": 11.2, "low": 10.8, "close": 11.0, "volume": 1e6},
    ]
    applied = MODULE.apply_breakeven_after_gain_to_fill(
        entry_date=days[0],
        exit_date=days[4],
        entry_price=10.0,
        baseline_pnl=0.10,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
        activate_pct=0.05,
    )
    assert applied["shortened"] is True
    assert applied["early_exit_date"] == days[3].isoformat()
    gross = 9.95 / 10.0 - 1.0
    expected = MODULE.net_round_trip(gross, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[3]))
    assert applied["pnl"] == pytest.approx(expected)
    assert applied["pnl"] < 0.10


def test_never_reaching_5pct_keeps_original_pnl() -> None:
    days = _weekdays(4)
    sessions = [
        {"date": day, "open": 10.0, "high": 10.3, "low": 9.8, "close": 10.2, "volume": 1e6}
        for day in days
    ]
    applied = MODULE.apply_breakeven_after_gain_to_fill(
        entry_date=days[0],
        exit_date=days[-1],
        entry_price=10.0,
        baseline_pnl=0.04,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
        activate_pct=0.05,
    )
    assert applied["shortened"] is False
    assert applied["pnl"] == 0.04


def test_missing_stock_bar_on_market_session_does_not_roll() -> None:
    days = _weekdays(5)
    sessions = [
        {"date": days[0], "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 1e6},
        {"date": days[1], "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6, "volume": 1e6},
        {"date": days[3], "open": 9.5, "high": 9.6, "low": 9.4, "close": 9.5, "volume": 1e6},
        {"date": days[4], "open": 11.0, "high": 11.2, "low": 10.8, "close": 11.0, "volume": 1e6},
    ]
    applied = MODULE.apply_breakeven_after_gain_to_fill(
        entry_date=days[0],
        exit_date=days[4],
        entry_price=10.0,
        baseline_pnl=0.08,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
        activate_pct=0.05,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "missing_bar"
    assert applied["pnl"] == 0.08


def test_overlay_targets_cup_2034_not_all_market_or_vcp() -> None:
    assert MODULE.CUP_RUN == "20260909T133226351846Z"
    assert MODULE.CUP_RUN != VCP_MAIN_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "filter_gate" in source
    assert "filter_rs" in source
    assert "filter_upper" in source
    assert "apply_breakeven_after_gain_to_fill" in source
    assert "detect(" not in source
    assert VCP_MAIN_RUN not in source
    assert "vcp_leader_breakout" not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 2034
    assert protocol["baseline"]["n_train"] != CUP_ALL_MARKET_N
    assert protocol["baseline"]["n_train"] != CUP_LEADER_OPEN_N
    assert protocol["baseline"]["run_id"] == MODULE.CUP_RUN
    assert protocol["change"]["id"] == "breakeven_after_5pct_close"
    assert protocol["baseline"]["avg_pnl"] == pytest.approx(0.005438)
