#!/usr/bin/env python3
"""Keep upper-half VCP fills whose breakout bar is a yang line (close > open)."""
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
    breakout_bullish_bar,
    breakout_close_upper_half,
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
    verdict,
    _as_date,
    _round,
)

FULL_RUN = "20260909T030431101979Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/breakout-bullish-bar-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/breakout-bullish-bar-v1-analysis.json"


def select(trades, sessions, calendar):
    kept, yin, missing = [], 0, 0
    for trade in trades:
        bars = sessions.get(str(trade["symbol"]), [])
        half = breakout_close_upper_half(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=bars,
            market_calendar=calendar,
        )
        if not half["upper"]:
            continue
        flag = breakout_bullish_bar(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=bars,
            market_calendar=calendar,
        )
        if flag["bullish"]:
            kept.append(trade)
        elif flag["reason"] == "yin":
            yin += 1
        else:
            missing += 1
    return kept, yin, missing


def stats(trades):
    return independent_trade_stats([float(t["pnl_pct"]) for t in trades])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = json.loads((Path(args.runs_root) / FULL_RUN / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train_all = training_trades(all_trades)
    val_all, val_open = slice_trades(all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31))
    symbols = sorted({str(t["symbol"]) for t in train_all + val_all})
    dates = [_as_date(t["entry_signal_date"]) for t in train_all + val_all]
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root), symbols, min(dates) - timedelta(days=5), max(dates)
    )
    train_base = [
        t
        for t in train_all
        if breakout_close_upper_half(
            signal_date=_as_date(t["entry_signal_date"]),
            sessions=sessions.get(str(t["symbol"]), []),
            market_calendar=calendar,
        )["upper"]
    ]
    val_base = [
        t
        for t in val_all
        if breakout_close_upper_half(
            signal_date=_as_date(t["entry_signal_date"]),
            sessions=sessions.get(str(t["symbol"]), []),
            market_calendar=calendar,
        )["upper"]
    ]
    train_kept, train_yin, train_miss = select(train_all, sessions, calendar)
    train_report = {
        "yin_dropped": train_yin,
        "missing": train_miss,
        "baseline": stats(train_base),
        "variant": stats(train_kept),
    }
    train_report["delta"] = {
        "avg_pnl": _round((train_report["variant"]["avg_pnl"] or 0) - (train_report["baseline"]["avg_pnl"] or 0))
        if train_report["variant"]["avg_pnl"] is not None and train_report["baseline"]["avg_pnl"] is not None
        else None,
        "win_rate": _round((train_report["variant"]["win_rate"] or 0) - (train_report["baseline"]["win_rate"] or 0))
        if train_report["variant"]["win_rate"] is not None and train_report["baseline"]["win_rate"] is not None
        else None,
        "profit_factor": None
        if train_report["variant"]["profit_factor"] is None or train_report["baseline"]["profit_factor"] is None
        else round(train_report["variant"]["profit_factor"] - train_report["baseline"]["profit_factor"], 2),
    }
    train_report["rule"] = verdict(train_report["variant"], train_report["baseline"])
    report = {
        "experiment": "vcp-breakout-bullish-bar-v1",
        "baseline_run": FULL_RUN,
        "protocol": str(args.protocol),
        "training_2016_2022": train_report,
        "rule": train_report["rule"],
        "gaps": [],
    }
    if train_report["rule"] == "keep":
        val_kept, val_yin, val_miss = select(val_all, sessions, calendar)
        val_report = {
            "yin_dropped": val_yin,
            "missing": val_miss,
            "baseline": stats(val_base),
            "variant": stats(val_kept),
            "incomplete_excluded": len(val_open),
        }
        val_report["delta"] = {
            "avg_pnl": _round((val_report["variant"]["avg_pnl"] or 0) - (val_report["baseline"]["avg_pnl"] or 0))
            if val_report["variant"]["avg_pnl"] is not None and val_report["baseline"]["avg_pnl"] is not None
            else None,
            "win_rate": _round((val_report["variant"]["win_rate"] or 0) - (val_report["baseline"]["win_rate"] or 0))
            if val_report["variant"]["win_rate"] is not None and val_report["baseline"]["win_rate"] is not None
            else None,
            "profit_factor": None
            if val_report["variant"]["profit_factor"] is None or val_report["baseline"]["profit_factor"] is None
            else round(val_report["variant"]["profit_factor"] - val_report["baseline"]["profit_factor"], 2),
        }
        val_report["rule"] = verdict(val_report["variant"], val_report["baseline"])
        report["validation_2023_2026"] = val_report
        report["validation_note"] = "exposure, not a clean holdout"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "rule": report["rule"], "training": train_report, "validation": report.get("validation_2023_2026")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
