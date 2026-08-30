"""Market lab API: ETF momentum, sector flow, macro timing, sizing and simulation."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.services.market_lab import (
    calculate_drawdown,
    calculate_pit,
    calculate_position,
    etf_momentum_from_repo,
    macro_dispersion_from_repo,
    monte_carlo,
    sector_flow_from_repo,
    sector_members_from_repo,
    sector_radar_from_repo,
)

router = APIRouter(prefix="/api/market-lab", tags=["market-lab"])


class PositionIn(BaseModel):
    balance: float = Field(gt=0)
    risk_pct: float = Field(gt=0, le=1)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float | None = Field(default=None, gt=0)
    mode: Literal["brave", "sensitive"] = "brave"
    trade_type: Literal["B1", "B2"] = "B1"


class PitIn(BaseModel):
    top: float = Field(gt=0)
    bottom: float = Field(gt=0)
    current: float = Field(gt=0)


class DrawdownIn(BaseModel):
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    high: float = Field(gt=0)
    target_r: float = Field(default=10, gt=0)
    drawdown_pct: float = Field(default=0.1, gt=0, lt=1)


class SimulationIn(BaseModel):
    balance: float = Field(gt=0)
    win_rate: float = Field(ge=0, le=1)
    win_r: float = Field(gt=0)
    loss_r: float = Field(gt=0)
    risk_pct: float = Field(gt=0, le=1)
    trades: int = Field(ge=1, le=500)
    paths: int = Field(ge=10, le=2_000)
    seed: int = 42
    target_return_pct: float = Field(default=50, ge=0, le=1000)
    max_drawdown_pct: float = Field(default=20, gt=0, lt=100)
    annual_trades: int = Field(default=50, ge=1, le=1000)


@router.get("/etf-momentum")
def etf_momentum(request: Request, limit: int = Query(40, ge=1, le=200)) -> dict:
    return etf_momentum_from_repo(request.app.state.repo, limit=limit)


@router.get("/sector-flow")
def sector_flow(request: Request, dimension: str = Query("industry", pattern="^(industry|concept)$")) -> dict:
    return sector_flow_from_repo(
        request.app.state.repo,
        dimension=dimension,
        fact_repo=getattr(request.app.state, "market_facts", None),
    )


@router.get("/sector-radar")
def sector_radar(
    request: Request,
    dimension: str = Query("industry", pattern="^(industry|concept)$"),
    as_of: date | None = None,
) -> dict:
    return sector_radar_from_repo(
        request.app.state.repo,
        dimension=dimension,
        as_of=as_of,
        fact_repo=getattr(request.app.state, "market_facts", None),
    )


@router.get("/sector-members")
def sector_members(
    request: Request,
    sector: str = Query(min_length=1, max_length=120),
    dimension: str = Query("industry", pattern="^(industry|concept)$"),
    as_of: date | None = None,
    limit: int = Query(10, ge=1, le=30),
) -> dict:
    return sector_members_from_repo(
        request.app.state.repo, dimension=dimension, sector=sector,
        as_of=as_of, limit=limit,
    )


@router.get("/macro-dispersion")
def macro_dispersion(request: Request) -> dict:
    return macro_dispersion_from_repo(request.app.state.repo)


@router.post("/position")
def position(body: PositionIn) -> dict:
    return calculate_position(**body.model_dump())


@router.post("/pit")
def pit(body: PitIn) -> dict:
    return calculate_pit(**body.model_dump())


@router.post("/drawdown")
def drawdown(body: DrawdownIn) -> dict:
    return calculate_drawdown(**body.model_dump())


@router.post("/simulate")
def simulate(body: SimulationIn) -> dict:
    return monte_carlo(**body.model_dump())
