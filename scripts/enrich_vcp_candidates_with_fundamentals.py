"""Attach strictly point-in-time market-core fundamentals to VCP candidates.

Run from ``backend`` after ``prepare_vcp_fundamentals.py`` and
``analyze_vcp_breakout_candidates.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "research" / "vcp"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-version", default="source-vcp-v3")
    parser.add_argument("--fundamental-version", default="market-core-v1")
    parser.add_argument("--output-version", default="source-vcp-v3-fundamental-v1")
    args = parser.parse_args()

    candidate_path = DATA / "candidate-labels" / args.candidate_version / "discovery-candidates.parquet"
    fundamental_path = DATA / "fundamentals" / args.fundamental_version / "metrics.parquet"
    if not candidate_path.exists() or not fundamental_path.exists():
        raise FileNotFoundError(f"missing input: {candidate_path} or {fundamental_path}")

    candidates = pl.read_parquet(candidate_path).with_columns(
        pl.col("signal_date").cast(pl.Utf8).str.slice(0, 10).str.to_date().alias("_signal_date")
    )
    fundamentals = (
        pl.read_parquet(fundamental_path)
        .sort(["symbol", "period_end", "announce_date"])
        .with_columns(
            pl.col("announce_date").shift(1).over("symbol").alias("fundamental_prior_announce_date"),
            pl.col("revenue_yoy").shift(1).over("symbol").alias("fundamental_prior_revenue_yoy"),
            pl.col("net_income_yoy").shift(1).over("symbol").alias("fundamental_prior_net_income_yoy"),
            pl.col("gross_margin").shift(1).over("symbol").alias("fundamental_prior_gross_margin"),
            pl.col("roe").shift(1).over("symbol").alias("fundamental_prior_roe"),
        )
        .with_columns(
            pl.when(pl.col("fundamental_prior_announce_date") < pl.col("announce_date"))
            .then(pl.col("revenue_yoy") - pl.col("fundamental_prior_revenue_yoy"))
            .alias("fundamental_revenue_growth_accel"),
            pl.when(pl.col("fundamental_prior_announce_date") < pl.col("announce_date"))
            .then(pl.col("net_income_yoy") - pl.col("fundamental_prior_net_income_yoy"))
            .alias("fundamental_profit_growth_accel"),
            pl.when(pl.col("fundamental_prior_announce_date") < pl.col("announce_date"))
            .then(pl.col("gross_margin") - pl.col("fundamental_prior_gross_margin"))
            .alias("fundamental_gross_margin_change"),
            pl.when(pl.col("fundamental_prior_announce_date") < pl.col("announce_date"))
            .then(pl.col("roe") - pl.col("fundamental_prior_roe"))
            .alias("fundamental_roe_change"),
        )
        .rename(
            {
                "announce_date": "fundamental_announce_date",
                "period_end": "fundamental_period_end",
                "revenue_yoy": "fundamental_revenue_yoy",
                "net_income_yoy": "fundamental_net_income_yoy",
                "roe": "fundamental_roe",
                "gross_margin": "fundamental_gross_margin",
                "quality_level": "fundamental_quality_level",
                "source": "fundamental_source",
            }
        )
    )
    fields = [
        "symbol",
        "fundamental_announce_date",
        "fundamental_period_end",
        "fundamental_revenue_yoy",
        "fundamental_net_income_yoy",
        "fundamental_roe",
        "fundamental_gross_margin",
        "fundamental_prior_announce_date",
        "fundamental_prior_revenue_yoy",
        "fundamental_prior_net_income_yoy",
        "fundamental_prior_gross_margin",
        "fundamental_prior_roe",
        "fundamental_revenue_growth_accel",
        "fundamental_profit_growth_accel",
        "fundamental_gross_margin_change",
        "fundamental_roe_change",
        "fundamental_quality_level",
        "fundamental_source",
    ]
    enriched = (
        candidates.sort(["_signal_date", "symbol"])
        .join_asof(
            fundamentals.select(fields).sort(["fundamental_announce_date", "symbol"]),
            left_on="_signal_date",
            right_on="fundamental_announce_date",
            by="symbol",
            strategy="backward",
            allow_exact_matches=False,
            check_sortedness=False,
        )
        .drop("_signal_date")
        .sort(["signal_date", "symbol"])
    )
    if enriched.height != candidates.height:
        raise RuntimeError("point-in-time join changed candidate row count")
    if enriched.filter(
        pl.col("fundamental_announce_date").is_not_null()
        & (
            pl.col("fundamental_announce_date")
            >= pl.col("signal_date").cast(pl.Utf8).str.slice(0, 10).str.to_date()
        )
    ).height:
        raise RuntimeError("lookahead fundamental row detected")

    output_dir = DATA / "candidate-labels" / args.output_version
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched.write_parquet(output_dir / "discovery-candidates.parquet")
    enriched.write_csv(output_dir / "discovery-candidates.csv", include_bom=True)
    report = {
        "candidate_version": args.candidate_version,
        "fundamental_version": args.fundamental_version,
        "output_version": args.output_version,
        "rows": enriched.height,
        "fundamental_coverage": float(
            enriched["fundamental_period_end"].is_not_null().mean()
        ),
        "revenue_yoy_coverage": float(
            enriched["fundamental_revenue_yoy"].is_not_null().mean()
        ),
        "net_income_yoy_coverage": float(
            enriched["fundamental_net_income_yoy"].is_not_null().mean()
        ),
        "strict_after_announcement": True,
        "source": "local_financial/akshare_eastmoney",
    }
    (output_dir / "enrichment-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
