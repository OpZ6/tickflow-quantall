#!/usr/bin/env python3
"""Reconstruct a causal nested final pivot inside broad VCP candidates."""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)
DEFAULT_OUTPUT = ROOT / "data/research/vcp/analysis/nested-final-pivot-2017-2026-v1.json"
DEFAULT_FEATURES = ROOT / "data/research/vcp/analysis/nested-final-pivot-2017-2026-v1.parquet"


def _candidates() -> pl.DataFrame:
    frames = []
    for path in CANDIDATE_INPUTS:
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(pl.read_parquet(path))
    return (
        pl.concat(frames, how="diagonal_relaxed")
        .with_columns(
            pl.col("signal_date").cast(pl.Utf8).str.to_date(strict=True),
            pl.col("pivot_date").cast(pl.Utf8).str.to_date(strict=True),
        )
        .sort(["signal_date", "symbol", "scale", "pivot_date"])
        .unique(["symbol", "scale", "pivot_date"], keep="first", maintain_order=True)
    )


def _market_by_symbol(candidates: pl.DataFrame) -> dict[str, pl.DataFrame]:
    symbols = candidates.get_column("symbol").unique().to_list()
    start = candidates.get_column("signal_date").min() - timedelta(days=150)
    end = candidates.get_column("signal_date").max()
    market = (
        pl.scan_parquet(str(ROOT / "data/kline_daily_enriched/date=*/part.parquet"))
        .select("symbol", "date", "high", "low", "close")
        .filter(
            pl.col("symbol").is_in(symbols)
            & (pl.col("date") >= start)
            & (pl.col("date") <= end)
        )
        .collect()
        .sort(["symbol", "date"])
    )
    return {
        str(key[0] if isinstance(key, tuple) else key): frame
        for key, frame in market.partition_by("symbol", as_dict=True).items()
    }


