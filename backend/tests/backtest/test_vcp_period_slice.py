import importlib.util
from datetime import date
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_period_slice.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_period_slice", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_slice_keeps_completed_exits_in_window_and_lists_later_exits() -> None:
    trades = [
        {"entry_date": "2022-12-01", "exit_date": "2022-12-20", "pnl_pct": 0.01},
        {"entry_date": "2022-12-01", "exit_date": "2023-01-10", "pnl_pct": 0.50},
        {"entry_date": "2023-02-01", "exit_date": "2023-03-01", "pnl_pct": -0.02},
        {"entry_date": "2023-06-01", "exit_date": "2026-12-31", "pnl_pct": 0.80},
    ]
    complete, openish = MODULE.slice_trades(
        trades, date(2016, 1, 1), date(2022, 12, 31), date(2022, 12, 31)
    )
    assert len(complete) == 1
    assert complete[0]["exit_date"] == "2022-12-20"
    assert len(openish) == 1
    assert openish[0]["exit_date"] == "2023-01-10"
    val, later = MODULE.slice_trades(
        trades, date(2023, 1, 1), date(2026, 6, 30), date(2026, 6, 30)
    )
    assert [t["exit_date"] for t in val] == ["2023-03-01"]
    assert [t["exit_date"] for t in later] == ["2026-12-31"]
