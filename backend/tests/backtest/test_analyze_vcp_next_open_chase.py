from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from analyze_vcp_next_open_chase import analyze


def test_actual_open_chase_uses_pivot_and_strict_boundary() -> None:
    trades = [
        {"symbol": "A", "entry_signal_date": "2017-01-02", "entry_date": "2017-01-03",
         "entry_price": 10.25, "pnl_pct": 0.1, "exit_reason": "signal"},
        {"symbol": "B", "entry_signal_date": "2020-01-02", "entry_date": "2020-01-03",
         "entry_price": 10.26, "pnl_pct": -0.1, "exit_reason": "stop_loss"},
        {"symbol": "C", "entry_signal_date": "2024-01-02", "entry_date": "2024-01-03",
         "entry_price": 10.30, "pnl_pct": -0.1, "exit_reason": "stop_loss"},
    ]
    structures = [
        {"symbol": row["symbol"], "entry_signal_date": row["entry_signal_date"],
         "entry_date": row["entry_date"], "pivot": 10.0}
        for row in trades
    ]

    result = analyze(trades, structures)

    assert result["retained"]["trades"] == 1
    assert result["rejected"]["trades"] == 2
