"""Deterministic multi-day QuantX dashboard derivations.

The module only reads Tickflow's own ``data/quantx`` snapshots.  It does not
consume QuantX HTML reports, editor decisions, or any LLM-owned artifact.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.market_facts.registry import DatasetId, get_route
from app.market_facts.repository import MarketFactRepository

from .io import read_json, validate_trade_date, write_json_atomic

SCHEMA_VERSION = "tickflow-quantx-multiday-v3"
WINDOWS = (5, 10, 20)


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        number = float(str(value).replace("%", "").replace(",", ""))
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int | None = None) -> int | None:
    number = _number(value)
    return int(number) if number is not None else default


def _canonical_theme(value: Any) -> str:
    name = re.sub(r"\s+", "", str(value or "").strip())
    aliases = {
        "人工智能概念": "人工智能",
        "AI算力": "算力",
        "机器人概念": "机器人",
        "数据中心概念": "数据中心",
    }
    return aliases.get(name, name)


def _fact_dates(repo: MarketFactRepository) -> list[date]:
    return repo.available_dates(DatasetId.MARKET_STATE_DAILY)


def _rank_strength(rank: int, total: int) -> float:
    return 100.0 if total <= 1 else round(100 * (1 - (rank - 1) / (total - 1)), 1)


def _theme_leaders(
    repo: MarketFactRepository,
    trade_date: date,
) -> dict[str, list[dict[str, str]]]:
    members = repo.get_theme_members(trade_date)
    leaders: dict[str, list[dict[str, str]]] = defaultdict(list)
    for stock in members.to_dicts():
        theme = _canonical_theme(stock.get("theme_name"))
        code = str(stock.get("symbol") or "")
        if theme and code and len(leaders[theme]) < 3:
            leaders[theme].append(
                {"code": code, "name": str(stock.get("name") or "")}
            )
    return dict(leaders)


def _themes(repo: MarketFactRepository, trade_date: date) -> list[dict[str, Any]]:
    observations = repo.get_theme_observations(trade_date)
    merged: dict[str, dict[str, Any]] = {}
    if observations.is_empty():
        return []
    for source in observations["source"].unique(maintain_order=True).to_list():
        source_rows = observations.filter(pl.col("source") == source).sort(
            "rank", nulls_last=True
        ).to_dicts()
        usable = [row for row in source_rows if _canonical_theme(row.get("theme_name"))]
        for fallback_rank, row in enumerate(usable, start=1):
            raw_name = str(row.get("theme_name") or "")
            value = _number(row.get("strength"), _number(row.get("stock_count")))
            rank = _integer(row.get("rank"), fallback_rank) or fallback_rank
            name = _canonical_theme(raw_name)
            item = merged.setdefault(name, {"name": name, "raw_names": set(), "sources": {}, "rank_strength": 0.0})
            item["raw_names"].add(raw_name)
            existing = item["sources"].get(source)
            candidate = {"rank": rank, "value": value, "rank_strength": _rank_strength(rank, len(usable))}
            if existing is None or rank < existing["rank"]:
                item["sources"][source] = candidate
    leaders = _theme_leaders(repo, trade_date)
    result = []
    for item in merged.values():
        source_rows = list(item["sources"].values())
        result.append(
            {
                "name": item["name"],
                "raw_names": sorted(item["raw_names"]),
                "sources": item["sources"],
                "source_count": len(source_rows),
                "rank_strength": round(sum(row["rank_strength"] for row in source_rows) / len(source_rows), 1),
                "leaders": leaders.get(item["name"], []),
            }
        )
    return sorted(result, key=lambda item: (-item["source_count"], -item["rank_strength"], item["name"]))[:40]


def _preferred_frame(frame: pl.DataFrame, dataset_id: DatasetId) -> pl.DataFrame:
    if frame.is_empty() or "source" not in frame.columns:
        return frame
    for source in get_route(dataset_id).sources:
        selected = frame.filter(pl.col("source") == source)
        if not selected.is_empty():
            return selected
    return frame.head(0)


def _sector_rows(repo: MarketFactRepository, trade_date: date) -> list[dict[str, Any]]:
    frame = _preferred_frame(
        repo.get_sector_flows(trade_date), DatasetId.SECTOR_FLOW_DAILY
    )
    return [
        {
            "name": str(row.get("sector_name") or ""),
            "code": str(row.get("sector_id") or ""),
            "pct_chg": _number(row.get("pct_chg")),
            "net_inflow_yi": _number(row.get("net_inflow_yi")),
            "amount_yi": _number(row.get("amount_yi")),
            "net_inflow_pct": None,
            "source": str(row.get("source") or ""),
        }
        for row in frame.to_dicts()
        if str(row.get("sector_name") or "").strip()
    ]


def _rule_candidates(repo: MarketFactRepository, trade_date: date) -> list[dict[str, Any]]:
    candidates = repo.get_screening_candidates(trade_date)
    return [
        {
            "code": str(item.get("symbol") or ""),
            "name": item.get("name"),
            "priority": item.get("priority") or "rule",
            "score": _number(item.get("score")),
            "pct_chg": _number(item.get("pct_chg")),
            "net_mf_yi": _number(item.get("net_mf_yi")),
            "industry": item.get("industry"),
            "source": item.get("candidate_type") or "deterministic_rule_screen",
        }
        for item in candidates.head(40).to_dicts()
        if item.get("symbol")
    ]


def _metrics(repo: MarketFactRepository, trade_date: date) -> dict[str, Any]:
    frame = repo.get_market_state(trade_date)
    if frame.is_empty():
        return {}
    state = frame.row(0, named=True)
    return {
        "market_heat_score": _number(state.get("market_heat_score")),
        "market_heat_zone": state.get("market_heat_zone"),
        "short_term_sentiment_score": _number(state.get("short_term_sentiment_score")),
        "trend_sentiment_score": _number(state.get("trend_sentiment_score")),
        "sentiment_semantics_version": _integer(state.get("sentiment_semantics_version"), 1),
        "up_ratio": _number(state.get("up_ratio_pct")),
        "up_count": _integer(state.get("up_count")),
        "down_count": _integer(state.get("down_count")),
        "limit_up_count": _integer(state.get("limit_up_count")),
        "limit_down_count": _integer(state.get("limit_down_count")),
        "seal_rate": _number(state.get("seal_rate_pct")),
        "max_board": _integer(state.get("max_board")),
        "advance_rate": _number(state.get("advance_rate_pct")),
        "premium_rate": _number(state.get("premium_rate_pct")),
        "loss_severity": state.get("loss_severity"),
        "ebb_signal_count": _integer(state.get("ebb_signal_count")),
        "crash_triggered": bool(state.get("crash_triggered")),
        "participation_verdict": state.get("participation_verdict"),
        "total_amount_yi": _number(state.get("total_amount_yi")),
    }


def _record(repo: MarketFactRepository, trade_date: date) -> dict[str, Any]:
    observations = repo.get_theme_observations(trade_date)
    ths = observations.filter(pl.col("source") == "ths_hot").sort(
        "rank", nulls_last=True
    ) if not observations.is_empty() else observations
    return {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "stage": "canonical",
        "metrics": _metrics(repo, trade_date),
        "themes": _themes(repo, trade_date),
        "factor_attribution": [
            {
                "name": _canonical_theme(item.get("theme_name")),
                "count": _integer(item.get("stock_count"), _integer(item.get("strength"), 0)),
            }
            for item in ths.head(12).to_dicts()
            if _canonical_theme(item.get("theme_name"))
        ],
        "market_activity": {
            "sectors": _sector_rows(repo, trade_date),
            "rule_candidates": _rule_candidates(repo, trade_date),
        },
    }


def _decorate_theme_lifecycle(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_valid: list[dict[str, dict[str, Any]]] = []
    events: list[dict[str, Any]] = []
    for record in records:
        current = {item["name"]: item for item in record["themes"]}
        previous = previous_valid[-1] if previous_valid else {}
        decorated = []
        for name, item in current.items():
            streak = 1
            for historical in reversed(previous_valid):
                if name not in historical:
                    break
                streak += 1
            old = previous.get(name)
            if old is None and all(name not in row for row in previous_valid[-3:]):
                lifecycle = "new"
            elif old is None:
                lifecycle = "continuing"
            elif item["source_count"] > old["source_count"] or item["rank_strength"] > old["rank_strength"] + 5:
                lifecycle = "strengthening"
            elif item["source_count"] < old["source_count"] or item["rank_strength"] < old["rank_strength"] - 5:
                lifecycle = "weakening"
            else:
                lifecycle = "continuing"
            enriched = {**item, "streak": streak, "lifecycle": lifecycle, "consensus": item["source_count"] >= 2}
            decorated.append(enriched)
            events.append({"trade_date": record["trade_date"], "name": name, "lifecycle": lifecycle, "streak": streak, "source_count": item["source_count"]})
        for name, old in previous.items():
            if name not in current and int(old.get("streak", 1)) >= 2:
                events.append({"trade_date": record["trade_date"], "name": name, "lifecycle": "exited", "streak": old.get("streak", 1), "source_count": 0})
        record["themes"] = sorted(decorated, key=lambda item: (-item["source_count"], -item["rank_strength"], item["name"]))
        previous_valid.append({item["name"]: item for item in record["themes"]})
    return events


def _component(key: str, values: list[float | None], threshold: float, *, reverse: bool = False) -> dict[str, Any]:
    valid = [value for value in values if value is not None]
    first, last = (valid[0], valid[-1]) if valid else (None, None)
    if first is None or last is None:
        arrow = "missing"
    elif abs(last - first) < threshold:
        arrow = "flat"
    else:
        arrow = "up" if last > first else "down"
    display = "down" if reverse and arrow == "up" else "up" if reverse and arrow == "down" else arrow
    return {"key": key, "first": first, "last": last, "delta": round(last - first, 2) if first is not None and last is not None else None, "arrow": display}


def _sector_flow_continuity(records: list[dict[str, Any]]) -> dict[str, Any]:
    industries: dict[str, dict[str, Any]] = {}
    stocks: dict[str, dict[str, Any]] = {}
    for record in records:
        for item in (record.get("market_activity") or {}).get("sectors") or []:
            name = item["name"]
            row = industries.setdefault(name, {"name": name, "active_days": 0, "net_inflow_sum_yi": 0.0, "last_net_inflow_yi": None, "last_pct_chg": None, "last_seen": None, "source": item.get("source")})
            row["active_days"] += 1
            row["net_inflow_sum_yi"] += _number(item.get("net_inflow_yi"), 0.0) or 0.0
            row["last_net_inflow_yi"] = item.get("net_inflow_yi")
            row["last_pct_chg"] = item.get("pct_chg")
            row["last_seen"] = record["trade_date"]
        for item in (record.get("market_activity") or {}).get("rule_candidates") or []:
            code = item.get("code")
            if not code:
                continue
            row = stocks.setdefault(code, {**item, "active_days": 0, "last_seen": None})
            row.update({key: value for key, value in item.items() if value is not None})
            row["active_days"] += 1
            row["last_seen"] = record["trade_date"]
    industry_rows = list(industries.values())
    for row in industry_rows:
        row["net_inflow_sum_yi"] = round(row["net_inflow_sum_yi"], 2)
    industry_rows.sort(key=lambda item: (-abs(item["net_inflow_sum_yi"]), -item["active_days"], item["name"]))
    stock_rows = sorted(stocks.values(), key=lambda item: (-item["active_days"], -(item.get("score") or 0), item["code"]))
    observed_days = sum(
        bool((record.get("market_activity") or {}).get("sectors")) for record in records
    )
    return {
        "semantics": "sector_flow_and_rule_candidates",
        "basis": "sector_flow_daily.net_inflow_yi + screening_candidate_daily",
        "available": observed_days > 0,
        "coverage": round(observed_days / len(records), 3) if records else 0.0,
        "industries": industry_rows[:20],
        "rule_candidates": stock_rows[:20],
        "direction": (
            f"{'净流入' if industry_rows[0]['net_inflow_sum_yi'] >= 0 else '净流出'}:{industry_rows[0]['name']}连续{industry_rows[0]['active_days']}日"
            if industry_rows
            else "暂无行业资金连续性数据"
        ),
    }


def _window_theme_structure(records: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [record for record in records if record.get("themes")]
    if not observed:
        return {"observed_days": 0, "mainline": [], "warming": [], "cooling": []}

    split = max(1, len(observed) // 2)
    early_count = split
    recent_count = len(observed) - split
    if recent_count == 0:
        recent_count = 1
        split = len(observed) - 1

    names = {
        item["name"]
        for record in observed
        for item in record.get("themes") or []
        if item.get("name")
    }
    latest_by_name = {
        item["name"]: item for item in observed[-1].get("themes") or [] if item.get("name")
    }
    rows: list[dict[str, Any]] = []
    for name in names:
        values = []
        active_days = 0
        for record in observed:
            item = next(
                (theme for theme in record.get("themes") or [] if theme.get("name") == name),
                None,
            )
            strength = float(item.get("rank_strength") or 0) if item else 0.0
            values.append(strength)
            active_days += int(item is not None)
        early_average = sum(values[:early_count]) / early_count
        recent_average = sum(values[split:]) / recent_count
        latest = latest_by_name.get(name) or {}
        rows.append(
            {
                "name": name,
                "active_days": active_days,
                "persistence_pct": round(active_days / len(observed) * 100, 1),
                "average_strength": round(sum(values) / len(observed), 1),
                "strength_change": round(recent_average - early_average, 1),
                "latest_strength": round(values[-1], 1),
                "source_count": latest.get("source_count", 0),
                "leaders": latest.get("leaders", []),
            }
        )

    minimum_mainline_days = max(1, math.ceil(len(observed) * 0.6))
    mainline = sorted(
        (row for row in rows if row["active_days"] >= minimum_mainline_days),
        key=lambda row: (-row["persistence_pct"], -row["average_strength"], row["name"]),
    )
    warming = sorted(
        (row for row in rows if row["latest_strength"] > 0 and row["strength_change"] >= 8),
        key=lambda row: (-row["strength_change"], -row["latest_strength"], row["name"]),
    )
    cooling = sorted(
        (row for row in rows if row["strength_change"] <= -8),
        key=lambda row: (row["strength_change"], row["name"]),
    )
    return {
        "observed_days": len(observed),
        "mainline": mainline[:8],
        "warming": warming[:8],
        "cooling": cooling[:8],
    }


def _window_signal(records: list[dict[str, Any]], window: int) -> dict[str, Any]:
    scoped = records[-window:]
    metrics = [record["metrics"] for record in scoped]
    heat = _component("heat", [item.get("market_heat_score") for item in metrics], 3)
    breadth = _component("breadth", [item.get("up_ratio") for item in metrics], 3)
    relay = _component("relay", [item.get("max_board") for item in metrics], 1)
    risk_values = [(_number(item.get("limit_down_count"), 0) or 0) + (20 if item.get("crash_triggered") else 0) for item in metrics]
    risk = _component("risk", risk_values, 2)
    positive = sum(item["arrow"] == "up" for item in (heat, breadth, relay))
    negative = sum(item["arrow"] == "down" for item in (heat, breadth, relay))
    if negative >= 2 and risk["arrow"] == "up":
        direction, tone = "退潮", "negative"
    elif heat["last"] is not None and heat["last"] >= 70 and negative and risk["arrow"] == "up":
        direction, tone = "高位钝化", "warning"
    elif heat["last"] is not None and heat["last"] < 45 and positive >= 2 and risk["arrow"] != "up":
        direction, tone = "低位修复", "neutral"
    elif positive >= 2 and risk["arrow"] != "up":
        direction, tone = "升温", "positive"
    else:
        direction, tone = "分歧轮动", "neutral"
    themes = _window_theme_structure(scoped)
    valid_ratio = len(scoped) / window
    confidence = "high" if valid_ratio >= 0.85 else "medium" if valid_ratio >= 0.6 else "low"
    sector_flow = _sector_flow_continuity(scoped)
    return {
        "window": window,
        "date_range": [scoped[0]["trade_date"], scoped[-1]["trade_date"]] if scoped else [],
        "valid_days": len(scoped),
        "confidence": confidence,
        "market": {"direction": direction, "tone": tone, "components": [heat, breadth, relay, risk]},
        "themes": themes,
        "sector_flow": sector_flow,
    }


def _summary(values: Iterable[Any]) -> dict[str, float | None]:
    usable = [_number(value) for value in values]
    valid = [value for value in usable if value is not None]
    return {
        "average": round(sum(valid) / len(valid), 2) if valid else None,
        "max": max(valid) if valid else None,
        "min": min(valid) if valid else None,
    }


def _window_statistics(records: list[dict[str, Any]], window: int) -> dict[str, Any]:
    scoped = records[-window:]
    return {
        "valid_days": len(scoped),
        "market_heat": _summary(record["metrics"].get("market_heat_score") for record in scoped),
        "limit_up": _summary(record["metrics"].get("limit_up_count") for record in scoped),
        "seal_rate": _summary(record["metrics"].get("seal_rate") for record in scoped),
        "max_board": _summary(record["metrics"].get("max_board") for record in scoped),
        "risk_days": sum(bool(record["metrics"].get("crash_triggered")) for record in scoped),
    }


def _theme_heatmap(records: list[dict[str, Any]]) -> dict[str, Any]:
    scoped = records[-20:]
    totals: dict[str, float] = defaultdict(float)
    by_date: dict[str, dict[str, float]] = {}
    for record in scoped:
        daily = {item["name"]: float(item.get("rank_strength") or 0) for item in record.get("themes") or []}
        by_date[record["trade_date"]] = daily
        for name, value in daily.items():
            totals[name] += value
    names = [name for name, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:16]]
    return {
        "dates": [record["trade_date"] for record in scoped],
        "rows": [{"name": name, "values": [by_date.get(record["trade_date"], {}).get(name) for record in scoped]} for name in names],
    }


def _opportunity_weights(window: int, valid_days: int) -> list[float]:
    if valid_days <= 0:
        return []
    if window == 5:
        return [0.1, 0.1, 0.15, 0.15, 0.5][-valid_days:]
    denominator = sum(range(1, window + 1))
    return [value / denominator for value in range(1, window + 1)][-valid_days:]


def _opportunity_window(
    records: list[dict[str, Any]], window: int
) -> dict[str, Any]:
    scoped = records[-window:]
    weights = _opportunity_weights(window, len(scoped))
    theme_scores: dict[str, dict[str, Any]] = {}
    sector_scores: dict[str, dict[str, Any]] = {}
    stock_scores: dict[str, dict[str, Any]] = {}
    for weight, record in zip(weights, scoped, strict=False):
        for item in record.get("themes") or []:
            row = theme_scores.setdefault(
                item["name"],
                {
                    "name": item["name"],
                    "score": 0.0,
                    "active_days": 0,
                    "last_seen": record["trade_date"],
                    "lifecycle": item.get("lifecycle"),
                    "leaders": item.get("leaders", []),
                },
            )
            row["score"] += weight * float(item.get("rank_strength") or 0)
            row["active_days"] += 1
            row.update(
                {
                    "last_seen": record["trade_date"],
                    "lifecycle": item.get("lifecycle"),
                    "leaders": item.get("leaders", []),
                }
            )
        for item in (record.get("market_activity") or {}).get("sectors") or []:
            row = sector_scores.setdefault(
                item["name"],
                {
                    "name": item["name"],
                    "score": 0.0,
                    "active_days": 0,
                    "last_seen": record["trade_date"],
                    "net_inflow_sum_yi": 0.0,
                    "last_net_inflow_yi": item.get("net_inflow_yi"),
                    "last_pct_chg": item.get("pct_chg"),
                },
            )
            flow = max(-50.0, min(50.0, _number(item.get("net_inflow_yi"), 0.0) or 0.0))
            price = max(-10.0, min(10.0, _number(item.get("pct_chg"), 0.0) or 0.0))
            row["score"] += weight * (50 + flow + price * 2.5)
            row["active_days"] += 1
            row["net_inflow_sum_yi"] += _number(item.get("net_inflow_yi"), 0.0) or 0.0
            row.update(
                {
                    "last_seen": record["trade_date"],
                    "last_net_inflow_yi": item.get("net_inflow_yi"),
                    "last_pct_chg": item.get("pct_chg"),
                }
            )
        leader_codes = {
            leader["code"]: leader
            for theme in record.get("themes") or []
            for leader in theme.get("leaders") or []
            if leader.get("code")
        }
        cores = {
            item["code"]: item
            for item in (record.get("market_activity") or {}).get("rule_candidates")
            or []
            if item.get("code")
        }
        for code, item in {**leader_codes, **cores}.items():
            row = stock_scores.setdefault(
                code,
                {
                    "code": code,
                    "name": item.get("name"),
                    "score": 0.0,
                    "active_days": 0,
                    "last_seen": record["trade_date"],
                    "priority": item.get("priority") or "题材龙头",
                    "source": item.get("source", "theme_leader"),
                },
            )
            row["score"] += weight * (70 if code in cores else 55)
            row["active_days"] += 1
            row.update(
                {
                    "name": item.get("name") or row.get("name"),
                    "last_seen": record["trade_date"],
                    "priority": item.get("priority") or row.get("priority"),
                    "source": item.get("source") or row.get("source"),
                }
            )
    for collection in (theme_scores, sector_scores, stock_scores):
        for row in collection.values():
            row["score"] = round(max(0.0, min(100.0, row["score"])), 1)
    for row in sector_scores.values():
        row["net_inflow_sum_yi"] = round(row["net_inflow_sum_yi"], 2)
    coverage = {
        "themes": round(sum(bool(record.get("themes")) for record in scoped) / window, 2),
        "sectors": round(
            sum(bool((record.get("market_activity") or {}).get("sectors")) for record in scoped)
            / window,
            2,
        ),
        "stocks": round(
            sum(
                bool((record.get("market_activity") or {}).get("rule_candidates"))
                for record in scoped
            )
            / window,
            2,
        ),
    }
    return {
        "window": window,
        "valid_days": len(scoped),
        "date_range": [scoped[0]["trade_date"], scoped[-1]["trade_date"]]
        if scoped
        else [],
        "coverage_confidence": coverage,
        "themes": sorted(theme_scores.values(), key=lambda item: (-item["score"], item["name"]))[:12],
        "sectors": sorted(sector_scores.values(), key=lambda item: (-item["score"], item["name"]))[:12],
        "stocks": sorted(stock_scores.values(), key=lambda item: (-item["score"], item["code"]))[:16],
    }


def _opportunity_radar(records: list[dict[str, Any]]) -> dict[str, Any]:
    windows = {
        str(window): _opportunity_window(records, window) for window in (5, 20)
    }
    default = windows["5"]
    return {
        "schema_version": "opportunity-radar-v2",
        "default_window": 5,
        "windows": windows,
        # v1 compatibility for existing API consumers and portable exports.
        "coverage_confidence": default["coverage_confidence"],
        "themes": default["themes"],
        "sectors": default["sectors"],
        "stocks": default["stocks"],
    }


def _snapshot_from_records(records: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    latest = records[-1]
    trade_date = latest["trade_date"]
    current_names = {item["name"] for item in latest["themes"]}
    latest_events = [event for event in events if event["trade_date"] == trade_date]
    sector_flow_continuity = _sector_flow_continuity(records[-20:])
    sector_flow_days = sum(
        bool((record.get("market_activity") or {}).get("sectors"))
        for record in records[-20:]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "llm": False,
        "window_signals": {str(window): _window_signal(records, window) for window in WINDOWS},
        "calendar": [{"trade_date": record["trade_date"], **record["metrics"]} for record in records[-60:]],
        "window_statistics": {str(window): _window_statistics(records, window) for window in WINDOWS},
        "theme_lifecycle": {
            "current": latest["themes"],
            "events": latest_events,
            "exited": [event for event in latest_events if event["lifecycle"] == "exited" and event["name"] not in current_names],
            "heatmap": _theme_heatmap(records),
        },
        "factor_attribution": latest["factor_attribution"],
        "opportunity_radar": _opportunity_radar(records),
        "sector_flow_continuity": sector_flow_continuity,
        "data_coverage": {
            "theme_days": sum(bool(record["themes"]) for record in records[-20:]),
            "sector_flow_days": sector_flow_days,
            "window_days": min(20, len(records)),
        },
    }


def build_multiday_snapshot(quantx_dir: Path, trade_date: str) -> dict[str, Any]:
    validate_trade_date(trade_date)
    quantx_dir = Path(quantx_dir).resolve()
    repo = MarketFactRepository(quantx_dir.parent)
    selected_day = datetime.strptime(trade_date, "%Y%m%d").date()
    dates = [value for value in _fact_dates(repo) if value <= selected_day]
    if not dates or dates[-1] != selected_day:
        raise FileNotFoundError(trade_date)
    records = [_record(repo, value) for value in dates]
    events = _decorate_theme_lifecycle(records)
    return _snapshot_from_records(records, events)


def load_multiday_snapshot(quantx_dir: Path, trade_date: str) -> dict[str, Any]:
    validate_trade_date(trade_date)
    path = Path(quantx_dir) / trade_date / "multiday_snapshot.json"
    cached = read_json(path)
    radar = cached.get("opportunity_radar") if isinstance(cached, dict) else None
    if (
        isinstance(cached, dict)
        and cached.get("schema_version") == SCHEMA_VERSION
        and isinstance(radar, dict)
        and radar.get("schema_version") == "opportunity-radar-v2"
    ):
        return cached
    return build_multiday_snapshot(quantx_dir, trade_date)


def rebuild_multiday_snapshots(quantx_dir: Path) -> dict[str, Any]:
    quantx_dir = Path(quantx_dir).resolve()
    repo = MarketFactRepository(quantx_dir.parent)
    dates = _fact_dates(repo)
    records = [_record(repo, value) for value in dates]
    events = _decorate_theme_lifecycle(records)
    for index, trade_date in enumerate(dates):
        snapshot = _snapshot_from_records(records[: index + 1], events)
        date_dir = quantx_dir / trade_date.strftime("%Y%m%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(date_dir / "multiday_snapshot.json", snapshot)
    from .catalog import build_and_save_catalog

    catalog = build_and_save_catalog(quantx_dir)
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "rebuilt": len(dates), "stats": catalog["stats"]}


def rebuild_multiday_snapshot(quantx_dir: Path, trade_date: str | None = None) -> dict[str, Any]:
    """Persist one selected/latest snapshot for an interactive rebuild."""
    quantx_dir = Path(quantx_dir).resolve()
    repo = MarketFactRepository(quantx_dir.parent)
    dates = _fact_dates(repo)
    selected = trade_date or (dates[-1].strftime("%Y%m%d") if dates else None)
    if selected is None:
        raise FileNotFoundError("no QuantX dates")
    snapshot = build_multiday_snapshot(quantx_dir, selected)
    write_json_atomic(quantx_dir / selected / "multiday_snapshot.json", snapshot)
    from .catalog import build_and_save_catalog

    catalog = build_and_save_catalog(quantx_dir)
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "trade_date": selected, "rebuilt": 1, "stats": catalog["stats"]}
