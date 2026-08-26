from __future__ import annotations

from pathlib import Path

from .schemas import RunStatus, SourceResult, SourceSpec

CORE_ARTIFACTS = (
    "market_overview.json", "market_breadth.json", "market_liquidity.json",
    "limit_summary.json", "limit_ladder.json", "limit_stocks.json",
    "promotion_stats.json", "premium_stats.json", "theme_snapshot.json",
    "theme_rankings.json", "theme_history.json", "theme_stocks.json", "sentiment_state.json",
    "risk_signals.json", "participation.json", "sector_fund_flow.json",
    "sector_rotation.json", "screening_candidates.json", "trend_history.json",
    "trend_pool.json", "_computed.json",
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
            if spec.required:
                errors.append(message)
            else:
                warnings.append(message)
                optional_failure = True
        elif result.status in {"partial", "degraded"} or result.used_fallback:
            detail = f"{spec.name}: degraded source payload"
            if spec.required:
                errors.append(detail)
            else:
                warnings.append(detail)
                optional_failure = True
    if errors:
        return RunStatus.FAILED, errors, warnings
    if optional_failure:
        return RunStatus.DEGRADED, errors, warnings
    return RunStatus.COMPLETE, errors, warnings


def validate_artifacts(date_dir: Path) -> list[str]:
    return [name for name in CORE_ARTIFACTS if not (date_dir / name).is_file()]
