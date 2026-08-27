"""Reconciliation checks for the published QuantX market-fact foundation."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.market_facts.registry import DATASETS, DatasetId


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def published_quantx_dates(data_root: Path) -> list[date]:
    """Return dates that have a published single-day dashboard artifact."""
    quantx_root = Path(data_root) / "quantx"
    dates: list[date] = []
    if not quantx_root.is_dir():
        return dates
    for path in quantx_root.glob("????????/review_data.json"):
        try:
            dates.append(datetime.strptime(path.parent.name, "%Y%m%d").date())
        except ValueError:
            continue
    return sorted(set(dates))


def fact_fingerprint(
    data_root: Path,
    datasets: Iterable[DatasetId] | None = None,
) -> dict[str, Any]:
    """Hash canonical fact paths and content in stable lexical order."""
    root = Path(data_root).resolve()
    selected = tuple(DatasetId if datasets is None else datasets)
    artifacts: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    for dataset_id in sorted(selected, key=lambda item: item.value):
        for path in sorted((root / dataset_id.value).glob("date=*/part.parquet")):
            relative = path.relative_to(root).as_posix()
            digest = _sha256(path)
            size = path.stat().st_size
            aggregate.update(f"{relative}\0{size}\0{digest}\n".encode())
            artifacts.append({"path": relative, "bytes": size, "sha256": digest})
    return {
        "algorithm": "sha256(path\\0size\\0sha256\\n)",
        "sha256": aggregate.hexdigest(),
        "file_count": len(artifacts),
        "bytes": sum(item["bytes"] for item in artifacts),
        "artifacts": artifacts,
    }


def _audit_partition(path: Path, dataset_id: DatasetId, day: date) -> dict[str, Any]:
    spec = DATASETS[dataset_id]
    relative = Path(dataset_id.value) / path.parent.name / path.name
    base: dict[str, Any] = {
        "trade_date": day.isoformat(),
        "dataset_id": dataset_id.value,
        "path": relative.as_posix(),
    }
    if not path.is_file():
        return {**base, "status": "missing_partition", "row_count": 0}
    try:
        schema = pl.read_parquet_schema(path)
        missing = sorted(set(spec.storage_schema) - set(schema))
        incompatible = {
            name: {
                "expected": str(expected),
                "observed": str(schema[name]),
            }
            for name, expected in spec.storage_schema.items()
            if name in schema and schema[name] != expected
        }
        if missing or incompatible:
            return {
                **base,
                "status": "schema_mismatch",
                "row_count": None,
                "missing_columns": missing,
                "incompatible_columns": incompatible,
            }
        frame = pl.read_parquet(path)
    except Exception as exc:
        return {
            **base,
            "status": "unreadable_partition",
            "row_count": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if frame.is_empty():
        return {**base, "status": "empty_partition", "row_count": 0}

    versions = sorted({int(value) for value in frame["schema_version"].drop_nulls().to_list()})
    if versions != [spec.schema_version]:
        return {
            **base,
            "status": "schema_version_mismatch",
            "row_count": frame.height,
            "expected_schema_version": spec.schema_version,
            "observed_schema_versions": versions,
        }

    partition_column = spec.partition_keys[0]
    observed_partition_values = sorted(
        {
            value.isoformat() if isinstance(value, date) else str(value)
            for value in frame[partition_column].drop_nulls().to_list()
        }
    )
    if observed_partition_values != [day.isoformat()]:
        return {
            **base,
            "status": "partition_value_mismatch",
            "row_count": frame.height,
            "partition_column": partition_column,
            "observed_partition_values": observed_partition_values,
        }

    source_counts = frame.group_by("source").len(name="rows").sort("source").to_dicts()
    quality_counts = (
        frame.group_by("quality_level").len(name="rows").sort("quality_level").to_dicts()
    )
    return {
        **base,
        "status": "present",
        "row_count": frame.height,
        "schema_version": spec.schema_version,
        "source_counts": source_counts,
        "quality_counts": quality_counts,
    }


def audit_quantx_data_foundation(
    data_root: Path,
    *,
    datasets: Iterable[DatasetId] | None = None,
    dates: Iterable[date] | None = None,
    include_artifacts: bool = False,
) -> dict[str, Any]:
    """Reconcile every published QuantX date against every fact contract."""
    root = Path(data_root).resolve()
    selected = tuple(DatasetId if datasets is None else datasets)
    expected_dates = sorted(
        set(published_quantx_dates(root) if dates is None else dates)
    )
    checks: list[dict[str, Any]] = []
    for day in expected_dates:
        for dataset_id in selected:
            path = root / dataset_id.value / f"date={day.isoformat()}" / "part.parquet"
            checks.append(_audit_partition(path, dataset_id, day))

    status_counts = Counter(item["status"] for item in checks)
    dataset_coverage: list[dict[str, Any]] = []
    for dataset_id in selected:
        items = [item for item in checks if item["dataset_id"] == dataset_id.value]
        counts = Counter(item["status"] for item in items)
        dataset_coverage.append(
            {
                "dataset_id": dataset_id.value,
                "expected_dates": len(expected_dates),
                "present_dates": counts["present"],
                "gap_dates": len(items) - counts["present"],
                "status_counts": dict(sorted(counts.items())),
            }
        )

    fingerprint = fact_fingerprint(root, selected)
    if not include_artifacts:
        fingerprint.pop("artifacts")
    gap_checks = [item for item in checks if item["status"] != "present"]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data_root": str(root),
        "published_date_count": len(expected_dates),
        "published_dates": [item.isoformat() for item in expected_dates],
        "dataset_count": len(selected),
        "summary": {
            "expected_partition_count": len(checks),
            "present_partition_count": status_counts["present"],
            "gap_partition_count": len(gap_checks),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "dataset_coverage": dataset_coverage,
        "gaps": gap_checks,
        "fact_fingerprint": fingerprint,
    }
