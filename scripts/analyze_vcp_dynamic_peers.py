#!/usr/bin/env python3
"""Audit causal co-moving peer confirmation for historical VCP candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)
DEFAULT_OUTPUT = ROOT / "data/research/vcp/analysis/dynamic-peer-confirmation-2017-2026-v1.json"
DEFAULT_FEATURES = ROOT / "data/research/vcp/analysis/dynamic-peer-confirmation-2017-2026-v1.parquet"
PEER_FEATURES = (
    "peer_correlation_median",
    "peer_above_ma20_share",
    "peer_return_20d_median",
    "peer_at_63d_high_share",
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


def _candidate_frame() -> pd.DataFrame:
    frames = []
    for path in CANDIDATE_INPUTS:
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(pl.read_parquet(path))
    data = pl.concat(frames, how="diagonal_relaxed").to_pandas()
    data["signal_date"] = pd.to_datetime(data["signal_date"])
    data["pivot_date"] = pd.to_datetime(data["pivot_date"])
    return (
        data.sort_values(["signal_date", "symbol", "scale", "pivot_date"])
        .drop_duplicates(["symbol", "scale", "pivot_date"], keep="first")
        .reset_index(drop=True)
    )


def _close_matrix(start: pd.Timestamp, end: pd.Timestamp) -> tuple[np.ndarray, list[pd.Timestamp], list[str]]:
    frame = (
        pl.scan_parquet(str(ROOT / "data/kline_daily_enriched/date=*/part.parquet"))
        .select("date", "symbol", "close")
        .filter(
            (pl.col("date") >= pl.lit(start.date()))
            & (pl.col("date") <= pl.lit(end.date()))
        )
        .collect()
        .pivot(index="date", on="symbol", values="close", aggregate_function="last")
        .sort("date")
    )
    dates = [pd.Timestamp(value) for value in frame.get_column("date").to_list()]
    symbols = [column for column in frame.columns if column != "date"]
    values = frame.select(symbols).to_numpy().astype(np.float64, copy=False)
    return values, dates, symbols


def _correlations(window: np.ndarray, candidate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(window) & np.isfinite(candidate[:, None])
    count = mask.sum(axis=0)
    x = np.where(mask, candidate[:, None], 0.0)
    y = np.where(mask, window, 0.0)
    sum_x = x.sum(axis=0)
    sum_y = y.sum(axis=0)
    numerator = count * (x * y).sum(axis=0) - sum_x * sum_y
    denominator = np.sqrt(
        (count * (x * x).sum(axis=0) - sum_x * sum_x)
        * (count * (y * y).sum(axis=0) - sum_y * sum_y)
    )
    corr = np.divide(
        numerator,
        denominator,
        out=np.full(window.shape[1], np.nan),
        where=(count >= 50) & (denominator > 0),
    )
    return corr, count


def _peer_features(
    close: np.ndarray,
    date_index: int,
    symbol_index: int,
) -> dict[str, float | int | None]:
    if date_index < 64:
        return {"peer_count": 0, **{feature: None for feature in PEER_FEATURES}}
    history = close[date_index - 64 : date_index]
    returns = history[1:] / history[:-1] - 1.0
    correlations, _counts = _correlations(returns, returns[:, symbol_index])
    correlations[symbol_index] = np.nan
    eligible = np.flatnonzero(np.isfinite(correlations) & (correlations > 0))
    if not len(eligible):
        return {"peer_count": 0, **{feature: None for feature in PEER_FEATURES}}
    order = eligible[np.argsort(correlations[eligible])[-20:]]

    current = close[date_index, order]
    ma20_window = close[date_index - 19 : date_index + 1, order]
    ma20_count = np.isfinite(ma20_window).sum(axis=0)
    ma20 = np.divide(
        np.nansum(ma20_window, axis=0),
        ma20_count,
        out=np.full(len(order), np.nan),
        where=ma20_count == 20,
    )
    above = current > ma20
    prior20 = close[date_index - 20, order]
    return20 = current / prior20 - 1.0
    high_window = close[date_index - 62 : date_index + 1, order]
    high_count = np.isfinite(high_window).sum(axis=0)
    high63 = np.max(np.where(np.isfinite(high_window), high_window, -np.inf), axis=0)
    at_high = current >= high63 * (1.0 - 1e-7)

    valid_above = np.isfinite(current) & np.isfinite(ma20)
    valid_return = np.isfinite(return20)
    valid_high = np.isfinite(current) & (high_count == 63)
    return {
        "peer_count": len(order),
        "peer_correlation_median": float(np.median(correlations[order])),
        "peer_above_ma20_share": float(np.mean(above[valid_above])) if valid_above.any() else None,
        "peer_return_20d_median": float(np.median(return20[valid_return])) if valid_return.any() else None,
        "peer_at_63d_high_share": float(np.mean(at_high[valid_high])) if valid_high.any() else None,
    }


def _quintiles(frame: pd.DataFrame, feature: str) -> list[dict]:
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


def _summary(frame: pd.DataFrame, feature: str) -> dict:
    annual = []
    for year, group in frame.groupby("year", sort=True):
        probability = _pairwise_probability(group[feature], group["true_breakout_10_7_20"])
        if probability is not None:
            annual.append({
                "year": int(year),
                "n": int(group[feature].notna().sum()),
                "pairwise_probability": probability,
            })
    return {
        "n": int(frame[feature].notna().sum()),
        "pairwise_probability": _pairwise_probability(frame[feature], frame["true_breakout_10_7_20"]),
        "spearman_return_40d": _spearman(frame[feature], frame["return_40d"]),
        "years_above_0_5": sum(row["pairwise_probability"] > 0.5 for row in annual),
        "years_below_0_5": sum(row["pairwise_probability"] < 0.5 for row in annual),
        "annual": annual,
        "quintiles": _quintiles(frame, feature),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--features-output", type=Path, default=DEFAULT_FEATURES)
    args = parser.parse_args()

    candidates = _candidate_frame()
    close, dates, symbols = _close_matrix(
        candidates["signal_date"].min() - pd.Timedelta(days=150),
        candidates["signal_date"].max(),
    )
    date_lookup = {value: index for index, value in enumerate(dates)}
    symbol_lookup = {value: index for index, value in enumerate(symbols)}
    features = []
    for row in candidates.itertuples(index=False):
        date_index = date_lookup.get(row.signal_date)
        symbol_index = symbol_lookup.get(row.symbol)
        if date_index is None or symbol_index is None:
            values = {"peer_count": 0, **{feature: None for feature in PEER_FEATURES}}
        else:
            values = _peer_features(close, date_index, symbol_index)
        features.append(values)
    feature_frame = pd.DataFrame(features)
    result_frame = pd.concat([candidates.reset_index(drop=True), feature_frame], axis=1)
    result_frame["year"] = result_frame["signal_date"].dt.year
    result_frame["true_breakout_10_7_20"] = result_frame["true_breakout_10_7_20"].astype("boolean")

    args.features_output.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(result_frame).write_parquet(args.features_output)
    result = {
        "analysis": "dynamic-peer-confirmation-2017-2026-v1",
        "unique_setups": len(result_frame),
        "setups_with_20_peers": int((result_frame["peer_count"] == 20).sum()),
        "date_range": [
            result_frame["signal_date"].min().date().isoformat(),
            result_frame["signal_date"].max().date().isoformat(),
        ],
        "features": {feature: _summary(result_frame, feature) for feature in PEER_FEATURES},
        "guardrails": {
            "strategy_changed": False,
            "threshold_selected": False,
            "portfolio_backtest_run": False,
            "peer_selection_ends_before_signal_day": True,
            "future_columns_used_only_as_labels": ["true_breakout_10_7_20", "return_40d", "mfe_40d"],
        },
        "candidate_features": str(args.features_output.relative_to(ROOT)).replace("\\", "/"),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "unique_setups": len(result_frame),
        "setups_with_20_peers": result["setups_with_20_peers"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
