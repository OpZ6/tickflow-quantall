"""Describe causal fundamental evidence for frozen VCP recall candidates.

This is a mechanism audit, not a threshold search.  It compares continuous
point-in-time financial observations between later successful and failed
breakouts and reports the comparison separately by signal year.

Run from ``backend``::

    uv run --no-sync python ../scripts/analyze_vcp_fundamental_growth.py
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "data/research/vcp/candidate-labels/source-vcp-v3-fundamental-v1"
    / "discovery-candidates.parquet"
)

FEATURES = (
    "fundamental_revenue_yoy",
    "fundamental_net_income_yoy",
    "fundamental_roe",
    "fundamental_gross_margin",
    "fundamental_revenue_growth_accel",
    "fundamental_profit_growth_accel",
    "fundamental_gross_margin_change",
    "fundamental_roe_change",
)
TARGET = "true_breakout_10_7_20"


def _finite(values: pl.Series) -> list[float]:
    return [
        float(value)
        for value in values.drop_nulls().to_list()
        if math.isfinite(float(value))
    ]


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _probability_greater(left: list[float], right: list[float]) -> float | None:
    """Return P(left > right) + 0.5 * P(tie), without choosing a cutoff."""
    if not left or not right:
        return None
    wins = 0.0
    for left_value in left:
        for right_value in right:
            if left_value > right_value:
                wins += 1.0
            elif left_value == right_value:
                wins += 0.5
    return wins / (len(left) * len(right))


def _comparison(frame: pl.DataFrame, feature: str) -> dict[str, Any]:
    winners = _finite(frame.filter(pl.col(TARGET))[feature])
    failures = _finite(frame.filter(~pl.col(TARGET))[feature])
    return {
        "rows": frame.height,
        "coverage": (len(winners) + len(failures)) / frame.height if frame.height else None,
        "winner_rows": len(winners),
        "failure_rows": len(failures),
        "winner_median": _median(winners),
        "failure_median": _median(failures),
        "probability_winner_greater": _probability_greater(winners, failures),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input.with_name("fundamental-growth-analysis.json")

    frame = pl.read_parquet(args.input).with_columns(
        pl.col("signal_date").cast(pl.Utf8).str.slice(0, 10).str.to_date().alias("_signal_date")
    )
    required = {TARGET, "symbol", "fundamental_announce_date", *FEATURES}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"missing required columns: {missing}")
    lookahead_rows = frame.filter(
        pl.col("fundamental_announce_date").is_not_null()
        & (pl.col("fundamental_announce_date") >= pl.col("_signal_date"))
    ).height
    if lookahead_rows:
        raise RuntimeError(f"found {lookahead_rows} rows with non-causal fundamentals")

    years = sorted(frame["_signal_date"].dt.year().drop_nulls().unique().to_list())
    feature_results: dict[str, Any] = {}
    for feature in FEATURES:
        feature_results[feature] = {
            "all": _comparison(frame, feature),
            "by_signal_year": {
                str(year): _comparison(
                    frame.filter(pl.col("_signal_date").dt.year() == year), feature
                )
                for year in years
            },
        }

    report = {
        "study": "frozen-vcp-recall-causal-fundamental-growth-audit-v1",
        "input": str(args.input.relative_to(ROOT)).replace("\\", "/"),
        "candidate_rows": frame.height,
        "candidate_symbols": frame["symbol"].n_unique(),
        "signal_range": [str(frame["_signal_date"].min()), str(frame["_signal_date"].max())],
        "target": TARGET,
        "target_rate": float(frame[TARGET].mean()),
        "strict_after_announcement": True,
        "lookahead_rows": lookahead_rows,
        "method": (
            "Continuous medians and common-language probability only; no cutoff, model, "
            "portfolio simulation, or parameter selection."
        ),
        "feature_results": feature_results,
        "data_limit": (
            "The full-market period snapshots may contain a later restatement in place of the "
            "original filing. The recorded later announcement delays availability, so this is "
            "conservative for lookahead but may leave the historical state stale or incomplete."
        ),
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
