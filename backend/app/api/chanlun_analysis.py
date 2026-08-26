"""Chan theory analysis API — native integration.

- POST /api/chanlun/analyze  本地流水线 (内置, 无外部依赖)
- GET  /api/chanlun/candles  窗口补全的 OHLCV (本地不足时经 TickFlow 拉取, 不落盘)
- GET  /api/chanlun/official ZenChart 官方图层直连 (可选 Pro token 走环境变量)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Query, Request

from app.chanlun.pipeline import analyze
from app.chanlun.zen import ZenError, fetch_official
from app.services import preferences
from app.services.kline_sync import fetch_daily_selected

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chanlun", tags=["chanlun"])


@router.post("/analyze")
def chanlun_analyze_post(body: dict):
    """对给定 K 线运行本地缠论分析。

    body: {"candles": [{time, open, high, low, close, volume}, ...]}
    time 为当日本地午夜 unix 秒, 与前端 candleTimeOf 约定一致。
    """
    candles = body.get("candles", [])
    if not candles or len(candles) < 10:
        return {"error": "need >= 10 candles"}
    return analyze(candles)


@router.get("/candles")
def chanlun_candles(
    request: Request,
    symbol: str = Query(..., description="标的代码, 如 600460.SH"),
    days: int = Query(500, ge=30, le=800),
):
    """返回窗口尽量补足的日 K OHLCV (供缠论分析与图表共用同一序列)。

    本地 enriched 表优先; 行数不足时经 TickFlow 实时拉取补齐但**不落盘**,
    避免浏览行为污染数据仓库。输出列与前端 toChanlunCandles 对齐。
    """
    import polars as pl

    repo = request.app.state.repo
    end = date.today()
    start = end - timedelta(days=days)
    asset_type = repo.resolve_asset_type(symbol)
    df = repo.get_daily_asset(asset_type, symbol, start, end)
    source = "local"
    provider = "local"
    if df.is_empty() or len(df) < days:
        try:
            raw = fetch_daily_selected([symbol], count=days + 40)
            if not raw.is_empty():
                keep = [c for c in ("date", "open", "high", "low", "close", "volume")
                        if c in raw.columns]
                raw = raw.select(keep).sort("date")
                # 本地已有部分时取并集中较全的一侧 (拉取通常更完整, 直接采用)
                if not raw.is_empty() and len(raw) >= len(df):
                    df = raw
                    source = "live"
                    provider = preferences.get_daily_data_provider()
        except Exception as exc:
            logger.warning("chanlun candles live fallback failed %s: %s", symbol, exc)

    if df.is_empty():
        return {"symbol": symbol, "source": "none", "provider": provider, "rows": []}

    if "volume" not in df.columns:
        df = df.with_columns(pl.lit(0).alias("volume"))
    rows = (
        df.select(["date", "open", "high", "low", "close", "volume"])
        .sort("date")
        .with_columns(pl.col("date").cast(pl.Utf8))
        .to_dicts()
    )
    rows = [r for r in rows if r.get("open") is not None and r.get("close") is not None]
    for r in rows:
        r["date"] = str(r["date"])[:10]
    return {"symbol": symbol, "source": source, "provider": provider, "rows": rows}


@router.get("/official")
def chanlun_official(
    symbol: str = Query(..., description="ZenChart 代码格式, 如 600460"),
    level: str = Query("D1"),
    limit: int = Query(300, ge=50, le=1000),
):
    """ZenChart 官方分析图层 (叠加对比用)。

    配置 TICKFLOW_ZENCHART_TOKEN 时走 Pro 端点 (含官方买卖点),
    否则走免费端点 (bsp 为空)。失败时 available=false, 不抛 5xx。
    """
    try:
        data = fetch_official(symbol, level=level, limit=limit)
        off = data["official"]
        return {
            "available": True,
            "source": data["source"],
            "name": data.get("name"),
            # ZenChart 自带 K 线窗口 —— 官方/叠加模式下前端以此为图表底座,
            # 与原型行为完全一致 (同 K 线同窗口, 层层严格对齐)
            "candles": off.get("candles", []),
            "counts": {
                "bi": len(off.get("bi", [])),
                "segments": len(off.get("segments", [])),
                "zhongshu": len(off.get("zhongshu", [])),
                "bsp": len(off.get("bsp", [])),
            },
            "official": {
                "bi": off.get("bi", []),
                "segments": off.get("segments", []),
                "zhongshu": off.get("zhongshu", []),
                "bsp": off.get("bsp", []),
            },
        }
    except ZenError as exc:
        return {"available": False, "detail": str(exc)}
