#!/usr/bin/env python3
"""Upper-half close filter on the 1421 leader-open launch_pullback fills."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_launch_pullback_gate import filter_gate  # noqa: E402
from research_launch_pullback_rs import filter_rs  # noqa: E402
from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    dual_regime_gate,
    load_training_market,
    rs_universe_mask,
)
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

PULLBACK_RUN = "20260909T053715693165Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/pullback/launch-pullback-upper-half-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/pullback/launch-pullback-upper-half-v1-analysis.json"


def pack(trades):
    return independent_trade_stats([float(t["pnl_pct"]) for t in trades])


def filter_upper(trades, sessions, calendar):
    kept, lower, missing = [], 0, 0
    for trade in trades:
        flag = breakout_close_upper_half(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if flag["upper"]:
            kept.append(trade)
        elif flag["reason"] == "lower_half":
            lower += 1
        else:
            missing += 1
    return kept, lower, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = json.loads((Path(args.runs_root) / PULLBACK_RUN / "result.json").read_text(encoding="utf-8"))
    train_all = training_trades(payload.get("trades") or [])
    val_all, val_open = slice_trades(
        payload.get("trades") or [], date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31)
    )
    print("loading market for leader-open universe", flush=True)
    market, _listing, _names = load_training_market(Path(args.data_root), DATA_START, date(2026, 12, 31))
    gate, _ = dual_regime_gate(market)
    _mask, ranks = rs_universe_mask(market, 85.0)
    dates = [_as_date(label) for label in market.timestamp_labels]
    symbols = list(market.symbols)
    train_base, _ = filter_gate(train_all, dates, gate)
    train_base, _ = filter_rs(train_base, symbols, dates, ranks, 85.0)
    val_base, _ = filter_gate(val_all, dates, gate)
    val_base, _ = filter_rs(val_base, symbols, dates, ranks, 85.0)
    need = train_base + val_base
    sigs = [_as_date(t["entry_signal_date"]) for t in need]
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        min(sigs) - timedelta(days=5),
        max(sigs),
    )
    train_kept, train_lower, train_miss = filter_upper(train_base, sessions, calendar)
    train_report = {
        "lower_half": train_lower,
        "missing": train_miss,
        "baseline": pack(train_base),
        "variant": pack(train_kept),
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
    positive = (train_report["variant"]["avg_pnl"] or 0) > 0
    train_report["rule"] = (
        "keep" if verdict(train_report["variant"], train_report["baseline"]) == "keep" and positive else "drop"
    )
    report = {
        "experiment": "launch-pullback-upper-half-v1",
        "baseline_run": PULLBACK_RUN,
        "protocol": str(args.protocol),
        "training_2016_2022": train_report,
        "rule": train_report["rule"],
        "gaps": [],
    }
    if train_report["rule"] == "keep":
        val_kept, val_lower, val_miss = filter_upper(val_base, sessions, calendar)
        val_report = {
            "lower_half": val_lower,
            "missing": val_miss,
            "baseline": pack(val_base),
            "variant": pack(val_kept),
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
        report["validation_note"] = "few post-2022 fills on this ledger"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
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
