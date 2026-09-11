#!/usr/bin/env python3
"""Verify frozen blind labels and summarize the sealed VCP casebook outcomes."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "data/research/vcp/casebooks/classic-vcp-blind-v1"
OUTPUT = ROOT / "data/research/vcp/analysis/classic-vcp-blind-casebook-v1.json"
CANDIDATE_INPUTS = (
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2017-2020-v1/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-v4/discovery-candidates.parquet",
    ROOT / "data/research/vcp/candidate-labels/source-vcp-2024-2026-v1/discovery-candidates.parquet",
)
SEMANTIC_FEATURES = (
    "leg_count",
    "last_to_first_depth",
    "skipped_pullbacks",
    "pullbacks_after_selected",
    "leg_volume_last_to_first",
    "leg_volume_monotonic_share",
    "base_depth",
    "prior_runup_63_before_base",
    "right_side_bars",
    "right_side_efficiency",
    "prebreakout_pivot_crosses_20",
    "prebreakout_range10_pct",
    "prebreakout_dry_volume_ratio",
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _summary(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "future_breakout_count": sum(bool(row["true_breakout_10_7_20"]) for row in rows),
        "future_breakout_rate": (
            sum(bool(row["true_breakout_10_7_20"]) for row in rows) / len(rows)
            if rows
            else None
        ),
        "return_40d_median": statistics.median(row["return_40d"] for row in rows) if rows else None,
        "mfe_40d_median": statistics.median(row["mfe_40d"] for row in rows) if rows else None,
    }


def _semantic_features(labels: list[dict], outcomes: list[dict], manifest: list[dict]) -> dict:
    identity = {
        row["case_id"]: {
            **row,
            "scale": next(item["scale"] for item in manifest if item["case_id"] == row["case_id"]),
        }
        for row in outcomes
    }
    candidates = (
        pl.concat([pl.read_parquet(path) for path in CANDIDATE_INPUTS], how="diagonal_relaxed")
        .sort(["signal_date", "symbol", "scale", "pivot_date"])
        .unique(["symbol", "scale", "pivot_date"], keep="first", maintain_order=True)
    )
    candidate_lookup = {
        (row["symbol"], row["signal_date"], row["scale"], row["pivot_date"]): row
        for row in candidates.select(
            "symbol", "signal_date", "scale", "pivot_date", "ends_at_latest_pullback", *SEMANTIC_FEATURES
        ).to_dicts()
    }
    joined = []
    for label in labels:
        row = identity[label["case_id"]]
        key = (row["symbol"], row["signal_date"], row["scale"], row["pivot_date"])
        candidate = candidate_lookup.get(key)
        if candidate is None:
            raise RuntimeError(f"candidate fields not found for {label['case_id']}")
        joined.append({**label, **candidate})

    result = {}
    for classification in ("classic", "partial", "nonclassic"):
        rows = [row for row in joined if row["classification"] == classification]
        result[classification] = {
            "cases": len(rows),
            "ends_at_latest_pullback_rate": sum(
                bool(row["ends_at_latest_pullback"]) for row in rows
            )
            / len(rows),
            "feature_medians": {
                feature: statistics.median(
                    row[feature] for row in rows if row[feature] is not None
                )
                for feature in SEMANTIC_FEATURES
            },
        }
    return result


def main() -> int:
    labels_path = CASEBOOK / "labels.json"
    freeze = _read_json(CASEBOOK / "label-freeze.json")
    actual_hash = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if actual_hash != freeze["labels_sha256"]:
        raise RuntimeError("labels.json changed after the blind label freeze")

    labels = _read_json(labels_path)
    outcomes = _read_json(CASEBOOK / "outcomes.json")
    manifest = _read_json(CASEBOOK / "manifest.json")
    if len(labels) != freeze["cases"]:
        raise RuntimeError("frozen case count does not match labels.json")
    if Counter(row["classification"] for row in labels) != Counter(
        freeze["classification_counts"]
    ):
        raise RuntimeError("frozen classification counts do not match labels.json")

    label_ids = {row["case_id"] for row in labels}
    outcome_by_id = {row["case_id"]: row for row in outcomes}
    if label_ids != set(outcome_by_id):
        raise RuntimeError("label and outcome case ids do not match")

    joined = [{**label, **outcome_by_id[label["case_id"]]} for label in labels]
    classifications = ("classic", "partial", "nonclassic")
    result = {
        "experiment": "production-leader-classic-vcp-blind-casebook-v1",
        "label_freeze_verified": True,
        "labels_sha256": actual_hash,
        "cases": len(joined),
        "classification_counts": dict(Counter(row["classification"] for row in joined)),
        "reason_code_counts": {
            "present": dict(Counter(code for row in joined for code in row["present"])),
            "missing_or_contrary": dict(
                Counter(code for row in joined for code in row["missing_or_contrary"])
            ),
        },
        "existing_detector_fields_by_blind_class": _semantic_features(labels, outcomes, manifest),
        "outcomes_overall": _summary(joined),
        "outcomes_by_classification": {
            classification: _summary(
                [row for row in joined if row["classification"] == classification]
            )
            for classification in classifications
        },
        "interpretation_boundary": (
            "The outcome split is descriptive only. The outcome-blind 24-case sample tests "
            "semantic coherence, not predictive performance, and must not set thresholds."
        ),
        "semantic_decision": (
            "mixed: preserve the broad detector as a watchlist, but do not describe every "
            "candidate as classic VCP; create a larger explicitly labeled structure dataset "
            "before testing a representation change"
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
