import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.backtest.engine import MatcherConfig

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_cup_loss_path_kind.py"
SPEC = importlib.util.spec_from_file_location("research_cup_loss_path_kind", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VCP_MAIN_RUN = "20260909T030431101979Z"
CUP_ALL_MARKET_N = 98489
CUP_LEADER_OPEN_N = 3750


def _weekdays(n: int, start: date = date(2020, 1, 2)) -> list[date]:
    days = []
    cursor = start
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_labels_partition_held_path_without_rewriting_signal() -> None:
    assert MODULE.label_held_loss_path(pnl=0.08, mfe=0.12) == "赢家"
    assert MODULE.label_held_loss_path(pnl=-0.03, mfe=0.06) == "给回"
    assert MODULE.label_held_loss_path(pnl=0.0, mfe=0.05) == "给回"
    assert MODULE.label_held_loss_path(pnl=-0.04, mfe=0.02) == "失败突破"
    assert MODULE.label_held_loss_path(pnl=-0.02, mfe=0.04) == "磨掉"


def test_held_excursions_do_not_roll_a_stock_hole() -> None:
    market = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8)]
    sessions = [
        {"date": date(2020, 1, 6), "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": 1e6},
        {"date": date(2020, 1, 8), "open": 9.5, "high": 9.6, "low": 9.4, "close": 9.5, "volume": 1e6},
    ]
    path = MODULE.held_excursions(
        entry_date=date(2020, 1, 6),
        exit_date=date(2020, 1, 8),
        entry_price=10.0,
        sessions=sessions,
        market_calendar=market,
    )
    assert path["complete"] is False
    assert path["reason"] == "missing_bar"
    assert "mfe" not in path


def test_summarize_loss_paths_names_largest_loser_bucket() -> None:
    records = [
        {"path": "赢家", "pnl": 0.10, "mfe": 0.12, "holding_bars": 8},
        {"path": "给回", "pnl": -0.04, "mfe": 0.07, "holding_bars": 6},
        {"path": "失败突破", "pnl": -0.05, "mfe": 0.01, "holding_bars": 3},
        {"path": "失败突破", "pnl": -0.06, "mfe": 0.02, "holding_bars": 4},
        {"path": "磨掉", "pnl": -0.03, "mfe": 0.04, "holding_bars": 10},
    ]
    summary = MODULE.summarize_loss_paths(records)
    assert summary["attacked_path"] == "失败突破"
    assert summary["paths"]["失败突破"]["n"] == 2
    assert summary["loser_n"] == 4


def test_overlay_targets_cup_2034_not_vcp_179() -> None:
    assert MODULE.CUP_RUN == "20260909T133226351846Z"
    assert MODULE.CUP_RUN != VCP_MAIN_RUN
    assert MODULE.VCP_MAIN_RUN == VCP_MAIN_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "build_cup_thin_book" in source
    assert "filter_upper" in source
    assert "label_held_loss_path" in source
    assert "apply_entry_day_close_stop_to_fill" in source
    assert VCP_MAIN_RUN in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 2034
    assert protocol["baseline"]["n_train"] != CUP_ALL_MARKET_N
    assert protocol["baseline"]["n_train"] != CUP_LEADER_OPEN_N
    assert protocol["baseline"]["run_id"] == MODULE.CUP_RUN
    assert protocol["baseline"]["run_id"] != VCP_MAIN_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.005438
    assert protocol["change"]["id"] == "cup_entry_day_close_below_cost"
    assert protocol["change"]["kind"] == "止损"
    assert protocol["change"]["attacked_path"] == "失败突破"
    assert protocol["change"]["id"] != "volume_ratio_ge_1_50"
    assert protocol["change"]["id"] != "tightness_ge_0_40"
    assert protocol["change"]["id"] != "breakeven_after_5pct"
    assert "apply_breakeven_after_gain_to_fill" not in source


CONFIG = MatcherConfig(
    matching="open_t+1",
    commission_pct=0.0003,
    slippage_bps=10.0,
    stamp_tax_policy="a_share_historical",
)


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
        baseline_pnl=0.08,
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
        baseline_pnl=0.08,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "early_exit_blocked"
    assert applied["pnl"] == 0.08
    assert applied.get("early_exit_date") != days[2].isoformat()
