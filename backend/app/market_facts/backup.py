"""Non-destructive backup and isolated restore for the QuantX data foundation."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.market_facts.registry import DatasetId

BACKUP_SCOPE_VERSION = 1
CORE_DATA_ROOTS = (
    "adj_factor",
    "instruments",
    "instruments_index",
    "kline_daily",
    "kline_daily_enriched",
    "kline_index_daily",
    "kline_index_enriched",
    "quantx",
    "source_snapshots",
)
MANIFEST_NAME = "quantx-data-foundation-backup.json"
PAYLOAD_DIR = "payload"


def backup_roots() -> tuple[str, ...]:
    return tuple(sorted({*(item.value for item in DatasetId), *CORE_DATA_ROOTS}))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_new_empty_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ValueError(f"{label} must not exist or must be an empty directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _is_nested(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _source_files(data_root: Path, roots: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for name in sorted(set(roots)):
        source = data_root / name
        if source.is_dir():
            files.extend(path for path in source.rglob("*") if path.is_file())
        elif source.is_file():
            files.append(source)
    return sorted(files, key=lambda path: path.relative_to(data_root).as_posix())


def _safe_relative(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe backup artifact path: {value}")
    return relative


def create_backup(
    data_root: Path,
    backup_dir: Path,
    *,
    roots: Iterable[str] | None = None,
) -> dict[str, Any]:
    source_root = Path(data_root).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    target_root = Path(backup_dir).resolve()
    if _is_nested(target_root, source_root):
        raise ValueError("backup directory must be outside the source data root")
    target_root = _require_new_empty_directory(target_root, "backup directory")
    payload_root = target_root / PAYLOAD_DIR
    selected_roots = tuple(sorted(set(roots or backup_roots())))
    artifacts: list[dict[str, Any]] = []
    try:
        for source in _source_files(source_root, selected_roots):
            relative = source.relative_to(source_root)
            target = payload_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            source_hash = _sha256(source)
            target_hash = _sha256(target)
            if target_hash != source_hash:
                raise OSError(f"backup hash mismatch: {relative.as_posix()}")
            artifacts.append(
                {
                    "path": relative.as_posix(),
                    "bytes": source.stat().st_size,
                    "sha256": source_hash,
                }
            )
        aggregate = hashlib.sha256()
        for item in artifacts:
            aggregate.update(f"{item['path']}\0{item['bytes']}\0{item['sha256']}\n".encode())
        manifest = {
            "schema_version": 1,
            "scope_version": BACKUP_SCOPE_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_data_root": str(source_root),
            "roots": list(selected_roots),
            "file_count": len(artifacts),
            "bytes": sum(item["bytes"] for item in artifacts),
            "sha256": aggregate.hexdigest(),
            "artifacts": artifacts,
        }
        (target_root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        verify_backup(target_root)
        return manifest
    except Exception:
        # Preserve partial output for diagnosis; the destination was guaranteed empty.
        raise


def load_manifest(backup_dir: Path) -> dict[str, Any]:
    path = Path(backup_dir).resolve() / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported backup manifest schema")
    return payload


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    root = Path(backup_dir).resolve()
    manifest = load_manifest(root)
    errors: list[str] = []
    aggregate = hashlib.sha256()
    expected_paths = {item["path"] for item in manifest["artifacts"]}
    actual_paths = {
        path.relative_to(root / PAYLOAD_DIR).as_posix()
        for path in (root / PAYLOAD_DIR).rglob("*")
        if path.is_file()
    }
    for unexpected in sorted(actual_paths - expected_paths):
        errors.append(f"unexpected:{unexpected}")
    for item in manifest["artifacts"]:
        relative = _safe_relative(item["path"])
        path = root / PAYLOAD_DIR / relative
        if not path.is_file():
            errors.append(f"missing:{relative.as_posix()}")
            continue
        size = path.stat().st_size
        digest = _sha256(path)
        if size != item["bytes"]:
            errors.append(f"size:{relative.as_posix()}")
        if digest != item["sha256"]:
            errors.append(f"sha256:{relative.as_posix()}")
        aggregate.update(f"{item['path']}\0{size}\0{digest}\n".encode())
    if aggregate.hexdigest() != manifest["sha256"]:
        errors.append("aggregate_sha256")
    if errors:
        raise ValueError("backup verification failed: " + ", ".join(errors[:20]))
    return {
        "status": "verified",
        "backup_dir": str(root),
        "file_count": manifest["file_count"],
        "bytes": manifest["bytes"],
        "sha256": manifest["sha256"],
    }


def restore_backup(backup_dir: Path, restore_data_root: Path) -> dict[str, Any]:
    backup_root = Path(backup_dir).resolve()
    verification = verify_backup(backup_root)
    target_root = Path(restore_data_root).resolve()
    if _is_nested(target_root, backup_root):
        raise ValueError("restore data root must be outside the backup directory")
    manifest = load_manifest(backup_root)
    original_root = Path(manifest["source_data_root"]).resolve()
    if _is_nested(target_root, original_root):
        raise ValueError("restore data root must be isolated from the source data root")
    target_root = _require_new_empty_directory(target_root, "restore data root")
    for item in manifest["artifacts"]:
        relative = _safe_relative(item["path"])
        source = backup_root / PAYLOAD_DIR / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if target.stat().st_size != item["bytes"] or _sha256(target) != item["sha256"]:
            raise OSError(f"restored file verification failed: {relative.as_posix()}")
    return {
        **verification,
        "status": "restored_and_verified",
        "restore_data_root": str(target_root),
    }
