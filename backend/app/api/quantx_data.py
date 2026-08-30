from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.quantx_data.advanced import build_advanced_snapshot
from app.quantx_data.catalog import build_catalog, load_artifact
from app.quantx_data.io import read_json
from app.quantx_data.multiday import (
    load_multiday_snapshot,
    rebuild_multiday_snapshot,
    rebuild_multiday_snapshots,
)
from app.quantx_data.new_high_clusters import build_new_high_cluster_members
from app.quantx_data.pipeline import get_status, run_pipeline
from app.quantx_data.repository import QuantXTableRepository

router = APIRouter(prefix="/api/quantx-data", tags=["quantx-data"])


def _root(request: Request) -> Path:
    return Path(request.app.state.repo.store.data_dir) / "quantx"


@router.get("/observability/{trade_date}")
def observability(
    trade_date: str,
    request: Request,
    pipeline_job_id: str | None = None,
) -> dict:
    """Return one publication's lineage, quality and refresh-control state."""
    from app.market_facts.audit import audit_quantx_data_foundation
    from app.quantx_data.collectors import SOURCE_MANAGER, SOURCE_SPECS
    from app.quantx_data.review_repository import QuantXReviewRepository

    try:
        day = datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="trade_date must use YYYYMMDD") from exc
    date_dir = _root(request) / trade_date
    status = read_json(date_dir / "_pipeline_status.json", {})
    manifest = read_json(date_dir / "_data_manifest.json", {})
    if not isinstance(status, dict) or not status:
        raise HTTPException(status_code=404, detail=f"no quantx data run for {trade_date}")
    if not isinstance(manifest, dict):
        manifest = {}

    source_states = status.get("sources") if isinstance(status.get("sources"), dict) else {}
    sources = []
    for spec in SOURCE_SPECS:
        state = source_states.get(spec.name) if isinstance(source_states.get(spec.name), dict) else {}
        metadata = SOURCE_MANAGER.describe(spec.name)
        sources.append(
            {
                **metadata,
                "required": spec.required,
                "status": state.get("status", "missing"),
                "freshness": "reused" if state.get("reused_snapshot") else "fresh",
                "record_count": state.get("record_count", 0),
                "collected_at": state.get("collected_at"),
                "input_path": state.get("input_path"),
                "error": state.get("error"),
                "error_kind": state.get("error_kind"),
                "attempts": state.get("attempts", 0),
                "raw_sha256": state.get("raw_sha256"),
                "manifest_health": "present" if state else "missing",
            }
        )

    fact_audit = audit_quantx_data_foundation(
        _root(request).parent,
        dates=[day],
    )
    checks = fact_audit.get("checks", [])
    artifacts = {
        item.get("dataset_id"): item
        for item in manifest.get("fact_artifacts", [])
        if isinstance(item, dict)
    }
    facts = []
    for check in checks:
        artifact = artifacts.get(check["dataset_id"], {})
        quality_counts = check.get("quality_counts", [])
        facts.append(
            {
                **check,
                "coverage": 1.0 if check.get("status") == "present" else 0.0,
                "quality_level": ", ".join(
                    f"{item['quality_level']}:{item['rows']}" for item in quality_counts
                ) or "missing",
                "bytes": artifact.get("bytes"),
                "sha256": artifact.get("sha256"),
            }
        )

    review = QuantXReviewRepository(
        _root(request),
        request.app.state.market_facts,
        request.app.state.repo if hasattr(request.app.state.repo, "get_index_daily") else None,
    ).load(trade_date)
    catalog_data = build_catalog(_root(request))
    catalog_record = next(
        (item for item in catalog_data.get("records", []) if item.get("trade_date") == trade_date),
        None,
    )
    multiday_data = read_json(date_dir / "multiday_snapshot.json", {})
    foundation = review.get("data_foundation", {}) if isinstance(review, dict) else {}
    metric_counts = {
        "field_drift": sum(1 for item in facts if item.get("status") == "schema_mismatch"),
        "stale_snapshot": sum(1 for item in sources if item["status"] == "stale"),
        "empty_result": sum(1 for item in sources if item["status"] == "empty"),
        "rate_limit": sum(1 for item in sources if item["error_kind"] == "rate_limit"),
    }
    gap_count = fact_audit.get("summary", {}).get("gap_partition_count", 0)
    return {
        "trade_date": trade_date,
        "pipeline_job_id": pipeline_job_id,
        "quantx_run_id": status.get("run_id"),
        "status": status.get("status"),
        "published_at": manifest.get("generated_at") or status.get("updated_at"),
        "sources": sources,
        "facts": facts,
        "fact_summary": fact_audit.get("summary", {}),
        "view": {
            "schema_version": foundation.get("schema_version"),
            "canonical_count": len(foundation.get("canonical_fields", [])),
            "derived_count": len(foundation.get("derived_fields", [])),
            "cache_count": len(foundation.get("presentation_cache_fields", [])),
            "fallback_count": len(foundation.get("fallback_fields", [])),
            "implicit_cache_count": len(foundation.get("implicit_cache_fields", [])),
        },
        "reconciliation": {
            "status": "ok" if not gap_count else "gaps",
            "gap_count": gap_count,
            "fingerprint": fact_audit.get("fact_fingerprint", {}).get("sha256"),
        },
        "multiday": {
            "published": bool(multiday_data),
            "schema_version": multiday_data.get("schema_version") if isinstance(multiday_data, dict) else None,
            "generated_at": multiday_data.get("generated_at") if isinstance(multiday_data, dict) else None,
        },
        "catalog": {
            "published": catalog_record is not None,
            "stage": catalog_record.get("stage") if catalog_record else None,
            "generated_at": catalog_data.get("generated_at"),
        },
        "metrics": metric_counts,
        "warnings": status.get("warnings", []),
        "errors": status.get("errors", []),
        "refreshed_at": datetime.now(UTC).isoformat(),
    }


