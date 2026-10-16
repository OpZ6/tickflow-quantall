"""Atomic publication of canonical market fact partitions."""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.market_facts.builders import FactBatch
from app.market_facts.registry import get_dataset


@dataclass(frozen=True)
class _StagedPartition:
    batch: FactBatch
    staged: Path
    target: Path
    backup: Path


class FactPublication:
    """Stage and atomically replace a set of per-date Parquet partitions."""

    def __init__(self, data_root: Path, run_id: str) -> None:
        self.data_root = Path(data_root).resolve()
        self.run_id = run_id
        self.stage_root = self.data_root / ".fact_runs" / run_id
        self._items: list[_StagedPartition] = []
        self._committed: list[tuple[_StagedPartition, bool]] = []
        self._replace = os.replace

    def stage(self, batches: list[FactBatch]) -> None:
        if self._items:
            raise RuntimeError("fact publication already staged")
        seen: set[tuple[str, str]] = set()
        for batch in batches:
            spec = get_dataset(batch.dataset_id)
            missing = set(spec.storage_schema) - set(batch.frame.columns)
            if missing:
                raise ValueError(
                    f"{batch.dataset_id} missing storage columns: {', '.join(sorted(missing))}"
                )
            key = (batch.dataset_id.value, batch.trade_date.isoformat())
            if key in seen:
                raise ValueError(f"duplicate fact batch: {key}")
            seen.add(key)
            relative = (
                Path(batch.dataset_id.value)
                / f"date={batch.trade_date.isoformat()}"
                / "part.parquet"
            )
            staged = self.stage_root / relative
            target = self.data_root / relative
            backup = target.with_name(f".part.{self.run_id}.backup")
            staged.parent.mkdir(parents=True, exist_ok=True)
            batch.frame.write_parquet(staged)
            self._items.append(_StagedPartition(batch, staged, target, backup))

    def manifest_artifacts(self) -> list[dict[str, object]]:
        artifacts: list[dict[str, object]] = []
        for item in self._items:
            artifacts.append(
                {
                    "dataset_id": item.batch.dataset_id.value,
                    "path": item.target.relative_to(self.data_root).as_posix(),
                    "rows": item.batch.frame.height,
                    "bytes": item.staged.stat().st_size,
                    "sha256": hashlib.sha256(item.staged.read_bytes()).hexdigest(),
                }
            )
        return artifacts

    def commit(self) -> None:
        if not self._items:
            raise RuntimeError("fact publication has not been staged")
        try:
            for item in self._items:
                item.target.parent.mkdir(parents=True, exist_ok=True)
                if item.backup.exists():
                    raise RuntimeError(f"stale fact backup exists: {item.backup}")
                had_original = item.target.exists()
                if had_original:
                    self._replace(item.target, item.backup)
                try:
                    self._replace(item.staged, item.target)
                except Exception:
                    if had_original and item.backup.exists():
                        self._replace(item.backup, item.target)
                    raise
                self._committed.append((item, had_original))
        except Exception:
            self.rollback()
            raise

    def rollback(self) -> None:
        for item, had_original in reversed(self._committed):
            if item.target.exists():
                item.target.unlink()
            if had_original and item.backup.exists():
                self._replace(item.backup, item.target)
        self._committed.clear()

    def finalize(self) -> None:
        for item, _ in self._committed:
            item.backup.unlink(missing_ok=True)
        self._committed.clear()
        shutil.rmtree(self.stage_root, ignore_errors=True)

    def abandon(self) -> None:
        if self._committed:
            self.rollback()
        shutil.rmtree(self.stage_root, ignore_errors=True)
