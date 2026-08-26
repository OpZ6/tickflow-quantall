"""Normalize QuantX source payloads into canonical market fact batches."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from app.market_facts.registry import DatasetId, get_dataset


class FactValidationError(ValueError):
    """Raised when a required canonical dataset cannot be constructed."""


@dataclass(frozen=True)
class FactBatch:
    dataset_id: DatasetId
    trade_date: date
    frame: pl.DataFrame


def _frame(dataset_id: DatasetId, rows: list[dict[str, Any]]) -> pl.DataFrame:
    spec = get_dataset(dataset_id)
    if not rows:
        return pl.DataFrame(schema=spec.storage_schema)
    return pl.DataFrame(
        rows,
        schema=spec.storage_schema,
        orient="row",
        strict=False,
    )


def _trade_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _calendar_date(value: Any) -> date | None:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return _trade_date(text)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        return int(match.group()) if match else None


def _records(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in keys:
        rows = value.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _stock_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _exchange(symbol: str) -> str:
    if symbol.startswith(("4", "8", "9")):
        return "BSE"
    if symbol.startswith("6"):
        return "SSE"
    return "SZSE"


def _observed_at(payload: dict[str, Any]) -> str:
    return str(payload.get("scraped_at") or payload.get("collected_at") or "")


def _metadata(
    *,
    source: str,
    source_record_id: str,
    observed_at: str,
    ingested_at: str,
    run_id: str,
    is_fallback: bool = False,
    quality_level: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_record_id": source_record_id,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "run_id": run_id,
        "schema_version": 1,
        "quality_level": quality_level or ("fallback" if is_fallback else "observed"),
        "is_fallback": is_fallback,
    }


def _build_trading_calendar(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    as_of_date = _trade_date(trade_date)
    tushare = sources.get("tushare") or {}
    calendar = (
        tushare.get("trade_calendar")
        if isinstance(tushare.get("trade_calendar"), dict)
        else {}
    )
    rows: list[dict[str, Any]] = []
    for item in _records(calendar, "records", "rows"):
        calendar_day = _calendar_date(
            item.get("cal_date") or item.get("trade_date") or item.get("date")
        )
        is_open_raw = item.get("is_open")
        if calendar_day is None or is_open_raw is None:
            continue
        exchange = str(item.get("exchange") or "SSE").upper()
        rows.append(
            {
                "trade_date": calendar_day,
                "as_of_date": as_of_date,
                "exchange": exchange,
                "is_open": bool(_integer(is_open_raw)),
                "previous_open_date": _calendar_date(item.get("pretrade_date")),
                **_metadata(
                    source="tushare",
                    source_record_id=f"tushare:{exchange}:{calendar_day.isoformat()}",
                    observed_at=_observed_at(tushare),
                    ingested_at=ingested_at,
                    run_id=run_id,
                ),
            }
        )

    fallback_source = next(
        (
            source
            for source in ("tickflow_enriched_aggregate", "tickflow_published_fact")
            if sources.get(source)
        ),
        None,
    )
    if not rows and fallback_source:
        payload = sources[fallback_source]
        rows.append(
            {
                "trade_date": as_of_date,
                "as_of_date": as_of_date,
                "exchange": "SSE",
                "is_open": True,
                "previous_open_date": None,
                **_metadata(
                    source=fallback_source,
                    source_record_id=f"{fallback_source}:SSE:{as_of_date.isoformat()}",
                    observed_at=_observed_at(payload),
                    ingested_at=ingested_at,
                    run_id=run_id,
                    is_fallback=True,
                ),
            }
        )
    if not rows:
        raise FactValidationError(f"cannot build trading_calendar for {trade_date}")
    frame = _frame(DatasetId.TRADING_CALENDAR, rows).unique(
        subset=["exchange", "trade_date"],
        keep="first",
        maintain_order=True,
    ).sort(["trade_date", "exchange"])
    return FactBatch(DatasetId.TRADING_CALENDAR, as_of_date, frame)


def _build_market_breadth(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    source = "tickflow_enriched_aggregate"
    payload = sources.get(source) or {}
    is_fallback = False
    if not _records(payload, "daily", "stocks", "records") and not isinstance(
        payload.get("daily_market"), dict
    ):
        source = "tushare"
        payload = sources.get(source) or {}
        is_fallback = True
    daily = _records(payload, "daily", "stocks", "records")
    summary = payload.get("daily_market") if isinstance(payload.get("daily_market"), dict) else {}
    if daily:
        changes = [_number(row.get("pct_chg")) for row in daily]
        up_count = sum(value is not None and value > 0 for value in changes)
        down_count = sum(value is not None and value < 0 for value in changes)
        flat_count = sum(value is not None and value == 0 for value in changes)
        total_count = len(daily)
    elif summary:
        up_count = int(summary.get("up_count") or 0)
        down_count = int(summary.get("down_count") or 0)
        flat_count = int(summary.get("flat_count") or 0)
        total_count = int(summary.get("total_stocks") or up_count + down_count + flat_count)
    else:
        raise FactValidationError(f"cannot build market_breadth_daily for {trade_date}")
    up_ratio_pct = round(up_count / total_count * 100, 2) if total_count else None
    row = {
        "trade_date": _trade_date(trade_date),
        "market": "CN_A",
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "total_count": total_count,
        "up_ratio_pct": up_ratio_pct,
        "advance_decline": up_count - down_count,
        **_metadata(
            source=source,
            source_record_id=f"{source}:{trade_date}:CN_A",
            observed_at=_observed_at(payload),
            ingested_at=ingested_at,
            run_id=run_id,
            is_fallback=is_fallback,
        ),
    }
    return FactBatch(
        DatasetId.MARKET_BREADTH_DAILY,
        _trade_date(trade_date),
        _frame(DatasetId.MARKET_BREADTH_DAILY, [row]),
    )


def _event_rows(
    *,
    trade_date: str,
    event_type: str,
    rows: list[dict[str, Any]],
    payload: dict[str, Any],
    source: str,
    run_id: str,
    ingested_at: str,
    is_fallback: bool,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        raw_code = row.get("source_code") or row.get("code") or row.get("ts_code")
        symbol = _stock_code(raw_code)
        if not symbol:
            continue
        board_height = _integer(
            row.get("limit_times") or row.get("limit_count") or row.get("board_height")
        )
        if event_type == "limit_up" and board_height is None:
            board_height = 1
        normalized.append(
            {
                "trade_date": _trade_date(trade_date),
                "symbol": symbol,
                "exchange": _exchange(symbol),
                "asset_type": "stock",
                "source_code": str(raw_code or symbol),
                "name": str(row.get("name") or ""),
                "event_type": event_type,
                "board_height": board_height,
                **_metadata(
                    source=source,
                    source_record_id=f"{source}:{trade_date}:{event_type}:{symbol}",
                    observed_at=_observed_at(payload),
                    ingested_at=ingested_at,
                    run_id=run_id,
                    is_fallback=is_fallback,
                ),
            }
        )
    return normalized


def _build_limit_events(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    pywencai = sources.get("pywencai") or {}
    rows: list[dict[str, Any]] = []
    limit_up = _records(pywencai.get("limit_up"), "stocks", "rows", "records")
    if limit_up:
        rows.extend(
            _event_rows(
                trade_date=trade_date,
                event_type="limit_up",
                rows=limit_up,
                payload=pywencai,
                source="pywencai",
                run_id=run_id,
                ingested_at=ingested_at,
                is_fallback=False,
            )
        )
    else:
        fallback = sources.get("zhangtingke") or {}
        fallback_rows = _records(fallback, "ladder_stocks", "stocks", "records")
        rows.extend(
            _event_rows(
                trade_date=trade_date,
                event_type="limit_up",
                rows=fallback_rows,
                payload=fallback,
                source="zhangtingke",
                run_id=run_id,
                ingested_at=ingested_at,
                is_fallback=True,
            )
        )
    for event_type, key in (("broken_board", "broken_board"), ("limit_down", "limit_down")):
        rows.extend(
            _event_rows(
                trade_date=trade_date,
                event_type=event_type,
                rows=_records(pywencai.get(key), "stocks", "rows", "records"),
                payload=pywencai,
                source="pywencai",
                run_id=run_id,
                ingested_at=ingested_at,
                is_fallback=False,
            )
        )
    frame = _frame(DatasetId.LIMIT_EVENT_DAILY, rows)
    if not frame.is_empty():
        frame = frame.unique(
            subset=["trade_date", "symbol", "event_type"],
            keep="first",
            maintain_order=True,
        ).sort(["event_type", "symbol"])
    return FactBatch(
        DatasetId.LIMIT_EVENT_DAILY,
        _trade_date(trade_date),
        frame,
    )


def _theme_row(
    *,
    trade_date: str,
    source: str,
    payload: dict[str, Any],
    name: Any,
    rank: Any,
    stock_count: Any,
    strength: Any,
    run_id: str,
    ingested_at: str,
) -> dict[str, Any] | None:
    theme_name = str(name or "").strip()
    if not theme_name:
        return None
    return {
        "trade_date": _trade_date(trade_date),
        "theme_id": theme_name,
        "theme_name": theme_name,
        "rank": _integer(rank),
        "stock_count": _integer(stock_count),
        "strength": _number(strength),
        **_metadata(
            source=source,
            source_record_id=f"{source}:{trade_date}:{theme_name}",
            observed_at=_observed_at(payload),
            ingested_at=ingested_at,
            run_id=run_id,
        ),
    }


def _build_theme_observations(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    rows: list[dict[str, Any]] = []
    ths = sources.get("ths_hot") or {}
    for rank, item in enumerate(_records(ths.get("reason_tags")), start=1):
        row = _theme_row(
            trade_date=trade_date,
            source="ths_hot",
            payload=ths,
            name=item.get("tag"),
            rank=rank,
            stock_count=item.get("count"),
            strength=item.get("count"),
            run_id=run_id,
            ingested_at=ingested_at,
        )
        if row:
            rows.append(row)

    pywencai = sources.get("pywencai") or {}
    limit_up = pywencai.get("limit_up") if isinstance(pywencai.get("limit_up"), dict) else {}
    for rank, item in enumerate(_records(limit_up.get("themes")), start=1):
        row = _theme_row(
            trade_date=trade_date,
            source="pywencai",
            payload=pywencai,
            name=item.get("name"),
            rank=rank,
            stock_count=item.get("count"),
            strength=item.get("count"),
            run_id=run_id,
            ingested_at=ingested_at,
        )
        if row:
            rows.append(row)

    deepq = sources.get("deepq") or {}
    latest_day = deepq.get("latest_day") if isinstance(deepq.get("latest_day"), dict) else {}
    for item in _records(latest_day.get("sectors")):
        row = _theme_row(
            trade_date=trade_date,
            source="deepq",
            payload=deepq,
            name=item.get("sectorName") or item.get("name"),
            rank=item.get("rank"),
            stock_count=item.get("stocksCount"),
            strength=item.get("heatValue"),
            run_id=run_id,
            ingested_at=ingested_at,
        )
        if row:
            rows.append(row)

    frame = _frame(DatasetId.THEME_OBSERVATION_DAILY, rows)
    if not frame.is_empty():
        frame = frame.unique(
            subset=["trade_date", "source", "theme_id"],
            keep="first",
            maintain_order=True,
        ).sort(["source", "rank", "theme_name"])
    return FactBatch(
        DatasetId.THEME_OBSERVATION_DAILY,
        _trade_date(trade_date),
        frame,
    )


def _sector_rows(
    *,
    trade_date: str,
    source: str,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    run_id: str,
    ingested_at: str,
    is_fallback: bool,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in rows:
        sector_name = str(item.get("name") or item.get("sector_name") or "").strip()
        if not sector_name:
            continue
        sector_id = str(item.get("code") or item.get("sector_id") or sector_name).strip()
        normalized.append(
            {
                "trade_date": _trade_date(trade_date),
                "sector_id": sector_id,
                "sector_name": sector_name,
                "dimension": str(item.get("dimension") or "industry"),
                "pct_chg": _number(item.get("pct_chg")),
                "net_inflow_yi": _number(
                    item.get("net_inflow_yi")
                    if item.get("net_inflow_yi") is not None
                    else item.get("net")
                ),
                "amount_yi": _number(item.get("amount_yi")),
                **_metadata(
                    source=source,
                    source_record_id=f"{source}:{trade_date}:{sector_id}",
                    observed_at=_observed_at(payload),
                    ingested_at=ingested_at,
                    run_id=run_id,
                    is_fallback=is_fallback,
                ),
            }
        )
    return normalized


def _build_sector_flows(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    rows: list[dict[str, Any]] = []
    primary = sources.get("sector_fund_flow_s4") or {}
    rows.extend(
        _sector_rows(
            trade_date=trade_date,
            source="sector_fund_flow_s4",
            payload=primary,
            rows=_records(primary, "sectors", "records", "rows"),
            run_id=run_id,
            ingested_at=ingested_at,
            is_fallback=False,
        )
    )
    fallback = sources.get("akshare") or {}
    rows.extend(
        _sector_rows(
            trade_date=trade_date,
            source="akshare",
            payload=fallback,
            rows=_records(fallback.get("sector_fund_flow"), "sectors", "records", "rows"),
            run_id=run_id,
            ingested_at=ingested_at,
            is_fallback=True,
        )
    )
    frame = _frame(DatasetId.SECTOR_FLOW_DAILY, rows)
    if not frame.is_empty():
        frame = frame.unique(
            subset=["trade_date", "source", "sector_id"],
            keep="first",
            maintain_order=True,
        ).sort(["source", "sector_id"])
    return FactBatch(
        DatasetId.SECTOR_FLOW_DAILY,
        _trade_date(trade_date),
        frame,
    )


def _build_limit_ladder(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    structured: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    table = structured.get("limit_ladder") or {}
    zhangtingke = sources.get("zhangtingke") or {}
    pywencai = sources.get("pywencai") or {}
    ladder = table.get("ladder_by_height") or zhangtingke.get("ladder_by_height")
    source = "zhangtingke"
    is_fallback = False
    rows_with_height: list[tuple[int, dict[str, Any]]] = []
    if isinstance(ladder, dict):
        for raw_height, members in ladder.items():
            height = _integer(raw_height)
            if height is None or height < 1 or not isinstance(members, list):
                continue
            rows_with_height.extend(
                (height, item) for item in members if isinstance(item, dict)
            )
    if not rows_with_height:
        members = _records(zhangtingke, "ladder_stocks", "stocks", "records")
        rows_with_height = [
            (_integer(item.get("limit_times") or item.get("limit_count")) or 1, item)
            for item in members
        ]
    if not rows_with_height:
        source = "pywencai"
        is_fallback = True
        limit_up = pywencai.get("limit_up") if isinstance(pywencai.get("limit_up"), dict) else {}
        members = _records(limit_up, "stocks", "records", "rows")
        rows_with_height = [
            (_integer(item.get("limit_times") or item.get("limit_count")) or 1, item)
            for item in members
        ]
    payload = sources.get(source) or {}
    rows = []
    for height, item in rows_with_height:
        raw_code = item.get("source_code") or item.get("code") or item.get("ts_code")
        symbol = _stock_code(raw_code)
        if not symbol:
            continue
        rows.append(
            {
                "trade_date": _trade_date(trade_date),
                "board_height": height,
                "symbol": symbol,
                "exchange": _exchange(symbol),
                "asset_type": "stock",
                "source_code": str(raw_code or symbol),
                "name": str(item.get("name") or ""),
                "theme_name": str(item.get("theme_name") or ""),
                **_metadata(
                    source=source,
                    source_record_id=f"{source}:{trade_date}:{height}:{symbol}",
                    observed_at=_observed_at(payload),
                    ingested_at=ingested_at,
                    run_id=run_id,
                    is_fallback=is_fallback,
                ),
            }
        )
    frame = _frame(DatasetId.LIMIT_LADDER_DAILY, rows)
    if not frame.is_empty():
        frame = frame.unique(
            subset=["trade_date", "board_height", "symbol"],
            keep="first",
            maintain_order=True,
        ).sort(["board_height", "symbol"], descending=[True, False])
    return FactBatch(DatasetId.LIMIT_LADDER_DAILY, _trade_date(trade_date), frame)


def _build_theme_members(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    structured: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    rows: list[dict[str, Any]] = []
    payload = sources.get("pywencai") or {}
    table = structured.get("theme_stocks") or {}
    themes = table.get("themes") if isinstance(table.get("themes"), dict) else {}
    pairs: list[tuple[str, dict[str, Any]]] = []
    for theme, members in themes.items():
        if isinstance(members, list):
            pairs.extend(
                (str(theme), item) for item in members if isinstance(item, dict)
            )
    if not pairs:
        limit_up = payload.get("limit_up") if isinstance(payload.get("limit_up"), dict) else {}
        for item in _records(limit_up, "stocks", "records", "rows"):
            concepts = item.get("concepts") or item.get("themes") or []
            if isinstance(concepts, list):
                pairs.extend((str(theme), item) for theme in concepts if str(theme).strip())
    for theme_name, item in pairs:
        symbol = _stock_code(item.get("code") or item.get("ts_code"))
        theme_name = theme_name.strip()
        if not symbol or not theme_name:
            continue
        rows.append(
            {
                "trade_date": _trade_date(trade_date),
                "theme_id": theme_name,
                "theme_name": theme_name,
                "symbol": symbol,
                "exchange": _exchange(symbol),
                "asset_type": "stock",
                "name": str(item.get("name") or ""),
                "role": "limit_up_leader",
                **_metadata(
                    source="pywencai",
                    source_record_id=f"pywencai:{trade_date}:{theme_name}:{symbol}",
                    observed_at=_observed_at(payload),
                    ingested_at=ingested_at,
                    run_id=run_id,
                ),
            }
        )
    frame = _frame(DatasetId.THEME_MEMBER_DAILY, rows)
    if not frame.is_empty():
        frame = frame.unique(
            subset=["trade_date", "source", "theme_id", "symbol"],
            keep="first",
            maintain_order=True,
        ).sort(["theme_name", "symbol"])
    return FactBatch(DatasetId.THEME_MEMBER_DAILY, _trade_date(trade_date), frame)


def _build_market_state(
    trade_date: str,
    structured: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    computed = structured.get("_computed") or structured.get("sentiment_state") or {}
    if not computed:
        return FactBatch(
            DatasetId.MARKET_STATE_DAILY,
            _trade_date(trade_date),
            _frame(DatasetId.MARKET_STATE_DAILY, []),
        )
    overview = structured.get("market_overview") or {}
    breadth = structured.get("market_breadth") or overview.get("breadth") or {}
    limit = structured.get("limit_summary") or {}
    heat = computed.get("market_heat") or {}
    heat_inputs = heat.get("inputs") or {}
    short = computed.get("short_term_sentiment") or {}
    trend = computed.get("trend_sentiment") or {}
    advance = computed.get("advance_stats") or {}
    loss = computed.get("loss_effect") or {}
    risk = computed.get("ebb_risk_check") or {}
    crash = computed.get("crash_signals") or {}
    participation = computed.get("participation_check") or {}
    row = {
        "trade_date": _trade_date(trade_date),
        "market": "CN_A",
        "market_heat_score": _number(heat.get("score")),
        "market_heat_zone": str(heat.get("zone") or ""),
        "short_term_sentiment_score": _number(short.get("score")),
        "trend_sentiment_score": _number(trend.get("score")),
        "sentiment_semantics_version": _integer(short.get("metric_semantics_version")),
        "up_ratio_pct": _number(breadth.get("up_ratio") or heat_inputs.get("up_ratio")),
        "up_count": _integer(breadth.get("up_count")),
        "down_count": _integer(breadth.get("down_count")),
        "limit_up_count": _integer(limit.get("limit_up_count") or heat_inputs.get("limit_up_count")),
        "limit_down_count": _integer(limit.get("limit_down_count") or loss.get("limit_down_count")),
        "seal_rate_pct": _number(limit.get("seal_rate") or heat_inputs.get("seal_rate")),
        "max_board": _integer(limit.get("max_board") or (computed.get("height_trend") or {}).get("latest_max_board")),
        "advance_rate_pct": _number(advance.get("advance_rate")),
        "premium_rate_pct": _number(advance.get("premium_rate")),
        "loss_severity": str(loss.get("severity") or ""),
        "ebb_signal_count": _integer(risk.get("signal_count")),
        "crash_triggered": bool(crash.get("any_triggered")),
        "participation_verdict": str(participation.get("verdict") or ""),
        "total_amount_yi": _number(overview.get("total_amount_yi")),
        "algorithm_version": "quantx-data-v1",
        "input_generation": run_id,
        **_metadata(
            source="quantx_deterministic_v1",
            source_record_id=f"quantx_deterministic_v1:{trade_date}:CN_A",
            observed_at=ingested_at,
            ingested_at=ingested_at,
            run_id=run_id,
            quality_level="derived",
        ),
    }
    return FactBatch(
        DatasetId.MARKET_STATE_DAILY,
        _trade_date(trade_date),
        _frame(DatasetId.MARKET_STATE_DAILY, [row]),
    )


def _build_screening_candidates(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    structured: dict[str, dict[str, Any]],
    run_id: str,
    ingested_at: str,
) -> FactBatch:
    table = structured.get("screening_candidates") or {}
    candidates = _records(table, "candidates", "active_pool", "active")
    if not candidates:
        pywencai = sources.get("pywencai") or {}
        limit_up = pywencai.get("limit_up") if isinstance(pywencai.get("limit_up"), dict) else {}
        candidates = _records(limit_up, "stocks", "records", "rows")
    rows = []
    for item in candidates:
        symbol = _stock_code(item.get("code") or item.get("ts_code"))
        if not symbol:
            continue
        rules = item.get("rules_matched") or ["limit_up"]
        rows.append(
            {
                "trade_date": _trade_date(trade_date),
                "symbol": symbol,
                "exchange": _exchange(symbol),
                "asset_type": "stock",
                "name": str(item.get("name") or ""),
                "candidate_type": str(table.get("kind") or "deterministic_rule_screen"),
                "priority": str(item.get("priority") or "rule"),
                "score": _number(item.get("score")),
                "pct_chg": _number(item.get("pct_chg")),
                "net_mf_yi": _number(item.get("net_mf_yi")),
                "industry": str(item.get("industry") or ""),
                "rules_matched": [str(rule) for rule in rules] if isinstance(rules, list) else [],
                "included": bool(item.get("included", True)),
                "algorithm_version": "quantx-rule-screen-v1",
                "input_generation": run_id,
                **_metadata(
                    source="quantx_rule_screen_v1",
                    source_record_id=f"quantx_rule_screen_v1:{trade_date}:{symbol}",
                    observed_at=ingested_at,
                    ingested_at=ingested_at,
                    run_id=run_id,
                    quality_level="derived",
                ),
            }
        )
    frame = _frame(DatasetId.SCREENING_CANDIDATE_DAILY, rows)
    if not frame.is_empty():
        frame = frame.unique(
            subset=["trade_date", "candidate_type", "symbol"],
            keep="first",
            maintain_order=True,
        ).sort("symbol")
    return FactBatch(
        DatasetId.SCREENING_CANDIDATE_DAILY,
        _trade_date(trade_date),
        frame,
    )


def build_initial_fact_batches(
    trade_date: str,
    sources: dict[str, dict[str, Any]],
    run_id: str,
    *,
    structured_tables: dict[str, dict[str, Any]] | None = None,
) -> list[FactBatch]:
    """Build the first canonical fact slice used by the migration dual-write."""
    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    structured = structured_tables or {}
    return [
        _build_trading_calendar(trade_date, sources, run_id, ingested_at),
        _build_market_breadth(trade_date, sources, run_id, ingested_at),
        _build_limit_events(trade_date, sources, run_id, ingested_at),
        _build_limit_ladder(
            trade_date, sources, structured, run_id, ingested_at
        ),
        _build_theme_observations(trade_date, sources, run_id, ingested_at),
        _build_theme_members(
            trade_date, sources, structured, run_id, ingested_at
        ),
        _build_sector_flows(trade_date, sources, run_id, ingested_at),
        _build_market_state(trade_date, structured, run_id, ingested_at),
        _build_screening_candidates(
            trade_date, sources, structured, run_id, ingested_at
        ),
    ]
