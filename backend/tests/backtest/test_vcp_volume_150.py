import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_volume_150.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_volume_150", SCRIPT_PATH)
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


def test_keep_volume_ratio_uses_detector_field_and_cuts_at_1_50() -> None:
    keep = {"valid": True, "volume_ratio": 1.50, "legs": [{}, {}, {}]}
    drop = {"valid": True, "volume_ratio": 1.49, "legs": [{}, {}, {}]}
    assert MODULE.keep_volume_ratio(keep, min_ratio=1.50) is True
    assert MODULE.keep_volume_ratio(drop, min_ratio=1.50) is False
    assert MODULE.keep_volume_ratio(None, min_ratio=1.50) is False
    assert MODULE.keep_volume_ratio({"valid": True, "volume_ratio": None}, min_ratio=1.50) is False
    assert MODULE.keep_volume_ratio({"valid": False, "volume_ratio": 2.0}, min_ratio=1.50) is False


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
    kept, thin, missing = MODULE.filter_volume_ratio([trade], sessions, {}, min_ratio=1.50)
    assert kept == []
    assert thin == 0
    assert missing == 1


def test_overlay_targets_vcp_179_not_all_market_or_cup() -> None:
    assert MODULE.VCP_RUN == "20260909T030431101979Z"
    assert MODULE.VCP_RUN != CUP_RUN
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "filter_min_legs" in source
    assert "filter_volume_ratio" in source
    assert "keep_volume_ratio" in source
    assert "volume_ratio" in source
    assert "upper_half" in source
    assert "apply_breakeven_after_gain_to_fill" in source
    assert "breakout_volume_expanded" not in source
    assert CUP_RUN not in source
    protocol = json.loads(Path(MODULE.DEFAULT_PROTOCOL).read_text(encoding="utf-8"))
    assert protocol["baseline"]["n_train"] == 179
    assert protocol["baseline"]["n_train"] != VCP_ALL_MARKET_TRAIN
    assert protocol["baseline"]["n_train"] != VCP_321_N
    assert protocol["baseline"]["run_id"] == MODULE.VCP_RUN
    assert protocol["baseline"]["avg_pnl"] == 0.019889
    assert protocol["change"]["id"] == "volume_ratio_ge_1_50"