class RunRequest(BaseModel):
    trade_date: str = Field(pattern=r"^\d{8}$")
    sources: list[str] | None = None
    force: bool = False
    recompute: bool = False


def _run(
    request: Request,
    trade_date: str,
    *,
    sources: list[str] | None = None,
    retry_sources: list[str] | None = None,
    force: bool = False,
    recompute: bool = False,
) -> dict:
    try:
        return run_pipeline(
            _root(request).parent,
            trade_date,
            selected_sources=sources,
            retry_sources=retry_sources,
            force=force,
            recompute=recompute,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs")
def create_run(body: RunRequest, request: Request) -> dict:
    return _run(request, body.trade_date, sources=body.sources, force=body.force, recompute=body.recompute)


@router.get("/runs/{trade_date}")
def run_status(trade_date: str, request: Request) -> dict:
    status = get_status(_root(request).parent, trade_date)
    if status is None:
        raise HTTPException(status_code=404, detail=f"no quantx data run for {trade_date}")
    return status


@router.post("/runs/{trade_date}/resume")
def resume_run(trade_date: str, request: Request) -> dict:
    return _run(request, trade_date)


@router.post("/runs/{trade_date}/recompute")
def recompute_run(trade_date: str, request: Request) -> dict:
    return _run(request, trade_date, recompute=True)


@router.post("/runs/{trade_date}/sources/{source}/retry")
def retry_source(trade_date: str, source: str, request: Request) -> dict:
    return _run(request, trade_date, retry_sources=[source])


@router.get("/catalog")
def catalog(request: Request) -> dict:
    return build_catalog(_root(request))


@router.post("/catalog/rebuild")
def rebuild_catalog(request: Request, trade_date: str | None = None, all_dates: bool = False) -> dict:
    try:
        return rebuild_multiday_snapshots(_root(request)) if all_dates else rebuild_multiday_snapshot(_root(request), trade_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dates")
def dates(request: Request) -> dict:
    data = build_catalog(_root(request))
    return {"dates": [item["trade_date"] for item in data["records"]], "stats": data["stats"]}


@router.get("/multiday/{trade_date}")
def multiday(trade_date: str, request: Request) -> dict:
    try:
        return load_multiday_snapshot(_root(request), trade_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no multiday data for {trade_date}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/advanced/{trade_date}")
def advanced(trade_date: str, request: Request) -> dict:
    """Return all data-backed advanced QuantX charts in one batch."""
    try:
        day = datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="trade_date must use YYYYMMDD") from exc
    return build_advanced_snapshot(
        _root(request).parent,
        day,
        request.app.state.repo,
    )


@router.get("/new-high/{trade_date}/members")
def new_high_cluster_members(
    trade_date: str,
    request: Request,
    dimension: Literal["concept", "industry_level1", "industry_level2"],
    window: int,
    name: str,
) -> dict:
    """Return stock-level evidence for one new-high cluster on demand."""
    try:
        day = datetime.strptime(trade_date, "%Y%m%d").date()
        return build_new_high_cluster_members(
            request.app.state.market_facts,
            day,
            dimension=dimension,
            window=window,
            name=name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{trade_date}/tables")
def tables(trade_date: str, request: Request) -> dict:
    try:
        facts = getattr(request.app.state, "market_facts", None)
        if facts is None:
            from app.market_facts.repository import MarketFactRepository

            facts = MarketFactRepository(_root(request).parent)
        return QuantXTableRepository(_root(request), facts).load(trade_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no structured data for {trade_date}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{trade_date}/overview")
def overview(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "market_overview", "market_breadth", "market_liquidity", "quality")}


@router.get("/{trade_date}/limit-ladder")
def limit_ladder(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "limit_summary", "limit_ladder", "limit_stocks", "promotion_stats", "premium_stats")}


@router.get("/{trade_date}/themes")
def themes(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "theme_snapshot", "theme_rankings", "theme_history", "theme_stocks", "trend_pool")}


@router.get("/{trade_date}/sentiment")
def sentiment(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "sentiment_state", "risk_signals", "participation", "_computed")}


@router.get("/{trade_date}/fund-flow")
def fund_flow(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "sector_fund_flow", "sector_rotation")}


@router.get("/{trade_date}/candidates")
def candidates(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "screening_candidates")}


@router.get("/{trade_date}/quality")
def quality(trade_date: str, request: Request) -> dict:
    data = tables(trade_date, request)
    return {key: data.get(key) for key in ("trade_date", "quality", "manifest")}


@router.get("/{trade_date}/{artifact}")
def artifact(trade_date: str, artifact: str, request: Request) -> dict:
    try:
        return load_artifact(_root(request), trade_date, artifact)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown artifact: {artifact}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"artifact not found: {artifact}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
