from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.stock_pools.evolution import build_evolution, candidate_history
from app.stock_pools.publisher import publish_stock_pool
from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.review import build_review

router = APIRouter(prefix="/api/stock-pools", tags=["stock-pools"])


def _repository(request: Request) -> StockPoolRepository:
    return StockPoolRepository(request.app.state.repo.store.data_dir)


def _day(value: str) -> date:
    text = value.replace("-", "")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date must use YYYYMMDD or YYYY-MM-DD") from exc


class StockPoolRunRequest(BaseModel):
    trade_date: str | None = None


@router.get("")
def catalog(request: Request) -> dict:
    repo = _repository(request)
    dates = repo.list_dates()
    return {"dates": dates, "latest_date": dates[-1] if dates else None}


@router.get("/{trade_date}")
def summary(trade_date: str, request: Request) -> dict:
    repo = _repository(request)
    payload = repo.get_summary(_day(trade_date))
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no stock-pool snapshot for {trade_date}")
    manifest = repo.get_manifest(_day(trade_date)) or {}
    return {**payload, "published_at": manifest.get("published_at"),
            "first_published_available": repo.first_date_dir(_day(trade_date)).is_dir()}


@router.get("/{trade_date}/candidates")
def candidates(
    trade_date: str,
    request: Request,
    source: Annotated[list[str] | None, Query()] = None,
    stage: Annotated[list[str] | None, Query()] = None,
    topic: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
    change: Annotated[list[str] | None, Query()] = None,
    q: str = "",
) -> dict:
    rows = _repository(request).get_candidates(_day(trade_date))
    if rows is None:
        raise HTTPException(status_code=404, detail=f"no stock-pool candidates for {trade_date}")
    sources, stages, topics, tiers, changes = map(set, (source or [], stage or [], topic or [], tier or [], change or []))
    needle = q.strip().lower()
    filtered = []
    for row in rows:
        if sources and not sources.intersection(row.get("source_ids", [])):
            continue
        if stages and row.get("primary_stage") not in stages:
            continue
        if topics and not topics.intersection(row.get("topics", [])):
            continue
        if tiers and row.get("tier") not in tiers:
            continue
        if changes and not changes.intersection(row.get("change_types", [])):
            continue
        if needle and needle not in f"{row.get('symbol', '')} {row.get('name', '')}".lower():
            continue
        filtered.append(row)
    return {"trade_date": _day(trade_date).isoformat(), "total": len(filtered), "rows": filtered}


@router.get("/{trade_date}/evolution")
def evolution(
    trade_date: str, request: Request,
    mode: Literal["hot", "low"] = "hot",
    topic: Annotated[str, Query(max_length=80)] = "",
    window: Annotated[int, Query(ge=2, le=30)] = 10,
) -> dict:
    payload = build_evolution(_repository(request), _day(trade_date), mode, topic.strip(), window)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no stock-pool snapshot for {trade_date}")
    return payload


@router.get("/{trade_date}/review")
def review(
    trade_date: str, request: Request,
    window: Annotated[int, Query(ge=2, le=30)] = 20,
    horizon: Annotated[int, Query(ge=1, le=5)] = 3,
    cost_bps: Annotated[int, Query(ge=0, le=100)] = 0,
) -> dict:
    if horizon not in (1, 3, 5):
        raise HTTPException(status_code=422, detail="horizon must be 1, 3 or 5")
    payload = build_review(_repository(request), request.app.state.repo, _day(trade_date), window, horizon, cost_bps)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no stock-pool snapshot for {trade_date}")
    return payload


@router.get("/{trade_date}/candidates/{symbol}")
def candidate_detail(trade_date: str, symbol: str, request: Request,
                     snapshot: Literal["current", "first"] = "current") -> dict:
    repo = _repository(request)
    details = repo.get_first_details(_day(trade_date)) if snapshot == "first" else repo.get_details(_day(trade_date))
    if details is None:
        raise HTTPException(status_code=404, detail=f"no stock-pool details for {trade_date}")
    normalized = symbol.upper()
    item = details.get(normalized)
    if item is None and "." not in normalized:
        item = next((value for key, value in details.items() if key.split(".")[0] == normalized), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not a candidate on {trade_date}")
    return item


@router.get("/{trade_date}/candidates/{symbol}/history")
def history(
    trade_date: str, symbol: str, request: Request,
    window: Annotated[int, Query(ge=2, le=30)] = 10,
) -> dict:
    payload = candidate_history(_repository(request), _day(trade_date), symbol, window)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not a candidate on {trade_date}")
    return payload


@router.post("/runs")
def run(payload: StockPoolRunRequest, request: Request) -> dict:
    repo = request.app.state.repo
    trade_date = _day(payload.trade_date) if payload.trade_date else repo.latest_enriched_date("stock")
    if trade_date is None:
        raise HTTPException(status_code=409, detail="no enriched trading date available")
    try:
        return publish_stock_pool(repo, trade_date)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
