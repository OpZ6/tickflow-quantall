"""Read-only stage and membership changes over published stock-pool snapshots."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any

from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.rules import EVENT_SOURCES, STAGE_PRIORITY

LOW_STAGES = {"趋势延续", "回踩整理", "企稳修复"}


def _low_labels(row: dict) -> set[str]:
    topics = set(row.get("topics") or [])
    if topics:
        return topics
    memberships = row.get("memberships") or {}
    concepts = memberships.get("concept") or []
    return {row.get("primary_concept") or (concepts[0] if concepts else "")}


def _scope(rows: dict[str, dict], mode: str, topic: str) -> dict[str, dict]:
    if mode == "low":
        return {symbol: row for symbol, row in rows.items()
                if row.get("primary_stage") in LOW_STAGES and (not topic or topic in _low_labels(row))}
    return {symbol: row for symbol, row in rows.items()
            if not topic or topic in (row.get("topics") or [])}


def _source_delta(before: dict | None, after: dict) -> tuple[list[str], list[str]]:
    previous = dict(zip(before.get("source_ids", []), before.get("sources", []), strict=False)) if before else {}
    current = dict(zip(after.get("source_ids", []), after.get("sources", []), strict=False))
    return (
        [label for source, label in current.items() if source not in previous],
        [label for source, label in previous.items() if source not in current],
    )


def _comparison_quality(current: dict, previous: dict | None, mode: str) -> str:
    if previous is None:
        return "unavailable"
    if current.get("rule_version") != previous.get("rule_version"):
        return "incompatible"
    if mode == "hot":
        current_topic = current.get("topic_normalization") or {}
        previous_topic = previous.get("topic_normalization") or {}
        if (current_topic.get("rule"), current_topic.get("mode"), current_topic.get("prompt_version")) != (
            previous_topic.get("rule"), previous_topic.get("mode"), previous_topic.get("prompt_version")
        ):
            return "incompatible"
    required = {"market_universe"}
    if mode == "hot":
        required.add("logic_evidence")
    for summary in (current, previous):
        quality = summary.get("source_quality") or {}
        if summary.get("status") == "degraded" or any(quality.get(key) not in (None, "complete") for key in required):
            return "limited"
    return "complete"


def build_evolution(repo: StockPoolRepository, trade_date: date, mode: str, topic: str, window: int) -> dict[str, Any] | None:
    current_rows = repo.get_candidates(trade_date)
    current_summary = repo.get_summary(trade_date)
    if current_rows is None or current_summary is None:
        return None
    days = [day for day in repo.list_dates() if day <= trade_date.isoformat()]
    previous_date = days[-2] if len(days) > 1 else None
    previous_rows = repo.get_candidates(previous_date) if previous_date else None
    previous_summary = repo.get_summary(previous_date) if previous_date else None
    current_pool = {row["symbol"]: row for row in current_rows}
    previous_pool = {row["symbol"]: row for row in previous_rows} if previous_rows is not None else {}
    current = _scope(current_pool, mode, topic)
    # Low-view membership uses today's cohort; the static concept source is not point-in-time history.
    previous = ({symbol: previous_pool[symbol] for symbol in current if symbol in previous_pool}
                if mode == "low" else _scope(previous_pool, mode, topic))
    quality = _comparison_quality(current_summary, previous_summary, mode) if previous_rows is not None else "unavailable"
    stage_names = list(STAGE_PRIORITY)
    current_counts = Counter(row.get("primary_stage") for row in current.values())
    previous_counts = Counter(row.get("primary_stage") for row in previous.values())
    stages = [{"stage": stage, "current": current_counts[stage],
               "previous": previous_counts[stage] if previous_rows is not None else None}
              for stage in stage_names if current_counts[stage] or previous_counts[stage]]

    flow_symbols: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    members: list[dict] = []
    seen_before_previous = {
        item["symbol"] for day in days[:-2] for item in (repo.get_candidates(day) or [])
    }
    for symbol, row in current.items():
        before = previous.get(symbol)
        pool_before = previous_pool.get(symbol)
        if before:
            kind = "stage_changed" if before.get("primary_stage") != row.get("primary_stage") else "source_changed"
            if kind == "source_changed" and set(before.get("source_ids") or []) == set(row.get("source_ids") or []):
                kind = "unchanged"
        elif previous_rows is None:
            kind = "unknown"
        elif pool_before and mode == "hot" and topic:
            kind = "entered_topic"
        else:
            kind = "entered_pool"
        added, removed = _source_delta(pool_before, row)
        from_stage = (pool_before or {}).get("primary_stage") or "昨日未入池"
        to_stage = row.get("primary_stage") or "未知阶段"
        flow_key = f"{kind}|{from_stage}|{to_stage}"
        if kind not in {"unchanged", "unknown"}:
            flow_symbols[(kind, from_stage, to_stage)].append(symbol)
        members.append({
            "symbol": symbol, "name": row.get("name") or symbol, "kind": kind,
            "previous_stage": pool_before.get("primary_stage") if pool_before else None,
            "current_stage": row.get("primary_stage"),
            "added_sources": added, "removed_sources": removed, "flow_key": flow_key,
            "pct_chg": row.get("pct_chg"), "price_context": row.get("price_context"),
            "research_count": row.get("research_count", 0), "freshness": row.get("freshness"),
            "reentry": bool(previous_rows is not None and not pool_before and symbol in seen_before_previous),
        })

    exits: list[dict] = []
    if mode == "hot":
        for symbol, row in previous.items():
            if symbol in current:
                continue
            kind = "left_topic" if symbol in current_pool and topic else "left_pool"
            from_stage = row.get("primary_stage") or "未知阶段"
            to_stage = "其他题材" if kind == "left_topic" else "今日未入池"
            flow_key = f"{kind}|{from_stage}|{to_stage}"
            flow_symbols[(kind, from_stage, to_stage)].append(symbol)
            exits.append({
                "symbol": symbol, "name": row.get("name") or symbol, "kind": kind,
                "previous_stage": from_stage, "current_stage": current_pool.get(symbol, {}).get("primary_stage"),
                "flow_key": flow_key,
            })

    flows = [{"key": f"{kind}|{from_stage}|{to_stage}", "kind": kind,
              "from_stage": from_stage, "to_stage": to_stage,
              "count": len(symbols), "symbols": symbols}
             for (kind, from_stage, to_stage), symbols in flow_symbols.items()]
    flows.sort(key=lambda flow: (-flow["count"], flow["kind"], flow["from_stage"], flow["to_stage"]))
    history: list[dict] = []
    for day in days[-window:]:
        published_rows = repo.get_candidates(day)
        if published_rows is None:
            history.append({"date": day, "count": None, "event_count": None, "stage_counts": {}})
            continue
        day_rows = {row["symbol"]: row for row in published_rows}
        cohort = ({symbol: day_rows[symbol] for symbol in current if symbol in day_rows}
                  if mode == "low" else _scope(day_rows, mode, topic))
        history.append({
            "date": day, "count": len(cohort),
            "event_count": sum(bool(set(row.get("source_ids") or []) & EVENT_SOURCES) for row in cohort.values()),
            "stage_counts": dict(Counter(row.get("primary_stage") for row in cohort.values())),
        })
    return {
        "trade_date": trade_date.isoformat(), "previous_date": previous_date,
        "mode": mode, "topic": topic, "basis": "current_cohort" if mode == "low" else "daily_membership",
        "comparison_status": quality, "current_count": len(current),
        "previous_count": len(previous) if previous_rows is not None else None,
        "stages": stages, "flows": flows, "members": members, "exits": exits, "history": history,
        "counts": {
            "retained": len(current.keys() & previous.keys()),
            "entered_topic": sum(row["kind"] == "entered_topic" for row in members),
            "entered_pool": sum(row["kind"] == "entered_pool" for row in members),
            "left_topic": sum(row["kind"] == "left_topic" for row in exits),
            "left_pool": sum(row["kind"] == "left_pool" for row in exits),
            "stage_changed": sum(row["kind"] == "stage_changed" for row in members),
            "source_changed": sum(row["kind"] == "source_changed" for row in members),
        },
    }


def candidate_history(repo: StockPoolRepository, trade_date: date, symbol: str, window: int) -> dict | None:
    current = repo.get_candidates(trade_date)
    if current is None:
        return None
    normalized = symbol.upper()
    if "." not in normalized:
        normalized = next((row["symbol"] for row in current if row["symbol"].split(".")[0] == normalized), normalized)
    if not any(row["symbol"] == normalized for row in current):
        return None
    days = [day for day in repo.list_dates() if day <= trade_date.isoformat()][-window:]
    timeline = []
    for day in days:
        published_rows = repo.get_candidates(day)
        row = next((item for item in published_rows if item["symbol"] == normalized), None) if published_rows is not None else None
        timeline.append({
            "date": day, "available": published_rows is not None, "present": row is not None,
            "stage": row.get("primary_stage") if row else None,
            "sources": row.get("sources", []) if row else [],
            "topics": row.get("topics", []) if row else [],
            "pct_chg": row.get("pct_chg") if row else None,
            "price_context": row.get("price_context") if row else None,
            "research_count": row.get("research_count", 0) if row else 0,
        })
    return {"trade_date": trade_date.isoformat(), "symbol": normalized, "timeline": timeline}
