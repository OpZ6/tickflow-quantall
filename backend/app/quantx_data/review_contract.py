"""Field-origin contract for the QuantX single-day compatibility response."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

REVIEW_SCHEMA_VERSION = "quantx-review.v1.1"

V2_FIELD_CONTRACTS: dict[str, str] = {
    "trade_date": "canonical_fact",
    "metric_strip.indexes": "canonical_kline",
    "metric_strip.up_count": "canonical_fact",
    "metric_strip.down_count": "canonical_fact",
    "metric_strip.flat_count": "canonical_fact",
    "metric_strip.total_amount_yi": "canonical_fact",
    "metric_strip.advance_rate": "canonical_fact",
    "emotion.market_heat": "canonical_fact",
    "emotion.short_term_sentiment": "canonical_fact",
    "emotion.trend_sentiment": "canonical_fact",
    "emotion.loss_effect": "canonical_fact",
    "emotion.height_trend": "derived_view",
    "emotion.daily_summary": "derived_view",
    "sections.s0.diagnosis": "derived_view",
    "sections.s0.risks": "derived_view",
    "sections.s1.indexes": "canonical_kline",
    "sections.s1.kline_history": "canonical_kline",
    "sections.s1.up_count_history": "canonical_fact",
    "sections.s1.width_heat": "canonical_fact",
    "sections.s1.width_heat_level2": "canonical_fact",
    "sections.s1.margin": "canonical_fact",
    "sections.s1.margin_history": "canonical_fact",
    "sections.s1.congestion": "canonical_fact",
    "sections.s2.participation": "canonical_fact",
    "sections.s2.ebb_risk": "canonical_fact",
    "sections.s2.themes_pywencai": "canonical_fact",
    "sections.s2.themes_ths": "canonical_fact",
    "sections.s2.new_high": "canonical_fact",
    "sections.s3.emotion_scores": "canonical_fact",
    "sections.s3.emotion_zones": "derived_view",
    "sections.s3.advance": "canonical_fact",
    "sections.s3.advance_history": "canonical_fact",
    "sections.s3.ebb_signals": "canonical_fact",
    "sections.s3.crash_signals": "canonical_fact",
    "sections.s3.ladder_grid": "canonical_fact",
    "sections.s3.ladder_detail": "canonical_fact",
    "sections.s3.height_history": "canonical_fact",
    "sections.s4.sector_flow": "canonical_fact",
    "sections.s4.sector_treemap": "canonical_fact",
    "sections.s5.candidates": "canonical_fact",
    "sections.s6.position": "derived_view",
    "sections.s6.scenes": "derived_view",
}

_V2_FIELD_UNITS = {
    "metric_strip.up_count": "count",
    "metric_strip.down_count": "count",
    "metric_strip.flat_count": "count",
    "metric_strip.total_amount_yi": "CNY_100M",
    "metric_strip.advance_rate": "percent_value",
    "emotion.market_heat": "score_0_100",
    "emotion.short_term_sentiment": "score_0_100",
    "emotion.trend_sentiment": "score_0_100",
}
_V2_LIST_SORT_RULES = {
    "metric_strip.indexes": "configured_index_order",
    "sections.s1.indexes": "configured_index_order",
    "sections.s1.kline_history": "trade_date_asc",
    "sections.s1.up_count_history": "trade_date_asc",
    "sections.s1.width_heat": "sector_id_asc",
    "sections.s1.width_heat_level2": "sector_id_asc",
    "sections.s1.margin_history": "trade_date_asc",
    "sections.s2.themes_pywencai": "rank_asc_nulls_last",
    "sections.s2.themes_ths": "rank_asc_nulls_last",
    "sections.s3.advance_history": "trade_date_asc",
    "sections.s3.ebb_signals": "signal_id_asc",
    "sections.s3.crash_signals": "signal_id_asc",
    "sections.s3.ladder_grid": "board_height_desc",
    "sections.s3.ladder_detail": "source_priority_then_storage_order",
    "sections.s3.height_history": "trade_date_asc",
    "sections.s4.sector_flow": "net_inflow_desc_or_asc",
    "sections.s4.sector_treemap": "absolute_net_inflow_desc",
    "sections.s5.candidates": "priority_asc_score_desc_symbol_asc",
    "sections.s6.scenes": "strong_neutral_weak",
}

_FRONTEND_ALIASES = {
    "ms": "metric_strip",
    "em": "emotion",
    **{f"s{index}": f"sections.s{index}" for index in range(7)},
}
_FRONTEND_PROPERTY = re.compile(
    r"\b(ms|em|s[0-6])\??\.([A-Za-z_][A-Za-z0-9_]*)"
)

_CANONICAL_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "trade_date": ("trade_date",),
    "metric_strip.market_breadth": (
        "metric_strip.up_count",
        "metric_strip.down_count",
        "metric_strip.flat_count",
    ),
    "metric_strip.total_amount_yi": ("metric_strip.total_amount_yi",),
    "metric_strip.advance_rate": ("metric_strip.advance_rate",),
    "metric_strip.indexes": ("metric_strip.indexes",),
    "emotion.scores": (
        "emotion.market_heat.score",
        "emotion.short_term_sentiment.score",
        "emotion.trend_sentiment.score",
    ),
    "emotion.loss_effect": ("emotion.loss_effect",),
    "sections.s3.emotion_scores": ("sections.s3.emotion_scores",),
    "sections.s3.advance": ("sections.s3.advance",),
    "sections.s1.up_count_history": ("sections.s1.up_count_history",),
    "sections.s1.width_heat": ("sections.s1.width_heat",),
    "sections.s1.width_heat_level2": ("sections.s1.width_heat_level2",),
    "sections.s1.congestion": ("sections.s1.congestion",),
    "sections.s3.advance_history": ("sections.s3.advance_history",),
    "sections.s2.participation": ("sections.s2.participation",),
    "sections.s2.ebb_risk": ("sections.s2.ebb_risk",),
    "sections.s3.ebb_signals": ("sections.s3.ebb_signals",),
    "sections.s3.crash_signals": ("sections.s3.crash_signals",),
    "sections.s1.margin": ("sections.s1.margin",),
    "sections.s1.margin_history": ("sections.s1.margin_history",),
    "sections.s2.themes_pywencai": ("sections.s2.themes_pywencai",),
    "sections.s2.themes_ths": ("sections.s2.themes_ths",),
    "sections.s3.ladder_grid": ("sections.s3.ladder_grid",),
    "sections.s3.ladder_detail": ("sections.s3.ladder_detail",),
    "sections.s3.height_history": ("sections.s3.height_history",),
    "sections.s4.sector_flow": ("sections.s4.sector_flow",),
    "sections.s4.sector_treemap": ("sections.s4.sector_treemap",),
    "sections.s5.candidates": ("sections.s5.candidates",),
    "sections.s2.new_high": ("sections.s2.new_high",),
    "sections.s1.indexes": ("sections.s1.indexes",),
    "sections.s1.kline_history": ("sections.s1.kline_history",),
}

_KNOWN_CANONICAL_PATHS = tuple(
    path for paths in _CANONICAL_EXPANSIONS.values() for path in paths
)

PRESENTATION_FIELDS = tuple(
    f"sections.s{index}.title" for index in range(7)
)

DEPRECATED_FIELDS = (
    *(f"sections.s{index}.llm_block" for index in range(7)),
    "sections.s1.futures",
    "sections.s4.institution",
    "sections.s4.dx_strength",
)

DEPRECATION_SCHEDULE = {
    field: {
        "removed_in": "quantx-review.v2",
        "reason": "no reliable canonical source or active V2 consumer",
        "replacement": None,
    }
    for field in DEPRECATED_FIELDS
}


def _leaf_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        if not value:
            return [prefix] if prefix else []
        paths: list[str] = []
        for key, child in value.items():
            if key == "data_foundation" and not prefix:
                continue
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_leaf_paths(child, child_prefix))
        return paths
    if isinstance(value, list):
        if not value:
            return [prefix] if prefix else []
        paths: list[str] = []
        for child in value:
            paths.extend(_leaf_paths(child, f"{prefix}[]"))
        return paths
    return [prefix] if prefix else []


def _matches(path: str, rule: str) -> bool:
    return path == rule or path.startswith(f"{rule}.") or path.startswith(
        f"{rule}[]"
    )


def _matched_rule(path: str, rules: Iterable[str]) -> str | None:
    matches = [rule for rule in rules if _matches(path, rule)]
    return max(matches, key=len) if matches else None


def _expanded(paths: Iterable[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for path in paths:
        expanded.extend(_CANONICAL_EXPANSIONS.get(path, (path,)))
    return tuple(expanded)


def audit_review_fields(
    snapshot: dict[str, Any],
    *,
    canonical_fields: Iterable[str],
    derived_fields: Iterable[str],
    cache_backed: bool = True,
    schema_version: str = REVIEW_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Classify every response leaf and expose cache fallbacks explicitly."""
    effective_canonical = _expanded(("trade_date", *canonical_fields))
    effective_derived = tuple(derived_fields)
    presentation: set[str] = set()
    deprecated: set[str] = set()
    fallback: set[str] = set()
    implicit: set[str] = set()

    for path in _leaf_paths(snapshot):
        if _matched_rule(path, effective_canonical):
            continue
        if _matched_rule(path, effective_derived):
            continue
        matched = _matched_rule(path, PRESENTATION_FIELDS)
        if matched:
            presentation.add(matched)
            continue
        matched = _matched_rule(path, DEPRECATED_FIELDS)
        if matched:
            deprecated.add(matched)
            continue
        if _matched_rule(path, _KNOWN_CANONICAL_PATHS):
            if cache_backed:
                fallback.add(path)
            continue
        implicit.add(path)

    return {
        "schema_version": schema_version,
        "presentation_fields": sorted(presentation),
        "deprecated_fields": sorted(deprecated),
        "fallback_fields": sorted(fallback),
        "implicit_cache_fields": sorted(implicit),
    }


