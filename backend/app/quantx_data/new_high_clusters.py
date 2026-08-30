"""Deterministic concept and industry clusters for 100-day-high stocks."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from typing import Any

import polars as pl

from app.market_facts.registry import DatasetId
from app.market_facts.repository import MarketFactRepository
from app.services.ext_data import ExtConfigStore
from app.services.market_overview_builder import (
    _dimension_field,
    _dimension_values,
    _read_ext_rows,
    _symbol_keys,
)

WINDOWS = (1, 5, 10, 20)
DIMENSIONS = ("concept", "industry_level1", "industry_level2")
_INDUSTRY_SPLIT = re.compile(r"\s*[-—>]+\s*")
_CONCEPT_NOISE = re.compile(
    r"(?:百日新高|近期新高|趋势股|昨日|高振幅|高换手|热股|打板|首板|连板|"
    r"融资融券|沪股通|深股通|陆股通|MSCI|富时罗素|中证\d+|上证\d+|深成\d+)",
    re.IGNORECASE,
)


def _symbol(value: Any) -> str:
    text = str(value or "").strip().upper().split(".", 1)[0]
    digits = "".join(character for character in text if character.isdigit())
    return digits[-6:].zfill(6) if digits else text


def _round(value: float) -> float:
    return round(value + 1e-12, 2)


def _is_investable_concept(value: str) -> bool:
    return len(value.strip()) >= 2 and not _CONCEPT_NOISE.search(value)


def _load_memberships(data_dir) -> dict[str, dict[str, set[str]]]:
    memberships: dict[str, dict[str, set[str]]] = {
        dimension: defaultdict(set) for dimension in DIMENSIONS
    }
    for config in ExtConfigStore(data_dir).load_all():
        concept_field = _dimension_field(config, "concept")
        if concept_field:
            for row in _read_ext_rows(data_dir, config, concept_field):
                concepts = {
                    value
                    for value in _dimension_values(row.get(concept_field))
                    if _is_investable_concept(value)
                }
                for key in _symbol_keys(row, config):
                    memberships["concept"][_symbol(key)].update(concepts)

        industry_field = _dimension_field(config, "industry")
        if industry_field:
            for row in _read_ext_rows(data_dir, config, industry_field):
                paths = _dimension_values(row.get(industry_field))
                levels: dict[str, set[str]] = {
                    "industry_level1": set(),
                    "industry_level2": set(),
                }
                for path in paths:
                    parts = [part.strip() for part in _INDUSTRY_SPLIT.split(path) if part.strip()]
                    if parts:
                        levels["industry_level1"].add(parts[0])
                    if len(parts) >= 2:
                        levels["industry_level2"].add(parts[1])
                for key in _symbol_keys(row, config):
                    normalized = _symbol(key)
                    for dimension, values in levels.items():
                        memberships[dimension][normalized].update(values)
    return memberships


def _new_high_rows(facts: MarketFactRepository, trade_date: date) -> dict[str, dict[str, Any]]:
    frame = facts.get_screening_candidates(trade_date)
    if frame.is_empty():
        return {}
    frame = frame.filter(
        pl.col("included") & (pl.col("candidate_type") == "new_high_100d")
    )
    return {
        _symbol(row["symbol"]): {
            "code": _symbol(row["symbol"]),
            "name": str(row.get("name") or ""),
            "pct_chg": row.get("pct_chg"),
        }
        for row in frame.to_dicts()
    }


def _daily_snapshot(
    facts: MarketFactRepository,
    trade_date: date,
    memberships: dict[str, dict[str, set[str]]],
) -> dict[str, Any]:
    stocks = _new_high_rows(facts, trade_date)
    symbols = set(stocks)
    grouped: dict[str, dict[str, set[str]]] = {}
    for dimension in DIMENSIONS:
        by_name: dict[str, set[str]] = defaultdict(set)
        for symbol in symbols:
            for name in memberships[dimension].get(symbol, set()):
                by_name[name].add(symbol)
        grouped[dimension] = by_name
    return {
        "trade_date": trade_date,
        "symbols": symbols,
        "stocks": stocks,
        "total": len(symbols),
        "dimensions": grouped,
    }


def _labels_for_symbol(daily: dict[str, Any], dimension: str, symbol: str) -> set[str]:
    return {
        name
        for name, symbols in daily["dimensions"][dimension].items()
        if symbol in symbols
    }


def _status(shares: list[float], active_days: int) -> str:
    if len(shares) == 1:
        return "当日集中"
    split = max(1, len(shares) // 2)
    early = sum(shares[:split]) / split
    recent_values = shares[split:] or shares[-1:]
    recent = sum(recent_values) / len(recent_values)
    change = recent - early
    if early == 0 and recent > 0:
        return "新生"
    if change >= 2:
        return "扩散"
    if change <= -2:
        return "收缩"
    if active_days >= math.ceil(len(shares) * 0.6):
        return "持续"
    return "轮动"


def _aggregate_dimension(days: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    names = {name for daily in days for name in daily["dimensions"][dimension]}
    current = days[-1]
    rows: list[dict[str, Any]] = []
    for name in names:
        shares: list[float] = []
        all_symbols: set[str] = set()
        active_days = 0
        for daily in days:
            member_symbols = daily["dimensions"][dimension].get(name, set())
            all_symbols.update(member_symbols)
            if member_symbols:
                active_days += 1
            shares.append(
                len(member_symbols) / daily["total"] * 100 if daily["total"] else 0.0
            )

        split = max(1, len(shares) // 2)
        early = sum(shares[:split]) / split
        recent_values = shares[split:] or shares[-1:]
        recent = sum(recent_values) / len(recent_values)
        current_members = current["dimensions"][dimension].get(name, set())
        weighted_count = sum(
            1 / len(labels)
            for symbol in current_members
            if (labels := _labels_for_symbol(current, dimension, symbol))
        )
        weighted_share = (
            weighted_count / current["total"] * 100 if current["total"] else 0.0
        )
        rows.append(
            {
                "name": name,
                "current_count": len(current_members),
                "unique_count": len(all_symbols),
                "active_days": active_days,
                "average_share_pct": _round(sum(shares) / len(shares)),
                "current_share_pct": _round(shares[-1]),
                "weighted_share_pct": _round(weighted_share),
                "change_pct": _round(recent - early),
                "status": _status(shares, active_days),
            }
        )
    rows.sort(
        key=lambda row: (
            row["current_count"] > 0,
            row["current_share_pct"],
            row["average_share_pct"],
            row["active_days"],
            row["name"],
        ),
        reverse=True,
    )
    return rows[:20]


def build_new_high_cluster_members(
    facts: MarketFactRepository,
    trade_date: date,
    *,
    dimension: str,
    window: int,
    name: str,
) -> dict[str, Any]:
    """Return complete member evidence for one new-high cluster on demand."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"unsupported new-high dimension: {dimension}")
    if window not in WINDOWS:
        raise ValueError(f"unsupported new-high window: {window}")
    cluster_name = name.strip()
    if not cluster_name:
        raise ValueError("cluster name must not be empty")

    memberships = _load_memberships(facts.data_dir)
    available = [
        value
        for value in facts.available_dates(DatasetId.SCREENING_CANDIDATE_DAILY)
        if value <= trade_date
    ][-window:]
    if not available or available[-1] != trade_date:
        available.append(trade_date)
    days = [_daily_snapshot(facts, value, memberships) for value in available]

    by_symbol: dict[str, dict[str, Any]] = {}
    for daily in days:
        member_symbols = daily["dimensions"][dimension].get(cluster_name, set())
        observed = daily["trade_date"].strftime("%Y%m%d")
        for symbol in member_symbols:
            source = daily["stocks"].get(symbol, {})
            item = by_symbol.setdefault(
                symbol,
                {
                    "code": symbol,
                    "name": str(source.get("name") or ""),
                    "pct_chg": source.get("pct_chg"),
                    "current": False,
                    "active_days": 0,
                    "first_seen": observed,
                    "last_seen": observed,
                },
            )
            item["active_days"] += 1
            item["last_seen"] = observed
            if source.get("name"):
                item["name"] = str(source["name"])
            item["pct_chg"] = source.get("pct_chg")

    current_symbols = days[-1]["dimensions"][dimension].get(cluster_name, set())
    for symbol, item in by_symbol.items():
        item["current"] = symbol in current_symbols

    members = sorted(
        by_symbol.values(),
        key=lambda item: (
            not item["current"],
            -item["active_days"],
            -int(item["last_seen"]),
            item["code"],
        ),
    )
    return {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "dimension": dimension,
        "window": window,
        "cluster_name": cluster_name,
        "valid_days": len(days),
        "current_count": len(current_symbols),
        "window_count": len(members),
        "mapping_semantics": "latest_ext_snapshot_proxy",
        "members": members,
    }


