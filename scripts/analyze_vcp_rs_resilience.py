#!/usr/bin/env python3
"""Audit signal-time VCP relative-strength persistence without tuning a strategy."""
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
DEFAULT_PROTOCOL = (
    ROOT / "docs/research/vcp/production-leader-final-leg-rs-resilience-audit-2017-2026-v2.json"
)
DEFAULT_OUTPUT = ROOT / "data/research/vcp/analysis/final-leg-rs-resilience-2017-2026-v2.json"
DEFAULT_FEATURES = ROOT / "data/research/vcp/analysis/final-leg-rs-resilience-2017-2026-v2.parquet"
PRIMARY_FEATURE = "final_leg_rs85_share"


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
        pl.scan_parquet(
            str(ROOT / "data/kline_daily_enriched/date=*/part.parquet"),
            extra_columns="ignore",
            missing_columns="insert",
        )
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
    return frame.select(symbols).to_numpy().astype(np.float32, copy=False), dates, symbols


def _valid_shift(values: np.ndarray, periods: int) -> np.ndarray:
    output = np.full(values.shape, np.nan, dtype=np.float32)
    for asset in range(values.shape[1]):
        rows = np.flatnonzero(np.isfinite(values[:, asset]) & (values[:, asset] > 0))
        if len(rows) > periods:
            output[rows[periods:], asset] = values[rows[:-periods], asset]
    return output


def _rs_percentiles(close: np.ndarray) -> np.ndarray:
    returns = []
    for period in (63, 126, 252):
        previous = _valid_shift(close, period)
        returns.append(
            np.divide(close, previous, out=np.full(close.shape, np.nan), where=previous > 0) - 1
        )
    raw = 0.4 * returns[0] + 0.2 * returns[1] + 0.4 * returns[2]
    ranks = np.full(raw.shape, np.nan, dtype=np.float32)
    for time_index, values in enumerate(raw):
        ids = np.flatnonzero(np.isfinite(values) & np.isfinite(close[time_index]))
        if not len(ids):
            continue
        ordered = np.sort(values[ids])
        ranks[time_index, ids] = (
            np.searchsorted(ordered, values[ids], "left")
            + np.searchsorted(ordered, values[ids], "right")
            + 1
        ) * 50.0 / len(ids)
    return ranks


def _market_sessions(protocol: dict) -> list[pd.Timestamp]:
    path = ROOT / protocol["measurement_contract"]["calendar_partition"]
    calendar = pl.read_parquet(path).filter(
        (pl.col("exchange") == "SSE") & pl.col("is_open")
    )
    dates = sorted(set(calendar.get_column("trade_date").to_list()))
    if not dates:
        raise RuntimeError(f"market calendar has no open sessions: {path}")
    return [pd.Timestamp(value) for value in dates]


def _pairwise_probability(values: pd.Series, labels: pd.Series) -> float | None:
    frame = pd.DataFrame({"value": values, "label": labels}).dropna()
    positive = frame.loc[frame["label"].astype(bool), "value"].to_numpy(float)
    negative = frame.loc[~frame["label"].astype(bool), "value"].to_numpy(float)
    if not len(positive) or not len(negative):
        return None
    comparisons = positive[:, None] - negative[None, :]
    return float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)


