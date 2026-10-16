#!/usr/bin/env python3
"""Describe the causal pre-breakout pivot shelf without fitting trade rules."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = (5, 10, 20, 40)


def compute_shelf_metrics(
    history: pl.DataFrame,
    *,
    signal_date: date,
    pivot: float,
    entry_price: float,
) -> dict[str, float]:
    """Compute metrics from bars strictly earlier than the signal date."""
    pretrigger = history.filter(pl.col("date") < signal_date).sort("date").tail(40)
    if pretrigger.height < 40:
        raise ValueError("pivot-shelf analysis requires 40 pretrigger bars")
    arrays = {
        column: pretrigger[column].to_numpy().astype(np.float32).astype(float)
        for column in ("high", "low", "close", "volume")
    }
    result: dict[str, float] = {}
    for window in WINDOWS:
        high = arrays["high"][-window:]
        low = arrays["low"][-window:]
        close = arrays["close"][-window:]
        result[f"range_{window}"] = float((np.max(high) - np.min(low)) / pivot)
        result[f"close_range_{window}"] = float(
            (np.max(close) - np.min(close)) / pivot
        )
        result[f"support_risk_{window}"] = float(
            1.0 - np.min(low) / entry_price
        )
    result["range_5_to_10"] = result["range_5"] / result["range_10"]
    result["range_10_to_20"] = result["range_10"] / result["range_20"]
    result["range_20_to_40"] = result["range_20"] / result["range_40"]
    result["volume_5_to_20"] = float(
        np.mean(arrays["volume"][-5:]) / np.mean(arrays["volume"][-20:])
    )
    result["volume_10_to_40"] = float(
        np.mean(arrays["volume"][-10:]) / np.mean(arrays["volume"][-40:])
    )
    result["pretrigger_high_10_to_pivot"] = float(
        np.max(arrays["high"][-10:]) / pivot - 1.0
    )
    return result


def _quantiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p25": None, "median": None, "p75": None}
    array = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "p25": round(float(np.quantile(array, 0.25)), 6),
        "median": round(float(np.median(array)), 6),
        "p75": round(float(np.quantile(array, 0.75)), 6),
    }


def _probability_first_lower(first: list[float], second: list[float]) -> float | None:
    if not first or not second:
        return None
    a = np.asarray(first, dtype=float)[:, None]
    b = np.asarray(second, dtype=float)[None, :]
    return round(float(np.mean(a < b) + 0.5 * np.mean(a == b)), 6)


def summarize(records: list[dict]) -> dict:
    groups = {
        "winner": [row for row in records if row["pnl_pct"] > 0],
        "nonwinner": [row for row in records if row["pnl_pct"] <= 0],
        "no_follow_failure": [
            row for row in records if row["failed_without_3pct_mfe"]
        ],
        "gave_back": [row for row in records if row["gave_back_5pct_move"]],
    }
    feature_names = sorted(records[0]["shelf"] if records else [])
    comparisons = {}
    for feature in feature_names:
        values = {
            name: [float(row["shelf"][feature]) for row in rows]
            for name, rows in groups.items()
        }
        comparisons[feature] = {
            name: _quantiles(group_values)
            for name, group_values in values.items()
        }
        comparisons[feature]["probability_winner_lower_than_no_follow"] = (
            _probability_first_lower(values["winner"], values["no_follow_failure"])
        )
    return {
        "group_counts": {name: len(rows) for name, rows in groups.items()},
        "feature_comparisons": comparisons,
    }


def analyze(
    entries: list[dict],
    paths: list[dict],
    trades: list[dict],
    bars: pl.DataFrame,
) -> list[dict]:
    grouped = {
        key[0] if isinstance(key, tuple) else key: frame
        for key, frame in bars.partition_by("symbol", as_dict=True).items()
    }
    path_by_key = {(row["symbol"], row["entry_date"]): row for row in paths}
    trade_by_key = {(row["symbol"], row["entry_date"]): row for row in trades}
    records = []
    for entry in entries:
        key = (entry["symbol"], entry["entry_date"])
        path = path_by_key[key]
        trade = trade_by_key[key]
        signal_date = date.fromisoformat(entry["entry_signal_date"])
        records.append(
            {
                "symbol": entry["symbol"],
                "entry_signal_date": entry["entry_signal_date"],
                "entry_date": entry["entry_date"],
                "pnl_pct": entry["pnl_pct"],
                "failed_without_3pct_mfe": path["failed_without_3pct_mfe"],
                "gave_back_5pct_move": path["gave_back_5pct_move"],
                "shelf": compute_shelf_metrics(
                    grouped[entry["symbol"]],
                    signal_date=signal_date,
                    pivot=float(entry["pivot"]),
                    entry_price=float(trade["entry_price"]),
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
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
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
    partition_start = f"date={(first_signal - timedelta(days=90)).isoformat()}"
    partition_end = f"date={last_signal.isoformat()}"
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if partition_start <= path.parent.name <= partition_end
    ]
    bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").is_in(symbols))
        .select("symbol", "date", "high", "low", "close", "volume")
        .collect()
    )
    records = analyze(entries, paths["trades"], result["trades"], bars)
    report = {
        "schema_version": 1,
        "run_id": args.run_id,
        "analysis_role": "signal_time_descriptive_evidence_only",
        "causal_cutoff": "strictly_before_entry_signal_date",
        "threshold_selection": False,
        "summary": summarize(records),
        "records": records,
    }
    output = run_dir / "pivot-shelf-analysis.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
