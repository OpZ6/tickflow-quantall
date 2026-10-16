import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_close_clears_prior_high.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_close_clears_prior_high", SCRIPT_PATH)
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


def _bar(day: date, open_px: float, high: float, low: float, close: float) -> dict:
    return {
        "date": day,
        "open": open_px,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1_000_000.0,
    }


def test_close_above_prior_high_keeps() -> None:
    days = _weekdays(3)
    sessions = [
        _bar(days[0], 10.0, 10.5, 9.8, 10.2),
        _bar(days[1], 10.3, 11.0, 10.1, 10.8),
        _bar(days[2], 10.8, 11.2, 10.6, 11.0),
    ]
    flag = MODULE.breakout_close_clears_prior_high(
        signal_date=days[1],
        sessions=sessions,
        market_calendar=days,
    )
    assert flag["clears"] is True
    assert flag["reason"] == "clears_prior_high"


def test_close_at_or_below_prior_high_drops() -> None:
    days = _weekdays(2)
    sessions = [
        _bar(days[0], 10.0, 10.5, 9.8, 10.2),
        _bar(days[1], 10.3, 10.8, 10.0, 10.5),
    ]
    equal = MODULE.breakout_close_clears_prior_high(
        signal_date=days[1], sessions=sessions, market_calendar=days,
    )
    assert equal["clears"] is False
    assert equal["reason"] == "fails_prior_high"

    sessions[1]["close"] = 10.4
    below = MODULE.breakout_close_clears_prior_high(
        signal_date=days[1], sessions=sessions, market_calendar=days,
    )
    assert below["clears"] is False
    assert below["reason"] == "fails_prior_high"


def test_wick_above_prior_high_but_close_inside_drops() -> None:
    days = _weekdays(2)
    sessions = [
        _bar(days[0], 10.0, 10.5, 9.8, 10.2),
        _bar(days[1], 10.3, 10.9, 10.0, 10.4),
    ]
    flag = MODULE.breakout_close_clears_prior_high(
        signal_date=days[1], sessions=sessions, market_calendar=days,
    )
    assert flag["clears"] is False
    assert sessions[1]["high"] > 10.5
    assert sessions[1]["close"] < 10.5


def test_prior_session_hole_does_not_roll() -> None:
    market = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8)]
    sessions = [
        _bar(date(2020, 1, 6), 10.0, 9.5, 9.0, 9.4),
        _bar(date(2020, 1, 8), 10.3, 11.0, 10.1, 10.8),
    ]
    flag = MODULE.breakout_close_clears_prior_high(
        signal_date=date(2020, 1, 8),
        sessions=sessions,
        market_calendar=market,
    )
    assert flag["clears"] is False
    assert flag["reason"] == "missing_prior_bar"


def test_limit_down_signal_bar_is_evaluated_not_skipped() -> None:
    days = _weekdays(2)
    sessions = [
        _bar(days[0], 10.0, 10.5, 9.8, 10.2),
        _bar(days[1], 9.0, 9.0, 9.0, 9.0),
    ]
    flag = MODULE.breakout_close_clears_prior_high(
        signal_date=days[1], sessions=sessions, market_calendar=days,
    )
    assert flag["clears"] is False
    assert flag["reason"] == "fails_prior_high"


def test_overlay_targets_failed_breakout_buy_kind_on_vcp_179() -> None:
    assert MODULE.VCP_RUN == "20260909T030431101979Z"
    assert MODULE.VCP_RUN != CUP_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "breakout_close_clears_prior_high" in source
    assert "from research_vcp_loss_path_kind import build_main_book" in source
    assert "upper_half" in source
    assert "apply_entry_day_close_stop_to_fill" not in source
    assert "apply_two_bar_no_demand_to_fill" not in source
    assert "breakout_bullish_bar" not in source
    assert "breakout_low_holds_prior_low" not in source
    assert CUP_RUN not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 179
    assert protocol["baseline"]["n_train"] != VCP_ALL_MARKET_TRAIN
    assert protocol["baseline"]["n_train"] != VCP_321_N
    assert protocol["baseline"]["run_id"] == MODULE.VCP_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.019889
    assert protocol["change"]["id"] == "close_clears_prior_high"
    assert protocol["change"]["kind"] == "突破"
    assert protocol["change"]["attacked_path"] == "失败突破"
    assert protocol["change"]["kind"] != "止损"
    assert protocol["change"]["kind"] != "利润保护"
    assert protocol["change"]["id"] != "volume_ratio_ge_1_50"
    assert protocol["change"]["id"] != "tightness_ge_0_40"
    assert protocol["change"]["id"] != "entry_day_close_below_cost"
