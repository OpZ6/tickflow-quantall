"""Audit canonical/derived QuantX review fields across published dates."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.market_facts.repository import MarketFactRepository
from app.quantx_data.io import read_json
from app.quantx_data.review_contract import (
    DEPRECATED_FIELDS,
    PRESENTATION_FIELDS,
    V2_FIELD_CONTRACTS,
    classify_review_path,
)
from app.quantx_data.review_repository import QuantXReviewRepository
from app.tickflow.repository import DataStore, KlineRepository

DERIVED_AUDIT_PATHS = (
    "emotion.market_heat.zone",
    "emotion.short_term_sentiment.zone",
    "emotion.trend_sentiment.zone",
    "emotion.height_trend",
    "emotion.daily_summary",
    "sections.s0.diagnosis",
    "sections.s0.risks",
    "sections.s3.emotion_zones",
    "sections.s6.position",
    "sections.s6.scenes",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit QuantX review cache replacement across history."
    )
    parser.add_argument("--data-root", type=Path, default=Path("../data"))
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _difference_reason(classification: str | None) -> str:
    return {
        "presentation_constant": "moved_to_frontend",
        "deprecated": "removed_no_reliable_source",
        "derived_view": "deterministic_rebuild",
        "canonical_fact": "canonical_fact_rebuild",
        "canonical_kline": "canonical_kline_rebuild",
    }.get(classification, "removed_unconsumed_cache")


def audit(data_root: Path) -> dict[str, Any]:
    data_root = data_root.resolve()
    quantx_dir = data_root / "quantx"
    dates = sorted(
        item.name
        for item in quantx_dir.iterdir()
        if item.is_dir()
        and item.name.isdigit()
        and (item / "review_data.json").is_file()
    )
    store = DataStore(data_root)
    repository = QuantXReviewRepository(
        quantx_dir,
        MarketFactRepository(data_root),
        KlineRepository(store),
    )
    changed_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    try:
        for trade_date in dates:
            cached = read_json(quantx_dir / trade_date / "review_data.json")
            compatibility = repository.load(trade_date, view_version="v1")
            response = repository.load(trade_date, view_version="v2")
            if (
                not isinstance(cached, dict)
                or not isinstance(compatibility, dict)
                or not isinstance(response, dict)
            ):
                records.append(
                    {
                        "trade_date": trade_date,
                        "status": "unavailable",
                    }
                )
                continue
            changed = [
                path
                for path in DERIVED_AUDIT_PATHS
                if _value(cached, path) != _value(response, path)
            ]
            changed_counts.update(changed)
            foundation = response.get("data_foundation") or {}
            compatibility_foundation = compatibility.get("data_foundation") or {}
            comparison_paths = set(V2_FIELD_CONTRACTS)
            comparison_paths.update(PRESENTATION_FIELDS)
            comparison_paths.update(DEPRECATED_FIELDS)
            comparison_paths.update(
                compatibility_foundation.get("implicit_cache_fields") or []
            )
            differences = []
            for path in sorted(comparison_paths):
                if "[]" in path:
                    differences.append(
                        {
                            "path": path,
                            "v1": "present",
                            "v2": None,
                            "classification": "compatibility_implicit",
                            "reason": "removed_unconsumed_cache",
                        }
                    )
                    continue
                v1_value = _value(compatibility, path)
                v2_value = _value(response, path)
                if v1_value == v2_value:
                    continue
                classification = classify_review_path(path)
                differences.append(
                    {
                        "path": path,
                        "v1": v1_value,
                        "v2": v2_value,
                        "classification": classification or "compatibility_implicit",
                        "reason": _difference_reason(classification),
                    }
                )
            records.append(
                {
                    "trade_date": trade_date,
                    "status": "ok",
                    "changed_derived_fields": changed,
                    "fallback_fields": foundation.get("fallback_fields") or [],
                    "implicit_cache_fields": (
                        foundation.get("implicit_cache_fields") or []
                    ),
                    "missing_derived_inputs": sorted(
                        field
                        for field, status in (
                            foundation.get("derived_field_status") or {}
                        ).items()
                        if status.get("status") != "available"
                    ),
                    "schema_version": foundation.get("schema_version"),
                    "source_json_read": foundation.get("source_json_read"),
                    "differences": differences,
                    "unexplained_differences": [
                        difference
                        for difference in differences
                        if not difference.get("reason")
                    ],
                }
            )
    finally:
        store.db.close()

    ok_records = [record for record in records if record["status"] == "ok"]
    return {
        "schema_version": "quantx-review-view-audit.v1",
        "data_root": str(data_root),
        "published_date_count": len(dates),
        "audited_date_count": len(ok_records),
        "fallback_date_count": sum(
            bool(record["fallback_fields"]) for record in ok_records
        ),
        "implicit_cache_date_count": sum(
            bool(record["implicit_cache_fields"]) for record in ok_records
        ),
        "schema_mismatch_date_count": sum(
            record["schema_version"] != "quantx-review.v2"
            for record in ok_records
        ),
        "source_json_read_date_count": sum(
            record["source_json_read"] is not False for record in ok_records
        ),
        "unexplained_difference_date_count": sum(
            bool(record["unexplained_differences"]) for record in ok_records
        ),
        "missing_derived_input_date_count": sum(
            bool(record["missing_derived_inputs"]) for record in ok_records
        ),
        "derived_change_counts": dict(sorted(changed_counts.items())),
        "records": records,
    }


def main() -> int:
    args = _args()
    report = audit(args.data_root)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "schema_version",
                        "data_root",
                        "published_date_count",
                        "audited_date_count",
                        "fallback_date_count",
                        "implicit_cache_date_count",
                        "schema_mismatch_date_count",
                        "source_json_read_date_count",
                        "unexplained_difference_date_count",
                        "missing_derived_input_date_count",
                        "derived_change_counts",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(f"full_report={args.output.resolve()}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
