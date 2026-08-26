from __future__ import annotations

from pathlib import Path

from app.market_facts.builders import FactBatch
from app.market_facts.registry import DatasetId, get_route

from .schemas import RunStatus, SourceResult, SourceSpec

CORE_ARTIFACTS = (
    "market_overview.json", "market_breadth.json", "market_liquidity.json",
    "limit_summary.json", "limit_ladder.json", "limit_stocks.json",
    "promotion_stats.json", "premium_stats.json", "theme_snapshot.json",
    "theme_rankings.json", "theme_history.json", "theme_stocks.json", "sentiment_state.json",
    "risk_signals.json", "participation.json", "sector_fund_flow.json",
    "sector_rotation.json", "screening_candidates.json", "trend_history.json",
    "trend_pool.json", "_computed.json",
    "review_data.json",
)


def validate_sources(specs: list[SourceSpec], results: dict[str, SourceResult]) -> tuple[RunStatus, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    optional_failure = False
    for spec in specs:
        result = results.get(spec.name)
        if result is None or result.status in {"error", "empty", "missing", "stale"} or result.record_count < spec.min_records:
            detail = result.error if result and result.error else f"status={result.status if result else 'missing'}, records={result.record_count if result else 0}"
            message = f"{spec.name}: {detail}"
            warnings.append(message)
            optional_failure = True
        elif result.status in {"partial", "degraded"} or result.used_fallback:
            detail = f"{spec.name}: degraded source payload"
            warnings.append(detail)
            optional_failure = True
    if errors:
        return RunStatus.FAILED, errors, warnings
    if optional_failure:
        return RunStatus.DEGRADED, errors, warnings
    return RunStatus.COMPLETE, errors, warnings


def validate_fact_batches(batches: list[FactBatch], sources: dict[str, dict]) -> tuple[RunStatus, list[str], list[str]]:
    """Apply requiredness and fallback policy at the dataset boundary."""
    by_id = {batch.dataset_id: batch for batch in batches}
    errors: list[str] = []
    warnings: list[str] = []
    required = {
        DatasetId.TRADING_CALENDAR,
        DatasetId.MARKET_BREADTH_DAILY,
        DatasetId.MARKET_LIQUIDITY_DAILY,
        DatasetId.LIMIT_EVENT_DAILY,
        DatasetId.MARKET_STATE_DAILY,
    }

    for dataset_id in DatasetId:
        batch = by_id.get(dataset_id)
        available = batch is not None and not batch.frame.is_empty()
        if dataset_id == DatasetId.LIMIT_EVENT_DAILY and not available:
            pywencai = sources.get("pywencai") or {}
            available = any(isinstance(pywencai.get(key), dict) for key in ("limit_up", "broken_board", "limit_down"))
        if dataset_id in required and not available:
            errors.append(f"required dataset unavailable: {dataset_id.value}")
            continue
        if dataset_id not in required and not available:
            warnings.append(f"optional dataset unavailable: {dataset_id.value}")
            continue
        if batch is None or batch.frame.is_empty() or "source" not in batch.frame.columns:
            continue
        present = set(batch.frame["source"].to_list())
        route = get_route(dataset_id).sources
        selected = next((source for source in route if source in present), None)
        if selected is not None and selected != route[0]:
            warnings.append(
                f"{dataset_id.value}: fallback source {selected} used instead of {route[0]}"
            )

    if errors:
        return RunStatus.FAILED, errors, warnings
    if warnings:
        return RunStatus.DEGRADED, errors, warnings
    return RunStatus.COMPLETE, errors, warnings


def validate_artifacts(date_dir: Path) -> list[str]:
    return [name for name in CORE_ARTIFACTS if not (date_dir / name).is_file()]
