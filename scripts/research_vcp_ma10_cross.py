#!/usr/bin/env python3
"""MA10-cross overlay on the 321 close-upper-half VCP original-exit book."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    apply_ma_cross_exit_to_fill,
    breakout_close_upper_half,
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
    verdict,
    _as_date,
    _round,
)

FULL_RUN = "20260909T030431101979Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/ma10-cross-exit-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/ma10-cross-exit-v1-analysis.json"


def upper_half(trades, sessions, calendar):
    kept = []
    for trade in trades:
        flag = breakout_close_upper_half(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if flag["upper"]:
            kept.append(trade)
    return kept


def overlay_book(trades, sessions, calendar, last_bar: date) -> dict:
    baseline_pnls, variant_pnls = [], []
    shortened = blocked = 0
    for trade in trades:
        applied = apply_ma_cross_exit_to_fill(
            entry_date=_as_date(trade["entry_date"]),
            exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]),
            baseline_pnl=float(trade["pnl_pct"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
            ma_days=10,
            last_bar=last_bar,
        )
        baseline_pnls.append(float(trade["pnl_pct"]))
        variant_pnls.append(float(applied["pnl"]))
        if applied.get("shortened"):
            shortened += 1
        if applied.get("reason") in {
            "missing_bar",
            "missing_exit_bar",
            "early_exit_blocked",
            "missing_entry_bar",
            "incomplete_ma",
        }:
            blocked += 1
    baseline = independent_trade_stats(baseline_pnls)
    variant = independent_trade_stats(variant_pnls)
    return {
        "baseline": baseline,
        "variant": variant,
        "shortened": shortened,
        "blocked_kept_baseline": blocked,
        "delta": {
            "avg_pnl": _round((variant["avg_pnl"] or 0) - (baseline["avg_pnl"] or 0))
            if variant["avg_pnl"] is not None and baseline["avg_pnl"] is not None
            else None,
            "win_rate": _round((variant["win_rate"] or 0) - (baseline["win_rate"] or 0))
            if variant["win_rate"] is not None and baseline["win_rate"] is not None
            else None,
            "profit_factor": None
            if variant["profit_factor"] is None or baseline["profit_factor"] is None
            else round(variant["profit_factor"] - baseline["profit_factor"], 2),
        },
        "rule": verdict(variant, baseline),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_file():
        raise SystemExit(f"protocol missing: {protocol_path}")
    payload = json.loads((Path(args.runs_root) / FULL_RUN / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train_all = training_trades(all_trades)
    val_all, val_open = slice_trades(all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31))
    symbols = sorted({str(t["symbol"]) for t in train_all + val_all})
    dates = [_as_date(t["entry_date"]) for t in train_all + val_all] + [
        _as_date(t["exit_date"]) for t in train_all + val_all
    ]
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root), symbols, min(dates) - timedelta(days=30), max(dates)
    )
    if not sessions:
        report = {"experiment": "vcp-ma10-cross-exit-v1", "gaps": ["no bars"], "rule": "blocked_missing_bars"}
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 1
    train = upper_half(train_all, sessions, calendar)
    val = upper_half(val_all, sessions, calendar)
    train_report = overlay_book(train, sessions, calendar, date(2022, 12, 31))
    report = {
        "experiment": "vcp-ma10-cross-exit-v1",
        "baseline_run": FULL_RUN,
        "protocol": str(protocol_path),
        "upper_half_train": len(train),
        "training_2016_2022": train_report,
        "rule": train_report["rule"],
        "gaps": [],
    }
    if train_report["rule"] == "keep":
        report["validation_2023_2026"] = overlay_book(val, sessions, calendar, date(2026, 12, 31))
        report["validation_2023_2026"]["incomplete_excluded"] = len(val_open)
        report["validation_note"] = "exposure, not a clean holdout"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
                "upper_half_train": len(train),
                "rule": report["rule"],
                "training": train_report,
                "validation": report.get("validation_2023_2026"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
