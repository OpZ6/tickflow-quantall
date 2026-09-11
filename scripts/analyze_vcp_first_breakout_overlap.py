#!/usr/bin/env python3
"""Compare purged production VCP trades with fresh generic breakout opportunities."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def _summary(rows: list[dict], *, alpha_key: str, mfe_key: str) -> dict:
    by_year: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        year = int(str(row["signal_date"])[:4])
        by_year[year].append(float(row[alpha_key]))
    count = len(rows)
    return {
        "candidates": count,
        "average_40d_alpha": sum(float(row[alpha_key]) for row in rows) / count,
        "positive_alpha_years": sum(sum(values) / len(values) > 0 for values in by_year.values()),
        "years_present": len(by_year),
        "mfe_20pct_rate": sum(float(row[mfe_key]) >= 0.2 for row in rows) / count,
        "mfe_50pct_rate": sum(float(row[mfe_key]) >= 0.5 for row in rows) / count,
        "mfe_100pct_rate": sum(float(row[mfe_key]) >= 1.0 for row in rows) / count,
        "by_signal_year": {
            str(year): {
                "candidates": len(values),
                "average_40d_alpha": sum(values) / len(values),
            }
            for year, values in sorted(by_year.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT
        / "docs/research/vcp/production-vcp-first-breakout-overlap-train-2016-2022-v1.json",
    )
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    label_end = protocol["training_period"][1]

    run_dir = ROOT / "data/research/vcp/runs" / protocol["vcp_source_run"]
    paths = json.loads((run_dir / "trade-path-analysis.json").read_text(encoding="utf-8"))
    vcp = (
        pl.DataFrame(paths["trades"])
        .with_columns(
            pl.col("entry_signal_date").str.to_date().alias("signal_date"),
            pl.col("evaluation_horizon_end_date").str.to_date().alias("label_end_date"),
        )
        .filter(pl.col("label_end_date") <= pl.lit(label_end).str.to_date())
    )
    opportunities = (
        pl.read_parquet(ROOT / protocol["generic_opportunity_source"])
        .with_columns(
            pl.col("signal_date").cast(pl.Date),
            pl.col("label_end_date").cast(pl.Date),
        )
        .filter(pl.col("label_end_date") <= pl.lit(label_end).str.to_date())
    )
    signal_matches = opportunities.filter(pl.col("first_failed_gate") == "selected_by_vcp")
    match_keys = signal_matches.select("symbol", "signal_date").unique()
    joined = vcp.join(
        match_keys.with_columns(pl.lit(True).alias("overlap")),
        on=["symbol", "signal_date"],
        how="left",
    ).with_columns(pl.col("overlap").fill_null(False))
    overlap = joined.filter("overlap")
    non_overlap = joined.filter(~pl.col("overlap"))

    controls = (
        opportunities.filter(pl.col("first_failed_gate") != "selected_by_vcp")
        .group_by("signal_date")
        .agg(
            pl.col("alpha_40d").mean().alias("control_alpha_40d"),
            (pl.col("mfe_40d") >= 0.5).mean().alias("control_mfe_50pct_rate"),
            pl.len().alias("control_candidates"),
        )
    )
    matched = overlap.join(controls, on="signal_date", how="inner").with_columns(
        (pl.col("excess_return_horizon") - pl.col("control_alpha_40d")).alias(
            "matched_alpha_spread"
        )
    )

    overlap_summary = _summary(
        overlap.to_dicts(), alpha_key="excess_return_horizon", mfe_key="horizon_mfe"
    )
    non_overlap_summary = _summary(
        non_overlap.to_dicts(), alpha_key="excess_return_horizon", mfe_key="horizon_mfe"
    )
    matched_control_alpha = float(matched["control_alpha_40d"].mean())
    matched_control_mfe50 = float(matched["control_mfe_50pct_rate"].mean())
    overlap_mfe50 = float(overlap_summary["mfe_50pct_rate"])
    comparisons = {
        "overlap_minus_non_overlap_40d_alpha": overlap_summary["average_40d_alpha"]
        - non_overlap_summary["average_40d_alpha"],
        "same_day_control_average_40d_alpha": matched_control_alpha,
        "overlap_minus_same_day_control_40d_alpha": float(matched["matched_alpha_spread"].mean()),
        "same_day_control_mfe_50pct_rate": matched_control_mfe50,
        "mfe_50pct_rate_enrichment_vs_same_day_control": overlap_mfe50 / matched_control_mfe50,
    }
    gates = protocol["freeze_gates"]
    checks = {
        "minimum_overlap_candidates": overlap.height >= gates["minimum_overlap_candidates"],
        "minimum_average_40d_alpha": overlap_summary["average_40d_alpha"]
        >= gates["minimum_average_40d_alpha"],
        "minimum_positive_alpha_years": overlap_summary["positive_alpha_years"]
        >= gates["minimum_positive_alpha_years"],
        "minimum_overlap_minus_non_overlap_alpha": comparisons[
            "overlap_minus_non_overlap_40d_alpha"
        ]
        >= gates["minimum_overlap_minus_non_overlap_alpha"],
        "minimum_overlap_minus_same_day_control_alpha": comparisons[
            "overlap_minus_same_day_control_40d_alpha"
        ]
        >= gates["minimum_overlap_minus_same_day_control_alpha"],
        "minimum_mfe_50pct_rate_enrichment_vs_same_day_control": comparisons[
            "mfe_50pct_rate_enrichment_vs_same_day_control"
        ]
        >= gates["minimum_mfe_50pct_rate_enrichment_vs_same_day_control"],
    }
    result = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "research_role": protocol["research_role"],
        "purged_vcp_candidates": vcp.height,
        "signal_logic_matches": signal_matches.height,
        "signal_logic_matches_not_in_production_vcp_trades": signal_matches.join(
            vcp.select("symbol", "signal_date"), on=["symbol", "signal_date"], how="anti"
        ).height,
        "overlap": overlap_summary,
        "non_overlap": non_overlap_summary,
        "comparisons": comparisons,
        "freeze_checks": checks,
        "passed_freeze_gates": all(checks.values()),
        "maximum_vcp_label_end_date": str(vcp["label_end_date"].max()),
        "temporal_test_inspected": False,
    }
    decision = {
        **result,
        "decision": "freeze_one_first_breakout_entry_rule"
        if result["passed_freeze_gates"]
        else "stop_first_breakout_entry_rule",
        "interpretation": (
            "This reanalysis may freeze one event rule, but only the untouched "
            "temporal test can accept or reject it."
        ),
    }
    output_dir = ROOT / "data/research/vcp/first-breakout-overlap" / protocol["experiment"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    decision_path = args.protocol.with_name(f"{protocol['experiment']}-decision.json")
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