def _nested_pivot(
    bars: pl.DataFrame,
    *,
    signal_date,
    last_low_date,
    signal_close: float,
) -> dict[str, object]:
    segment = bars.filter(
        (pl.col("date") >= last_low_date) & (pl.col("date") < signal_date)
    )
    if segment.height < 3:
        return {"nested_pivot_available": False, "nested_pivot_reason": "fewer_than_3_pre_signal_bars"}
    highs = segment.get_column("high").to_numpy()
    lows = segment.get_column("low").to_numpy()
    dates = segment.get_column("date").to_list()
    candidates = [
        index
        for index in range(1, len(highs) - 1)
        if np.isfinite(highs[index - 1 : index + 2]).all()
        and highs[index] >= highs[index - 1]
        and highs[index] >= highs[index + 1]
        and (highs[index] > highs[index - 1] or highs[index] > highs[index + 1])
        and highs[index] < signal_close
    ]
    if not candidates:
        return {"nested_pivot_available": False, "nested_pivot_reason": "no_confirmed_local_high"}
    pivot_index = candidates[-1]
    post_pivot_lows = lows[pivot_index + 1 :]
    if not len(post_pivot_lows) or not np.isfinite(post_pivot_lows).any():
        return {"nested_pivot_available": False, "nested_pivot_reason": "no_post_pivot_low"}
    structure_low = float(np.nanmin(post_pivot_lows))
    pivot = float(highs[pivot_index])
    return {
        "nested_pivot_available": True,
        "nested_pivot_reason": "ok",
        "nested_pivot_date": dates[pivot_index],
        "nested_pivot": pivot,
        "nested_structure_low": structure_low,
        "nested_risk_from_signal_close": 1.0 - structure_low / signal_close,
        "nested_pivot_distance_from_signal_close": signal_close / pivot - 1.0,
        "nested_structure_bars": len(highs) - pivot_index - 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--features-output", type=Path, default=DEFAULT_FEATURES)
    args = parser.parse_args()

    candidates = _candidates()
    market = _market_by_symbol(candidates)
    records = []
    for row in candidates.iter_rows(named=True):
        last_low_date = row["signal_date"] - timedelta(days=int(row["last_low_age_days"]))
        bars = market.get(row["symbol"])
        if bars is None:
            nested = {"nested_pivot_available": False, "nested_pivot_reason": "missing_symbol_bars"}
            broad_risk = None
            signal_close = None
        else:
            low_row = bars.filter(pl.col("date") == last_low_date)
            signal_row = bars.filter(pl.col("date") == row["signal_date"])
            broad_low = float(low_row.get_column("low").item()) if low_row.height == 1 else None
            signal_close = (
                float(signal_row.get_column("close").item())
                if signal_row.height == 1
                else None
            )
            broad_risk = (
                1.0 - broad_low / signal_close
                if broad_low is not None and signal_close is not None and signal_close > 0
                else None
            )
            nested = (
                _nested_pivot(
                    bars,
                    signal_date=row["signal_date"],
                    last_low_date=last_low_date,
                    signal_close=signal_close,
                )
                if signal_close is not None
                else {"nested_pivot_available": False, "nested_pivot_reason": "missing_signal_bar"}
            )
        nested_risk = nested.get("nested_risk_from_signal_close")
        compression = (
            float(nested_risk) / broad_risk
            if nested_risk is not None and broad_risk is not None and broad_risk > 0
            else None
        )
        records.append({
            "symbol": row["symbol"],
            "signal_date": row["signal_date"],
            "scale": row["scale"],
            "pivot_date": row["pivot_date"],
            "last_low_date": last_low_date,
            "signal_close": signal_close,
            "broad_last_low_risk_from_signal_close": broad_risk,
            "risk_compression_ratio": compression,
            "true_breakout_10_7_20": row["true_breakout_10_7_20"],
            "return_40d": row["return_40d"],
            "mfe_40d": row["mfe_40d"],
            **nested,
        })
    features = pl.DataFrame(records).with_columns(pl.col("signal_date").dt.year().alias("year"))
    args.features_output.parent.mkdir(parents=True, exist_ok=True)
    features.write_parquet(args.features_output)

    usable = features.filter(pl.col("nested_pivot_available"))
    annual = (
        features.group_by("year")
        .agg(
            pl.len().alias("setups"),
            pl.col("nested_pivot_available").sum().alias("available"),
            pl.col("nested_pivot_available").mean().alias("coverage"),
            pl.col("nested_risk_from_signal_close").median().alias("nested_risk_median"),
            pl.col("broad_last_low_risk_from_signal_close").median().alias("broad_risk_median"),
        )
        .sort("year")
        .to_dicts()
    )
    by_outcome = (
        usable.group_by("true_breakout_10_7_20")
        .agg(
            pl.len().alias("setups"),
            pl.col("nested_risk_from_signal_close").median().alias("nested_risk_median"),
            pl.col("broad_last_low_risk_from_signal_close").median().alias("broad_risk_median"),
            pl.col("return_40d").median().alias("return_40d_median"),
        )
        .sort("true_breakout_10_7_20")
        .to_dicts()
    )
    full_years = [row for row in annual if 2018 <= row["year"] <= 2025]
    coverage = usable.height / features.height
    nested_median = float(usable.get_column("nested_risk_from_signal_close").median())
    broad_median = float(usable.get_column("broad_last_low_risk_from_signal_close").median())
    accepted = bool(
        coverage >= 0.70
        and all(row["coverage"] >= 0.60 for row in full_years)
        and nested_median <= broad_median * 0.5
    )
    result = {
        "analysis": "nested-final-pivot-2017-2026-v1",
        "unique_setups": features.height,
        "available_setups": usable.height,
        "coverage": coverage,
        "nested_risk_median": nested_median,
        "broad_risk_median_on_available_setups": broad_median,
        "risk_compression_ratio_of_medians": nested_median / broad_median,
        "annual": annual,
        "by_future_outcome_descriptive_only": by_outcome,
        "acceptance": {
            "overall_coverage_at_least_0_70": coverage >= 0.70,
            "every_full_year_coverage_at_least_0_60": all(row["coverage"] >= 0.60 for row in full_years),
            "median_nested_risk_at_most_half_broad_risk": nested_median <= broad_median * 0.5,
            "accepted": accepted,
        },
        "guardrails": {
            "strategy_changed": False,
            "threshold_selected": False,
            "portfolio_backtest_run": False,
            "signal_day_high_low_used": False,
            "future_columns_used_only_as_descriptive_labels": True,
        },
        "features": str(args.features_output.relative_to(ROOT)).replace("\\", "/"),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "unique_setups": features.height,
        "coverage": coverage,
        "nested_risk_median": nested_median,
        "broad_risk_median": broad_median,
        "accepted": accepted,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