def _summarize(frame: pd.DataFrame, protocol: dict) -> dict:
    annual = []
    for year, group in frame.groupby("year", sort=True):
        probability = _pairwise_probability(group[PRIMARY_FEATURE], group["true_breakout_10_7_20"])
        if probability is not None:
            annual.append({
                "year": int(year),
                "n": int(group[PRIMARY_FEATURE].notna().sum()),
                "pairwise_probability": probability,
            })
    usable = frame.dropna(subset=[PRIMARY_FEATURE, "true_breakout_10_7_20"]).copy()
    usable["year_rank"] = usable.groupby("year")[PRIMARY_FEATURE].rank(method="average", pct=True)
    usable["quintile"] = np.minimum(np.ceil(usable["year_rank"] * 5), 5).astype(int)
    quintiles = []
    for quintile, group in usable.groupby("quintile", sort=True):
        quintiles.append({
            "quintile": int(quintile),
            "n": len(group),
            "feature_median": float(group[PRIMARY_FEATURE].median()),
            "true_breakout_rate": float(group["true_breakout_10_7_20"].mean()),
            "return_40d_median": float(group["return_40d"].median()),
        })
    coverage = float(frame[PRIMARY_FEATURE].notna().mean())
    pairwise = _pairwise_probability(frame[PRIMARY_FEATURE], frame["true_breakout_10_7_20"])
    years_above = sum(row["pairwise_probability"] > 0.5 for row in annual)
    top_bottom = float(quintiles[-1]["true_breakout_rate"] - quintiles[0]["true_breakout_rate"])
    limits = protocol["acceptance"]
    gates = {
        "feature_coverage": coverage >= limits["feature_coverage_min"],
        "overall_pairwise_probability": pairwise is not None
        and pairwise >= limits["overall_pairwise_probability_min"],
        "years_above_0_5": years_above >= limits["years_above_0_5_min"],
        "top_minus_bottom_quintile_breakout_rate": (
            top_bottom >= limits["within_year_top_minus_bottom_quintile_breakout_rate_min"]
        ),
    }
    return {
        "analysis": protocol["experiment"],
        "unique_setups": len(frame),
        "date_range": [
            frame["signal_date"].min().date().isoformat(),
            frame["signal_date"].max().date().isoformat(),
        ],
        "primary_feature": PRIMARY_FEATURE,
        "coverage": coverage,
        "overall_pairwise_probability": pairwise,
        "years_above_0_5": years_above,
        "years_below_0_5": sum(row["pairwise_probability"] < 0.5 for row in annual),
        "top_minus_bottom_quintile_breakout_rate": top_bottom,
        "annual": annual,
        "quintiles": quintiles,
        "diagnostics": {
            "complete_windows": int(frame["final_leg_rs_complete"].sum()),
            "incomplete_windows": int((~frame["final_leg_rs_complete"]).sum()),
            "missing_rs_sessions": int(frame["final_leg_missing_rs_sessions"].sum()),
            "signal_rs_median": float(frame["signal_rs"].median()),
            "pivot_rs_median": float(frame["pivot_rs"].median()),
            "final_leg_min_rs_median": float(frame["final_leg_min_rs"].median()),
            "final_leg_sessions_median": float(frame["final_leg_sessions"].median()),
        },
        "acceptance": limits,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "guardrails": {
            "strategy_changed": False,
            "threshold_search": False,
            "portfolio_backtest": False,
            "future_columns_used_only_as_labels": ["true_breakout_10_7_20", "return_40d"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--features-output", type=Path, default=DEFAULT_FEATURES)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    candidates = _candidate_frame()
    expected = int(protocol["population"]["expected_unique_setups"])
    if len(candidates) != expected:
        raise RuntimeError(f"candidate count changed: expected {expected}, got {len(candidates)}")
    close, dates, symbols = _close_matrix(
        candidates["pivot_date"].min() - pd.Timedelta(days=550),
        candidates["signal_date"].max(),
    )
    ranks = _rs_percentiles(close)
    date_lookup = {value: index for index, value in enumerate(dates)}
    symbol_lookup = {value: index for index, value in enumerate(symbols)}
    market_sessions = _market_sessions(protocol)
    market_session_set = set(market_sessions)
    records = []
    for row in candidates.itertuples(index=False):
        asset = symbol_lookup.get(row.symbol)
        expected_dates = [
            value for value in market_sessions
            if row.pivot_date <= value <= row.signal_date
        ]
        values = np.array([
            ranks[date_lookup[value], asset]
            if asset is not None and value in date_lookup
            else np.nan
            for value in expected_dates
        ], dtype=float)
        complete = bool(
            expected_dates
            and row.pivot_date in market_session_set
            and row.signal_date in market_session_set
            and np.all(np.isfinite(values))
        )
        start = date_lookup.get(row.pivot_date)
        end = date_lookup.get(row.signal_date)
        finite_values = values[np.isfinite(values)]
        records.append({
            "final_leg_rs85_share": float(np.mean(values >= 85.0)) if complete else None,
            "final_leg_min_rs": float(np.min(values)) if complete else None,
            "pivot_rs": float(ranks[start, asset])
            if start is not None and asset is not None and np.isfinite(ranks[start, asset])
            else None,
            "signal_rs": float(ranks[end, asset])
            if end is not None and asset is not None and np.isfinite(ranks[end, asset])
            else None,
            "final_leg_sessions": len(expected_dates),
            "final_leg_valid_rs_sessions": len(finite_values),
            "final_leg_missing_rs_sessions": len(expected_dates) - len(finite_values),
            "final_leg_rs_complete": complete,
        })
    result_frame = pd.concat([candidates, pd.DataFrame(records)], axis=1)
    result_frame["year"] = result_frame["signal_date"].dt.year
    result_frame["true_breakout_10_7_20"] = result_frame["true_breakout_10_7_20"].astype("boolean")
    args.features_output.parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(result_frame).write_parquet(args.features_output)
    result = _summarize(result_frame, protocol)
    result["protocol"] = str(args.protocol.resolve().relative_to(ROOT)).replace("\\", "/")
    result["candidate_features"] = str(args.features_output.resolve().relative_to(ROOT)).replace("\\", "/")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