def extract_frontend_review_paths(source: str) -> list[str]:
    """Extract top-level response fields consumed by the QuantX page."""
    return sorted(
        {
            f"{_FRONTEND_ALIASES[alias]}.{field}"
            for alias, field in _FRONTEND_PROPERTY.findall(source)
        }
    )


def classify_frontend_review_paths(paths: Iterable[str]) -> dict[str, list[str]]:
    """Fail closed when a frontend field lacks one V2 source class."""
    missing: list[str] = []
    conflicts: list[str] = []
    for path in sorted(set(paths)):
        classifications = [
            value for key, value in V2_FIELD_CONTRACTS.items() if key == path
        ]
        if not classifications:
            missing.append(path)
        elif len(set(classifications)) != 1:
            conflicts.append(path)
    return {"missing": missing, "conflicts": conflicts}


def classify_review_path(path: str) -> str | None:
    """Return the single declared V2 source class for a response path."""
    matched = _matched_rule(path, V2_FIELD_CONTRACTS)
    if matched:
        return V2_FIELD_CONTRACTS[matched]
    if _matched_rule(path, PRESENTATION_FIELDS):
        return "presentation_constant"
    if _matched_rule(path, DEPRECATED_FIELDS):
        return "deprecated"
    return None


def review_v2_contract_manifest() -> dict[str, dict[str, str]]:
    """Return machine-readable source, unit, null, and ordering semantics."""
    return {
        path: {
            "classification": classification,
            "unit": _V2_FIELD_UNITS.get(path, "structured"),
            "null_behavior": "null_or_empty_without_cache_fallback",
            "sort": _V2_LIST_SORT_RULES.get(path, "not_applicable"),
        }
        for path, classification in sorted(V2_FIELD_CONTRACTS.items())
    }
