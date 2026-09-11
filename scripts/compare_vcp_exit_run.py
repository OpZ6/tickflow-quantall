#!/usr/bin/env python3
"""Compare a VCP exit-method run with its frozen baseline on common entries."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _read(run_id: str) -> dict:
    path = ROOT / "data/research/vcp/runs" / run_id / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = _read(args.baseline)
    experiment = _read(args.experiment)
    base_trades = pd.DataFrame(baseline["trades"])
    experiment_trades = pd.DataFrame(experiment["trades"])
    common = base_trades.merge(
        experiment_trades,
        on=["symbol", "entry_date"],
        how="inner",
        suffixes=("_baseline", "_experiment"),
        validate="one_to_one",
    )
    baseline_winners = common[common["pnl_pct_baseline"] > 0]
    base_stats = baseline["stats"]
    experiment_stats = experiment["stats"]
    result = {
        "baseline_run": args.baseline,
        "experiment_run": args.experiment,
        "baseline": {
            "trades": base_stats["n_trades"],
            "average_loss": base_stats["avg_loss"],
            "average_win": base_stats["avg_win"],
            "annual_return": base_stats["annual_return"],
            "max_drawdown": base_stats["max_drawdown"],
        },
        "experiment": {
            "trades": experiment_stats["n_trades"],
            "average_loss": experiment_stats["avg_loss"],
            "average_win": experiment_stats["avg_win"],
            "annual_return": experiment_stats["annual_return"],
            "max_drawdown": experiment_stats["max_drawdown"],
            "exit_signal_ids": dict(Counter(experiment_trades["exit_signal_id"].dropna())),
        },
        "matched": {
            "trades": len(common),
            "baseline_mean_return": float(common["pnl_pct_baseline"].mean()),
            "experiment_mean_return": float(common["pnl_pct_experiment"].mean()),
            "mean_return_change": float(
                (common["pnl_pct_experiment"] - common["pnl_pct_baseline"]).mean()
            ),
            "baseline_winners": len(baseline_winners),
            "winners_remaining_positive": int(
                (baseline_winners["pnl_pct_experiment"] > 0).sum()
            ),
            "winner_retention_rate": float(
                (baseline_winners["pnl_pct_experiment"] > 0).mean()
            ),
            "winner_mean_return_change": float(
                (
                    baseline_winners["pnl_pct_experiment"]
                    - baseline_winners["pnl_pct_baseline"]
                ).mean()
            ),
        },
        "new_experiment_entries": len(experiment_trades) - len(common),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
