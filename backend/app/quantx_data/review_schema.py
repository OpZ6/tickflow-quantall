"""Strict response schema for the canonical QuantX single-day view."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REVIEW_V2_SCHEMA_VERSION = "quantx-review.v2"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoreBlock(_StrictModel):
    score: float | None = Field(default=None, ge=0, le=100, description="0-100 score")
    zone: str = ""


class LossEffect(_StrictModel):
    severity: str = ""
    limit_down_count: int | None = Field(default=None, ge=0, description="stock count")


class HeightTrend(_StrictModel):
    days: list[dict[str, Any]] = Field(default_factory=list)
    latest_max_board: int = Field(default=0, ge=0, description="board count")
    previous_high_5d: int | None = Field(default=None, ge=0, description="board count")
    height_compressed: bool = False
    evidence: str = ""


class MetricStrip(_StrictModel):
    indexes: list[dict[str, Any]] = Field(default_factory=list, description="stable index order")
    up_count: int | None = Field(default=None, ge=0, description="stock count")
    down_count: int | None = Field(default=None, ge=0, description="stock count")
    flat_count: int | None = Field(default=None, ge=0, description="stock count")
    total_amount_yi: float | None = Field(default=None, ge=0, description="CNY 100m")
    advance_rate: float | None = Field(default=None, description="percent value")


class Emotion(_StrictModel):
    market_heat: ScoreBlock = Field(default_factory=ScoreBlock)
    short_term_sentiment: ScoreBlock = Field(default_factory=ScoreBlock)
    trend_sentiment: ScoreBlock = Field(default_factory=ScoreBlock)
    loss_effect: LossEffect = Field(default_factory=LossEffect)
    height_trend: HeightTrend = Field(default_factory=HeightTrend)
    daily_summary: str = ""


class Section0(_StrictModel):
    diagnosis: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)


class Section1(_StrictModel):
    indexes: list[dict[str, Any]] = Field(default_factory=list)
    kline_history: list[dict[str, Any]] = Field(default_factory=list)
    up_count_history: list[dict[str, Any]] = Field(default_factory=list)
    width_heat: list[dict[str, Any]] = Field(default_factory=list)
    width_heat_level2: list[dict[str, Any]] = Field(default_factory=list)
    margin: dict[str, Any] | None = None
    margin_history: list[dict[str, Any]] = Field(default_factory=list)
    congestion: dict[str, Any] | None = None


class Section2(_StrictModel):
    participation: dict[str, Any] | None = None
    ebb_risk: dict[str, Any] | None = None
    themes_pywencai: list[dict[str, Any]] = Field(default_factory=list)
    themes_ths: list[dict[str, Any]] = Field(default_factory=list)
    new_high: dict[str, Any] | None = None


class Section3(_StrictModel):
    emotion_scores: dict[str, Any] = Field(default_factory=dict)
    emotion_zones: dict[str, str] = Field(default_factory=dict)
    advance: dict[str, Any] = Field(default_factory=dict)
    advance_history: list[dict[str, Any]] = Field(default_factory=list)
    ebb_signals: list[dict[str, Any]] = Field(default_factory=list)
    crash_signals: list[dict[str, Any]] = Field(default_factory=list)
    ladder_grid: list[dict[str, Any]] = Field(default_factory=list)
    ladder_detail: list[dict[str, Any]] = Field(default_factory=list)
    height_history: list[dict[str, Any]] = Field(default_factory=list)


class Section4(_StrictModel):
    sector_flow: dict[str, Any] = Field(
        default_factory=lambda: {"top_in": [], "top_out": []}
    )
    sector_treemap: list[dict[str, Any]] = Field(default_factory=list)


class Section5(_StrictModel):
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class Section6(_StrictModel):
    position: dict[str, Any] | None = None
    scenes: list[dict[str, Any]] = Field(default_factory=list)


class ReviewSections(_StrictModel):
    s0: Section0 = Field(default_factory=Section0)
    s1: Section1 = Field(default_factory=Section1)
    s2: Section2 = Field(default_factory=Section2)
    s3: Section3 = Field(default_factory=Section3)
    s4: Section4 = Field(default_factory=Section4)
    s5: Section5 = Field(default_factory=Section5)
    s6: Section6 = Field(default_factory=Section6)


class ReviewDataFoundationV2(_StrictModel):
    schema_version: Literal["quantx-review.v2"] = REVIEW_V2_SCHEMA_VERSION
    read_mode: Literal["canonical_view_v2"] = "canonical_view_v2"
    cache_artifact: None = None
    source_json_read: Literal[False] = False
    presentation_cache_read: Literal[False] = False
    canonical_fields: list[str] = Field(default_factory=list)
    derived_fields: list[str] = Field(default_factory=list)
    view_algorithm_version: str
    derived_field_status: dict[str, dict[str, Any]] = Field(default_factory=dict)
    presentation_fields: list[str] = Field(default_factory=list)
    presentation_cache_fields: list[str] = Field(default_factory=list)
    deprecated_fields: list[str] = Field(default_factory=list)
    fallback_fields: list[str] = Field(default_factory=list)
    implicit_cache_fields: list[str] = Field(default_factory=list)


class QuantXReviewResponseV2(_StrictModel):
    trade_date: str = Field(pattern=r"^\d{8}$", description="YYYYMMDD trading date")
    metric_strip: MetricStrip = Field(default_factory=MetricStrip)
    emotion: Emotion = Field(default_factory=Emotion)
    sections: ReviewSections = Field(default_factory=ReviewSections)
    data_foundation: ReviewDataFoundationV2 | None = None

    @classmethod
    def empty(cls, trade_date: str) -> QuantXReviewResponseV2:
        """Return a typed empty view; missing facts remain null or empty."""
        return cls(trade_date=trade_date)
