"""QuantX 情绪+复盘 API — 情绪状态查询/计算 + review V4 报告 + 多日驾驶舱。

数据目录: data/quantx/YYYYMMDD/
  _computed.json — 情绪算法产出
  review.html — review V4 draft
  catalog.json — 多日驾驶舱
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.services.emotion_state import compute as compute_emotion
from app.services.market_catalog import build_and_save_catalog
from app.services.review_v4 import build_review_html

router = APIRouter(prefix="/api/quantx", tags=["quantx"])


def _quantx_dir(request: Request) -> Path:
    data_dir = Path(request.app.state.repo.store.data_dir)
    return data_dir / "quantx"


def _date_dir(request: Request, trade_date: str) -> Path:
    d = _quantx_dir(request) / trade_date
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"no data for {trade_date}")
    return d


# ---- 情绪状态 ----

@router.get("/emotion/{trade_date}")
def get_emotion(trade_date: str, request: Request):
    d = _date_dir(request, trade_date)
    computed_path = d / "_computed.json"
    if not computed_path.exists():
        raise HTTPException(status_code=404, detail=f"no _computed.json for {trade_date}")
    import json
    return json.loads(computed_path.read_text(encoding="utf-8"))


@router.post("/emotion/{trade_date}/compute")
def compute_emotion_state(trade_date: str, request: Request):
    d = _date_dir(request, trade_date)
    result = compute_emotion(d, _quantx_dir(request))
    return result


# ---- review V4 ----


@router.get("/review/schema/v2")
def get_review_v2_schema():
    from app.quantx_data.review_contract import review_v2_contract_manifest
    from app.quantx_data.review_schema import QuantXReviewResponseV2

    return {
        "schema": QuantXReviewResponseV2.model_json_schema(),
        "field_contracts": review_v2_contract_manifest(),
    }

@router.get("/review/{trade_date}", response_class=HTMLResponse)
def get_review(trade_date: str, request: Request):
    d = _date_dir(request, trade_date)
    review_path = d / "review.html"
    if not review_path.exists():
        raise HTTPException(status_code=404, detail=f"no review.html for {trade_date}")
    return HTMLResponse(content=review_path.read_text(encoding="utf-8"))


@router.post("/review/{trade_date}/build")
def build_review(trade_date: str, request: Request):
    d = _date_dir(request, trade_date)
    computed_path = d / "_computed.json"
    if not computed_path.exists():
        compute_emotion(d, _quantx_dir(request))
    html = build_review_html(d)
    return {"status": "ok", "trade_date": trade_date, "bytes": len(html)}


@router.get("/review/{trade_date}/data")
def get_review_data(
    trade_date: str,
    request: Request,
    view_version: Literal["v2"] = "v2",
):
    _date_dir(request, trade_date)
    from app.quantx_data.review_repository import QuantXReviewRepository

    snapshot = QuantXReviewRepository(
        _quantx_dir(request),
        request.app.state.market_facts,
        request.app.state.repo,
    ).load(trade_date, view_version=view_version)
    return snapshot


# ---- 多日驾驶舱 ----

@router.get("/catalog")
def get_catalog(request: Request):
    quantx_dir = _quantx_dir(request)
    catalog_path = quantx_dir / "catalog.json"
    if not catalog_path.exists():
        raise HTTPException(status_code=404, detail="no catalog.json; run POST /api/quantx/catalog/build")
    import json
    return json.loads(catalog_path.read_text(encoding="utf-8"))


@router.post("/catalog/build")
def build_catalog(request: Request):
    quantx_dir = _quantx_dir(request)
    if not quantx_dir.exists():
        raise HTTPException(status_code=404, detail="quantx dir not found")
    catalog, _html = build_and_save_catalog(quantx_dir)
    return {
        "status": "ok",
        "total_dates": catalog["stats"]["total_dates"],
        "complete": catalog["stats"]["complete"],
    }


@router.get("/catalog/html", response_class=HTMLResponse)
def get_catalog_html(request: Request):
    quantx_dir = _quantx_dir(request)
    html_path = quantx_dir / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="no index.html; run POST /api/quantx/catalog/build")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
