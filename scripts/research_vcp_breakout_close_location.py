#!/usr/bin/env python3
"""Keep VCP fills whose breakout bar closes in the upper half of the day's range."""
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
    breakout_close_upper_half,
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
    verdict,
    _as_date,
    _round,
)

FULL_RUN = "20260909T030431101979Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/breakout-close-upper-half-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/breakout-close-upper-half-v1-analysis.json"


def filter_book(trades, sessions, calendar):
    kept_pnls, all_pnls = [], []
    kept = lower = missing = 0
    for trade in trades:
        all_pnls.append(float(trade["pnl_pct"]))
        flag = breakout_close_upper_half(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if flag["upper"]:
            kept_pnls.append(float(trade["pnl_pct"]))
            kept += 1
        elif flag["reason"] == "lower_half":
            lower += 1
        else:
            missing += 1
    baseline = independent_trade_stats(all_pnls)
    variant = independent_trade_stats(kept_pnls)
    return {
        "kept": kept,
        "lower_half": lower,
        "missing": missing,
        "baseline": baseline,
        "variant": variant,
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
    payload = json.loads((Path(args.runs_root) / FULL_RUN / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train = training_trades(all_trades)
    val, val_open = slice_trades(all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31))
    symbols = sorted({str(t["symbol"]) for t in train + val})
    dates = [_as_date(t["entry_signal_date"]) for t in train + val]
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root), symbols, min(dates) - timedelta(days=5), max(dates)
    )
    train_report = filter_book(train, sessions, calendar)
    report = {
        "experiment": "vcp-breakout-close-upper-half-v1",
        "baseline_run": FULL_RUN,
        "protocol": str(args.protocol),
        "training_2016_2022": train_report,
        "rule": train_report["rule"],
        "gaps": [],
    }
    if train_report["rule"] == "keep":
        report["validation_2023_2026"] = filter_book(val, sessions, calendar)
        report["validation_2023_2026"]["incomplete_excluded"] = len(val_open)
        report["validation_note"] = "exposure, not a clean holdout"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "rule": report["rule"], "training": train_report, "validation": report.get("validation_2023_2026")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
