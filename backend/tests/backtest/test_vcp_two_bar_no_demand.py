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


def _sessions(prices: list[tuple[float, float, float, float]], start: date = date(2020, 1, 2)) -> list[dict]:
    days = []
    cursor = start
    while len(days) < len(prices):
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    rows = []
    for day, (open_px, high, low, close) in zip(days, prices, strict=True):
        rows.append(
            {
                "date": day,
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return rows


def _calendar(sessions: list[dict]) -> list[date]:
    return [row["date"] for row in sessions]


def test_never_plus_3pct_sells_two_sessions_after_entry() -> None:
    sessions = _sessions(
        [
            (10.0, 10.1, 9.9, 10.0),
            (10.0, 10.2, 9.8, 10.0),
            (9.8, 9.9, 9.7, 9.8),
            (11.0, 11.2, 10.8, 11.0),
        ]
    )
    applied = MODULE.apply_two_bar_no_demand_to_fill(
        entry_date=sessions[0]["date"],
        exit_date=sessions[3]["date"],
        entry_price=10.0,
        baseline_pnl=0.08,
        sessions=sessions,
        market_calendar=_calendar(sessions),
        config=CONFIG,
    )
    assert applied["shortened"] is True
    assert applied["early_exit_date"] == sessions[2]["date"].isoformat()
    gross = 9.8 / 10.0 - 1.0
    expected = MODULE.net_round_trip(
        gross, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(sessions[2]["date"])
    )
    assert applied["pnl"] == pytest.approx(expected)
    assert applied["pnl"] < gross


def test_plus_3pct_print_keeps_baseline_exit() -> None:
    sessions = _sessions(
        [
            (10.0, 10.4, 9.9, 10.2),
            (10.2, 10.3, 10.0, 10.2),
            (10.2, 10.5, 10.1, 10.4),
        ]
    )
    applied = MODULE.apply_two_bar_no_demand_to_fill(
        entry_date=sessions[0]["date"],
        exit_date=sessions[2]["date"],
        entry_price=10.0,
        baseline_pnl=0.05,
        sessions=sessions,
        market_calendar=_calendar(sessions),
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "demand_printed"
    assert applied["pnl"] == 0.05


def test_missing_bar_does_not_roll() -> None:
    sessions = _sessions(
        [
            (10.0, 10.1, 9.9, 10.0),
            (10.0, 10.1, 9.9, 10.0),
        ]
    )
    applied = MODULE.apply_two_bar_no_demand_to_fill(
        entry_date=sessions[0]["date"],
        exit_date=date(2020, 2, 3),
        entry_price=10.0,
        baseline_pnl=-0.02,
        sessions=sessions,
        market_calendar=[*_calendar(sessions), date(2020, 1, 6), date(2020, 1, 7)],
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "missing_early_exit_bar"
    assert applied["pnl"] == -0.02


def test_one_price_limit_down_does_not_roll() -> None:
    sessions = _sessions(
        [
            (10.0, 10.1, 9.9, 10.0),
            (10.0, 10.1, 9.9, 10.0),
            (9.0, 9.0, 9.0, 9.0),
            (11.0, 11.1, 10.9, 11.0),
        ]
    )
    applied = MODULE.apply_two_bar_no_demand_to_fill(
        entry_date=sessions[0]["date"],
        exit_date=sessions[3]["date"],
        entry_price=10.0,
        baseline_pnl=0.04,
        sessions=sessions,
        market_calendar=_calendar(sessions),
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "early_exit_blocked"
    assert applied["pnl"] == 0.04


def test_stock_hole_on_market_session_does_not_roll() -> None:
    """Entry Monday 2020-01-06; Tuesday missing on the stock; never +3% must keep baseline."""
    market = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8), date(2020, 1, 9)]
    sessions = [
        {"date": date(2020, 1, 6), "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": 1_000_000.0},
        {"date": date(2020, 1, 8), "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": 1_000_000.0},
        {"date": date(2020, 1, 9), "open": 9.5, "high": 9.6, "low": 9.4, "close": 9.5, "volume": 1_000_000.0},
    ]
    applied = MODULE.apply_two_bar_no_demand_to_fill(
        entry_date=date(2020, 1, 6),
        exit_date=date(2020, 1, 9),
        entry_price=10.0,
        baseline_pnl=0.07,
        sessions=sessions,
        market_calendar=market,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "missing_early_exit_bar"
    assert applied["pnl"] == 0.07
    assert applied.get("early_exit_date") != "2020-01-09"


def test_independent_stats_match_engine_payoff_definition() -> None:
    stats = MODULE.independent_trade_stats([0.10, -0.05, 0.0])
    assert stats["n_trades"] == 3
    assert stats["win_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert stats["avg_win"] == pytest.approx(0.10)
    assert stats["avg_loss"] == pytest.approx(0.025)
    assert stats["profit_factor"] == pytest.approx(0.10 / 0.025)
    assert stats["avg_pnl"] == pytest.approx(0.05 / 3, abs=1e-6)


@pytest.mark.parametrize("second_close,shortened", [(9.9, True), (10.0, False), (10.1, False), (float("nan"), False)])
def test_underwater_gate_uses_second_close_before_exit(second_close, shortened):
    sessions = _sessions([
        (10.0, 10.1, 9.8, 10.0),
        (10.0, 10.2, 9.8, second_close),
        (9.8, 10.2, 9.7, 10.1),
        (11.0, 11.2, 10.8, 11.0),
    ])
    applied = MODULE.apply_two_bar_no_demand_to_fill(
        entry_date=sessions[0]["date"], exit_date=sessions[3]["date"],
        entry_price=10.0, baseline_pnl=0.08, sessions=sessions,
        market_calendar=_calendar(sessions), config=CONFIG, require_underwater=True,
    )
    assert applied["shortened"] is shortened
    if shortened:
        assert applied["early_exit_date"] == sessions[2]["date"].isoformat()
        assert applied["pnl"] == pytest.approx(MODULE.net_round_trip(
            -0.02, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(sessions[2]["date"])))
    else:
        assert applied["pnl"] == 0.08
