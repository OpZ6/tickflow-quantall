from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import sha256_file, write_json_atomic
from .schemas import RunStatus, SourceResult


def write_manifest(
    date_dir: Path,
    trade_date: str,
    run_id: str,
    status: RunStatus,
    sources: dict[str, SourceResult],
    *,
    errors: list[str],
    warnings: list[str],
    fact_artifacts: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    artifacts = []
    for path in sorted(date_dir.rglob("*")):
        if not path.is_file() or (path.name.startswith("_") and path.name == "_data_manifest.json"):
            continue
        artifacts.append({"path": path.relative_to(date_dir).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    payload = {
        "schema_version": 2,
        "trade_date": trade_date,
        "run_id": run_id,
        "status": status.value,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pipeline": "tickflow.quantx_data",
        "calculation_version": "quantx-data-v1",
        "llm": False,
        "sources": {name: result.to_dict() for name, result in sources.items()},
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "fact_artifacts": fact_artifacts or [],
        "errors": errors,
        "warnings": warnings,
    }
    write_json_atomic(date_dir / "_data_manifest.json", payload)
    return payload
