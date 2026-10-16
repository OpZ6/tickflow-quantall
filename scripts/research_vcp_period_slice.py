#!/usr/bin/env python3
"""Slice frozen VCP independent fills by entry window; optional hold-low filter."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_vcp_two_bar_no_demand import (  # noqa: E402
    breakout_low_holds_prior_low,
    independent_trade_stats,
    load_symbol_sessions,
    _as_date,
    _round,
)

FULL_RUN = "20260909T030431101979Z"


def slice_trades(trades: list[dict], entry_start: date, entry_end: date, exit_end: date) -> tuple[list[dict], list[dict]]:
    complete, openish = [], []
    for trade in trades:
        entry = _as_date(trade["entry_date"])
        exit_day = _as_date(trade["exit_date"])
        if not (entry_start <= entry <= entry_end):
            continue
        if exit_day <= exit_end:
            complete.append(trade)
        else:
            openish.append(trade)
    return complete, openish


def apply_hold_low(trades: list[dict], sessions: dict, calendar: list) -> tuple[list[dict], int, int]:
    kept, undercut, missing = [], 0, 0
    for trade in trades:
        flag = breakout_low_holds_prior_low(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if flag["holds"]:
            kept.append(trade)
        elif flag["reason"] == "undercut_prior_low":
            undercut += 1
        else:
            missing += 1
    return kept, undercut, missing


def yearly(trades: list[dict]) -> dict:
    buckets: dict[str, list[float]] = {}
    for trade in trades:
        year = str(_as_date(trade["entry_date"]).year)
        buckets.setdefault(year, []).append(float(trade["pnl_pct"]))
    return {year: independent_trade_stats(pnls) for year, pnls in sorted(buckets.items())}


def pack(trades: list[dict], extra: dict | None = None) -> dict:
    stats = independent_trade_stats([float(t["pnl_pct"]) for t in trades])
    row = {"stats": stats, "yearly": yearly(trades)}
    if extra:
        row.update(extra)
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(ROOT / "docs/research/vcp/hold-low-2023-2026-validation-v1-analysis.json"))
    args = parser.parse_args()
    payload = json.loads((Path(args.runs_root) / FULL_RUN / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train_c, train_open = slice_trades(all_trades, date(2016, 1, 1), date(2022, 12, 31), date(2022, 12, 31))
    val_c, val_open = slice_trades(all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31))
    symbols = sorted({str(t["symbol"]) for t in train_c + val_c + train_open + val_open})
    dates = [_as_date(t["entry_signal_date"]) for t in train_c + val_c] + [_as_date(t["exit_date"]) for t in train_c + val_c]
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root), symbols, min(dates) - timedelta(days=10), max(dates)
    )
    train_kept, train_cut, train_miss = apply_hold_low(train_c, sessions, calendar)
    val_kept, val_cut, val_miss = apply_hold_low(val_c, sessions, calendar)
    report = {
        "experiment": "vcp-hold-low-2023-2026-validation-v1",
        "baseline_run": FULL_RUN,
        "note": "2023-2026 is exposure/validation, not a clean holdout.",
        "training_2016_2022": {
            "original": pack(train_c, {"incomplete_excluded": len(train_open)}),
            "hold_low": pack(train_kept, {"undercut": train_cut, "missing": train_miss}),
        },
        "validation_2023_2026": {
            "original": pack(val_c, {"incomplete_excluded": len(val_open)}),
            "hold_low": pack(val_kept, {"undercut": val_cut, "missing": val_miss}),
            "incomplete_entries": [
                {
                    "symbol": t["symbol"],
                    "entry_date": t["entry_date"],
                    "exit_date": t["exit_date"],
                    "exit_reason": t.get("exit_reason"),
                }
                for t in val_open
            ],
        },
        "gaps": [],
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
                "train_original": report["training_2016_2022"]["original"]["stats"],
                "train_hold_low": report["training_2016_2022"]["hold_low"]["stats"],
                "val_original": report["validation_2023_2026"]["original"]["stats"],
                "val_hold_low": report["validation_2023_2026"]["hold_low"]["stats"],
                "val_incomplete": len(val_open),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
