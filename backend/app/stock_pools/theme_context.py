"""Dated leaderboard context for topics already present in the stock pool."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.market_facts.registry import DatasetId, get_route
from app.stock_pools.topic_cluster import _norm

VERSION = "source-rank-v2"
WINDOW = 5
SOURCES = get_route(DatasetId.THEME_OBSERVATION_DAILY).sources


def build_theme_context(
    trade_date: date,
    trading_days: list[date],
    observations: list[dict[str, Any]],
    labels: set[str],
    dynamic_labels: set[str],
    term_labels: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Compare a topic only within each source's own dated top-N list."""
    days = sorted({day.isoformat() for day in trading_days if day <= trade_date})[-WINDOW:]
    target = trade_date.isoformat()
    aliases: dict[str, set[str]] = {label: {_norm(label)} for label in labels}
    for term, label in term_labels.items():
        if label in aliases:
            aliases[label].add(_norm(term))
    owners: dict[str, set[str]] = defaultdict(set)
    for label, names in aliases.items():
        for name in names:
            if name:
                owners[name].add(label)

    available: dict[tuple[str, str], int] = defaultdict(int)
    daily_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    matches: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    conflicts: set[tuple[str, str, str]] = set()
    for row in observations:
        day = str(row.get("trade_date") or "")[:10]
        source = str(row.get("source") or "")
        if day not in days or source not in SOURCES:
            continue
        available[(day, source)] += 1
        daily_rows[(day, source)].append(row)
        labels_for_name = owners.get(_norm(str(row.get("theme_name") or "")), set())
        if len(labels_for_name) == 1:
            label = next(iter(labels_for_name))
            matches[(day, source, label)].append(row)
        elif len(labels_for_name) > 1:
            conflicts.update((day, source, label) for label in labels_for_name)

    def first_rank(day: str, source: str, label: str) -> dict[str, Any] | None:
        rows = matches.get((day, source, label), [])
        return min(rows, key=lambda row: (row.get("rank") is None, row.get("rank") or 0)) if rows else None

    contexts: dict[str, dict[str, Any]] = {}
    for label in sorted(labels):
        source_contexts = []
        for source in SOURCES:
            current = first_rank(target, source, label)
            normalized_label = _norm(label)
            related = [
                {"name": str(row.get("theme_name")), "rank": row.get("rank")}
                for row in daily_rows[(target, source)]
                if len(normalized_label) >= 2
                and normalized_label in _norm(str(row.get("theme_name") or ""))
                and _norm(str(row.get("theme_name") or "")) != normalized_label
            ]
            related.sort(key=lambda row: (row["rank"] is None, row["rank"] or 0, row["name"]))
            prior = next((day for day in reversed(days) if day < target and available[(day, source)]), None)
            previous = first_rank(prior, source, label) if prior else None
            available_days = sum(bool(available[(day, source)]) for day in days)
            seen_days = sum(bool(matches.get((day, source, label))) for day in days)
            status = "ranked" if current else "not_ranked" if available[(target, source)] else "unavailable"
            if (target, source, label) in conflicts and not current:
                status = "ambiguous"
            source_contexts.append({
                "source": source,
                "status": status,
                "rank": current.get("rank") if current else None,
                "list_size": available[(target, source)] or None,
                "previous_date": prior,
                "previous_rank": previous.get("rank") if previous else None,
                "seen_days": seen_days,
                "available_days": available_days,
                "raw_name": current.get("theme_name") if current else None,
                "match_basis": (
                    "name" if _norm(str(current.get("theme_name"))) == _norm(label) else "dated_term"
                ) if current else None,
                "observed_at": current.get("observed_at") if current else None,
                "quality_level": current.get("quality_level") if current else None,
                "related_narrower": related[:2],
            })
        contexts[label] = {
            "basis": "dated_logic" if label in dynamic_labels else "latest_static_proxy",
            "window_start": days[0] if days else None,
            "sources": source_contexts,
        }
    return contexts
