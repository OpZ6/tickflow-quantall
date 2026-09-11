#!/usr/bin/env python3
"""Evaluate frozen semantic labels against sealed supply-wave v3 predictions."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "data/research/vcp/casebooks/supply-wave-v3-blind"
OUTPUT = ROOT / "data/research/vcp/analysis/supply-wave-v3-semantic-v1.json"


def _read(name: str):
    return json.loads((CASEBOOK / name).read_text(encoding="utf-8"))


def _summary(rows: list[dict]) -> dict:
    accepted = sum(row["classification"] in {"classic", "partial"} for row in rows)
    return {
        "cases": len(rows),
        "classic": sum(row["classification"] == "classic" for row in rows),
        "partial": sum(row["classification"] == "partial" for row in rows),
        "nonclassic": sum(row["classification"] == "nonclassic" for row in rows),
        "classic_or_partial_rate": accepted / len(rows) if rows else None,
        "nonclassic_rate": 1 - accepted / len(rows) if rows else None,
        "future_breakout_rate_descriptive": (
            sum(bool(row["true_breakout_10_7_20"]) for row in rows) / len(rows) if rows else None
        ),
        "return_40d_median_descriptive": (
            statistics.median(row["return_40d"] for row in rows) if rows else None
        ),
    }


def main() -> int:
    freeze = _read("label-freeze.json")
    labels_path = CASEBOOK / freeze["labels_file"]
    actual_hash = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if actual_hash != freeze["labels_sha256"]:
        raise RuntimeError("reviewed labels changed after freeze")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    if len(labels) != freeze["cases"] or Counter(row["classification"] for row in labels) != Counter(freeze["classification_counts"]):
        raise RuntimeError("reviewed label counts changed after freeze")
    sealed = _read("sealed.json")
    sealed_by_id = {row["case_id"]: row for row in sealed}
    if {row["case_id"] for row in labels} != set(sealed_by_id):
        raise RuntimeError("reviewed labels and sealed cases differ")
    joined = [{**label, **sealed_by_id[label["case_id"]]} for label in labels]
    supported = [row for row in joined if row["representation"]["supported"]]
    unsupported = [row for row in joined if not row["representation"]["supported"]]
    supported_summary, unsupported_summary = _summary(supported), _summary(unsupported)
    semantic_gap = supported_summary["classic_or_partial_rate"] - unsupported_summary["classic_or_partial_rate"]
    gates = {
        "supported_classic_or_partial_rate_min_0_75": supported_summary["classic_or_partial_rate"] >= 0.75,
        "supported_nonclassic_rate_max_0_25": supported_summary["nonclassic_rate"] <= 0.25,
        "supported_minus_unsupported_classic_or_partial_min_0_30": semantic_gap >= 0.30,
    }
    result = {
        "experiment": "supply-wave-v3-semantic-v1",
        "label_freeze_verified": True,
        "labels_sha256": actual_hash,
        "cases": len(joined),
        "supported": supported_summary,
        "unsupported": unsupported_summary,
        "supported_minus_unsupported_classic_or_partial": semantic_gap,
        "semantic_gates": gates,
        "all_semantic_gates_passed": all(gates.values()),
        "decision": "advance_to_fixed_time_split" if all(gates.values()) else "stop_without_variants",
        "interpretation_boundary": "Semantic labels decide whether this representation deserves its name. Future outcomes were opened only after label freeze and are descriptive only.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
