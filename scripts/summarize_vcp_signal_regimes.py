#!/usr/bin/env python3
"""Evaluate frozen VCP signal branches as causal applicability periods."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(rows: list[dict]) -> dict:
    by_year: dict[int, list[dict]] = defaultdict(list)
    by_market_outcome: dict[str, list[dict]] = defaultdict(list)
    by_exit_reason: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        signal_date = str(row.get("entry_signal_date") or row["entry_date"])[:10]
        by_year[int(signal_date[:4])].append(row)
        by_market_outcome[str(row["market_outcome_held"])].append(row)
        by_exit_reason[str(row["exit_reason"])].append(row)
    yearly_alpha = {
        str(year): sum(float(row["excess_return_held"]) for row in items) / len(items)
        for year, items in sorted(by_year.items())
    }
    yearly_40d_alpha = {
        str(year): sum(float(row["excess_return_horizon"]) for row in items) / len(items)
        for year, items in sorted(by_year.items())
    }
    market_outcome_attribution = {
        outcome: {
            "trades": len(items),
            "average_excess_return_held": sum(
                float(row["excess_return_held"]) for row in items
            ) / len(items),
            "average_40d_excess_return": sum(
                float(row["excess_return_horizon"]) for row in items
            ) / len(items),
        }
        for outcome, items in sorted(by_market_outcome.items())
    }
    exit_reason_attribution = {
        reason: {
            "trades": len(items),
            "average_excess_return_held": sum(
                float(row["excess_return_held"]) for row in items
            ) / len(items),
            "average_40d_excess_return": sum(
                float(row["excess_return_horizon"]) for row in items
            ) / len(items),
        }
        for reason, items in sorted(by_exit_reason.items())
    }
    early_excess_returns = {
        horizon: sum(
            float(row["early_excess_returns"][horizon]) for row in rows
        ) / len(rows)
        for horizon in ("5", "10", "20")
    } if rows else {horizon: None for horizon in ("5", "10", "20")}
    return {
        "trades": len(rows),
        "average_absolute_return": (
            sum(float(row["pnl_pct"]) for row in rows) / len(rows) if rows else None
        ),
        "average_excess_return_held": (
            sum(float(row["excess_return_held"]) for row in rows) / len(rows)
            if rows else None
        ),
        "average_40d_excess_return": (
            sum(float(row["excess_return_horizon"]) for row in rows) / len(rows)
            if rows else None
        ),
        "mfe_20pct_rate": (
            sum(float(row["horizon_mfe"]) >= 0.2 for row in rows) / len(rows)
            if rows else None
        ),
        "mfe_20pct_count": sum(float(row["horizon_mfe"]) >= 0.2 for row in rows),
        "mfe_50pct_count": sum(float(row["horizon_mfe"]) >= 0.5 for row in rows),
        "mfe_100pct_count": sum(float(row["horizon_mfe"]) >= 1.0 for row in rows),
        "positive_alpha_years": sum(value > 0 for value in yearly_alpha.values()),
        "by_signal_year_alpha": yearly_alpha,
        "by_signal_year_40d_alpha": yearly_40d_alpha,
        "average_early_excess_returns": early_excess_returns,
        "by_exit_reason": exit_reason_attribution,
        "by_future_market_outcome_held": market_outcome_attribution,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "docs/research/vcp/production-leader-signal-regime-profile-v1.json",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    run_dir = args.data_root / "research/vcp/runs" / protocol["source_run"]
    report = json.loads((run_dir / "trade-path-analysis.json").read_text(encoding="utf-8"))
    rows = report["trades"]
    training_start, training_end = protocol["training_period"]
    test_start, test_end = protocol["temporal_test_period"]
    gate = protocol["training_gate"]
    branches = {}
    for branch, signal_id in protocol["branches"].items():
        branch_rows = [row for row in rows if row["entry_signal_id"] == signal_id]
        training = [
            row for row in branch_rows
            if training_start <= str(row.get("entry_signal_date") or row["entry_date"])[:10] <= training_end
        ]
        training_summary = summarize(training)
        checks = {
            "minimum_trades": training_summary["trades"] >= gate["minimum_trades"],
            "minimum_average_excess_return_held": (
                training_summary["average_excess_return_held"] is not None
                and training_summary["average_excess_return_held"] >= gate["minimum_average_excess_return_held"]
            ),
            "minimum_positive_alpha_years": (
                training_summary["positive_alpha_years"] >= gate["minimum_positive_alpha_years"]
            ),
            "minimum_mfe_20pct_rate": (
                training_summary["mfe_20pct_rate"] is not None
                and training_summary["mfe_20pct_rate"] >= gate["minimum_mfe_20pct_rate"]
            ),
        }
        passed_training = all(checks.values())
        test = [
            row for row in branch_rows
            if test_start <= str(row.get("entry_signal_date") or row["entry_date"])[:10] <= test_end
        ]
        branches[branch] = {
            "signal_id": signal_id,
            "training": training_summary,
            "training_checks": checks,
            "passed_training": passed_training,
            "temporal_test": summarize(test) if passed_training else None,
            "conditional_strategy_success": (
                passed_training
                and bool(test)
                and summarize(test)["average_excess_return_held"] > 0
            ),
        }
    result = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "source_run": protocol["source_run"],
        "branches": branches,
        "successful_conditional_branches": [
            branch for branch, item in branches.items()
            if item["conditional_strategy_success"]
        ],
    }
    output = ROOT / "docs/research/vcp/production-leader-signal-regime-profile-v1-decision.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
