#!/usr/bin/env python3
"""Sequence-3 watch-list 20-session-high breakout contrast.

Does not run a VCP / cup-handle / flag detector. Watch list is not a buy-all book.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    TRAINING_END,
    gaps_for_training,
    load_training_market,
    run_watchlist_breakout_contrast,
)

DEFAULT_PROTOCOL = ROOT / "docs/research/watchlist-20d-high-breakout-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/watchlist-20d-high-breakout-v1-analysis.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--trigger", default="fresh_20d")
    parser.add_argument("--entry-filter", default="")
    parser.add_argument("--exit-rule", default="")
    args = parser.parse_args()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_file():
        raise SystemExit(f"protocol missing: {protocol_path}")
    data_root = Path(args.data_root)
    gaps = gaps_for_training(data_root, DATA_START, TRAINING_END)
    if gaps:
        report = {
            "experiment": protocol_path.stem,
            "protocol": str(protocol_path),
            "gaps": gaps,
            "windows": {},
            "rule": "blocked_missing_bars",
        }
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"output": args.output, "gaps": gaps}, ensure_ascii=False))
        return 1
    print("loading market matrix", flush=True)
    market, listing_dates, names = load_training_market(data_root, DATA_START, TRAINING_END)
    print(f"loaded sessions={market.shape[0]} symbols={market.shape[1]}", flush=True)
    report = run_watchlist_breakout_contrast(
        market,
        listing_dates,
        names,
        experiment=protocol_path.stem,
        trigger=args.trigger,
        entry_filter=args.entry_filter or None,
        exit_rule=args.exit_rule or None,
    )
    report["protocol"] = str(protocol_path)
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": args.output,
                "rule": report["rule"],
                "date_ew_net": {
                    hold: report["windows"][hold]["date_ew_net"] for hold in ("5", "10", "20")
                },
                "date_ew_vs_unselected": {
                    hold: report["windows"][hold]["date_ew_vs_unselected"]
                    for hold in ("5", "10", "20")
                },
                "date_ew_net_excess": {
                    hold: report["windows"][hold]["date_ew_net_excess"]
                    for hold in ("5", "10", "20")
                },
                "signal_days": {
                    hold: report["windows"][hold]["signal_days"] for hold in ("5", "10", "20")
                },
                "complete": {
                    hold: report["windows"][hold]["complete"] for hold in ("5", "10", "20")
                },
                "gaps": report["gaps"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
