#!/usr/bin/env python3
"""Audit continuous VCP dimensions on the full training opportunity universe."""
from __future__ import annotations

import argparse
import json
from itertools import pairwise
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def _quintile_summary(frame: pl.DataFrame, *, feature: str, direction: int) -> dict:
    ranked = (
        frame.filter(pl.col(feature).is_not_null() & pl.col(feature).is_finite())
        .with_columns((pl.col(feature) * direction).alias("_expected_score"))
        .with_columns(
            pl.col("_expected_score").rank("average").over("signal_year").alias("_rank"),
            pl.len().over("signal_year").alias("_year_count"),
        )
        .with_columns(
            (
                ((pl.col("_rank") - 1) * 5 / pl.col("_year_count"))
                .floor()
                .add(1)
                .clip(1, 5)
                .cast(pl.Int8)
            ).alias("expected_quintile")
        )
    )
    quintiles = (
        ranked.group_by("expected_quintile")
        .agg(
            pl.len().alias("opportunities"),
            pl.col("alpha_40d").mean().alias("average_40d_alpha"),
            pl.col("close_return_40d").mean().alias("average_40d_return"),
            (pl.col("mfe_40d") >= 0.2).mean().alias("mfe_20pct_rate"),
            (pl.col("mfe_40d") >= 0.5).mean().alias("mfe_50pct_rate"),
            (pl.col("mfe_40d") >= 1.0).mean().alias("mfe_100pct_rate"),
        )
        .sort("expected_quintile")
    )
    by_quintile = {
        str(row["expected_quintile"]): {
            key: row[key]
            for key in (
                "opportunities",
                "average_40d_alpha",
                "average_40d_return",
                "mfe_20pct_rate",
                "mfe_50pct_rate",
                "mfe_100pct_rate",
            )
        }
        for row in quintiles.to_dicts()
    }
    yearly = (
        ranked.filter(pl.col("expected_quintile").is_in([1, 5]))
        .group_by("signal_year", "expected_quintile")
        .agg(pl.col("alpha_40d").mean().alias("alpha"))
    )
    yearly_lookup = {
        (int(row["signal_year"]), int(row["expected_quintile"])): float(row["alpha"])
        for row in yearly.to_dicts()
    }
    years = sorted({year for year, _ in yearly_lookup})
    yearly_spreads = {
        str(year): yearly_lookup[(year, 5)] - yearly_lookup[(year, 1)]
        for year in years
        if (year, 1) in yearly_lookup and (year, 5) in yearly_lookup
    }
    alpha_path = [float(by_quintile[str(value)]["average_40d_alpha"]) for value in range(1, 6)]
    best = by_quintile["5"]
    worst = by_quintile["1"]
    future_outcomes = (
        ranked.filter(pl.col("expected_quintile") == 5)
        .with_columns(
            pl.when(pl.col("market_return_40d") < -0.05)
            .then(pl.lit("down"))
            .when(pl.col("market_return_40d") > 0.05)
            .then(pl.lit("up"))
            .otherwise(pl.lit("sideways"))
            .alias("future_market_outcome")
        )
        .group_by("future_market_outcome")
        .agg(
            pl.len().alias("opportunities"),
            pl.col("alpha_40d").mean().alias("average_40d_alpha"),
        )
        .sort("future_market_outcome")
    )
    return {
        "valid_opportunities": ranked.height,
        "by_expected_quintile": by_quintile,
        "best_minus_worst_40d_alpha": (
            float(best["average_40d_alpha"]) - float(worst["average_40d_alpha"])
        ),
        "best_to_worst_50pct_leader_enrichment": (
            float(best["mfe_50pct_rate"]) / float(worst["mfe_50pct_rate"])
            if float(worst["mfe_50pct_rate"]) > 0
            else None
        ),
        "monotonic_alpha_steps": sum(
            right >= left for left, right in pairwise(alpha_path)
        ),
        "positive_spread_years": sum(value > 0 for value in yearly_spreads.values()),
        "by_signal_year_best_minus_worst_alpha": yearly_spreads,
        "expected_best_quintile_by_future_market_outcome": {
            row["future_market_outcome"]: {
                "opportunities": row["opportunities"],
                "average_40d_alpha": row["average_40d_alpha"],
            }
            for row in future_outcomes.to_dicts()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "docs/research/vcp/production-vcp-continuous-dimension-audit-train-2016-2022-v1.json",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    opportunities = pl.read_parquet(ROOT / protocol["source"])
    event_keys = opportunities.select(
        "symbol", pl.col("signal_date").alias("date")
    ).lazy()
    end = protocol["training_period"][1]
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if path.parent.name <= f"date={end}"
    ]
    panel = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "date", "high", "low", "close", "volume")
        .sort(["symbol", "date"])
    )
    features = (
        panel.with_columns(
            pl.col("close").shift(1).alias("previous_close"),
            pl.col("close").shift(1).rolling_mean(50).over("symbol").alias("ma50"),
            pl.col("close").shift(1).rolling_mean(150).over("symbol").alias("ma150"),
            pl.col("close").shift(1).rolling_mean(200).over("symbol").alias("ma200"),
            pl.col("high").shift(1).rolling_max(10).over("symbol").alias("recent_high"),
            pl.col("low").shift(1).rolling_min(10).over("symbol").alias("recent_low"),
            pl.col("high").shift(11).rolling_max(30).over("symbol").alias("prior_high"),
            pl.col("low").shift(11).rolling_min(30).over("symbol").alias("prior_low"),
            pl.col("volume").shift(1).rolling_mean(10).over("symbol").alias("recent_volume"),
            pl.col("volume").shift(11).rolling_mean(30).over("symbol").alias("prior_volume"),
        )
        .join(event_keys, on=["symbol", "date"], how="inner")
        .with_columns(
            pl.min_horizontal(
                pl.col("previous_close") / pl.col("ma50") - 1,
                pl.col("ma50") / pl.col("ma150") - 1,
                pl.col("ma150") / pl.col("ma200") - 1,
            ).alias("trend_stack_margin"),
            (
                (pl.col("recent_high") / pl.col("recent_low") - 1)
                / (pl.col("prior_high") / pl.col("prior_low") - 1)
            ).alias("range_contraction_ratio"),
            (pl.col("recent_volume") / pl.col("prior_volume")).alias("volume_dry_ratio"),
        )
        .select(
            "symbol", "date", "trend_stack_margin", "range_contraction_ratio", "volume_dry_ratio"
        )
        .collect()
    )
    frame = opportunities.join(
        features, left_on=["symbol", "signal_date"], right_on=["symbol", "date"], how="left"
    )
    definitions = {
        "trend_stack_margin": 1,
        "rs_percentile": 1,
        "range_contraction_ratio": -1,
        "volume_dry_ratio": -1,
    }
    gates = protocol["direction_gate"]
    dimensions = {}
    passed = []
    alpha_supported = []
    for feature, direction in definitions.items():
        summary = _quintile_summary(frame, feature=feature, direction=direction)
        checks = {
            "minimum_valid_opportunities": summary["valid_opportunities"] >= gates["minimum_valid_opportunities"],
            "minimum_best_minus_worst_40d_alpha": summary["best_minus_worst_40d_alpha"] >= gates["minimum_best_minus_worst_40d_alpha"],
            "minimum_positive_spread_years": summary["positive_spread_years"] >= gates["minimum_positive_spread_years"],
            "minimum_monotonic_alpha_steps": summary["monotonic_alpha_steps"] >= gates["minimum_monotonic_alpha_steps"],
            "minimum_50pct_leader_enrichment": summary["best_to_worst_50pct_leader_enrichment"] is not None
            and summary["best_to_worst_50pct_leader_enrichment"] >= gates["minimum_50pct_leader_enrichment"],
        }
        summary["checks"] = checks
        summary["alpha_direction_supported"] = all(
            checks[key]
            for key in (
                "minimum_valid_opportunities",
                "minimum_best_minus_worst_40d_alpha",
                "minimum_positive_spread_years",
                "minimum_monotonic_alpha_steps",
            )
        )
        summary["passed"] = all(checks.values())
        dimensions[feature] = summary
        if summary["alpha_direction_supported"]:
            alpha_supported.append(feature)
        if summary["passed"]:
            passed.append(feature)
    output_dir = args.data_root / "research/vcp/dimension-audits" / protocol["experiment"]
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(output_dir / "opportunities-with-dimensions.parquet")
    result = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "opportunities": frame.height,
        "dimensions": dimensions,
        "alpha_supported_dimensions": alpha_supported,
        "passed_dimensions": passed,
        "decision": (
            "promote_mechanism"
            if passed
            else "retain_alpha_mechanism_without_strategy_promotion"
            if alpha_supported
            else "freeze_current_technical_shape_route"
        ),
        "interpretation": (
            "Alpha support and large-winner recall are reported separately. A dimension may be retained as a reusable quality mechanism without qualifying as a standalone selector."
        ),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    decision_path = args.protocol.with_name(f"{protocol['experiment']}-decision.json")
    decision_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
