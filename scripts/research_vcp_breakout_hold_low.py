#!/usr/bin/env python3
"""Full independent VCP fills: keep breakouts that do not undercut the prior session low."""
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
    TRAINING_START,
    breakout_low_holds_prior_low,
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
    verdict,
    _as_date,
    _round,
)

FULL_RUN = "20260909T030431101979Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/breakout-low-holds-prior-low-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/breakout-low-holds-prior-low-v1-analysis.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = json.loads((Path(args.runs_root) / FULL_RUN / "result.json").read_text(encoding="utf-8"))
    trades = training_trades(payload.get("trades") or [])
    symbols = sorted({str(t["symbol"]) for t in trades})
    signals = [_as_date(t["entry_signal_date"]) for t in trades]
    ends = [_as_date(t["exit_date"]) for t in trades]
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root), symbols, min(signals) - timedelta(days=10), max(ends)
    )
    baseline_pnls = [float(t["pnl_pct"]) for t in trades]
    variant_pnls = []
    kept = undercut = missing = 0
    for trade in trades:
        flag = breakout_low_holds_prior_low(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if flag["holds"]:
            variant_pnls.append(float(trade["pnl_pct"]))
            kept += 1
        elif flag["reason"] == "undercut_prior_low":
            undercut += 1
        else:
            missing += 1
    baseline = independent_trade_stats(baseline_pnls)
    variant = independent_trade_stats(variant_pnls)
    report = {
        "experiment": "vcp-breakout-low-holds-prior-low-v1",
        "baseline_run": FULL_RUN,
        "kept": kept,
        "undercut": undercut,
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
        "protocol": str(args.protocol),
        "gaps": [],
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "n_baseline": baseline["n_trades"], **{k: report[k] for k in ("rule", "kept", "undercut", "missing", "variant", "baseline", "delta")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
