from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from app.market_facts.audit import audit_quantx_data_foundation, fact_fingerprint
from app.market_facts.backup import (
    MANIFEST_NAME,
    PAYLOAD_DIR,
    create_backup,
    restore_backup,
    verify_backup,
)
from app.market_facts.registry import DATASETS, DatasetId

DAY = date(2026, 8, 25)


def _publish_day(root: Path) -> None:
    path = root / "quantx" / "20260825" / "review_data.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")


def _fact_frame(dataset_id: DatasetId, *, schema_version: int | None = None) -> pl.DataFrame:
    spec = DATASETS[dataset_id]
    values: dict[str, list[object]] = {}
    for name, dtype in spec.storage_schema.items():
        if name in spec.partition_keys or name == "trade_date":
            value: object = DAY
        elif name == "schema_version":
            value = schema_version if schema_version is not None else spec.schema_version
        elif dtype == pl.String:
            value = "test"
        elif dtype == pl.Boolean:
            value = False
        elif dtype.is_integer():
            value = 1
        elif dtype.is_float():
            value = 1.0
        elif isinstance(dtype, pl.List):
            value = ["test"]
        else:
            value = None
        values[name] = [value]
    return pl.DataFrame(values, schema=spec.storage_schema)


def _write_fact(root: Path, dataset_id: DatasetId, frame: pl.DataFrame) -> Path:
    path = root / dataset_id.value / "date=2026-08-25" / "part.parquet"
    path.parent.mkdir(parents=True)
    frame.write_parquet(path)
    return path


def test_audit_classifies_present_missing_empty_and_schema_errors(tmp_path: Path) -> None:
    _publish_day(tmp_path)
    present = DatasetId.MARKET_BREADTH_DAILY
    empty = DatasetId.MARKET_LIQUIDITY_DAILY
    schema_error = DatasetId.LIMIT_EVENT_DAILY
    version_error = DatasetId.LIMIT_LADDER_DAILY
    missing = DatasetId.SECTOR_FLOW_DAILY
    _write_fact(tmp_path, present, _fact_frame(present))
    _write_fact(tmp_path, empty, _fact_frame(empty).clear())
    bad_schema = _fact_frame(schema_error).drop("source_record_id")
    _write_fact(tmp_path, schema_error, bad_schema)
    _write_fact(tmp_path, version_error, _fact_frame(version_error, schema_version=99))

    result = audit_quantx_data_foundation(
        tmp_path,
        datasets=(present, empty, schema_error, version_error, missing),
    )

    assert result["published_dates"] == ["2026-08-25"]
    assert result["summary"]["status_counts"] == {
        "empty_partition": 1,
        "missing_partition": 1,
        "present": 1,
        "schema_mismatch": 1,
        "schema_version_mismatch": 1,
    }
    assert result["summary"]["gap_partition_count"] == 4


def test_fact_fingerprint_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    dataset = DatasetId.MARKET_BREADTH_DAILY
    path = _write_fact(tmp_path, dataset, _fact_frame(dataset))
    first = fact_fingerprint(tmp_path, (dataset,))
    second = fact_fingerprint(tmp_path, (dataset,))
    assert first == second

    path.write_bytes(path.read_bytes() + b"changed")
    assert fact_fingerprint(tmp_path, (dataset,))["sha256"] != first["sha256"]


def test_theme_member_builder_uses_limit_up_reason_when_concepts_are_absent() -> None:
    from app.market_facts.builders import _build_theme_members

    batch = _build_theme_members(
        "20260825",
        {
            "pywencai": {
                "scraped_at": "2026-08-25T16:00:00+08:00",
                "limit_up": {
                    "stocks": [
                        {"code": "000001", "name": "示例", "reason": "机器人"}
                    ]
                },
            }
        },
        {},
        "run-test",
        "2026-08-25T16:01:00+08:00",
    )
    frame = batch.frame
    assert frame.select("theme_name", "symbol", "role").rows() == [
        ("机器人", "000001", "limit_up_reason")
    ]


def test_backup_verify_and_isolated_restore(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "quantx" / "20260825").mkdir(parents=True)
    (data_root / "quantx" / "20260825" / "review_data.json").write_text("{}", encoding="utf-8")
    _write_fact(
        data_root, DatasetId.MARKET_BREADTH_DAILY, _fact_frame(DatasetId.MARKET_BREADTH_DAILY)
    )
    backup_dir = tmp_path / "backup"

    manifest = create_backup(
        data_root,
        backup_dir,
        roots=("quantx", DatasetId.MARKET_BREADTH_DAILY.value),
    )
    assert manifest["file_count"] == 2
    assert (backup_dir / MANIFEST_NAME).is_file()
    assert verify_backup(backup_dir)["status"] == "verified"

    restore_root = tmp_path / "restored-data"
    restored = restore_backup(backup_dir, restore_root)
    assert restored["status"] == "restored_and_verified"
    for item in manifest["artifacts"]:
        assert (restore_root / item["path"]).read_bytes() == (
            backup_dir / PAYLOAD_DIR / item["path"]
        ).read_bytes()


def test_backup_detects_corruption_and_rejects_unsafe_destinations(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = data_root / "quantx" / "20260825" / "review_data.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="outside"):
        create_backup(data_root, data_root / "backup", roots=("quantx",))

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        create_backup(data_root, nonempty, roots=("quantx",))

    backup_dir = tmp_path / "backup"
    create_backup(data_root, backup_dir, roots=("quantx",))
    manifest = json.loads((backup_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    artifact = backup_dir / PAYLOAD_DIR / manifest["artifacts"][0]["path"]
    artifact.write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="verification failed"):
        verify_backup(backup_dir)


def test_restore_rejects_nonempty_target_and_manifest_traversal(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = data_root / "quantx" / "20260825" / "review_data.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")
    backup_dir = tmp_path / "backup"
    create_backup(data_root, backup_dir, roots=("quantx",))

    nonempty = tmp_path / "restore"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        restore_backup(backup_dir, nonempty)

    with pytest.raises(ValueError, match="isolated"):
        restore_backup(backup_dir, data_root / "nested-restore")

    manifest_path = backup_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../escape.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        verify_backup(backup_dir)
