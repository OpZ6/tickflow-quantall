#!/usr/bin/env python3
"""Independent-trade stats for a frozen strategy run (training slice)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_vcp_two_bar_no_demand import independent_trade_stats, training_trades  # noqa: E402

DEFAULTS = {
    "cup": {
        "run": "20260909T133226351846Z",
        "strategy_id": "quants_cup_handle_legacy_v1",
        "experiment": "cup-handle-independent-train-2016-2022-v1",
        "output": ROOT / "docs/research/cup-handle/cup-handle-independent-train-2016-2022-v1-analysis.json",
    },
    "htf": {
        "run": "20260909T130617820559Z",
        "strategy_id": "quants_high_tight_flag_legacy_v1",
        "experiment": "high-tight-flag-independent-train-2016-2022-v1",
        "output": ROOT / "docs/research/high-tight-flag/high-tight-flag-independent-train-2016-2022-v1-analysis.json",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialect", choices=sorted(DEFAULTS), default="cup")
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    args = parser.parse_args()
    spec = DEFAULTS[args.dialect]
    path = Path(args.runs_root) / spec["run"] / "result.json"
    if not path.is_file():
        report = {"experiment": spec["experiment"], "gaps": [f"missing {path}"], "rule": "blocked_missing_bars"}
        spec["output"].parent.mkdir(parents=True, exist_ok=True)
        spec["output"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    trades = payload.get("trades") or []
    train = training_trades(trades)
    report = {
        "experiment": spec["experiment"],
        "strategy_id": spec["strategy_id"],
        "baseline_run": spec["run"],
        "n_all": len(trades),
        "training": independent_trade_stats([float(t["pnl_pct"]) for t in train]),
        "gaps": [],
    }
    spec["output"].parent.mkdir(parents=True, exist_ok=True)
    spec["output"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(spec["output"]), **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
