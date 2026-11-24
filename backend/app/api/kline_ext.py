"""图表行情与单股日线补数（本地增强，独立于上游 kline 路由）。

放在独立模块里，`app/api/kline.py` 就不必承载这些端点，上游同步时零冲突。
路径与上游完全一致（prefix 同为 /api/kline），前端无感。
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.market_time import cn_today
from app.services import kline_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kline", tags=["kline-ext"])


def _canonical_chart_symbol(repo, symbol: str) -> str:
    """Resolve a bare A-share code before querying chart storage."""
    normalized = symbol.strip().upper()
    if "." in normalized or not normalized.isdigit() or len(normalized) != 6:
        return normalized
    candidates = [f"{normalized}.SH", f"{normalized}.SZ", f"{normalized}.BJ"]
    matches = list(repo.get_name_map(candidates))
    if len(matches) == 1:
        return matches[0]
    if normalized.startswith(("4", "8", "92")):
        preferred = f"{normalized}.BJ"
    elif normalized.startswith(("5", "6", "9")):
        preferred = f"{normalized}.SH"
    else:
        preferred = f"{normalized}.SZ"
    return preferred if not matches or preferred in matches else matches[0]


@router.get("/chart")
def get_chart_data(
    request: Request,
    symbol: Annotated[str, Query(min_length=1, max_length=32)],
    asset_type: Annotated[str | None, Query(pattern="^(stock|etf|index)$")] = None,
    interval: Annotated[str, Query(pattern="^(1m|5m|15m|30m|60m|1d|1w|1mo)$")] = "1d",
    adjustment: Annotated[str, Query(pattern="^(none|qfq|hfq)$")] = "qfq",
    range_name: Annotated[str, Query(alias="range", pattern="^(1m|3m|6m|1y|3y|5y|all|custom)$")] = "1y",
    start_date: date | None = None,
    end_date: date | None = None,
    layers: Annotated[str | None, Query(description="逗号分隔: pattern,strategy,event,plan")] = None,
    strategy_ids: Annotated[str | None, Query(description="逗号分隔策略 ID")] = None,
    source_run_id: Annotated[str | None, Query(max_length=160)] = None,
    params_fingerprint: Annotated[str | None, Query(max_length=160)] = None,
    warmup_bars: Annotated[int, Query(ge=0, le=2000)] = 160,
    indicator_warmups: Annotated[str | None, Query(max_length=2000)] = None,
    indicator_params: Annotated[str | None, Query(max_length=4096)] = None,
):
    """统一图表行情: 显式周期、复权、范围以及真实覆盖元数据。"""
    from app.services.chart_data import ChartQuery, build_chart_response

    repo = request.app.state.repo
    symbol = _canonical_chart_symbol(repo, symbol)
    resolved_asset_type = asset_type or repo.resolve_asset_type(symbol)
    if asset_type is not None and asset_type != repo.resolve_asset_type(symbol):
        raise HTTPException(status_code=422, detail="asset_type 与本地标的类型不一致")
    try:
        parsed_indicator_params = json.loads(indicator_params) if indicator_params else {}
        layer_categories = {item.strip() for item in (layers or "").split(",") if item.strip()}
        unknown_layers = layer_categories - {"pattern", "strategy", "event", "plan"}
        if unknown_layers:
            raise ValueError(f"未知图层分类: {sorted(unknown_layers)}")
        selected_strategies = tuple(dict.fromkeys(item.strip() for item in (strategy_ids or "").split(",") if item.strip()))
        if len(selected_strategies) > 32:
            raise ValueError("strategy_ids 最多 32 个")
        parsed_indicator_warmups: list[tuple[str, int]] = []
        for raw_item in (indicator_warmups or "").split(","):
            if not raw_item.strip():
                continue
            indicator_id, separator, raw_bars = raw_item.strip().rpartition(":")
            if not separator or not indicator_id or len(indicator_id) > 80 or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for character in indicator_id
            ):
                raise ValueError(f"无效指标预热声明: {raw_item}")
            bars = int(raw_bars)
            if bars < 0 or bars > 2000:
                raise ValueError(f"指标预热超出范围: {raw_item}")
            parsed_indicator_warmups.append((indicator_id, bars))
        if len(parsed_indicator_warmups) > 80:
            raise ValueError("indicator_warmups 最多 80 项")
        return build_chart_response(
            repo,
            ChartQuery(
                symbol=symbol,
                asset_type=resolved_asset_type,
                interval=interval,
                adjustment=adjustment,
                range_name=range_name,
                start_date=start_date,
                end_date=end_date or cn_today(),
                required_warmup_bars=warmup_bars,
                indicator_warmups=tuple(dict(parsed_indicator_warmups).items()),
                indicator_params=parsed_indicator_params,
            ),
            data_dir=repo.store.data_dir,
            layer_categories=layer_categories,
            strategy_ids=selected_strategies,
            source_run_id=source_run_id,
            params_fingerprint=params_fingerprint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sync_daily_single")
async def sync_daily_single(request: Request):
    """按明确起止日期补齐当前单股日线, 不触发全市场历史任务。"""
    from datetime import datetime, time

    from app.api.data import invalidate_storage_cache
    from app.tickflow.capabilities import Cap

    body = await request.json()
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol 不能为空")
    try:
        start = date.fromisoformat(str(body.get("start_date") or ""))
        end = date.fromisoformat(str(body.get("end_date") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="start_date/end_date 必须为 YYYY-MM-DD") from exc
    if start > end:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")

    repo = request.app.state.repo
    capset = request.app.state.capabilities
    asset_type = repo.resolve_asset_type(symbol)
    if asset_type == "index":
        raise HTTPException(status_code=422, detail="指数历史请使用指数同步能力")
    start_time = datetime.combine(start, time.min)
    end_time = datetime.combine(end, time.max)
    # A long-range chart commonly already has the recent tail. Re-fetching the
    # whole range would then rewrite hundreds of existing daily partitions.
    # Only fill the uncovered prefix/suffix; factors still refresh across the
    # full requested range below because their coverage is independent.
    missing_ranges = [(start, end)]
    get_existing = getattr(repo, "get_raw_daily_asset", None)
    if callable(get_existing):
        try:
            existing = get_existing(asset_type, symbol, start, end)
            if existing is not None and not existing.is_empty() and "date" in existing.columns:
                coverage_start = existing["date"].min()
                coverage_end = existing["date"].max()
                if isinstance(coverage_start, datetime):
                    coverage_start = coverage_start.date()
                if isinstance(coverage_end, datetime):
                    coverage_end = coverage_end.date()
                if not isinstance(coverage_start, date):
                    coverage_start = date.fromisoformat(str(coverage_start)[:10])
                if not isinstance(coverage_end, date):
                    coverage_end = date.fromisoformat(str(coverage_end)[:10])
                missing_ranges = []
                if coverage_start > start:
                    missing_ranges.append((start, coverage_start - timedelta(days=1)))
                if coverage_end < end:
                    missing_ranges.append((coverage_end + timedelta(days=1), end))
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("single daily coverage probe failed for %s: %s", symbol, exc)

    rows = 0
    for missing_start, missing_end in missing_ranges:
        rows += kline_sync.sync_and_persist_daily_batch(
            [symbol], repo, capset,
            start_date=datetime.combine(missing_start, time.min),
            end_date=datetime.combine(missing_end, time.max),
        )
    factor_rows = 0
    warning = None
    if capset.has(Cap.ADJ_FACTOR):
        try:
            factor_rows, _ = kline_sync.sync_adj_factor(
                [symbol], repo, capset,
                start_time=start_time, end_time=end_time, asset_type=asset_type,
            )
        except Exception as exc:
            logger.warning("single daily adjustment sync failed for %s: %s", symbol, exc)
            warning = f"日线已写入, 但复权因子补齐失败: {exc}"
    invalidate_storage_cache()
    return {
        "status": "ok", "symbol": symbol, "asset_type": asset_type,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "rows": rows, "factor_rows": factor_rows, "warning": warning,
    }
