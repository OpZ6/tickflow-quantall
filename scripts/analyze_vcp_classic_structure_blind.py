#!/usr/bin/env python3
"""Evaluate frozen semantic labels against the sealed classic-structure prediction."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "data/research/vcp/casebooks/classic-structure-v1-blind"
OUTPUT = ROOT / "data/research/vcp/analysis/classic-structure-representation-v1.json"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _group_summary(rows: list[dict]) -> dict:
    accepted = sum(row["classification"] in {"classic", "partial"} for row in rows)
    return {
        "cases": len(rows),
        "classic": sum(row["classification"] == "classic" for row in rows),
        "partial": sum(row["classification"] == "partial" for row in rows),
        "nonclassic": sum(row["classification"] == "nonclassic" for row in rows),
        "classic_or_partial_rate": accepted / len(rows) if rows else None,
        "nonclassic_rate": 1 - accepted / len(rows) if rows else None,
        "future_breakout_rate_descriptive": (
            sum(bool(row["true_breakout_10_7_20"]) for row in rows) / len(rows)
            if rows
            else None
        ),
        "return_40d_median_descriptive": (
            statistics.median(row["return_40d"] for row in rows) if rows else None
        ),
    }


def main() -> int:
    labels_path = CASEBOOK / "labels.json"
    freeze = _read(CASEBOOK / "label-freeze.json")
    actual_hash = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if actual_hash != freeze["labels_sha256"]:
        raise RuntimeError("labels.json changed after freeze")
    labels = _read(labels_path)
    if len(labels) != freeze["cases"]:
        raise RuntimeError("label count changed after freeze")
    if Counter(row["classification"] for row in labels) != Counter(
        freeze["classification_counts"]
    ):
        raise RuntimeError("classification counts changed after freeze")

    sealed = _read(CASEBOOK / "sealed.json")
    sealed_by_id = {row["case_id"]: row for row in sealed}
    if {row["case_id"] for row in labels} != set(sealed_by_id):
        raise RuntimeError("label and sealed case ids do not match")
    joined = [{**label, **sealed_by_id[label["case_id"]]} for label in labels]
    supported = [row for row in joined if row["representation"]["supported"]]
    unsupported = [row for row in joined if not row["representation"]["supported"]]
    supported_summary = _group_summary(supported)
    unsupported_summary = _group_summary(unsupported)
    semantic_gap = (
        supported_summary["classic_or_partial_rate"]
        - unsupported_summary["classic_or_partial_rate"]
    )
    gates = {
        "supported_classic_or_partial_rate_min_0_75": (
            supported_summary["classic_or_partial_rate"] >= 0.75
        ),
        "supported_nonclassic_rate_max_0_25": supported_summary["nonclassic_rate"] <= 0.25,
        "supported_minus_unsupported_classic_or_partial_min_0_30": semantic_gap >= 0.30,
    }
    result = {
        "experiment": "classic-structure-representation-v1",
        "label_freeze_verified": True,
        "labels_sha256": actual_hash,
        "cases": len(joined),
        "supported": supported_summary,
        "unsupported": unsupported_summary,
        "supported_minus_unsupported_classic_or_partial": semantic_gap,
        "semantic_gates": gates,
        "all_semantic_gates_passed": all(gates.values()),
        "supported_failure_reason_counts": dict(
            Counter(row["representation"]["reason"] for row in supported)
        ),
        "unsupported_failure_reason_counts": dict(
            Counter(row["representation"]["reason"] for row in unsupported)
        ),
        "interpretation_boundary": (
            "Semantic labels evaluate whether the representation matches its name. Future outcomes "
            "were opened only after label freeze and are descriptive; they cannot tune this method."
        ),
    }
    result["decision"] = (
        "retain_for_preperformance_structure_research"
        if result["all_semantic_gates_passed"]
        else "stop_topology_without_variants"
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
