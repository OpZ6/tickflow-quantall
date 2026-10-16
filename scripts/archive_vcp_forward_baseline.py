"""Create one recoverable, no-overwrite archive for a frozen VCP baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION_MANIFEST = ROOT / "docs/research/vcp/forward-v2-version-manifest.json"
CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _root_path(relative: str) -> Path:
    path = (ROOT / relative.replace("\\", "/")).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise RuntimeError(f"archive input escapes repository root: {relative}") from exc
    return path


def _merged(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merged(result[key], value)
        else:
            result[key] = value
    return result


def _load_plan(version_manifest_path: Path) -> tuple[dict, list[tuple[str, Path]]]:
    overlay = json.loads(version_manifest_path.read_text(encoding="utf-8"))
    base_manifest_path = None
    if overlay.get("base_manifest"):
        base_manifest_path = _root_path(overlay["base_manifest"])
        expected = overlay.get("base_manifest_sha256")
        if expected and _sha256(base_manifest_path) != expected:
            raise RuntimeError("base version manifest hash mismatch")
        base = json.loads(base_manifest_path.read_text(encoding="utf-8"))
        manifest = _merged(base, overlay)
    else:
        manifest = overlay
    selection = manifest["data_reference"].get("snapshot_selection")
    if selection:
        inputs = _load_selected_snapshot(selection)
        support_paths = {
            version_manifest_path.resolve(),
            _root_path(manifest["strategy_contract"]),
            _root_path(manifest["code_reference"]["behavior_source_archive"]),
        }
        if base_manifest_path is not None:
            support_paths.add(base_manifest_path)
        for path in support_paths:
            if not path.is_file():
                raise RuntimeError(f"archive support input missing: {path}")
            inputs[path.relative_to(ROOT).as_posix()] = path
        return manifest, sorted(inputs.items())

    inventory_path = _root_path(manifest["data_reference"]["inventory"])
    if _sha256(inventory_path) != manifest["data_reference"]["inventory_sha256"]:
        raise RuntimeError("data inventory hash no longer matches the frozen manifest")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    replacements = {
        item["path"].replace("\\", "/"): item
        for item in manifest["data_reference"].get("inventory_replacements", [])
    }
    inputs: dict[str, Path] = {}
    for item in inventory["files"]:
        inventory_relative = item["path"].replace("\\", "/")
        relative = f"data/{inventory_relative}"
        path = _root_path(relative)
        if not path.is_file():
            raise RuntimeError(f"archive input missing: {relative}")
        stat = path.stat()
        expected = replacements.pop(inventory_relative, item)
        if stat.st_size != int(expected["size"]) or stat.st_mtime_ns != int(expected["mtime_ns"]):
            raise RuntimeError(f"archive input changed since selected inventory: {relative}")
        if expected.get("sha256") and _sha256(path) != expected["sha256"]:
            raise RuntimeError(f"replacement archive input hash mismatch: {relative}")
        inputs[relative] = path
    if replacements:
        raise RuntimeError(f"inventory replacement paths not found: {sorted(replacements)}")
    critical = {
        item["path"].replace("\\", "/"): item
        for item in manifest["data_reference"]["critical_fact_files"]
    }
    for item in manifest["data_reference"].get("critical_fact_file_replacements", []):
        critical[item["path"].replace("\\", "/")] = item
    for relative, item in critical.items():
        path = _root_path(relative)
        if not path.is_file() or path.stat().st_size != int(item["size"]):
            raise RuntimeError(f"critical archive input missing or resized: {relative}")
        if _sha256(path) != item["sha256"]:
            raise RuntimeError(f"critical archive input hash mismatch: {relative}")
        inputs[relative] = path
    support_paths = {
        version_manifest_path.resolve(),
        inventory_path,
        _root_path(manifest["strategy_contract"]),
        _root_path(manifest["code_reference"]["behavior_source_archive"]),
    }
    if base_manifest_path is not None:
        support_paths.add(base_manifest_path)
    for path in support_paths:
        if not path.is_file():
            raise RuntimeError(f"archive support input missing: {path}")
        inputs[path.relative_to(ROOT).as_posix()] = path
    return manifest, sorted(inputs.items())


def _load_selected_snapshot(selection: dict) -> dict[str, Path]:
    completed_through = str(selection["completed_through"])
    inputs: dict[str, Path] = {}
    date_sets: dict[str, set[str]] = {}
    for dataset in selection["dated_datasets"]:
        root = _root_path(f"data/{dataset}")
        dates: set[str] = set()
        for path in sorted(root.glob("date=*/part.parquet")):
            label = path.parent.name.removeprefix("date=")
            if label <= completed_through:
                relative = path.relative_to(ROOT).as_posix()
                inputs[relative] = path
                dates.add(label)
        if not dates:
            raise RuntimeError(f"selected archive dataset is empty: {dataset}")
        date_sets[dataset] = dates
        minimum_rows = int(selection.get("minimum_rows_by_dataset", {}).get(dataset, 0))
        if minimum_rows:
            for relative, path in inputs.items():
                if relative.startswith(f"data/{dataset}/date="):
                    rows = pq.ParquetFile(path).metadata.num_rows
                    if rows < minimum_rows:
                        raise RuntimeError(
                            f"archive partition below minimum rows: {relative} "
                            f"has {rows}, requires {minimum_rows}"
                        )
    aligned = selection.get("aligned_date_datasets", [])
    if aligned:
        reference = date_sets[aligned[0]]
        for dataset in aligned[1:]:
            if date_sets[dataset] != reference:
                raise RuntimeError(f"archive date coverage is not aligned: {dataset}")
        if max(reference) != completed_through:
            raise RuntimeError("archive datasets do not reach completed_through")
    for item in selection["files"]:
        relative = str(item["path"]).replace("\\", "/")
        path = _root_path(relative)
        if not path.is_file() or path.stat().st_size != int(item["size"]):
            raise RuntimeError(f"selected archive file missing or resized: {relative}")
        if _sha256(path) != item["sha256"]:
            raise RuntimeError(f"selected archive file hash mismatch: {relative}")
        inputs[relative] = path
    observation_dir = selection.get("forward_observation_dir")
    if observation_dir:
        root = _root_path(observation_dir)
        observations = []
        for path in sorted(root.glob("*.json")):
            if path.stem <= completed_through:
                inputs[path.relative_to(ROOT).as_posix()] = path
                observations.append(path.stem)
        if not observations or max(observations) != completed_through:
            raise RuntimeError("forward observations do not reach completed_through")
    return inputs


def _write_archive(output: Path, inputs: list[tuple[str, Path]]) -> list[dict]:
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary archive already exists: {temporary}")
    members = []
    try:
        with ZipFile(temporary, "x", compression=ZIP_STORED, allowZip64=True) as archive:
            for relative, source in inputs:
                before = source.stat()
                digest = hashlib.sha256()
                info = ZipInfo.from_file(source, relative)
                info.compress_type = ZIP_STORED
                with source.open("rb") as reader, archive.open(info, "w", force_zip64=True) as writer:
                    while chunk := reader.read(CHUNK_SIZE):
                        digest.update(chunk)
                        writer.write(chunk)
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f"archive input changed while reading: {relative}")
                members.append({
                    "path": relative,
                    "size": after.st_size,
                    "sha256": digest.hexdigest(),
                })
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return members


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-manifest", type=Path, default=DEFAULT_VERSION_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    version_manifest_path = args.version_manifest.resolve()
    manifest, inputs = _load_plan(version_manifest_path)
    output = (args.output or (
        ROOT / "data/research/vcp/forward/archives"
        / f"{manifest['manifest_id']}-baseline.zip"
    )).resolve()
    sidecar = output.with_suffix(".manifest.json")
    if output.exists() or sidecar.exists():
        raise FileExistsError(f"baseline archive is append-only: {output}")
    total_bytes = sum(path.stat().st_size for _, path in inputs)
    if args.dry_run:
        print(json.dumps({
            "status": "validated_dry_run",
            "manifest_id": manifest["manifest_id"],
            "files": len(inputs),
            "bytes": total_bytes,
            "output": str(output),
        }, ensure_ascii=False))
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    members = _write_archive(output, inputs)
    result = {
        "schema_version": 1,
        "archive_id": f"{manifest['manifest_id']}-baseline",
        "created_at": datetime.now(UTC).isoformat(),
        "source_version_manifest": version_manifest_path.relative_to(ROOT).as_posix(),
        "source_version_manifest_sha256": _sha256(version_manifest_path),
        "archive": output.relative_to(ROOT).as_posix(),
        "archive_sha256": _sha256(output),
        "archive_bytes": output.stat().st_size,
        "uncompressed_bytes": total_bytes,
        "files": members,
        "write_policy": "no overwrite; future completed days use separate archives",
    }
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "created",
        "archive": str(output),
        "files": len(members),
        "archive_bytes": output.stat().st_size,
        "archive_sha256": result["archive_sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
