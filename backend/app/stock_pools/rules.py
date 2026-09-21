from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import polars as pl

from app.market_facts.repository import MarketFactRepository

RULE_VERSION = "stock-pools-v2"

SOURCE_META = {
    "breakthrough": ("突破", "突破启动", "10日"),
    "limit_ladder": ("涨停", "涨停强化", "当日"),
    "abnormal_surge": ("异动", "异动加速", "3日"),
    "liquidity_trend": ("趋势", "趋势延续", "每日重算"),
    "divergence": ("分歧", "高位分歧", "3日"),
    "failed_limit_repair": ("炸板修复", "企稳修复", "3日"),
    "trend_pullback": ("趋势回踩", "回踩整理", "3日"),
    "active_character": ("股性活跃", "活跃观察", "每日重算"),
    "popularity_warm": ("人气中温", "人气观察", "当日"),
}

STAGE_PRIORITY = (
    "涨停强化", "高位分歧", "异动加速", "突破启动", "企稳修复",
    "回踩整理", "趋势延续", "活跃观察", "人气观察",
)

EVENT_SOURCES = {
    "breakthrough", "limit_ladder", "abnormal_surge", "divergence",
    "failed_limit_repair", "trend_pullback",
}


def _code(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else ""


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _features(history: pl.DataFrame) -> pl.DataFrame:
    frame = history.sort(["symbol", "date"])
    by = "symbol"
    return frame.with_columns(
        pl.col("close").rolling_mean(10).over(by).alias("ma10"),
        pl.col("close").rolling_mean(20).over(by).alias("ma20"),
        pl.col("close").rolling_mean(60).over(by).alias("ma60"),
        pl.col("volume").shift(1).rolling_mean(20).over(by).alias("prior_volume20"),
        pl.col("high").shift(1).rolling_max(20).over(by).alias("prior_high20"),
        pl.col("high").shift(1).rolling_max(60).over(by).alias("prior_high60"),
        pl.col("high").shift(1).rolling_max(100).over(by).alias("prior_high100"),
        pl.col("high").shift(1).rolling_max(250).over(by).alias("prior_high250"),
        pl.col("close").shift(1).rolling_max(60).over(by).alias("prior_close60"),
        pl.col("close").shift(1).rolling_max(100).over(by).alias("prior_close100"),
        pl.col("close").shift(1).rolling_max(250).over(by).alias("prior_close250"),
        (pl.col("close") / pl.col("close").shift(3).over(by) - 1).alias("return3"),
        (pl.col("close") / pl.col("close").shift(10).over(by) - 1).alias("return10"),
        (pl.col("close") / pl.col("close").shift(30).over(by) - 1).alias("return30"),
    ).with_columns(
        (pl.col("volume") / pl.col("prior_volume20")).alias("volume_ratio"),
        pl.col("ma20").shift(10).over(by).alias("ma20_10ago"),
        pl.col("high").rolling_max(20).over(by).alias("high20"),
    )


def _event_maps(
    facts: MarketFactRepository,
    trading_dates: list[date],
) -> tuple[dict[date, dict[str, dict]], dict[date, dict[str, dict]], dict[date, dict[str, dict]]]:
    limits: dict[date, dict[str, dict]] = defaultdict(dict)
    broken: dict[date, dict[str, dict]] = defaultdict(dict)
    ladders: dict[date, dict[str, dict]] = defaultdict(dict)
    for day in trading_dates[-35:]:
        for row in facts.get_limit_events(day).to_dicts():
            code = _code(row.get("symbol"))
            if row.get("event_type") == "limit_up":
                limits[day][code] = row
            elif row.get("event_type") == "broken_board":
                broken[day][code] = row
        for row in facts.get_limit_ladder(day).to_dicts():
            ladders[day][_code(row.get("symbol"))] = row
    return limits, broken, ladders


def build_candidates(
    history: pl.DataFrame,
    instruments: pl.DataFrame,
    facts: MarketFactRepository,
    trade_date: date,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    if history.is_empty() or "date" not in history.columns:
        raise ValueError(f"no enriched history for {trade_date}")
    frame = _features(history.filter(pl.col("date") <= trade_date))
    trading_dates = sorted(frame["date"].unique().to_list())
    if not trading_dates or trading_dates[-1] != trade_date:
        raise ValueError(f"enriched history does not contain {trade_date}")
    date_index = {day: index for index, day in enumerate(trading_dates)}
    current_index = date_index[trade_date]
    recent_dates = trading_dates[max(0, current_index - 30): current_index + 1]
    recent = frame.filter(pl.col("date").is_in(recent_dates))
    current = recent.filter(pl.col("date") == trade_date)

    inst_cols = [column for column in ("symbol", "name", "exchange", "total_shares") if column in instruments.columns]
    current = current.join(instruments.select(inst_cols).unique("symbol"), on="symbol", how="left")
    price_column = "raw_close" if "raw_close" in current.columns else "close"
    current = current.with_columns(
        (pl.col(price_column) * pl.col("total_shares") / 1e8).alias("market_cap_yi"),
        (pl.col("amount") / 1e8).alias("amount_yi"),
    )
    eligible = current.filter(
        pl.col("name").fill_null("").str.to_uppercase().str.contains("ST").not_()
        & pl.col("market_cap_yi").is_between(20, 3000)
        & (pl.col("amount_yi") >= 1)
        & (pl.col("turnover_rate") >= 1)
    )
    eligible_symbols = set(eligible["symbol"].to_list())
    current_rows = {row["symbol"]: row for row in eligible.to_dicts()}
    recent_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in recent.filter(pl.col("symbol").is_in(eligible_symbols)).to_dicts():
        recent_rows[row["symbol"]].append(row)

    limits, broken, ladders = _event_maps(facts, trading_dates)
    code_to_symbol = {_code(symbol): symbol for symbol in eligible_symbols}
    events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(source_id: str, symbol: str, evidence: str, event_day: date, anchor: float | None = None, details: dict | None = None) -> None:
        if symbol not in eligible_symbols or any(item["source_id"] == source_id for item in events[symbol]):
            return
        age = current_index - date_index.get(event_day, current_index)
        label, stage, expiry = SOURCE_META[source_id]
        events[symbol].append({
            "source_id": source_id, "source": label, "stage": stage,
            "event_date": event_day.isoformat(), "event_age": age,
            "anchor_price": round(anchor, 3) if anchor is not None else None,
            "expires": expiry, "evidence": evidence, "details": details or {},
        })

    # Breakthrough: retain the latest valid breakout for ten trading sessions.
    for symbol, rows in recent_rows.items():
        latest: tuple[dict, list[str]] | None = None
        for row in rows[-11:]:
            windows = []
            for window in (60, 100, 250):
                if _safe_float(row.get(f"prior_close{window}")) is not None and row["close"] > row[f"prior_close{window}"]:
                    windows.append(f"收盘{window}日")
                elif _safe_float(row.get(f"prior_high{window}")) is not None and row["high"] > row[f"prior_high{window}"]:
                    windows.append(f"盘中{window}日")
            if windows:
                latest = (row, windows)
        if latest:
            row, windows = latest
            anchor = max(value for value in (row.get("prior_close60"), row.get("prior_high60")) if value is not None)
            if current_rows[symbol]["close"] >= anchor:
                add("breakthrough", symbol, f"{'、'.join(windows)}新高 · 量比{(row.get('volume_ratio') or 0):.2f}", row["date"], anchor)

    # Today's true limit ladder.
    for code, detail in ladders.get(trade_date, {}).items():
        symbol = code_to_symbol.get(code)
        if symbol:
            height = int(detail.get("board_height") or 1)
            add("limit_ladder", symbol, "首板" if height == 1 else f"{height}板", trade_date, details=detail)

    # Surge is a fresh acceleration event; later days are represented by their new stage.
    for symbol, rows in recent_rows.items():
        latest = rows[-1]
        prior = rows[-2] if len(rows) > 1 else None
        triggered = ((latest.get("return10") or 0) >= .30 and (not prior or (prior.get("return10") or 0) < .30)) \
            or ((latest.get("return30") or 0) >= .50 and (not prior or (prior.get("return30") or 0) < .50)) \
            or (latest.get("return3") or 0) >= .15
        if triggered:
            add("abnormal_surge", symbol, f"10日{(latest.get('return10') or 0) * 100:+.1f}% · 30日{(latest.get('return30') or 0) * 100:+.1f}%", latest["date"])

    # Stable high-liquidity trend.
    amount_rank = {symbol: index for index, symbol in enumerate(current.sort(["amount", "symbol"], descending=[True, False])["symbol"].to_list(), 1)}
    for symbol, row in current_rows.items():
        high20 = row.get("high20") or row["close"]
        drawdown = row["close"] / high20 - 1
        if amount_rank[symbol] <= 200 and row.get("ma20") and row.get("ma60") and row["close"] > row["ma20"] > row["ma60"] and row["ma20"] > (row.get("ma20_10ago") or row["ma20"]) and drawdown >= -.15:
            add("liquidity_trend", symbol, f"成交额第{amount_rank[symbol]} · 距20日高{drawdown * 100:.1f}%", trade_date)

    # Divergence and failed-board repair use canonical event facts and event-day lows.
    row_by_key = {(row["symbol"], row["date"]): row for rows in recent_rows.values() for row in rows}
    current_limit_codes = set(limits.get(trade_date, {}))
    for event_day in trading_dates[max(0, current_index - 3):current_index]:
        age = current_index - date_index[event_day]
        for code in limits.get(event_day, {}):
            symbol = code_to_symbol.get(code)
            now = current_rows.get(symbol or "")
            event = row_by_key.get((symbol, event_day)) if symbol else None
            height = int((ladders.get(event_day, {}).get(code) or {}).get("board_height") or 1)
            if not now or not event or code in current_limit_codes or height > 2:
                continue
            spread = now["high"] - now["low"]
            location = (now["close"] - now["low"]) / spread if spread > 0 else .5
            day_return = now["close"] / now["open"] - 1
            if -0.05 <= day_return <= .03 and now["close"] >= event["low"] and location >= .55:
                add("divergence", symbol, f"{'首板' if height == 1 else '二板'}后{age}日 · 收盘位置{location * 100:.0f}%", event_day, event["low"])
        for code in broken.get(event_day, {}):
            symbol = code_to_symbol.get(code)
            now = current_rows.get(symbol or "")
            event = row_by_key.get((symbol, event_day)) if symbol else None
            if not now or not event:
                continue
            spread = now["high"] - now["low"]
            location = (now["close"] - now["low"]) / spread if spread > 0 else .5
            day_return = now["close"] / now["open"] - 1
            if now["close"] >= event["low"] and day_return > 0 and location >= .6 and (now.get("volume_ratio") or 99) < 1:
                add("failed_limit_repair", symbol, f"炸板后{age}日 · 量比{now['volume_ratio']:.2f} · 收涨{day_return * 100:.1f}%", event_day, event["low"])

    # Pullback requires a recent breakout, trend context and a reclaimed MA10/20.
    for symbol, rows in recent_rows.items():
        now = current_rows[symbol]
        prior_row = rows[-2] if len(rows) > 1 else None
        prior_breakouts = []
        for row in rows:
            age = current_index - date_index[row["date"]]
            if not 5 <= age <= 20:
                continue
            if any(
                _safe_float(row.get(f"prior_{basis}{window}")) is not None
                and row[basis] > row[f"prior_{basis}{window}"]
                for basis in ("close", "high") for window in (60, 100, 250)
            ):
                prior_breakouts.append(row)
        if not prior_breakouts or not prior_row or not now.get("ma60") or now["close"] < now["ma60"] or (now.get("volume_ratio") or 99) >= 1:
            continue
        for support in (10, 20):
            ma = now.get(f"ma{support}")
            prior_ma = prior_row.get(f"ma{support}")
            if ma and prior_ma and prior_row["low"] > prior_ma * 1.01 and now["low"] <= ma * 1.01 and now["high"] >= ma * .99 and now["close"] >= ma:
                add("trend_pullback", symbol, f"突破后回踩MA{support} · 量比{now['volume_ratio']:.2f}", trade_date, ma)
                break

    # Active character: true limit-up memory with the latest event low protected.
    for symbol, now in current_rows.items():
        code = _code(symbol)
        prior_limit_days = [day for day in trading_dates[max(0, current_index - 30):current_index + 1] if code in limits.get(day, {})]
        if not prior_limit_days or code in current_limit_codes:
            continue
        latest_day = prior_limit_days[-1]
        event = row_by_key.get((symbol, latest_day))
        if event and (current_index - date_index[latest_day] <= 10 or len(prior_limit_days) >= 2) and now.get("ma20") and now["close"] > now["ma20"] and now["close"] >= event["low"] and now["close"] / (now.get("high20") or now["close"]) - 1 >= -.15:
            add("active_character", symbol, f"距涨停{current_index - date_index[latest_day]}日 · 30日涨停{len(prior_limit_days)}次", latest_day, event["low"])

    # Popularity is a reusable optional fact; absence remains unavailable.
    popularity = facts.get_security_popularity(trade_date)
    popularity_status = "unavailable"
    if not popularity.is_empty():
        popularity_status = "complete"
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in popularity.to_dicts():
            grouped[_code(item.get("symbol"))].append(item)
        for code, rankings in grouped.items():
            symbol = code_to_symbol.get(code)
            selected = [item for item in rankings if 20 <= int(item.get("rank") or 0) <= 100]
            if symbol and selected:
                evidence = " · ".join(f"{item.get('source_name') or item.get('source')}第{int(item['rank'])}名" for item in selected)
                add("popularity_warm", symbol, evidence, trade_date, details={"rankings": rankings})

    candidates: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    stage_rank = {stage: index for index, stage in enumerate(STAGE_PRIORITY)}
    for symbol, source_events in events.items():
        if not source_events:
            continue
        now = current_rows[symbol]
        source_ids = [event["source_id"] for event in source_events]
        source_labels = [event["source"] for event in source_events]
        stages = {event["stage"] for event in source_events}
        stage = min(stages, key=stage_rank.__getitem__)
        event_count = sum(source in EVENT_SOURCES for source in source_ids)
        tier = "core" if len(source_ids) >= 3 or (len(source_ids) >= 2 and event_count) else "focus" if event_count or len(source_ids) >= 2 else "all"
        evidence = " · ".join(event["evidence"] for event in source_events[:2])
        if len(source_events) > 2:
            evidence += f" · 另{len(source_events) - 2}项"
        observation_window = " / ".join(event["expires"] for event in source_events[:2])
        rows = recent_rows[symbol]
        display_price = now.get("raw_close") or now["close"]
        previous = rows[-2] if len(rows) > 1 else None
        previous_close = (previous.get("raw_close") or previous["close"]) if previous else None
        pct = (display_price / previous_close - 1) * 100 if previous_close else 0
        item = {
            "symbol": symbol, "code": _code(symbol), "name": now.get("name") or symbol,
            "exchange": now.get("exchange") or symbol.split(".")[-1],
            "price": round(display_price, 2), "pct_chg": round(pct, 2),
            "amount_yi": round(now["amount_yi"], 2), "market_cap_yi": round(now["market_cap_yi"], 2),
            "turnover_pct": round(now["turnover_rate"], 2), "volume_ratio": round(now.get("volume_ratio") or 0, 2),
            "source_ids": source_ids, "sources": source_labels, "primary_stage": stage,
            "tier": tier, "freshness": "当日事件" if any(event["event_age"] == 0 and event["source_id"] in EVENT_SOURCES for event in source_events) else "延续观察",
            "topics": [], "industry": "", "change_types": [],
            "memberships": {}, "primary_concept": None,
            "evidence": evidence, "observation_window": observation_window,
        }
        candidates.append(item)
        details[symbol] = {**item, "source_events": source_events, "topic_evidence": [], "research": []}

    quality = {
        "popularity": popularity_status,
        "limit_events": "complete" if limits.get(trade_date) else "unavailable",
        "logic_evidence": "complete" if not facts.get_stock_logic_evidence(trade_date).is_empty() else "unavailable",
    }
    return candidates, details, {
        "quality": quality,
        "market_count": current.height,
        "eligible_count": len(eligible_symbols),
    }
