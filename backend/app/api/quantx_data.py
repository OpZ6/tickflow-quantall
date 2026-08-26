from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.quantx_data.catalog import build_catalog, load_artifact, load_tables
from app.quantx_data.multiday import (
    load_multiday_snapshot,
    rebuild_multiday_snapshot,
    rebuild_multiday_snapshots,
)
from app.quantx_data.pipeline import get_status, run_pipeline

router = APIRouter(prefix="/api/quantx-data", tags=["quantx-data"])


def _root(request: Request) -> Path:
    return Path(request.app.state.repo.store.data_dir) / "quantx"


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


@router.get("/{trade_date}/tables")
def tables(trade_date: str, request: Request) -> dict:
    try:
        return load_tables(_root(request), trade_date)
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
