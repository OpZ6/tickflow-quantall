"""Compressed, content-addressed raw source snapshots."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.market_facts.registry import DatasetId


@dataclass(frozen=True)
class SnapshotRecord:
    sha256: str
    blob_path: Path
    metadata_paths: tuple[Path, ...]


@dataclass(frozen=True)
class SnapshotRetentionPolicy:
    retention_days: int = 730

    def __post_init__(self) -> None:
        if self.retention_days < 30:
            raise ValueError("snapshot retention_days must be at least 30")

    @classmethod
    def from_environment(cls) -> SnapshotRetentionPolicy:
        raw = os.environ.get("TICKFLOW_SOURCE_SNAPSHOT_RETENTION_DAYS", "730").strip()
        try:
            return cls(retention_days=int(raw))
        except ValueError as exc:
            raise ValueError(
                "TICKFLOW_SOURCE_SNAPSHOT_RETENTION_DAYS must be an integer >= 30"
            ) from exc


@dataclass(frozen=True)
class SnapshotRetentionPlan:
    root: Path
    retention_days: int
    cutoff_date: date
    metadata_paths: tuple[Path, ...]
    blob_paths: tuple[Path, ...]

    @property
    def dry_run(self) -> bool:
        return True

    @property
    def metadata_count(self) -> int:
        return len(self.metadata_paths)

    @property
    def blob_count(self) -> int:
        return len(self.blob_paths)

    @property
    def bytes_reclaimable(self) -> int:
        return sum(
            path.stat().st_size for path in (*self.metadata_paths, *self.blob_paths)
            if path.is_file()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "retention_days": self.retention_days,
            "cutoff_date": self.cutoff_date.isoformat(),
            "metadata_count": self.metadata_count,
            "blob_count": self.blob_count,
            "bytes_reclaimable": self.bytes_reclaimable,
            "metadata_paths": [
                path.relative_to(self.root.parent).as_posix()
                for path in self.metadata_paths
            ],
            "blob_paths": [
                path.relative_to(self.root.parent).as_posix() for path in self.blob_paths
            ],
        }


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
        self.root = (Path(data_root) / "source_snapshots").resolve()

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

    def plan_retention(
        self,
        policy: SnapshotRetentionPolicy | None = None,
        *,
        today: date | None = None,
    ) -> SnapshotRetentionPlan:
        """Build a read-only plan; unknown metadata always remains protected."""
        selected = policy or SnapshotRetentionPolicy.from_environment()
        cutoff = (today or date.today()) - timedelta(days=selected.retention_days)
        metadata: list[Path] = []
        references: dict[str, list[bool]] = {}
        for path in sorted(self.root.glob("*/*/trade_date=*/*.meta.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                digest = str(payload["blob_sha256"])
                if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                    continue
            except (KeyError, OSError, json.JSONDecodeError):
                continue
            try:
                trade_date = datetime.strptime(str(payload["trade_date"]), "%Y%m%d").date()
            except (KeyError, ValueError):
                references.setdefault(digest, []).append(False)
                continue
            expired = trade_date < cutoff
            references.setdefault(digest, []).append(expired)
            if expired:
                metadata.append(path)

        blobs = []
        for digest, expired_refs in references.items():
            path = self.root / "blobs" / f"{digest}.json.gz"
            if expired_refs and all(expired_refs) and path.is_file():
                blobs.append(path)
        return SnapshotRetentionPlan(
            root=self.root.resolve(),
            retention_days=selected.retention_days,
            cutoff_date=cutoff,
            metadata_paths=tuple(metadata),
            blob_paths=tuple(sorted(blobs)),
        )

    def apply_retention(
        self,
        plan: SnapshotRetentionPlan,
        *,
        confirmed: bool,
    ) -> dict[str, Any]:
        """Move planned files into a recoverable quarantine after confirmation."""
        if not confirmed:
            raise ValueError("explicit retention confirmation is required")
        root = self.root.resolve()
        if plan.root.resolve() != root:
            raise ValueError("retention plan belongs to a different snapshot root")
        selected = tuple(dict.fromkeys((*plan.metadata_paths, *plan.blob_paths)))
        plan_payload = plan.to_dict()
        for path in selected:
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not path.is_file():
                raise ValueError(f"retention target is missing or outside snapshot root: {path}")

        quarantine = root / "_quarantine" / (
            "retention-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"-{uuid.uuid4().hex[:8]}"
        )
        moved: list[tuple[Path, Path]] = []
        try:
            for source in selected:
                destination = quarantine / source.resolve().relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                moved.append((source, destination))
            manifest = {
                "schema_version": 1,
                "status": "quarantined",
                "recoverable": True,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                **plan_payload,
                "dry_run": False,
            }
            _atomic_write(
                quarantine / "_retention_manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        except Exception:
            for source, destination in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    os.replace(destination, source)
            raise
        return {
            "status": "quarantined",
            "recoverable": True,
            "quarantine_path": str(quarantine),
            "metadata_count": plan.metadata_count,
            "blob_count": plan.blob_count,
            "bytes_reclaimable": plan_payload["bytes_reclaimable"],
        }
