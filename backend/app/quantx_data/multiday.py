"""Deterministic multi-day QuantX dashboard derivations.

The module only reads Tickflow's own ``data/quantx`` snapshots.  It does not
consume QuantX HTML reports, editor decisions, or any LLM-owned artifact.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import read_json, validate_trade_date, write_json_atomic

SCHEMA_VERSION = "tickflow-quantx-multiday-v1"
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


def _date_dirs(quantx_dir: Path) -> list[Path]:
    if not quantx_dir.is_dir():
        return []
    return [
        path
        for path in sorted(quantx_dir.iterdir(), key=lambda item: item.name)
        if path.is_dir() and len(path.name) == 8 and path.name.isdigit() and (path / "_computed.json").is_file()
    ]


def _rank_strength(rank: int, total: int) -> float:
    return 100.0 if total <= 1 else round(100 * (1 - (rank - 1) / (total - 1)), 1)


def _theme_source_rows(date_dir: Path) -> dict[str, list[tuple[str, float | None]]]:
    pywencai = read_json(date_dir / "pywencai.json", {}) or {}
    ths = read_json(date_dir / "ths_hot.json", {}) or {}
    deepq = read_json(date_dir / "deepq.json", {}) or {}
    ranking = read_json(date_dir / "theme_rankings.json", {}) or {}
    py_themes = (pywencai.get("limit_up") or {}).get("themes") or []
    deepq_themes = (deepq.get("latest_day") or {}).get("sectors") or []
    return {
        "pywencai": [(str(item.get("name") or ""), _number(item.get("count"))) for item in py_themes],
        "ths": [(str(item.get("tag") or ""), _number(item.get("count"))) for item in ths.get("reason_tags") or []],
        "deepq": [
            (
                str(item.get("name") or item.get("sectorName") or item.get("sector") or ""),
                _number(item.get("heatValue"), _number(item.get("value"))),
            )
            for item in deepq_themes
        ],
        "tickflow": [(str(item.get("name") or ""), _number(item.get("count"))) for item in ranking.get("themes") or []],
    }


def _theme_leaders(date_dir: Path) -> dict[str, list[dict[str, str]]]:
    pywencai = read_json(date_dir / "pywencai.json", {}) or {}
    leaders: dict[str, list[dict[str, str]]] = defaultdict(list)
    for stock in (pywencai.get("limit_up") or {}).get("stocks") or []:
        code = str(stock.get("code") or "")
        name = str(stock.get("name") or "")
        concepts = stock.get("concepts") or stock.get("themes") or []
        for raw_theme in concepts:
            theme = _canonical_theme(raw_theme)
            if theme and code and len(leaders[theme]) < 3:
                leaders[theme].append({"code": code, "name": name})
    return dict(leaders)


def _themes(date_dir: Path) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source, rows in _theme_source_rows(date_dir).items():
        usable = [(name, value) for name, value in rows if _canonical_theme(name)]
        for rank, (raw_name, value) in enumerate(usable, start=1):
            name = _canonical_theme(raw_name)
            item = merged.setdefault(name, {"name": name, "raw_names": set(), "sources": {}, "rank_strength": 0.0})
            item["raw_names"].add(raw_name)
            existing = item["sources"].get(source)
            candidate = {"rank": rank, "value": value, "rank_strength": _rank_strength(rank, len(usable))}
            if existing is None or rank < existing["rank"]:
                item["sources"][source] = candidate
    leaders = _theme_leaders(date_dir)
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


def _sector_rows(date_dir: Path) -> list[dict[str, Any]]:
    structured = read_json(date_dir / "sector_fund_flow.json", {}) or {}
    legacy = read_json(date_dir / "sector_fund_flow_s4.json", {}) or {}
    akshare = read_json(date_dir / "akshare.json", {}) or {}
    rows = structured.get("sectors") or legacy.get("sectors") or akshare.get("sector_fund_flow") or []
    result = []
    for raw in rows:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        result.append(
            {
                "name": name,
                "code": str(raw.get("code") or ""),
                "pct_chg": _number(raw.get("pct_chg")),
                "net_inflow_yi": _number(raw.get("net_inflow_yi")),
                "amount_yi": _number(raw.get("amount_yi")),
                "net_inflow_pct": _number(raw.get("net_inflow_pct")),
                "source": "eastmoney_s4" if legacy.get("sectors") or structured.get("sectors") else "akshare",
            }
        )
    return result


def _core_stocks(date_dir: Path) -> list[dict[str, Any]]:
    pool = read_json(date_dir / "institution_trend_pool.json", {}) or read_json(date_dir / "trend_pool.json", {}) or {}
    active = pool.get("active_pool") or pool.get("active") or []
    if active:
        return [
            {
                "code": str(item.get("code") or ""),
                "name": item.get("name"),
                "priority": item.get("priority") or "observe",
                "score": _number(item.get("score")),
                "pct_chg": _number(item.get("pct_chg")),
                "net_mf_yi": _number(item.get("net_mf_yi")),
                "industry": item.get("industry") or (item.get("theme_path") or {}).get("industry_chain"),
                "source": "institution_trend_pool",
            }
            for item in active[:40]
            if item.get("code")
        ]
    candidates = read_json(date_dir / "screening_candidates.json", {}) or {}
    return [
        {
            "code": str(item.get("code") or ""),
            "name": item.get("name"),
            "priority": "rule",
            "score": None,
            "pct_chg": None,
            "net_mf_yi": None,
            "industry": None,
            "source": "deterministic_rule_screen",
        }
        for item in (candidates.get("candidates") or [])[:40]
        if item.get("code")
    ]


def _metrics(date_dir: Path) -> dict[str, Any]:
    computed = read_json(date_dir / "_computed.json", {}) or {}
    overview = read_json(date_dir / "market_overview.json", {}) or {}
    breadth = read_json(date_dir / "market_breadth.json", {}) or overview.get("breadth") or {}
    limit = read_json(date_dir / "limit_summary.json", {}) or {}
    heat = computed.get("market_heat") or {}
    heat_inputs = heat.get("inputs") or {}
    short = computed.get("short_term_sentiment") or {}
    trend = computed.get("trend_sentiment") or {}
    loss = computed.get("loss_effect") or {}
    risk = computed.get("ebb_risk_check") or {}
    crash = computed.get("crash_signals") or {}
    participation = computed.get("participation_check") or {}
    advance = computed.get("advance_stats") or {}
    return {
        "market_heat_score": _number(heat.get("score")),
        "market_heat_zone": heat.get("zone"),
        "short_term_sentiment_score": _number(short.get("score")),
        "trend_sentiment_score": _number(trend.get("score")),
        "sentiment_semantics_version": _integer(short.get("metric_semantics_version"), 1),
        "up_ratio": _number(breadth.get("up_ratio"), _number(heat_inputs.get("up_ratio"))),
        "up_count": _integer(breadth.get("up_count")),
        "down_count": _integer(breadth.get("down_count")),
        "limit_up_count": _integer(limit.get("limit_up_count"), _integer(heat_inputs.get("limit_up_count"))),
        "limit_down_count": _integer(limit.get("limit_down_count"), _integer(loss.get("limit_down_count"))),
        "seal_rate": _number(limit.get("seal_rate"), _number(heat_inputs.get("seal_rate"))),
        "max_board": _integer(limit.get("max_board"), _integer((computed.get("height_trend") or {}).get("latest_max_board"))),
        "advance_rate": _number(advance.get("advance_rate")),
        "premium_rate": _number(advance.get("premium_rate")),
        "loss_severity": loss.get("severity"),
        "ebb_signal_count": _integer(risk.get("signal_count")),
        "crash_triggered": bool(crash.get("any_triggered")),
        "participation_verdict": participation.get("verdict"),
        "total_amount_yi": _number(overview.get("total_amount_yi")),
    }


def _record(date_dir: Path) -> dict[str, Any]:
    status = read_json(date_dir / "_pipeline_status.json", {}) or {}
    ths = read_json(date_dir / "ths_hot.json", {}) or {}
    return {
        "trade_date": date_dir.name,
        "stage": status.get("status") or "data_only",
        "metrics": _metrics(date_dir),
        "themes": _themes(date_dir),
        "factor_attribution": [
            {"name": _canonical_theme(item.get("tag")), "count": _integer(item.get("count"), 0)}
            for item in (ths.get("reason_tags") or [])[:12]
            if _canonical_theme(item.get("tag"))
        ],
        "institution": {"sectors": _sector_rows(date_dir), "core_stocks": _core_stocks(date_dir)},
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


def _institution_continuity(records: list[dict[str, Any]]) -> dict[str, Any]:
    industries: dict[str, dict[str, Any]] = {}
    stocks: dict[str, dict[str, Any]] = {}
    for record in records:
        for item in (record.get("institution") or {}).get("sectors") or []:
            name = item["name"]
            row = industries.setdefault(name, {"name": name, "active_days": 0, "net_inflow_sum_yi": 0.0, "last_net_inflow_yi": None, "last_pct_chg": None, "last_seen": None, "source": item.get("source")})
            row["active_days"] += 1
            row["net_inflow_sum_yi"] += _number(item.get("net_inflow_yi"), 0.0) or 0.0
            row["last_net_inflow_yi"] = item.get("net_inflow_yi")
            row["last_pct_chg"] = item.get("pct_chg")
            row["last_seen"] = record["trade_date"]
        for item in (record.get("institution") or {}).get("core_stocks") or []:
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
    observed_days = sum(bool((record.get("institution") or {}).get("sectors")) for record in records)
    return {
        "available": observed_days > 0,
        "coverage": round(observed_days / len(records), 3) if records else 0.0,
        "industries": industry_rows[:20],
        "core_stocks": stock_rows[:20],
        "direction": (
            f"{'净流入' if industry_rows[0]['net_inflow_sum_yi'] >= 0 else '净流出'}:{industry_rows[0]['name']}连续{industry_rows[0]['active_days']}日"
            if industry_rows
            else "暂无机构趋势数据"
        ),
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
    current = scoped[-1].get("themes") if scoped else []
    themes = {
        "mainline": [item for item in current or [] if item.get("streak", 0) >= 2][:8],
        "warming": [item for item in current or [] if item.get("lifecycle") in {"new", "strengthening"}][:8],
        "cooling": [item for item in current or [] if item.get("lifecycle") == "weakening"][:8],
    }
    valid_ratio = len(scoped) / window
    confidence = "high" if valid_ratio >= 0.85 else "medium" if valid_ratio >= 0.6 else "low"
    return {
        "window": window,
        "date_range": [scoped[0]["trade_date"], scoped[-1]["trade_date"]] if scoped else [],
        "valid_days": len(scoped),
        "confidence": confidence,
        "market": {"direction": direction, "tone": tone, "components": [heat, breadth, relay, risk]},
        "themes": themes,
        "institution": _institution_continuity(scoped),
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


def _opportunity_radar(records: list[dict[str, Any]]) -> dict[str, Any]:
    scoped = records[-20:]
    recent = scoped[-5:]
    weights = [0.1, 0.1, 0.15, 0.15, 0.5][-len(recent):]
    theme_scores: dict[str, dict[str, Any]] = {}
    sector_scores: dict[str, dict[str, Any]] = {}
    stock_scores: dict[str, dict[str, Any]] = {}
    for weight, record in zip(weights, recent, strict=False):
        for item in record.get("themes") or []:
            row = theme_scores.setdefault(item["name"], {"name": item["name"], "score": 0.0, "active_days": 0, "last_seen": record["trade_date"], "lifecycle": item.get("lifecycle"), "leaders": item.get("leaders", [])})
            row["score"] += weight * float(item.get("rank_strength") or 0)
            row["active_days"] += 1
            row.update({"last_seen": record["trade_date"], "lifecycle": item.get("lifecycle"), "leaders": item.get("leaders", [])})
        for item in (record.get("institution") or {}).get("sectors") or []:
            row = sector_scores.setdefault(item["name"], {"name": item["name"], "score": 0.0, "active_days": 0, "last_seen": record["trade_date"], "net_inflow_yi": item.get("net_inflow_yi"), "pct_chg": item.get("pct_chg")})
            flow = max(-50.0, min(50.0, _number(item.get("net_inflow_yi"), 0.0) or 0.0))
            price = max(-10.0, min(10.0, _number(item.get("pct_chg"), 0.0) or 0.0))
            row["score"] += weight * (50 + flow + price * 2.5)
            row["active_days"] += 1
            row.update({"last_seen": record["trade_date"], "net_inflow_yi": item.get("net_inflow_yi"), "pct_chg": item.get("pct_chg")})
        leader_codes = {leader["code"]: leader for theme in record.get("themes") or [] for leader in theme.get("leaders") or [] if leader.get("code")}
        cores = {item["code"]: item for item in (record.get("institution") or {}).get("core_stocks") or [] if item.get("code")}
        for code, item in {**leader_codes, **cores}.items():
            row = stock_scores.setdefault(code, {"code": code, "name": item.get("name"), "score": 0.0, "active_days": 0, "last_seen": record["trade_date"], "source": item.get("source", "theme_leader")})
            row["score"] += weight * (70 if code in cores else 55)
            row["active_days"] += 1
            row["last_seen"] = record["trade_date"]
    for collection in (theme_scores, sector_scores, stock_scores):
        for row in collection.values():
            row["score"] = round(max(0.0, min(100.0, row["score"])), 1)
    coverage = {
        "themes": round(sum(bool(record.get("themes")) for record in recent) / len(recent), 2) if recent else 0.0,
        "sectors": round(sum(bool((record.get("institution") or {}).get("sectors")) for record in recent) / len(recent), 2) if recent else 0.0,
        "stocks": round(sum(bool((record.get("institution") or {}).get("core_stocks")) for record in recent) / len(recent), 2) if recent else 0.0,
    }
    return {
        "schema_version": "opportunity-radar-v1",
        "coverage_confidence": coverage,
        "themes": sorted(theme_scores.values(), key=lambda item: (-item["score"], item["name"]))[:12],
        "sectors": sorted(sector_scores.values(), key=lambda item: (-item["score"], item["name"]))[:12],
        "stocks": sorted(stock_scores.values(), key=lambda item: (-item["score"], item["code"]))[:16],
    }


def _snapshot_from_records(records: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    latest = records[-1]
    trade_date = latest["trade_date"]
    current_names = {item["name"] for item in latest["themes"]}
    latest_events = [event for event in events if event["trade_date"] == trade_date]
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
        "institution_continuity": _institution_continuity(records[-20:]),
        "data_coverage": {
            "theme_days": sum(bool(record["themes"]) for record in records[-20:]),
            "institution_days": sum(bool((record.get("institution") or {}).get("sectors")) for record in records[-20:]),
            "window_days": min(20, len(records)),
        },
    }


def build_multiday_snapshot(quantx_dir: Path, trade_date: str) -> dict[str, Any]:
    validate_trade_date(trade_date)
    quantx_dir = Path(quantx_dir).resolve()
    dirs = [path for path in _date_dirs(quantx_dir) if path.name <= trade_date]
    if not dirs or dirs[-1].name != trade_date:
        raise FileNotFoundError(trade_date)
    records = [_record(path) for path in dirs]
    events = _decorate_theme_lifecycle(records)
    return _snapshot_from_records(records, events)


def load_multiday_snapshot(quantx_dir: Path, trade_date: str) -> dict[str, Any]:
    validate_trade_date(trade_date)
    path = Path(quantx_dir) / trade_date / "multiday_snapshot.json"
    cached = read_json(path)
    if isinstance(cached, dict) and cached.get("schema_version") == SCHEMA_VERSION:
        return cached
    return build_multiday_snapshot(quantx_dir, trade_date)


def rebuild_multiday_snapshots(quantx_dir: Path) -> dict[str, Any]:
    quantx_dir = Path(quantx_dir).resolve()
    date_dirs = _date_dirs(quantx_dir)
    records = [_record(path) for path in date_dirs]
    events = _decorate_theme_lifecycle(records)
    for index, date_dir in enumerate(date_dirs):
        snapshot = _snapshot_from_records(records[: index + 1], events)
        write_json_atomic(date_dir / "multiday_snapshot.json", snapshot)
    from .catalog import build_and_save_catalog

    catalog = build_and_save_catalog(quantx_dir)
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "rebuilt": len(date_dirs), "stats": catalog["stats"]}


def rebuild_multiday_snapshot(quantx_dir: Path, trade_date: str | None = None) -> dict[str, Any]:
    """Persist one selected/latest snapshot for an interactive rebuild."""
    quantx_dir = Path(quantx_dir).resolve()
    date_dirs = _date_dirs(quantx_dir)
    selected = trade_date or (date_dirs[-1].name if date_dirs else None)
    if selected is None:
        raise FileNotFoundError("no QuantX dates")
    snapshot = build_multiday_snapshot(quantx_dir, selected)
    write_json_atomic(quantx_dir / selected / "multiday_snapshot.json", snapshot)
    from .catalog import build_and_save_catalog

    catalog = build_and_save_catalog(quantx_dir)
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "trade_date": selected, "rebuilt": 1, "stats": catalog["stats"]}
