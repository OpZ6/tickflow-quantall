import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.backtest.engine import MatcherConfig

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_failed_breakout_kind.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_failed_breakout_kind", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CUP_RUN = "20260909T133226351846Z"
VCP_ALL_MARKET_TRAIN = 474
VCP_321_N = 321

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


def _sessions(prices: list[tuple[float, float, float, float]], start: date = date(2020, 1, 2)) -> list[dict]:
    days = _weekdays(len(prices), start)
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


def test_entry_day_close_below_cost_sells_next_open() -> None:
    sessions = _sessions(
        [
            (10.0, 10.2, 9.7, 9.8),
            (9.75, 9.9, 9.6, 9.7),
            (12.0, 12.2, 11.8, 12.0),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_entry_day_close_stop_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=0.18,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is True
    assert applied["early_exit_date"] == days[1].isoformat()
    expected = MODULE.net_round_trip(
        9.75 / 10.0 - 1.0, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[1])
    )
    assert applied["pnl"] == pytest.approx(expected)
    assert applied["pnl"] < 9.75 / 10.0 - 1.0
    assert applied["reason"] == "entry_day_close_below_cost"


def test_entry_day_close_at_or_above_cost_keeps_baseline() -> None:
    sessions = _sessions(
        [
            (10.0, 10.2, 9.8, 10.0),
            (10.0, 10.1, 9.7, 9.8),
            (9.8, 10.0, 9.6, 9.7),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_entry_day_close_stop_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=-0.03,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["pnl"] == -0.03

    sessions[0]["close"] = 10.1
    applied = MODULE.apply_entry_day_close_stop_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=0.04,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["pnl"] == 0.04


def test_does_not_wait_for_second_bar_or_plus_3pct_print() -> None:
    sessions = _sessions(
        [
            (10.0, 10.4, 9.7, 9.85),
            (9.8, 10.5, 9.7, 10.4),
            (10.4, 10.6, 10.2, 10.5),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_entry_day_close_stop_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=0.05,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is True
    assert applied["early_exit_date"] == days[1].isoformat()
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "apply_two_bar_no_demand_to_fill" not in source
    assert "require_underwater" not in source
    assert "DEMAND_PCT" not in source


def test_stock_hole_on_market_session_does_not_roll() -> None:
    market = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8)]
    sessions = [
        {"date": date(2020, 1, 6), "open": 10.0, "high": 10.2, "low": 9.7, "close": 9.8, "volume": 1e6},
        {"date": date(2020, 1, 8), "open": 9.5, "high": 9.6, "low": 9.4, "close": 9.5, "volume": 1e6},
    ]
    applied = MODULE.apply_entry_day_close_stop_to_fill(
        entry_date=date(2020, 1, 6),
        exit_date=date(2020, 1, 8),
        entry_price=10.0,
        baseline_pnl=-0.05,
        sessions=sessions,
        market_calendar=market,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] in {"missing_exit_bar", "missing_bar"}
    assert applied["pnl"] == -0.05
    assert applied.get("early_exit_date") != "2020-01-08"


def test_one_price_limit_down_does_not_roll() -> None:
    sessions = _sessions(
        [
            (10.0, 10.2, 9.7, 9.8),
            (9.0, 9.0, 9.0, 9.0),
            (12.0, 12.2, 11.8, 12.0),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_entry_day_close_stop_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=0.18,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "early_exit_blocked"
    assert applied["pnl"] == 0.18
    assert applied.get("early_exit_date") != days[2].isoformat()


def test_overlay_targets_failed_breakout_stop_on_vcp_179() -> None:
    assert MODULE.VCP_RUN == "20260909T030431101979Z"
    assert MODULE.VCP_RUN != CUP_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "apply_entry_day_close_stop_to_fill" in source
    assert "from research_vcp_loss_path_kind import build_main_book" in source
    assert "upper_half" in source
    assert CUP_RUN not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 179
    assert protocol["baseline"]["n_train"] != VCP_ALL_MARKET_TRAIN
    assert protocol["baseline"]["n_train"] != VCP_321_N
    assert protocol["baseline"]["run_id"] == MODULE.VCP_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.019889
    assert protocol["change"]["id"] == "entry_day_close_below_cost"
    assert protocol["change"]["kind"] == "止损"
    assert protocol["change"]["attacked_path"] == "失败突破"
    assert protocol["change"]["id"] != "high_print_breakeven"
    assert protocol["change"]["id"] != "volume_ratio_ge_1_50"
    assert protocol["change"]["id"] != "tightness_ge_0_40"
    assert protocol["change"]["kind"] != "利润保护"
