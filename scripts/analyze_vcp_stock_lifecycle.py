#!/usr/bin/env python3
"""Describe whether VCP follow-through varies with the stock's trend lifecycle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)
DEFAULT_OUTPUT = ROOT / "data/research/vcp/analysis/stock-lifecycle-2017-2026-v1.json"
FEATURES = (
    "prior_runup_63_before_base",
    "prior_return_126d",
    "base_days",
    "base_depth",
    "distance_to_252d_high",
    "prior_unique_setups_365d",
    "days_since_prior_unique_setup",
)


def _pairwise_probability(values: pd.Series, labels: pd.Series) -> float | None:
    frame = pd.DataFrame({"value": values, "label": labels}).dropna()
    positive = frame.loc[frame["label"].astype(bool), "value"].to_numpy(float)
    negative = frame.loc[~frame["label"].astype(bool), "value"].to_numpy(float)
    if not len(positive) or not len(negative):
        return None
    comparisons = positive[:, None] - negative[None, :]
    return float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)


def _spearman(values: pd.Series, outcomes: pd.Series) -> float | None:
    frame = pd.DataFrame({"value": values, "outcome": outcomes}).dropna()
    if len(frame) < 3 or frame["value"].nunique() < 2 or frame["outcome"].nunique() < 2:
        return None
    return float(frame["value"].rank().corr(frame["outcome"].rank()))


def _add_prior_setup_history(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values(["symbol", "signal_date", "scale", "pivot_date"]).copy()
    counts: list[int] = []
    gaps: list[float] = []
    history: dict[str, list[pd.Timestamp]] = {}
    for row in frame.itertuples(index=False):
        dates = history.setdefault(row.symbol, [])
        prior = [value for value in dates if 0 < (row.signal_date - value).days <= 365]
        counts.append(len(prior))
        gaps.append(float((row.signal_date - dates[-1]).days) if dates else np.nan)
        dates.append(row.signal_date)
    frame["prior_unique_setups_365d"] = counts
    frame["days_since_prior_unique_setup"] = gaps
    return frame


def _quintile_profile(frame: pd.DataFrame, feature: str) -> list[dict]:
    usable = frame.dropna(subset=[feature, "return_40d", "true_breakout_10_7_20"]).copy()
    usable["year_rank"] = usable.groupby("year")[feature].rank(method="average", pct=True)
    usable["quintile"] = np.minimum(np.ceil(usable["year_rank"] * 5), 5).astype(int)
    rows = []
    for quintile, group in usable.groupby("quintile", sort=True):
        rows.append({
            "quintile": int(quintile),
            "n": len(group),
            "feature_median": float(group[feature].median()),
            "true_breakout_rate": float(group["true_breakout_10_7_20"].mean()),
            "return_40d_median": float(group["return_40d"].median()),
            "mfe_40d_median": float(group["mfe_40d"].median()),
        })
    return rows


def _feature_summary(frame: pd.DataFrame, feature: str) -> dict:
    overall_auc = _pairwise_probability(frame[feature], frame["true_breakout_10_7_20"])
    annual = []
    for year, group in frame.groupby("year", sort=True):
        auc = _pairwise_probability(group[feature], group["true_breakout_10_7_20"])
        if auc is not None:
            annual.append({"year": int(year), "n": int(group[feature].notna().sum()), "pairwise_probability": auc})
    return {
        "n": int(frame[feature].notna().sum()),
        "pairwise_probability": overall_auc,
        "spearman_return_40d": _spearman(frame[feature], frame["return_40d"]),
        "annual": annual,
        "years_above_0_5": sum(row["pairwise_probability"] > 0.5 for row in annual),
        "years_below_0_5": sum(row["pairwise_probability"] < 0.5 for row in annual),
        "quintiles": _quintile_profile(frame, feature),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    frames = []
    for path in DEFAULT_INPUTS:
        if not path.exists():
            raise FileNotFoundError(path)
        item = pl.read_parquet(path).with_columns(pl.lit(path.parent.name).alias("source_slice"))
        frames.append(item)
    data = pl.concat(frames, how="diagonal_relaxed").to_pandas()
    data["signal_date"] = pd.to_datetime(data["signal_date"])
    data["pivot_date"] = pd.to_datetime(data["pivot_date"])
    input_rows = len(data)
    data = (
        data.sort_values(["signal_date", "symbol", "scale", "pivot_date"])
        .drop_duplicates(["symbol", "scale", "pivot_date"], keep="first")
        .reset_index(drop=True)
    )
    data = _add_prior_setup_history(data)
    data["year"] = data["signal_date"].dt.year
    data["true_breakout_10_7_20"] = data["true_breakout_10_7_20"].astype("boolean")

    repeated_groups = []
    setup_group = pd.cut(
        data["prior_unique_setups_365d"],
        bins=[-1, 0, 1, np.inf],
        labels=["0", "1", "2_plus"],
    )
    for label, group in data.groupby(setup_group, observed=True):
        usable = group.dropna(subset=["true_breakout_10_7_20", "return_40d"])
        repeated_groups.append({
            "prior_unique_setups_365d": str(label),
            "n": len(usable),
            "true_breakout_rate": float(usable["true_breakout_10_7_20"].mean()),
            "return_40d_median": float(usable["return_40d"].median()),
            "mfe_40d_median": float(usable["mfe_40d"].median()),
        })

    result = {
        "analysis": "stock-lifecycle-2017-2026-v1",
        "inputs": [str(path.relative_to(ROOT)).replace("\\", "/") for path in DEFAULT_INPUTS],
        "input_rows": input_rows,
        "unique_setups": len(data),
        "removed_repeat_daily_signals": input_rows - len(data),
        "date_range": [data["signal_date"].min().date().isoformat(), data["signal_date"].max().date().isoformat()],
        "years": sorted(int(value) for value in data["year"].unique()),
        "outcome_rate": float(data["true_breakout_10_7_20"].mean()),
        "features": {feature: _feature_summary(data, feature) for feature in FEATURES},
        "prior_setup_groups": repeated_groups,
        "guardrails": {
            "strategy_changed": False,
            "threshold_selected": False,
            "portfolio_backtest_run": False,
            "future_columns_used_only_as_labels": ["true_breakout_10_7_20", "return_40d", "mfe_40d"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "input_rows": input_rows,
        "unique_setups": len(data),
        "date_range": result["date_range"],
        "outcome_rate": result["outcome_rate"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
