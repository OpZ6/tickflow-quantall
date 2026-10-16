import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_tightness.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_tightness", SCRIPT_PATH)
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


def test_keep_tightness_uses_detector_field_and_cuts_at_0_40() -> None:
    keep = {"valid": True, "tightness": 0.40, "legs": [{}, {}, {}]}
    drop = {"valid": True, "tightness": 0.39, "legs": [{}, {}, {}]}
    assert MODULE.keep_tightness(keep, min_tightness=0.40) is True
    assert MODULE.keep_tightness(drop, min_tightness=0.40) is False
    assert MODULE.keep_tightness(None, min_tightness=0.40) is False
    assert MODULE.keep_tightness({"valid": True, "tightness": None}, min_tightness=0.40) is False
    assert MODULE.keep_tightness({"valid": False, "tightness": 0.80}, min_tightness=0.40) is False


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
    kept, loose, missing = MODULE.filter_tightness([trade], sessions, {}, min_tightness=0.40)
    assert kept == []
    assert loose == 0
    assert missing == 1


def test_overlay_targets_vcp_179_not_all_market_or_cup() -> None:
    assert MODULE.VCP_RUN == "20260909T030431101979Z"
    assert MODULE.VCP_RUN != CUP_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "filter_min_legs" in source
    assert "filter_tightness" in source
    assert "keep_tightness" in source
    assert "tightness" in source
    assert "upper_half" in source
    assert "apply_breakeven_after_gain_to_fill" in source
    assert "volume_ratio_ge_1_60" not in source
    assert CUP_RUN not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 179
    assert protocol["baseline"]["n_train"] != VCP_ALL_MARKET_TRAIN
    assert protocol["baseline"]["n_train"] != VCP_321_N
    assert protocol["baseline"]["run_id"] == MODULE.VCP_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.019889
    assert protocol["change"]["id"] == "tightness_ge_0_40"
