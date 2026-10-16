import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.backtest.engine import MatcherConfig

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_loss_path_kind.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_loss_path_kind", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CUP_RUN = "20260909T133226351846Z"
VCP_ALL_MARKET_TRAIN = 474
VCP_321_N = 321


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
    assert MODULE.label_held_loss_path(pnl=-0.01, mfe=0.029) == "失败突破"
    assert MODULE.label_held_loss_path(pnl=-0.02, mfe=0.04) == "磨掉"
    assert MODULE.label_held_loss_path(pnl=-0.01, mfe=0.03) == "磨掉"
    assert MODULE.label_held_loss_path(pnl=-0.01, mfe=0.049) == "磨掉"


def test_held_excursions_use_highs_and_lows_until_exit() -> None:
    days = _weekdays(4)
    sessions = [
        {"date": days[0], "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6},
        {"date": days[1], "open": 100.0, "high": 106.0, "low": 98.0, "close": 103.0, "volume": 1e6},
        {"date": days[2], "open": 103.0, "high": 103.0, "low": 94.0, "close": 95.0, "volume": 1e6},
        {"date": days[3], "open": 120.0, "high": 125.0, "low": 118.0, "close": 122.0, "volume": 1e6},
    ]
    path = MODULE.held_excursions(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=100.0,
        sessions=sessions,
        market_calendar=days,
    )
    assert path["complete"] is True
    assert path["mfe"] == pytest.approx(0.06)
    assert path["mae"] == pytest.approx(-0.06)
    assert path["holding_bars"] == 3
    assert MODULE.label_held_loss_path(pnl=-0.05, mfe=path["mfe"]) == "给回"


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


def test_summarize_loss_paths_counts_loser_buckets() -> None:
    records = [
        {"path": "赢家", "pnl": 0.10, "mfe": 0.12, "holding_bars": 8},
        {"path": "给回", "pnl": -0.04, "mfe": 0.07, "holding_bars": 6},
        {"path": "给回", "pnl": -0.02, "mfe": 0.05, "holding_bars": 4},
        {"path": "失败突破", "pnl": -0.05, "mfe": 0.01, "holding_bars": 3},
        {"path": "磨掉", "pnl": -0.03, "mfe": 0.04, "holding_bars": 10},
    ]
    summary = MODULE.summarize_loss_paths(records)
    assert summary["book_n"] == 5
    assert summary["loser_n"] == 4
    assert summary["paths"]["给回"]["n"] == 2
    assert summary["paths"]["失败突破"]["n"] == 1
    assert summary["paths"]["磨掉"]["n"] == 1
    assert summary["paths"]["赢家"]["n"] == 1
    assert summary["attacked_path"] in {"给回", "失败突破", "磨掉"}
    assert summary["paths"]["给回"]["share_of_losers"] == pytest.approx(0.5)


def test_overlay_targets_vcp_179_not_all_market_or_cup() -> None:
    assert MODULE.VCP_RUN == "20260909T030431101979Z"
    assert MODULE.VCP_RUN != CUP_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "label_held_loss_path" in source
    assert "held_excursions" in source
    assert "filter_min_legs" in source
    assert "upper_half" in source
    assert "apply_breakeven_after_gain_to_fill" in source
    assert "apply_high_print_breakeven_to_fill" in source
    assert CUP_RUN not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 179
    assert protocol["baseline"]["n_train"] != VCP_ALL_MARKET_TRAIN
    assert protocol["baseline"]["n_train"] != VCP_321_N
    assert protocol["baseline"]["run_id"] == MODULE.VCP_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.019889
    assert protocol["change"]["id"] == "high_print_breakeven"
    assert protocol["change"]["kind"] == "利润保护"
    assert protocol["change"]["attacked_path"] == "给回"
    assert protocol["change"]["id"] != "volume_ratio_ge_1_50"
    assert protocol["change"]["id"] != "tightness_ge_0_40"


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


def test_high_print_then_close_below_entry_sells_next_open() -> None:
    sessions = _sessions(
        [
            (10.0, 10.6, 9.9, 10.3),
            (10.3, 10.4, 9.8, 9.9),
            (9.85, 10.0, 9.7, 9.8),
            (12.0, 12.2, 11.8, 12.0),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_high_print_breakeven_to_fill(
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
    gross = 9.85 / 10.0 - 1.0
    expected = MODULE.net_round_trip(
        gross, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[2])
    )
    assert applied["pnl"] == pytest.approx(expected)
    assert applied["pnl"] < gross
    assert applied["reason"] == "high_print_breakeven"


def test_same_bar_high_print_and_close_below_entry_sells_next_open() -> None:
    sessions = _sessions(
        [
            (10.0, 10.6, 9.7, 9.8),
            (9.7, 9.8, 9.6, 9.7),
            (12.0, 12.2, 11.8, 12.0),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_high_print_breakeven_to_fill(
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
        9.7 / 10.0 - 1.0, CONFIG.buy_cost_pct(), CONFIG.sell_cost_pct(days[1])
    )
    assert applied["pnl"] == pytest.approx(expected)


def test_high_never_plus_5pct_keeps_baseline() -> None:
    sessions = _sessions(
        [
            (10.0, 10.4, 9.8, 10.1),
            (10.1, 10.3, 9.7, 9.8),
            (9.8, 10.0, 9.6, 9.7),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_high_print_breakeven_to_fill(
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


def test_high_print_but_close_holds_entry_keeps_baseline() -> None:
    sessions = _sessions(
        [
            (10.0, 10.6, 9.9, 10.4),
            (10.4, 10.5, 10.0, 10.1),
            (10.1, 10.3, 10.0, 10.2),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_high_print_breakeven_to_fill(
        entry_date=days[0],
        exit_date=days[2],
        entry_price=10.0,
        baseline_pnl=0.02,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["pnl"] == 0.02


def test_stock_hole_on_market_session_does_not_roll() -> None:
    market = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8), date(2020, 1, 9)]
    sessions = [
        {"date": date(2020, 1, 6), "open": 10.0, "high": 10.6, "low": 9.9, "close": 10.3, "volume": 1e6},
        {"date": date(2020, 1, 8), "open": 9.5, "high": 9.6, "low": 9.4, "close": 9.5, "volume": 1e6},
        {"date": date(2020, 1, 9), "open": 9.4, "high": 9.5, "low": 9.3, "close": 9.4, "volume": 1e6},
    ]
    applied = MODULE.apply_high_print_breakeven_to_fill(
        entry_date=date(2020, 1, 6),
        exit_date=date(2020, 1, 9),
        entry_price=10.0,
        baseline_pnl=-0.06,
        sessions=sessions,
        market_calendar=market,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "missing_bar"
    assert applied["pnl"] == -0.06
    assert applied.get("early_exit_date") != "2020-01-08"


def test_one_price_limit_down_does_not_roll() -> None:
    sessions = _sessions(
        [
            (10.0, 10.6, 9.9, 10.3),
            (10.3, 10.4, 9.8, 9.9),
            (9.0, 9.0, 9.0, 9.0),
            (12.0, 12.2, 11.8, 12.0),
        ]
    )
    days = [row["date"] for row in sessions]
    applied = MODULE.apply_high_print_breakeven_to_fill(
        entry_date=days[0],
        exit_date=days[3],
        entry_price=10.0,
        baseline_pnl=0.18,
        sessions=sessions,
        market_calendar=days,
        config=CONFIG,
    )
    assert applied["shortened"] is False
    assert applied["reason"] == "early_exit_blocked"
    assert applied["pnl"] == 0.18
    assert applied.get("early_exit_date") != days[3].isoformat()
