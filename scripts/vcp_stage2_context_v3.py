#!/usr/bin/env python3
"""Build and evaluate an outcome-blind stage-two VCP context packet."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
from build_vcp_blind_casebook import OUTPUT as FIRST_PACKET
from build_vcp_blind_casebook import PAGE_SIZE, _candidates, _draw_case, _font, _market
from build_vcp_classic_structure_blind_casebook import OUTPUT as SECOND_PACKET
from build_vcp_supply_wave_v3_blind_casebook import OUTPUT as THIRD_PACKET
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/research/vcp/casebooks/stage2-base-context-v3-blind"
ANALYSIS_OUTPUT = ROOT / "data/research/vcp/analysis/stage2-base-context-v3-semantic-v1.json"
YEARS = tuple(range(2018, 2026))
PER_STATUS_PER_YEAR = 2


def represent_stage2_context(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
) -> dict[str, Any]:
    """Represent a continuous stage-two advance and high retained base."""
    high, low, close, volume = [np.asarray(values, dtype=float) for values in (high, low, close, volume)]
    if len(close) < 151 or any(len(values) != len(close) for values in (high, low, volume)):
        return {"supported": False, "reason": "history_too_short"}
    if any(not np.all(np.isfinite(values)) for values in (high, low, close, volume)) or np.any(low <= 0) or np.any(volume <= 0):
        return {"supported": False, "reason": "invalid_input"}

    pattern_high, pattern_low, pattern_close, pattern_volume = high[-151:-1], low[-151:-1], close[-151:-1], volume[-151:-1]
    early, middle, late = np.split(pattern_close, 3)
    early_median, middle_median, late_median = (float(np.median(block)) for block in (early, middle, late))
    pattern_high_close = float(np.max(pattern_close))
    retained_floor = (early_median + pattern_high_close) / 2.0
    prior_advance = middle_median > early_median
    gain_retention = late_median > early_median and float(np.min(late)) > retained_floor

    log_returns = np.diff(np.log(pattern_close))
    positive_returns = np.sort(log_returns[log_returns > 0])[::-1]
    leading_gains = float(np.sum(positive_returns[:3]))
    remaining_gains = float(np.sum(positive_returns[3:]))
    continuous_advance = bool(len(positive_returns) > 3 and leading_gains < remaining_gains)

    normalized_range = (pattern_high - pattern_low) / pattern_close
    _, middle_range, late_range = np.split(normalized_range, 3)
    settling = float(np.median(late_range)) < float(np.median(middle_range))

    prior_high = float(np.max(pattern_high[-20:]))
    volume_baseline = float(np.median(pattern_volume[-20:]))
    signal_range = high[-1] - low[-1]
    signal_close_location = float((close[-1] - low[-1]) / signal_range) if signal_range > 0 else 0.5
    demand = bool(close[-1] > prior_high and signal_close_location >= 0.5 and volume[-1] > volume_baseline)
    checks = {
        "prior_advance": prior_advance,
        "gain_retention": gain_retention,
        "continuous_advance": continuous_advance,
        "settling": settling,
        "breakout_demand": demand,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "supported": not failed,
        "reason": "supported" if not failed else "+".join(failed),
        "checks": checks,
        "early_median": early_median,
        "middle_median": middle_median,
        "late_median": late_median,
        "retained_floor": retained_floor,
        "leading_to_remaining_positive_return_ratio": leading_gains / remaining_gains if remaining_gains > 0 else None,
        "middle_to_late_range_ratio": float(np.median(late_range) / np.median(middle_range)),
        "signal_volume_ratio": volume[-1] / volume_baseline if volume_baseline > 0 else None,
        "signal_close_location": signal_close_location,
    }


def _selection_hash(row: dict, supported: bool) -> str:
    key = "|".join(str(value) for value in (row["symbol"], row["signal_date"], row["scale"], supported))
    return hashlib.sha256(key.encode()).hexdigest()


def _excluded_cases() -> set[tuple[str, str]]:
    files = (
        FIRST_PACKET / "outcomes.json",
        SECOND_PACKET / "sealed.json",
        THIRD_PACKET / "sealed.json",
    )
    rows = [row for path in files for row in json.loads(path.read_text(encoding="utf-8"))]
    return {(row["symbol"], row["signal_date"]) for row in rows}


def build() -> int:
    candidates = _candidates()
    market = _market(
        candidates.get_column("symbol").unique().to_list(),
        candidates.get_column("signal_date").min() - timedelta(days=300),
        candidates.get_column("signal_date").max(),
    )
    excluded = _excluded_cases()
    represented = []
    for row in candidates.to_dicts():
        identity = (row["symbol"], row["signal_date"].isoformat())
        if row["signal_date"].year not in YEARS or identity in excluded:
            continue
        bars = market.get(row["symbol"])
        if bars is None:
            continue
        visible = bars.filter(bars["date"] <= row["signal_date"]).tail(160)
        if visible.height < 151 or visible.get_column("date")[-1] != row["signal_date"]:
            continue
        representation = represent_stage2_context(
            visible["high"].to_numpy(), visible["low"].to_numpy(), visible["close"].to_numpy(), visible["volume"].to_numpy()
        )
        represented.append({**row, "bars": visible, "representation": representation,
                            "selection_hash": _selection_hash(row, representation["supported"])})

    selected, availability, shortages = [], {}, []
    for year in YEARS:
        availability[str(year)] = {}
        for supported in (True, False):
            status = "supported" if supported else "unsupported"
            group = [row for row in represented if row["signal_date"].year == year and row["representation"]["supported"] is supported]
            group.sort(key=lambda row: row["selection_hash"])
            availability[str(year)][status] = len(group)
            if len(group) < PER_STATUS_PER_YEAR:
                shortages.append({"year": year, "status": status, "available": len(group)})
                continue
            selected.extend(group[:PER_STATUS_PER_YEAR])
    if shortages:
        print(json.dumps({"decision": "insufficient_blind_packet_coverage", "availability": availability,
                          "shortages": shortages}, ensure_ascii=False, indent=2))
        return 2
    selected.sort(key=lambda row: (row["signal_date"].year, row["selection_hash"]))

    OUTPUT.mkdir(parents=True, exist_ok=False)
    manifest, sealed, labels = [], [], []
    for offset in range(0, len(selected), 6):
        page = offset // 6 + 1
        image = Image.new("RGB", PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        draw.text((55, 20), "Blind stage-two context validation - status, identity and outcome hidden", fill="#111827", font=_font(30))
        draw.text((55, 58), "black: completed signal day | classify price and volume structure only", fill="#374151", font=_font(18))
        for local_index, row in enumerate(selected[offset : offset + 6]):
            case_id = f"B{offset + local_index + 1:02d}"
            column, panel_row = local_index % 2, local_index // 2
            panel_left, panel_top = 55 + column * 1165, 105 + panel_row * 605
            _draw_case(draw, (panel_left, panel_top, panel_left + 1125, panel_top + 575), case_id, row, show_structure=False)
            manifest.append({"case_id": case_id, "scale": row["scale"], "visible_bars": row["bars"].height,
                             "page": f"page-{page}.png", "panel": local_index + 1, "selection_hash": row["selection_hash"]})
            sealed.append({"case_id": case_id, "symbol": row["symbol"], "signal_date": row["signal_date"].isoformat(),
                           "representation": row["representation"], "true_breakout_10_7_20": row["true_breakout_10_7_20"],
                           "return_40d": row["return_40d"], "mfe_40d": row["mfe_40d"]})
            labels.append({"case_id": case_id, "classification": None, "confidence": None,
                           "present": [], "missing_or_contrary": [], "note": None})
        image.save(OUTPUT / f"page-{page}.png")
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUTPUT / "sealed.json").write_text(json.dumps(sealed, indent=2), encoding="utf-8")
    (OUTPUT / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "cases": len(selected), "pages": (len(selected) + 5) // 6,
                      "availability": availability, "sealed_opened": False}, ensure_ascii=False, indent=2))
    return 0


def _summary(rows: list[dict]) -> dict:
    accepted = sum(row["classification"] in {"classic", "partial"} for row in rows)
    return {
        "cases": len(rows),
        "classic": sum(row["classification"] == "classic" for row in rows),
        "partial": sum(row["classification"] == "partial" for row in rows),
        "nonclassic": sum(row["classification"] == "nonclassic" for row in rows),
        "classic_or_partial_rate": accepted / len(rows) if rows else None,
        "nonclassic_rate": 1 - accepted / len(rows) if rows else None,
        "future_breakout_rate_descriptive": sum(bool(row["true_breakout_10_7_20"]) for row in rows) / len(rows) if rows else None,
        "return_40d_median_descriptive": statistics.median(row["return_40d"] for row in rows) if rows else None,
    }


def analyze() -> int:
    freeze = json.loads((OUTPUT / "label-freeze.json").read_text(encoding="utf-8"))
    labels_path = OUTPUT / freeze["labels_file"]
    actual_hash = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if actual_hash != freeze["labels_sha256"]:
        raise RuntimeError("reviewed labels changed after freeze")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    if len(labels) != freeze["cases"] or Counter(row["classification"] for row in labels) != Counter(freeze["classification_counts"]):
        raise RuntimeError("reviewed label counts changed after freeze")
    sealed = json.loads((OUTPUT / "sealed.json").read_text(encoding="utf-8"))
    sealed_by_id = {row["case_id"]: row for row in sealed}
    joined = [{**label, **sealed_by_id[label["case_id"]]} for label in labels]
    supported = [row for row in joined if row["representation"]["supported"]]
    unsupported = [row for row in joined if not row["representation"]["supported"]]
    supported_summary, unsupported_summary = _summary(supported), _summary(unsupported)
    gap = supported_summary["classic_or_partial_rate"] - unsupported_summary["classic_or_partial_rate"]
    gates = {
        "supported_classic_or_partial_rate_min_0_75": supported_summary["classic_or_partial_rate"] >= 0.75,
        "supported_nonclassic_rate_max_0_25": supported_summary["nonclassic_rate"] <= 0.25,
        "supported_minus_unsupported_classic_or_partial_min_0_30": gap >= 0.30,
    }
    result = {"experiment": "stage2-base-context-v3-semantic-v1", "label_freeze_verified": True,
              "labels_sha256": actual_hash, "cases": len(joined), "supported": supported_summary,
              "unsupported": unsupported_summary, "supported_minus_unsupported_classic_or_partial": gap,
              "semantic_gates": gates, "all_semantic_gates_passed": all(gates.values()),
              "decision": "freeze_context_for_combination" if all(gates.values()) else "stop_without_variants",
              "interpretation_boundary": "Future outcomes were opened only after semantic labels were frozen and are descriptive only."}
    ANALYSIS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "analyze"))
    args = parser.parse_args()
    return build() if args.action == "build" else analyze()


if __name__ == "__main__":
    raise SystemExit(main())
