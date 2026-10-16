#!/usr/bin/env python3
"""Compare preregistered omitted-breakout structures with matched failures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = (
    "contracting_shelf",
    "contraction_without_dry_up",
    "volume_dry_base",
    "ascending_base",
    "range_compression_only",
    "loose_breakout",
)


def classify_structure(*, range_contracting: bool, higher_low: bool, volume_dry: bool) -> str:
    if range_contracting and higher_low and volume_dry:
        return "contracting_shelf"
    if range_contracting and higher_low:
        return "contraction_without_dry_up"
    if volume_dry:
        return "volume_dry_base"
    if higher_low:
        return "ascending_base"
    if range_contracting:
        return "range_compression_only"
    return "loose_breakout"


def _matched_expected(
    rows: list[dict], category: str, *, year: int | None = None
) -> tuple[int, float]:
    scoped = [row for row in rows if year is None or int(row["signal_year"]) == year]
    leaders = [row for row in scoped if row["leader_50"]]
    controls = [row for row in scoped if row["failed_control"]]
    observed = sum(row["structure_category"] == category for row in leaders)
    expected = 0.0
    for regime in ("broad_bull", "transition", "weak_bear"):
        regime_leaders = [
            row for row in leaders if row["market_regime_at_signal"] == regime
        ]
        regime_controls = [
            row for row in controls if row["market_regime_at_signal"] == regime
        ]
        category_controls = sum(
            row["structure_category"] == category for row in regime_controls
        )
        expected += len(regime_leaders) * (category_controls + 1) / (
            len(regime_controls) + len(CATEGORIES)
        )
    return observed, expected


def summarize(rows: list[dict]) -> dict:
    years = sorted({int(row["signal_year"]) for row in rows})
    result = {}
    for category in CATEGORIES:
        items = [row for row in rows if row["structure_category"] == category]
        observed, expected = _matched_expected(rows, category)
        yearly = {}
        positive_enrichment_years = 0
        positive_alpha_years = 0
        for year in years:
            year_items = [row for row in items if int(row["signal_year"]) == year]
            year_observed, year_expected = _matched_expected(rows, category, year=year)
            enrichment = year_observed / year_expected if year_expected > 0 else None
            alpha = (
                sum(float(row["alpha_40d"]) for row in year_items) / len(year_items)
                if year_items else None
            )
            positive_enrichment_years += enrichment is not None and enrichment > 1.0
            positive_alpha_years += alpha is not None and alpha > 0
            yearly[str(year)] = {
                "opportunities": len(year_items),
                "leaders_50pct": year_observed,
                "matched_expected_leaders": year_expected,
                "matched_leader_enrichment": enrichment,
                "average_40d_alpha": alpha,
            }
        result[category] = {
            "opportunities": len(items),
            "leaders_50pct": observed,
            "leaders_100pct": sum(row["leader_100"] for row in items),
            "failed_controls": sum(row["failed_control"] for row in items),
            "matched_expected_leaders": expected,
            "matched_leader_enrichment": observed / expected if expected > 0 else None,
            "average_40d_alpha": (
                sum(float(row["alpha_40d"]) for row in items) / len(items)
                if items else None
            ),
            "positive_enrichment_years": positive_enrichment_years,
            "positive_alpha_years": positive_alpha_years,
            "by_year": yearly,
            "by_causal_market_regime": {
                regime: _category_headline([
                    row for row in rows
                    if row["market_regime_at_signal"] == regime
                ], category)
                for regime in ("broad_bull", "transition", "weak_bear")
            },
        }
    return result


def _category_headline(rows: list[dict], category: str) -> dict:
    items = [row for row in rows if row["structure_category"] == category]
    years = sorted({int(row["signal_year"]) for row in items})
    observed, expected = _matched_expected(rows, category)
    positive_enrichment_years = 0
    positive_alpha_years = 0
    for year in years:
        year_items = [row for row in items if int(row["signal_year"]) == year]
        year_observed, year_expected = _matched_expected(rows, category, year=year)
        positive_enrichment_years += year_expected > 0 and year_observed / year_expected > 1.0
        positive_alpha_years += (
            sum(float(row["alpha_40d"]) for row in year_items) / len(year_items) > 0
        )
    return {
        "opportunities": len(items),
        "leaders_50pct": observed,
        "leaders_100pct": sum(row["leader_100"] for row in items),
        "matched_expected_leaders": expected,
        "matched_leader_enrichment": observed / expected if expected > 0 else None,
        "average_40d_alpha": (
            sum(float(row["alpha_40d"]) for row in items) / len(items)
            if items else None
        ),
        "years_present": len(years),
        "positive_enrichment_years": positive_enrichment_years,
        "positive_alpha_years": positive_alpha_years,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "docs/research/vcp/production-vcp-omitted-category-audit-train-2016-2022-v1.json",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    opportunities = pl.read_parquet(ROOT / protocol["source"]).filter(
        pl.col("first_failed_gate") != "selected_by_vcp"
    )
    end = protocol["training_period"][1]
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if "date=2015-09-01" <= path.parent.name <= f"date={end}"
    ]
    event_keys = opportunities.select(
        pl.col("symbol"), pl.col("signal_date").alias("date")
    ).lazy()
    panel = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "date", "high", "low", "close", "volume")
        .sort(["symbol", "date"])
    )
    features = (
        panel
        .with_columns(
            pl.col("high").shift(1).rolling_max(10).over("symbol").alias("recent_high"),
            pl.col("low").shift(1).rolling_min(10).over("symbol").alias("recent_low"),
            pl.col("high").shift(11).rolling_max(10).over("symbol").alias("prior_high"),
            pl.col("low").shift(11).rolling_min(10).over("symbol").alias("prior_low"),
            pl.col("volume").shift(1).rolling_mean(10).over("symbol").alias("recent_volume"),
            pl.col("volume").shift(11).rolling_mean(30).over("symbol").alias("prior_volume"),
        )
        .join(event_keys, on=["symbol", "date"], how="inner")
        .with_columns(
            ((pl.col("recent_high") / pl.col("recent_low") - 1.0)
             < (pl.col("prior_high") / pl.col("prior_low") - 1.0)).alias("range_contracting"),
            (pl.col("recent_low") > pl.col("prior_low")).alias("higher_low"),
            (pl.col("recent_volume") < pl.col("prior_volume")).alias("volume_dry"),
        )
        .select("symbol", "date", "range_contracting", "higher_low", "volume_dry")
        .collect()
    )
    market = (
        panel.select("symbol", "date", "close")
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1.0)
            .alias("stock_return")
        )
        .filter(pl.col("stock_return").is_finite() & pl.col("stock_return").is_between(-0.5, 0.5))
        .group_by("date")
        .agg(pl.col("stock_return").mean().alias("market_return"))
        .sort("date")
        .with_columns((1.0 + pl.col("market_return")).cum_prod().alias("market_index"))
        .with_columns(
            (pl.col("market_index") / pl.col("market_index").shift(63) - 1.0)
            .alias("market_return_63d_at_signal")
        )
        .select("date", "market_return_63d_at_signal")
        .collect()
    )
    joined = opportunities.join(
        features, left_on=["symbol", "signal_date"], right_on=["symbol", "date"], how="inner"
    ).join(
        market, left_on="signal_date", right_on="date", how="left"
    ).with_columns(
        pl.when(
            (pl.col("market_breadth_ma20") >= 0.7)
            & (pl.col("market_return_63d_at_signal") >= 0)
        )
        .then(pl.lit("broad_bull"))
        .when(
            (pl.col("market_breadth_ma20") < 0.3)
            & (pl.col("market_return_63d_at_signal") < 0)
        )
        .then(pl.lit("weak_bear"))
        .otherwise(pl.lit("transition"))
        .alias("market_regime_at_signal"),
        pl.when(pl.col("market_return_40d") < -0.05)
        .then(pl.lit("down"))
        .when(pl.col("market_return_40d") > 0.05)
        .then(pl.lit("up"))
        .otherwise(pl.lit("sideways"))
        .alias("market_outcome"),
        (pl.col("mfe_40d") >= 0.5).alias("leader_50"),
        (pl.col("mfe_40d") >= 1.0).alias("leader_100"),
        ((pl.col("mfe_40d") < 0.1) & (pl.col("alpha_40d") <= 0)).alias("failed_control"),
    )
    rows = joined.to_dicts()
    for row in rows:
        row["structure_category"] = classify_structure(
            range_contracting=bool(row["range_contracting"]),
            higher_low=bool(row["higher_low"]),
            volume_dry=bool(row["volume_dry"]),
        )
    categorized = pl.DataFrame(rows)
    category_summary = summarize(rows)
    gates = protocol["direction_gate"]
    regime_gates = protocol["regime_specific_direction_gate"]
    decisions = {}
    eligible_scopes = []
    for category, item in category_summary.items():
        checks = {
            "minimum_opportunities": item["opportunities"] >= gates["minimum_opportunities"],
            "minimum_50pct_leaders": item["leaders_50pct"] >= gates["minimum_50pct_leaders"],
            "minimum_matched_leader_enrichment": (
                item["matched_leader_enrichment"] is not None
                and item["matched_leader_enrichment"] >= gates["minimum_matched_leader_enrichment"]
            ),
            "minimum_positive_enrichment_years": (
                item["positive_enrichment_years"] >= gates["minimum_positive_enrichment_years"]
            ),
            "minimum_positive_alpha_years": (
                item["positive_alpha_years"] >= gates["minimum_positive_alpha_years"]
            ),
            "promotable_category": category != "loose_breakout",
        }
        all_market_passed = all(checks.values())
        regime_checks = {}
        for regime, regime_item in item["by_causal_market_regime"].items():
            scoped_checks = {
                "minimum_opportunities": regime_item["opportunities"] >= regime_gates["minimum_opportunities"],
                "minimum_50pct_leaders": regime_item["leaders_50pct"] >= regime_gates["minimum_50pct_leaders"],
                "minimum_matched_leader_enrichment": (
                    regime_item["matched_leader_enrichment"] is not None
                    and regime_item["matched_leader_enrichment"] >= regime_gates["minimum_matched_leader_enrichment"]
                ),
                "minimum_years_present": regime_item["years_present"] >= regime_gates["minimum_years_present"],
                "minimum_positive_enrichment_years": regime_item["positive_enrichment_years"] >= regime_gates["minimum_positive_enrichment_years"],
                "minimum_positive_alpha_years": regime_item["positive_alpha_years"] >= regime_gates["minimum_positive_alpha_years"],
                "promotable_category": category != "loose_breakout",
            }
            regime_checks[regime] = {
                "checks": scoped_checks,
                "passed": all(scoped_checks.values()),
            }
            if all(scoped_checks.values()):
                eligible_scopes.append((
                    category,
                    regime,
                    regime_item["leaders_50pct"],
                    regime_item["matched_leader_enrichment"],
                ))
        decisions[category] = {
            "all_market": {"checks": checks, "passed": all_market_passed},
            "by_causal_market_regime": regime_checks,
        }
        if all_market_passed:
            eligible_scopes.append((
                category,
                "all_market",
                item["leaders_50pct"],
                item["matched_leader_enrichment"],
            ))
    selected_scope = max(
        eligible_scopes,
        key=lambda value: (value[2], value[3]),
        default=None,
    )
    selected = selected_scope[0] if selected_scope else None
    output_dir = (
        args.data_root / "research/vcp/category-audits" / protocol["experiment"]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    categorized.write_parquet(output_dir / "categorized-opportunities.parquet")
    report = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "source_opportunities": opportunities.height,
        "categorized_opportunities": categorized.height,
        "categories": category_summary,
        "direction_decisions": decisions,
        "selected_category": selected,
        "selected_applicability": selected_scope[1] if selected_scope else None,
        "decision": "register_one_category" if selected else "stop_representation",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "output": str(output_dir / "summary.json"),
        "categorized_opportunities": categorized.height,
        "selected_category": selected,
        "selected_applicability": selected_scope[1] if selected_scope else None,
        "decision": report["decision"],
        "category_headlines": {
            category: {
                key: item[key]
                for key in (
                    "opportunities", "leaders_50pct", "leaders_100pct",
                    "matched_leader_enrichment", "positive_enrichment_years",
                    "positive_alpha_years",
                )
            }
            for category, item in category_summary.items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
