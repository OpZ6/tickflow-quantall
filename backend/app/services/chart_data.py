"""统一 K 线图表数据服务。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from typing import Literal

import polars as pl

from app.indicators.levels import compute_levels
from app.indicators.pipeline import _apply_adj_factor, compute_indicators

ChartInterval = Literal["1m", "5m", "15m", "30m", "60m", "1d", "1w", "1mo"]
ChartAdjustment = Literal["none", "qfq", "hfq"]
ChartRange = Literal["1m", "3m", "6m", "1y", "3y", "5y", "all", "custom"]

_RANGE_DAYS: dict[str, int] = {
    "1m": 31,
    "3m": 93,
    "6m": 186,
    "1y": 366,
    "3y": 1096,
    "5y": 1827,
}
_MINUTE_INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
_WARMUP_CALENDAR_DAYS: dict[str, int] = {
    "1m": 45,
    "5m": 45,
    "15m": 60,
    "30m": 90,
    "60m": 120,
    "1d": 400,
    "1w": 1_200,
    "1mo": 3_000,
}
_MIN_WARMUP_BARS = 160


@dataclass(frozen=True)
class ChartQuery:
    symbol: str
    asset_type: str
    interval: ChartInterval
    adjustment: ChartAdjustment
    range_name: ChartRange
    start_date: date | None
    end_date: date


def resolve_date_range(query: ChartQuery, earliest: date | None = None) -> tuple[date, date]:
    if query.start_date is not None:
        if query.start_date > query.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        return query.start_date, query.end_date
    if query.range_name == "custom":
        raise ValueError("range=custom 时必须提供 start_date")
    if query.range_name == "all":
        return earliest or date(1990, 1, 1), query.end_date
    return query.end_date - timedelta(days=_RANGE_DAYS[query.range_name]), query.end_date


def apply_adjustment(
    rows: pl.DataFrame,
    factors: pl.DataFrame,
    adjustment: ChartAdjustment,
) -> pl.DataFrame:
    """从原始日 K 生成 none/qfq/hfq, 成交量和成交额保持原口径。"""
    if rows.is_empty() or adjustment == "none" or factors.is_empty():
        return rows
    normalized = factors.with_columns(
        pl.col("trade_date").cast(pl.Date, strict=False),
        pl.col("ex_factor").cast(pl.Float64, strict=False),
    ).drop_nulls(["trade_date", "ex_factor"])
    if adjustment == "qfq":
        return _apply_adj_factor(rows, normalized)

    cumulative = (
        normalized.unique(["symbol", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
        .with_columns(pl.col("ex_factor").cum_prod().over("symbol").alias("_cum_factor"))
    )
    adjusted = rows.sort(["symbol", "date"]).join_asof(
        cumulative.select("symbol", "trade_date", "_cum_factor"),
        left_on="date",
        right_on="trade_date",
        by="symbol",
        strategy="backward",
    )
    price_columns = [column for column in ("open", "high", "low", "close") if column in adjusted.columns]
    return adjusted.with_columns(
        [pl.col(column) * pl.col("_cum_factor").fill_null(1.0) for column in price_columns]
    ).drop([column for column in ("trade_date", "_cum_factor") if column in adjusted.columns])


def aggregate_daily(rows: pl.DataFrame, interval: ChartInterval) -> pl.DataFrame:
    if rows.is_empty() or interval == "1d":
        return rows
    if interval not in {"1w", "1mo"}:
        raise ValueError(f"不支持的日线聚合周期: {interval}")
    period = "1w" if interval == "1w" else "1mo"
    aggregations = [
        pl.col("symbol").first().alias("symbol"),
        pl.col("open").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"),
    ]
    for column in ("volume", "amount"):
        if column in rows.columns:
            aggregations.append(pl.col(column).sum().alias(column))
    for column in ("signal_limit_up", "signal_broken_limit_up"):
        if column in rows.columns:
            aggregations.append(pl.col(column).fill_null(False).any().alias(column))
    return (
        rows.sort("date")
        .group_by_dynamic("date", every=period, period=period, closed="left", label="right")
        .agg(aggregations)
        .with_columns(
            pl.when(pl.col("date") > rows["date"].max())
            .then(pl.lit(rows["date"].max()))
            .otherwise(pl.col("date"))
            .alias("date")
        )
        .sort("date")
    )


def _minute_bucket(value: datetime, interval_minutes: int) -> datetime | None:
    current = value.time().replace(tzinfo=None)
    if time(9, 30) <= current <= time(11, 30):
        anchor = value.replace(hour=9, minute=30, second=0, microsecond=0)
    elif time(13, 0) <= current <= time(15, 0):
        anchor = value.replace(hour=13, minute=0, second=0, microsecond=0)
    else:
        return None
    elapsed = int((value - anchor).total_seconds() // 60)
    bucket = max(0, elapsed // interval_minutes)
    return anchor + timedelta(minutes=bucket * interval_minutes)


def aggregate_minute(rows: pl.DataFrame, interval: ChartInterval) -> pl.DataFrame:
    if rows.is_empty():
        return rows
    minutes = _MINUTE_INTERVALS[interval]
    if minutes == 1:
        return rows.sort("datetime")
    materialized = []
    for row in rows.sort("datetime").iter_rows(named=True):
        bucket = _minute_bucket(row["datetime"], minutes)
        if bucket is not None:
            materialized.append({**row, "_bucket": bucket})
    if not materialized:
        return pl.DataFrame()
    framed = pl.DataFrame(materialized)
    aggregations = [
        pl.col("symbol").first().alias("symbol"),
        pl.col("open").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"),
    ]
    for column in ("volume", "amount"):
        if column in framed.columns:
            aggregations.append(pl.col(column).sum().alias(column))
    return framed.group_by("_bucket", maintain_order=True).agg(aggregations).rename({"_bucket": "datetime"}).sort("datetime")


def _factor_ratio_by_date(
    dates: list[date],
    symbol: str,
    factors: pl.DataFrame,
    adjustment: ChartAdjustment,
) -> dict[date, float]:
    if adjustment == "qfq" or factors.is_empty():
        return {day: 1.0 for day in dates}
    synthetic = pl.DataFrame({
        "symbol": [symbol] * len(dates),
        "date": dates,
        "open": [1.0] * len(dates),
        "high": [1.0] * len(dates),
        "low": [1.0] * len(dates),
        "close": [1.0] * len(dates),
    })
    # 分钟仓库是 qfq: 目标 none/hfq 相对 qfq 的倍率由日因子唯一确定。
    qfq = apply_adjustment(synthetic, factors, "qfq")["close"].to_list()
    target = apply_adjustment(synthetic, factors, adjustment)["close"].to_list()
    return {day: float(target_value / qfq_value) for day, qfq_value, target_value in zip(dates, qfq, target, strict=True)}


def adjust_minute(
    rows: pl.DataFrame,
    symbol: str,
    factors: pl.DataFrame,
    adjustment: ChartAdjustment,
) -> pl.DataFrame:
    if rows.is_empty() or adjustment == "qfq":
        return rows
    dates = sorted(set(rows["datetime"].dt.date().to_list()))
    ratios = _factor_ratio_by_date(dates, symbol, factors, adjustment)
    ratio_frame = pl.DataFrame({"_date": dates, "_ratio": [ratios[day] for day in dates]})
    adjusted = rows.with_columns(pl.col("datetime").dt.date().alias("_date")).join(ratio_frame, on="_date", how="left")
    price_columns = [column for column in ("open", "high", "low", "close") if column in adjusted.columns]
    return adjusted.with_columns(
        [pl.col(column) * pl.col("_ratio").fill_null(1.0) for column in price_columns]
    ).drop("_date", "_ratio")


def _chart_input_fingerprint(rows: list[dict]) -> str:
    payload = [
        {key: row.get(key) for key in ("date", "open", "high", "low", "close", "volume")}
        for row in rows
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def build_chart_response(
    repo,
    query: ChartQuery,
    *,
    data_dir: Path | None = None,
    layer_categories: set[str] | None = None,
    strategy_ids: tuple[str, ...] = (),
    source_run_id: str | None = None,
    params_fingerprint: str | None = None,
) -> dict:
    earliest = repo.earliest_daily_date()
    start, end = resolve_date_range(query, earliest)
    # 指标必须先在展示区间之前预热, 再裁剪; 否则范围起点处的 MA/MACD/RSI
    # 会被错误地当成一段全新序列。all 仍从权威最早日期开始。
    fetch_start = start if query.range_name == "all" else start - timedelta(days=_WARMUP_CALENDAR_DAYS[query.interval])
    warnings: list[str] = []
    effective_adjustment: ChartAdjustment = query.adjustment
    warmup_bars = 0
    if query.asset_type == "index" and query.adjustment != "none":
        effective_adjustment = "none"
        warnings.append("指数不适用复权, 已使用不复权价格")

    factors = repo.get_adjustment_factors(query.asset_type, query.symbol)
    if query.interval in _MINUTE_INTERVALS:
        if query.asset_type == "index":
            rows = pl.DataFrame()
            warnings.append("当前本地分钟仓库不提供指数分钟线")
        else:
            rows = repo.get_minute_range([query.symbol], fetch_start, end, asset_type=query.asset_type)
            rows = adjust_minute(rows, query.symbol, factors, effective_adjustment)
            rows = aggregate_minute(rows, query.interval)
            if not rows.is_empty():
                rows = compute_indicators(rows.rename({"datetime": "date"})).rename({"date": "datetime"})
                warmup_bars = rows.filter(pl.col("datetime").dt.date() < start).height
                rows = rows.filter(pl.col("datetime").dt.date().is_between(start, end))
        time_column = "datetime"
        source = "local_minute"
    else:
        rows = repo.get_raw_daily_asset(query.asset_type, query.symbol, fetch_start, end)
        if rows.is_empty():
            # 历史安装可能只有 enriched; 保持可读并明确降级来源。
            rows = repo.get_daily_asset(query.asset_type, query.symbol, fetch_start, end)
            source = "local_enriched_fallback"
            if effective_adjustment != "qfq" and query.asset_type != "index":
                warnings.append("原始日线缺失, 当前只能使用已有前复权历史")
                effective_adjustment = "qfq"
        else:
            rows = apply_adjustment(rows, factors, effective_adjustment)
            source = "local_daily"
            # 涨停/炸板是日期事件, 从既有 enriched 事实附加到同一组最终 candles;
            # 价格、价位和结构计算仍只使用上面的显式复权原始 OHLCV.
            events = repo.get_daily_asset(
                query.asset_type,
                query.symbol,
                fetch_start,
                end,
                columns=["date", "signal_limit_up", "signal_broken_limit_up"],
            )
            event_columns = [
                column for column in ("signal_limit_up", "signal_broken_limit_up") if column in events.columns
            ]
            if not events.is_empty() and "date" in events.columns and event_columns:
                rows = rows.join(events.select("date", *event_columns).unique("date"), on="date", how="left")
        rows = aggregate_daily(rows, query.interval)
        if not rows.is_empty():
            rows = compute_indicators(rows)
            warmup_bars = rows.filter(pl.col("date") < start).height
            rows = rows.filter(pl.col("date").is_between(start, end))
        time_column = "date"

    warmup_complete = query.range_name == "all" or warmup_bars >= _MIN_WARMUP_BARS
    if not warmup_complete:
        warnings.append(f"指标预热数据不足: 需要至少 {_MIN_WARMUP_BARS} 根, 实际 {warmup_bars} 根; 区间起点部分指标为空")

    coverage_start = None
    coverage_end = None
    if not rows.is_empty():
        series_dates = rows[time_column].dt.date().to_list() if time_column == "datetime" else rows[time_column].to_list()
        coverage_start = min(series_dates)
        coverage_end = max(series_dates)
    complete = bool(
        coverage_start is not None
        and coverage_end is not None
        and coverage_start <= start + timedelta(days=7)
        and coverage_end >= end - timedelta(days=7)
    )
    if not complete:
        actual = f"{coverage_start or '无'}—{coverage_end or '无'}"
        warnings.append(f"本地数据未完整覆盖请求区间, 实际覆盖 {actual}")

    level_rows = rows.rename({"datetime": "date"}) if time_column == "datetime" and not rows.is_empty() else rows
    levels = compute_levels(level_rows)

    if time_column == "datetime" and not rows.is_empty():
        rows = rows.with_columns(pl.col("datetime").dt.strftime("%Y-%m-%dT%H:%M:%S").alias("date")).drop("datetime")
    elif not rows.is_empty():
        rows = rows.with_columns(pl.col("date").cast(pl.Utf8))

    output_rows = rows.to_dicts()
    input_fingerprint = _chart_input_fingerprint(output_rows)
    annotation_layers: list[dict] = []
    if layer_categories:
        from app.chart_layers.models import ChartLayerContext
        from app.chart_layers.providers import default_chart_layer_registry

        context = ChartLayerContext(
            symbol=query.symbol,
            asset_type=query.asset_type,
            interval=query.interval,
            price_basis=effective_adjustment,
            rows=output_rows,
            visible_start=(coverage_start or start).isoformat(),
            visible_end=(coverage_end or end).isoformat(),
            input_fingerprint=input_fingerprint,
            key_levels=levels,
            data_dir=data_dir,
            strategy_ids=strategy_ids,
            source_run_id=source_run_id,
            params_fingerprint=params_fingerprint,
        )
        annotation_layers = [
            layer.to_dict()
            for layer in default_chart_layer_registry().build(context, layer_categories)
        ]
        pattern_refs_by_date: dict[str, list[str]] = {}
        for layer in annotation_layers:
            if layer["category"] != "pattern":
                continue
            version = layer.get("algorithm_version") or "unknown"
            for item in layer.get("evidence") or []:
                confirmed_at = str((item.get("metadata") or {}).get("confirmed_at") or "")[:10]
                if confirmed_at:
                    pattern_refs_by_date.setdefault(confirmed_at, []).append(
                        f"{layer['id']}@{version}:{item['id']}"
                    )
        for layer in annotation_layers:
            if layer["category"] != "strategy":
                continue
            for item in layer.get("evidence") or []:
                metadata = item.setdefault("metadata", {})
                event_date = str(metadata.get("event_date") or "")[:10]
                existing = list(metadata.get("pattern_refs") or [])
                metadata["pattern_refs"] = sorted(set(existing + pattern_refs_by_date.get(event_date, [])))

    return {
        "symbol": query.symbol,
        "asset_type": query.asset_type,
        "rows": output_rows,
        "levels": levels,
        "annotation_layers": annotation_layers,
        "meta": {
            "requested_interval": query.interval,
            "effective_interval": query.interval,
            "requested_adjustment": query.adjustment,
            "adjustment": effective_adjustment,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "source": source,
            "coverage_start": coverage_start.isoformat() if coverage_start else None,
            "coverage_end": coverage_end.isoformat() if coverage_end else None,
            "complete": complete,
            "warmup_bars": warmup_bars,
            "warmup_complete": warmup_complete,
            "input_fingerprint": input_fingerprint,
            "warnings": warnings,
        },
    }
