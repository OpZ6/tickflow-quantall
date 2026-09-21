import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_cup_upper_half.py"
SPEC = importlib.util.spec_from_file_location("research_cup_upper_half", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VCP_MAIN_RUN = "20260909T030431101979Z"
CUP_ALL_MARKET_N = 98489


def _weekdays(n: int, start: date = date(2020, 1, 2)) -> list[date]:
    days = []
    cursor = start
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_upper_half_keeps_ge_half_and_drops_below() -> None:
    days = _weekdays(2)
    sessions = {
        "600000.SH": [
            {"date": days[0], "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.1, "volume": 1e6},
            {"date": days[1], "open": 10.0, "high": 11.0, "low": 9.0, "close": 9.9, "volume": 1e6},
        ]
    }
    trades = [
        {
            "symbol": "600000.SH",
            "entry_signal_date": days[0].isoformat(),
            "pnl_pct": 0.02,
        },
        {
            "symbol": "600000.SH",
            "entry_signal_date": days[1].isoformat(),
            "pnl_pct": -0.01,
        },
    ]
    kept, lower, missing = MODULE.filter_upper(trades, sessions, days)
    assert [t["entry_signal_date"] for t in kept] == [days[0].isoformat()]
    assert lower == 1
    assert missing == 0
    flag_keep = MODULE.breakout_close_upper_half(
        signal_date=days[0], sessions=sessions["600000.SH"], market_calendar=days
    )
    flag_drop = MODULE.breakout_close_upper_half(
        signal_date=days[1], sessions=sessions["600000.SH"], market_calendar=days
    )
    assert flag_keep["upper"] is True
    assert flag_keep["location"] >= 0.5
    assert flag_drop["upper"] is False
    assert flag_drop["location"] < 0.5


def test_missing_signal_bar_is_not_kept() -> None:
    days = _weekdays(2)
    sessions = {
        "600000.SH": [
            {"date": days[1], "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.8, "volume": 1e6},
        ]
    }
    trades = [
        {
            "symbol": "600000.SH",
            "entry_signal_date": days[0].isoformat(),
            "pnl_pct": 0.04,
        }
    ]
    kept, lower, missing = MODULE.filter_upper(trades, sessions, days)
    assert kept == []
    assert lower == 0
    assert missing == 1


def test_overlay_is_cup_leader_open_not_all_market_or_vcp() -> None:
    assert MODULE.CUP_RUN == "20260909T133226351846Z"
    assert MODULE.CUP_RUN != VCP_MAIN_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "filter_gate" in source
    assert "filter_rs" in source
    assert "filter_upper" in source
    assert "breakout_close_upper_half" in source
    assert "detect(" not in source
    assert VCP_MAIN_RUN not in source
    assert "vcp_leader_breakout" not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 3750
    assert protocol["baseline"]["n_train"] != CUP_ALL_MARKET_N
    assert protocol["baseline"]["run_id"] == MODULE.CUP_RUN
    assert protocol["change"]["id"] == "signal_close_location_ge_0_5"
