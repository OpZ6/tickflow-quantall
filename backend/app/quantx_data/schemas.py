from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    DEGRADED = "degraded"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    required: bool
    collector: str
    role: str
    min_records: int = 0
    freshness_required: bool = True
    max_retries: int = 2


@dataclass
class SourceResult:
    name: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    error: str | None = None
    used_fallback: bool = False
    record_count: int = 0
    collected_at: str | None = None
    input_path: str | None = None
    raw_sha256: str | None = None
    normalized_sha256: str | None = None
    reused_snapshot: bool = False
    snapshot_refs: tuple[str, ...] = ()
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "source": self.source or self.name,
            "error": self.error,
            "used_fallback": self.used_fallback,
            "record_count": self.record_count,
            "collected_at": self.collected_at,
            "input_path": self.input_path,
            "raw_sha256": self.raw_sha256,
            "normalized_sha256": self.normalized_sha256,
            "reused_snapshot": self.reused_snapshot,
            "snapshot_refs": list(self.snapshot_refs),
            "attempts": self.attempts,
        }


@dataclass
class PipelineResult:
    trade_date: str
    status: RunStatus
    run_id: str
    stages: list[str]
    sources: dict[str, SourceResult]
    artifacts: dict[str, str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "status": self.status.value,
            "run_id": self.run_id,
            "stages": self.stages,
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
            "artifacts": self.artifacts,
            "errors": self.errors,
            "warnings": self.warnings,
        }
