from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

LayerCategory = Literal["pattern", "strategy", "event", "plan"]
LayerStatus = Literal["available", "insufficient_data", "unavailable", "error"]
PriceBasis = Literal["none", "qfq", "hfq"]


@dataclass(frozen=True)
class AnnotationEvidence:
    id: str
    title: str
    summary: str
    metrics: list[dict[str, Any]] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnnotationMarker:
    id: str
    layer_id: str
    date: str
    role: str
    price: float | None = None
    label: str = ""
    evidence_id: str | None = None
    detected_at: str | None = None
    confirmed_at: str | None = None
    invalidated_at: str | None = None
    count: int = 1


@dataclass(frozen=True)
class AnnotationLine:
    id: str
    layer_id: str
    role: str
    value: float
    start_date: str | None = None
    end_date: str | None = None
    end_value: float | None = None
    label: str = ""
    evidence_id: str | None = None


@dataclass(frozen=True)
class AnnotationZone:
    id: str
    layer_id: str
    role: str
    start_date: str
    end_date: str
    low: float | None = None
    high: float | None = None
    label: str = ""
    evidence_id: str | None = None
    confirmed_at: str | None = None


@dataclass(frozen=True)
class AnnotationSegment:
    id: str
    layer_id: str
    role: str
    points: list[dict[str, Any]]
    label: str = ""
    evidence_id: str | None = None
    confirmed_at: str | None = None


@dataclass
class ChartAnnotationLayer:
    id: str
    category: LayerCategory
    title: str
    status: LayerStatus
    price_basis: PriceBasis
    schema_version: int = 1
    algorithm_version: str | None = None
    input_fingerprint: str | None = None
    markers: list[AnnotationMarker] = field(default_factory=list)
    lines: list[AnnotationLine] = field(default_factory=list)
    zones: list[AnnotationZone] = field(default_factory=list)
    segments: list[AnnotationSegment] = field(default_factory=list)
    evidence: list[AnnotationEvidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChartLayerContext:
    symbol: str
    asset_type: str
    interval: str
    price_basis: PriceBasis
    rows: list[dict[str, Any]]
    visible_start: str
    visible_end: str
    input_fingerprint: str
    key_levels: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    data_dir: Any = None
    strategy_ids: tuple[str, ...] = ()
    source_run_id: str | None = None
    params_fingerprint: str | None = None
