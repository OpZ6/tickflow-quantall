"""Compressed, content-addressed raw source snapshots."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.market_facts.registry import DatasetId


@dataclass(frozen=True)
class SnapshotRecord:
    sha256: str
    blob_path: Path
    metadata_paths: tuple[Path, ...]


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


class SourceSnapshotStore:
    def __init__(self, data_root: Path) -> None:
        self.root = Path(data_root) / "source_snapshots"

    def record(
        self,
        *,
        source_id: str,
        dataset_ids: tuple[DatasetId, ...],
        trade_date: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> SnapshotRecord:
        parsed_date = datetime.strptime(trade_date, "%Y%m%d").date().isoformat()
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        blob = self.root / "blobs" / f"{digest}.json.gz"
        if not blob.exists():
            _atomic_write(blob, gzip.compress(raw, mtime=0))

        metadata_paths: list[Path] = []
        for dataset_id in dataset_ids:
            metadata = {
                "schema_version": 1,
                "source_id": source_id,
                "dataset_id": dataset_id.value,
                "trade_date": trade_date,
                "run_id": run_id,
                "blob_sha256": digest,
                "blob_path": blob.relative_to(self.root.parent).as_posix(),
                "uncompressed_bytes": len(raw),
            }
            path = (
                self.root
                / source_id
                / dataset_id.value
                / f"trade_date={parsed_date}"
                / f"{run_id}.meta.json"
            )
            encoded = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
            _atomic_write(path, encoded)
            metadata_paths.append(path)
        return SnapshotRecord(digest, blob, tuple(metadata_paths))
