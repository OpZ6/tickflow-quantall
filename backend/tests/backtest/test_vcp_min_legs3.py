import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_min_legs.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_min_legs", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CUP_RUN = "20260909T133226351846Z"
VCP_ALL_MARKET_TRAIN = 474


def _weekdays(n: int, start: date = date(2020, 1, 2)) -> list[date]:
    days = []
    cursor = start
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_keep_min_legs_keeps_three_and_drops_two() -> None:
    three = {"valid": True, "legs": [{"depth": 0.2}, {"depth": 0.12}, {"depth": 0.06}]}
    two = {"valid": True, "legs": [{"depth": 0.2}, {"depth": 0.12}]}
    assert MODULE.keep_min_legs(three, min_legs=3) is True
    assert MODULE.keep_min_legs(two, min_legs=3) is False
    assert MODULE.keep_min_legs(None, min_legs=3) is False
    assert MODULE.keep_min_legs({"valid": False, "legs": three["legs"]}, min_legs=3) is False


def test_missing_signal_bar_or_reconstruction_is_not_kept() -> None:
    days = _weekdays(5)
    sessions = {
        "600000.SH": [
            {"date": days[1], "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1e6},
        ]
    }
    trade = {
        "symbol": "600000.SH",
        "entry_signal_date": days[0].isoformat(),
        "pnl_pct": 0.02,
    }
    primary = MODULE.reconstruct_primary(trade, sessions, {"legacy_semantics": True})
    assert primary is None
    kept, short, missing = MODULE.filter_min_legs([trade], sessions, {}, min_legs=3)
    assert kept == []
    assert short == 0
    assert missing == 1


def test_overlay_targets_vcp_321_not_all_market_or_cup() -> None:
    assert MODULE.VCP_RUN == "20260909T030431101979Z"
    assert MODULE.VCP_RUN != CUP_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "upper_half" in source
    assert "apply_breakeven_after_gain_to_fill" in source
    assert "filter_min_legs" in source
    assert "keep_min_legs" in source
    assert "from app.strategy.builtin._quants_vcp import detect" in source
    assert CUP_RUN not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 321
    assert protocol["baseline"]["n_train"] != VCP_ALL_MARKET_TRAIN
    assert protocol["baseline"]["run_id"] == MODULE.VCP_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.012957
    assert protocol["change"]["id"] == "min_legs_ge_3"
