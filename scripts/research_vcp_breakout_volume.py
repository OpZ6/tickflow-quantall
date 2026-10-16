#!/usr/bin/env python3
"""VCP leader fills: keep only 放量 breakout days vs current two-bar baseline."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_vcp_two_bar_no_demand import (  # noqa: E402
    BASELINE_RUN,
    TRAINING_START,
    apply_two_bar_no_demand_to_fill,
    breakout_volume_expanded,
    independent_trade_stats,
    load_symbol_sessions,
    prebreakout_volume_contracted,
    training_trades,
    verdict,
    _as_date,
    _round,
)

DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/breakout-volume-expansion-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/breakout-volume-expansion-v1-analysis.json"


def run_volume_contrast(
    trades: list[dict], sessions: dict, calendar: list, *, mode: str = "expansion"
) -> dict:
    baseline_pnls = []
    variant_pnls = []
    kept = 0
    quiet = 0
    missing = 0
    for trade in trades:
        symbol = str(trade["symbol"])
        bars = sessions.get(symbol, [])
        applied = apply_two_bar_no_demand_to_fill(
            entry_date=_as_date(trade["entry_date"]),
            exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]),
            baseline_pnl=float(trade["pnl_pct"]),
            sessions=bars,
            market_calendar=calendar,
        )
        baseline_pnls.append(float(applied["pnl"]))
        signal = _as_date(trade["entry_signal_date"])
        if mode == "contraction":
            flag = prebreakout_volume_contracted(
                signal_date=signal, sessions=bars, market_calendar=calendar
            )
            keep = flag["contracted"]
            skip_reason = flag["reason"]
        elif mode == "pre_expand":
            flag = prebreakout_volume_contracted(
                signal_date=signal, sessions=bars, market_calendar=calendar
            )
            keep = bool(flag.get("expanding"))
            skip_reason = "still_contracted" if flag["contracted"] else flag["reason"]
        else:
            flag = breakout_volume_expanded(
                signal_date=signal, sessions=bars, market_calendar=calendar
            )
            keep = flag["expanded"]
            skip_reason = flag["reason"]
        if keep:
            variant_pnls.append(float(applied["pnl"]))
            kept += 1
        elif skip_reason in {"quiet_breakout", "not_contracted", "still_contracted"}:
            quiet += 1
        else:
            missing += 1
    baseline = independent_trade_stats(baseline_pnls)
    variant = independent_trade_stats(variant_pnls)
    return {
        "experiment": {
            "contraction": "vcp-prebreakout-volume-contraction-v1",
            "pre_expand": "vcp-prebreakout-volume-expansion-v1",
        }.get(mode, "vcp-breakout-volume-expansion-v1"),
        "baseline_run": BASELINE_RUN,
        "training_start": TRAINING_START.isoformat(),
        "kept": kept,
        "quiet_breakout": quiet,
        "missing_volume_history": missing,
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
        "pass_metric": "independent_avg_pnl_and_payoff",
        "gaps": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", default="expansion", choices=["expansion", "contraction", "pre_expand"])
    args = parser.parse_args()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_file():
        raise SystemExit(f"protocol missing: {protocol_path}")
    payload = json.loads((Path(args.runs_root) / BASELINE_RUN / "result.json").read_text(encoding="utf-8"))
    trades = training_trades(payload.get("trades") or [])
    symbols = sorted({str(t["symbol"]) for t in trades})
    signals = [_as_date(t["entry_signal_date"]) for t in trades]
    ends = [_as_date(t["exit_date"]) for t in trades]
    start = min(signals) - timedelta(days=80)
    sessions, calendar = load_symbol_sessions(Path(args.data_root), symbols, start, max(ends))
    if not sessions:
        report = {"experiment": "vcp-breakout-volume-expansion-v1", "gaps": ["no bars"], "rule": "blocked_missing_bars"}
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 1
    report = run_volume_contrast(trades, sessions, calendar, mode=args.mode)
    report["protocol"] = str(protocol_path)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
                "rule": report["rule"],
                "kept": report["kept"],
                "quiet_breakout": report["quiet_breakout"],
                "variant": report["variant"],
                "baseline": report["baseline"],
                "delta": report["delta"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