def build_new_high_clusters(
    facts: MarketFactRepository,
    trade_date: date,
) -> dict[str, Any]:
    """Build multi-window new-high clusters from canonical candidates and local mappings."""
    memberships = _load_memberships(facts.data_dir)
    available = [
        value
        for value in facts.available_dates(DatasetId.SCREENING_CANDIDATE_DAILY)
        if value <= trade_date
    ][-max(WINDOWS) :]
    if not available or available[-1] != trade_date:
        available.append(trade_date)
    daily = [_daily_snapshot(facts, value, memberships) for value in available]
    latest = daily[-1]

    coverage = {}
    for dimension in DIMENSIONS:
        covered = sum(1 for symbol in latest["symbols"] if memberships[dimension].get(symbol))
        coverage[dimension] = _round(covered / latest["total"] * 100) if latest["total"] else 0.0

    windows = {}
    for window in WINDOWS:
        selected = daily[-window:]
        windows[str(window)] = {
            "valid_days": len(selected),
            "date_range": [
                selected[0]["trade_date"].strftime("%Y%m%d"),
                selected[-1]["trade_date"].strftime("%Y%m%d"),
            ],
            "dimensions": {
                dimension: _aggregate_dimension(selected, dimension)
                for dimension in DIMENSIONS
            },
        }

    return {
        "total_stocks": latest["total"],
        "coverage_pct": coverage,
        "mapping_semantics": "latest_ext_snapshot_proxy",
        "windows": windows,
    }
