"""Repository-based AMV research extension."""
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.services.active_market_value import analyze_active_market_value, list_sector_activity

EXTENSION_ID = "tickflow.amv"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
router = APIRouter(prefix="/api/amv", tags=["amv"])
Symbol = Annotated[str, Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")]
Dimension = Literal["concept", "industry_level1", "industry_level2"]


class AmvRequest(BaseModel):
    trade_date: date
    symbols: list[Symbol] = Field(default_factory=list, max_length=1500)
    sector: str = Field(default="", max_length=80)
    dimension: Dimension = "concept"

    @model_validator(mode="after")
    def has_scope(self):
        self.sector = self.sector.strip()
        if not self.symbols and not self.sector:
            raise ValueError("请提供证券或板块名称")
        return self


@router.post("/analyze")
def analyze(payload: AmvRequest, request: Request) -> dict:
    try:
        return analyze_active_market_value(request.app.state.repo, payload.trade_date,
                                           payload.symbols, sector=payload.sector, dimension=payload.dimension)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sectors")
def sectors(request: Request, trade_date: date | None = None, dimension: Dimension = "concept") -> dict:
    try:
        return list_sector_activity(request.app.state.repo, trade_date, dimension=dimension)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(router)
