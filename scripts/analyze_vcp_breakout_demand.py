#!/usr/bin/env python3
"""Describe signal-day VCP demand without fitting thresholds or a model."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def compute_demand_metrics(
    history: pl.DataFrame, *, signal_date: date, pivot: float
) -> dict[str, float]:
    """Use data through the completed signal bar and exclude later bars."""
    observed = history.filter(pl.col("date") <= signal_date).sort("date").tail(21)
    if observed.height < 21 or observed["date"].max() != signal_date:
        raise ValueError("breakout-demand analysis requires 21 bars through signal date")
    arrays = {
        column: observed[column].to_numpy().astype(np.float32).astype(float)
        for column in ("open", "high", "low", "close", "volume")
    }
    previous_close = arrays["close"][-2]
    signal_range = arrays["high"][-1] - arrays["low"][-1]
    prior_ranges = (arrays["high"][-20:-1] - arrays["low"][-20:-1]) / arrays[
        "close"
    ][-21:-2]
    prior_volume = arrays["volume"][-20:-1]
    return {
        "gap_return": float(arrays["open"][-1] / previous_close - 1.0),
        "close_return": float(arrays["close"][-1] / previous_close - 1.0),
        "intraday_return": float(arrays["close"][-1] / arrays["open"][-1] - 1.0),
        "high_return": float(arrays["high"][-1] / previous_close - 1.0),
        "range_pct": float(signal_range / previous_close),
        "range_expansion": float(
            signal_range / previous_close / np.mean(prior_ranges)
        ),
        "close_location": float(
            (arrays["close"][-1] - arrays["low"][-1]) / signal_range
            if signal_range > 0
            else 0.5
        ),
        "volume_ratio_20": float(arrays["volume"][-1] / np.mean(prior_volume)),
        "pivot_clearance": float(arrays["close"][-1] / pivot - 1.0),
    }


def _distribution(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "p25": round(float(np.quantile(array, 0.25)), 6),
        "median": round(float(np.median(array)), 6),
        "p75": round(float(np.quantile(array, 0.75)), 6),
    }


def _probability_first_greater(first: list[float], second: list[float]) -> float:
    a = np.asarray(first, dtype=float)[:, None]
    b = np.asarray(second, dtype=float)[None, :]
    return round(float(np.mean(a > b) + 0.5 * np.mean(a == b)), 6)


def summarize(records: list[dict]) -> dict:
    groups = {
        "winner": [row for row in records if row["pnl_pct"] > 0],
        "nonwinner": [row for row in records if row["pnl_pct"] <= 0],
        "no_follow_failure": [
            row for row in records if row["failed_without_3pct_mfe"]
        ],
        "gave_back": [row for row in records if row["gave_back_5pct_move"]],
    }
    comparisons = {}
    for feature in sorted(records[0]["demand"] if records else []):
        values = {
            name: [float(row["demand"][feature]) for row in rows]
            for name, rows in groups.items()
        }
        comparisons[feature] = {
            name: _distribution(group_values)
            for name, group_values in values.items()
        }
        comparisons[feature]["probability_winner_greater_than_no_follow"] = (
            _probability_first_greater(
                values["winner"], values["no_follow_failure"]
            )
        )
    return {
        "group_counts": {name: len(rows) for name, rows in groups.items()},
        "feature_comparisons": comparisons,
    }


def analyze(entries, paths, bars: pl.DataFrame) -> list[dict]:
    grouped = {
        key[0] if isinstance(key, tuple) else key: frame
        for key, frame in bars.partition_by("symbol", as_dict=True).items()
    }
    path_by_key = {(row["symbol"], row["entry_date"]): row for row in paths}
    records = []
    for entry in entries:
        path = path_by_key[(entry["symbol"], entry["entry_date"])]
        records.append(
            {
                "symbol": entry["symbol"],
                "entry_signal_date": entry["entry_signal_date"],
                "entry_date": entry["entry_date"],
                "pnl_pct": entry["pnl_pct"],
                "failed_without_3pct_mfe": path["failed_without_3pct_mfe"],
                "gave_back_5pct_move": path["gave_back_5pct_move"],
                "demand": compute_demand_metrics(
                    grouped[entry["symbol"]],
                    signal_date=date.fromisoformat(entry["entry_signal_date"]),
                    pivot=float(entry["pivot"]),
                ),
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    run_dir = args.data_root.resolve() / "research" / "vcp" / "runs" / args.run_id
    evidence = json.loads(
        (run_dir / "entry-structure-evidence.json").read_text(encoding="utf-8")
    )
    paths = json.loads(
        (run_dir / "trade-path-analysis.json").read_text(encoding="utf-8")
    )
    entries = list(evidence["records"])
    symbols = sorted({str(row["symbol"]) for row in entries})
    first_signal = min(date.fromisoformat(row["entry_signal_date"]) for row in entries)
    last_signal = max(date.fromisoformat(row["entry_signal_date"]) for row in entries)
    partition_start = f"date={(first_signal - timedelta(days=60)).isoformat()}"
    partition_end = f"date={last_signal.isoformat()}"
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if partition_start <= path.parent.name <= partition_end
    ]
    bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").is_in(symbols))
        .select("symbol", "date", "open", "high", "low", "close", "volume")
        .collect()
    )
    records = analyze(entries, paths["trades"], bars)
    report = {
        "schema_version": 1,
        "run_id": args.run_id,
        "analysis_role": "signal_day_descriptive_evidence_only",
        "causal_cutoff": "entry_signal_date_completed_bar",
        "threshold_selection": False,
        "summary": summarize(records),
        "records": records,
    }
    output = run_dir / "breakout-demand-analysis.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
