from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.services.emotion_state import compute as compute_emotion

from ..io import read_json


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _records(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _market_tables(trade_date: str, sources: dict[str, dict[str, Any]], computed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tushare = sources.get("tushare", {})
    aggregate = sources.get("tickflow_enriched_aggregate", {})
    market_payload = aggregate or tushare
    daily = _records(market_payload, "daily", "stocks", "records")
    daily_market = market_payload.get("daily_market") if isinstance(market_payload.get("daily_market"), dict) else {}
    indexes_value = tushare.get("indexes") or tushare.get("index") or []
    if isinstance(indexes_value, dict):
        indexes = [{"code": code, **(row if isinstance(row, dict) else {})} for code, row in indexes_value.items()]
    else:
        indexes = _records(tushare, "indexes", "index")
    up = sum(1 for row in daily if _num(row.get("pct_chg")) > 0) if daily else int(daily_market.get("up_count") or 0)
    down = sum(1 for row in daily if _num(row.get("pct_chg")) < 0) if daily else int(daily_market.get("down_count") or 0)
    flat = max(len(daily) - up - down, 0) if daily else int(daily_market.get("flat_count") or 0)
    # Tushare amount is in thousand RMB; other sources may already provide 亿.
    amount_yi = sum(_num(row.get("amount")) for row in daily) / 100000
    if not amount_yi:
        amount_yi = sum(_num(row.get("amount_yi")) for row in daily)
    if not amount_yi:
        amount_yi = _num(daily_market.get("total_amount_yi"))
    index_rows = []
    for row in indexes:
        index_rows.append({
            "code": row.get("code") or row.get("ts_code") or "",
            "name": row.get("name") or row.get("index_name") or "",
            "close": _num(row.get("close"), 0) or None,
            "pct_chg": _num(row.get("pct_chg"), 0),
            "amount_yi": _num(row.get("amount")) / 100000 if row.get("amount") is not None else None,
        })
    breadth = {
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "total_count": len(daily) or int(daily_market.get("total_stocks") or up + down + flat),
        "up_ratio": round(up / len(daily) * 100, 2) if daily else daily_market.get("up_ratio"),
        "advance_decline": up - down,
    }
    market_overview = {
        "schema_version": 1, "trade_date": trade_date,
        "indexes": index_rows, "breadth": breadth,
        "daily_market": daily_market,
        "total_amount_yi": round(amount_yi, 2),
        "market_heat": computed.get("market_heat", {}),
        "source_refs": ["tickflow_enriched_aggregate", "tushare", "akshare"],
    }
    liquidity = {
        "schema_version": 1, "trade_date": trade_date,
        "total_amount_yi": round(amount_yi, 2),
        "top5_amount_yi": round(sum(sorted((_num(r.get("amount_yi"), _num(r.get("amount")) / 100000) for r in daily), reverse=True)[:5]), 2) if daily else None,
        "congestion": computed.get("congestion", {}),
        "source_refs": ["tickflow_enriched_aggregate", "tushare", "legulegu"],
    }
    return {"market_overview": market_overview, "market_breadth": breadth, "market_liquidity": liquidity}


def _limit_tables(trade_date: str, sources: dict[str, dict[str, Any]], computed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    py = sources.get("pywencai", {})
    ztk = sources.get("zhangtingke", {})
    py_limit = py.get("limit_up", {}) if isinstance(py.get("limit_up"), dict) else {}
    stocks = _records(py_limit, "stocks")
    if not stocks:
        stocks = _records(ztk, "ladder_stocks")
    ladder = ztk.get("ladder_by_height") or py_limit.get("ladder") or computed.get("limit_ladder", {}).get("ladder_by_height", {})
    ladder = {str(key): value for key, value in ladder.items()} if isinstance(ladder, dict) else {}
    broken = py.get("broken_board", {}) if isinstance(py.get("broken_board"), dict) else {}
    limit_down = py.get("limit_down", {}) if isinstance(py.get("limit_down"), dict) else {}
    summary = {
        "schema_version": 1, "trade_date": trade_date,
        "limit_up_count": py_limit.get("count", len(stocks)),
        "broken_board_count": broken.get("count", 0),
        "limit_down_count": limit_down.get("count", computed.get("loss_effect", {}).get("limit_down_count")),
        "seal_rate": py.get("seal_rate", computed.get("short_term_sentiment", {}).get("inputs", {}).get("seal_rate")),
        "broken_rate": py.get("broken_rate"),
        "max_board": max((int(k) for k in ladder if str(k).isdigit()), default=0),
        "source_refs": ["pywencai", "duanxianxia", "zhangtingke", "zhangtingjun", "dabanke"],
    }
    return {
        "limit_summary": summary,
        "limit_ladder": {"schema_version": 1, "trade_date": trade_date, "ladder_by_height": ladder, "source": "zhangtingke>pywencai"},
        "limit_stocks": {"schema_version": 1, "trade_date": trade_date, "stocks": stocks},
        "promotion_stats": {"schema_version": 1, "trade_date": trade_date, **computed.get("advance_stats", {})},
        "premium_stats": {"schema_version": 1, "trade_date": trade_date, "premium_rate": computed.get("advance_stats", {}).get("premium_rate")},
    }


def _theme_tables(trade_date: str, sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: Counter[str] = Counter()
    stocks_by_theme: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    ths = sources.get("ths_hot", {})
    for item in ths.get("reason_tags", []) if isinstance(ths.get("reason_tags"), list) else []:
        if item.get("tag"):
            counts[str(item["tag"])] += int(item.get("count") or 0)
    py = sources.get("pywencai", {})
    for item in py.get("limit_up", {}).get("themes", []) if isinstance(py.get("limit_up"), dict) else []:
        if item.get("name"):
            counts[str(item["name"])] += int(item.get("count") or 0)
    for item in _records(py.get("limit_up", {}), "stocks"):
        for theme in item.get("concepts", []) if isinstance(item.get("concepts"), list) else []:
            stocks_by_theme[str(theme)].append(item)
    rankings = [{"name": name, "count": count, "rank": i + 1} for i, (name, count) in enumerate(counts.most_common(50))]
    return {
        "theme_snapshot": {"schema_version": 1, "trade_date": trade_date, "themes": rankings[:20], "source_refs": ["ths_hot", "pywencai"]},
        "theme_rankings": {"schema_version": 1, "trade_date": trade_date, "themes": rankings},
        "theme_stocks": {"schema_version": 1, "trade_date": trade_date, "themes": dict(stocks_by_theme)},
    }


def _theme_history(trade_date: str, quantx_dir: Path, current: dict[str, Any]) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    for date_dir in sorted(quantx_dir.iterdir()) if quantx_dir.exists() else []:
        if not date_dir.is_dir() or not date_dir.name.isdigit() or date_dir.name == trade_date:
            continue
        old = read_json(date_dir / "theme_rankings.json", {}) or read_json(date_dir / "theme_snapshot.json", {})
        themes = old.get("themes", []) if isinstance(old, dict) else []
        if themes:
            days.append({"date": date_dir.name, "themes": themes[:20]})
    days.append({"date": trade_date, "themes": current.get("themes", [])[:20]})
    return {"schema_version": 1, "trade_date": trade_date, "days": days[-120:]}


def _fund_flow_tables(trade_date: str, sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    payload = sources.get("sector_fund_flow_s4", {})
    sectors = _records(payload, "sectors", "records")
    if not sectors:
        sectors = _records(sources.get("akshare", {}), "sector_fund_flow", "sectors")
    sectors = sorted(sectors, key=lambda row: _num(row.get("net_inflow_yi"), _num(row.get("net"))), reverse=True)
    return {
        "sector_fund_flow": {"schema_version": 1, "trade_date": trade_date, "sectors": sectors, "source_refs": ["sector_fund_flow_s4", "akshare"]},
        "sector_rotation": {"schema_version": 1, "trade_date": trade_date, "top_in": sectors[:20], "top_out": list(reversed(sectors[-20:])) if sectors else []},
    }


def _screening_table(trade_date: str, sources: dict[str, dict[str, Any]], computed: dict[str, Any]) -> dict[str, Any]:
    py = sources.get("pywencai", {})
    rows = _records(py.get("limit_up", {}), "stocks")
    rows = rows or _records(sources.get("zhangtingke", {}), "ladder_stocks")
    candidates = []
    for row in rows:
        code = str(row.get("code") or "")
        if not code:
            continue
        board = int(row.get("limit_times") or row.get("limit_count") or 1)
        rules = ["limit_up"]
        if board >= 2:
            rules.append("consecutive_limit_up")
        if _num(row.get("turnover_pct")) > 0:
            rules.append("has_turnover")
        candidates.append({"code": code, "name": row.get("name", ""), "included": True, "rules_matched": rules, "rules_failed": [], "source_refs": ["pywencai", "zhangtingke"]})
    return {"schema_version": 1, "trade_date": trade_date, "candidates": candidates, "count": len(candidates), "kind": "deterministic_rule_screen"}


def _trend_tables(trade_date: str, quantx_dir: Path, computed: dict[str, Any], themes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for date_dir in sorted(quantx_dir.iterdir()) if quantx_dir.exists() else []:
        if not date_dir.is_dir() or not date_dir.name.isdigit() or date_dir.name == trade_date:
            continue
        old = read_json(date_dir / "_computed.json", {})
        if old:
            history.append({"date": date_dir.name, "market_heat": old.get("market_heat", {}).get("score"), "short_term": old.get("short_term_sentiment", {}).get("score"), "trend": old.get("trend_sentiment", {}).get("score"), "max_board": old.get("height_trend", {}).get("latest_max_board")})
    history.append({"date": trade_date, "market_heat": computed.get("market_heat", {}).get("score"), "short_term": computed.get("short_term_sentiment", {}).get("score"), "trend": computed.get("trend_sentiment", {}).get("score"), "max_board": computed.get("height_trend", {}).get("latest_max_board")})
    history = history[-120:]
    return {"trend_history": {"schema_version": 1, "trade_date": trade_date, "days": history}, "trend_pool": {"schema_version": 1, "trade_date": trade_date, "themes": themes.get("themes", [])[:20]}}


def build_daily_tables(trade_date: str, date_dir: Path, quantx_dir: Path, sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    computed = compute_emotion(date_dir, quantx_dir)
    tables: dict[str, dict[str, Any]] = {"_computed": computed}
    tables.update(_market_tables(trade_date, sources, computed))
    tables.update(_limit_tables(trade_date, sources, computed))
    themes = _theme_tables(trade_date, sources)
    tables.update(themes)
    tables["theme_history"] = _theme_history(trade_date, quantx_dir, themes["theme_rankings"])
    tables.update(_fund_flow_tables(trade_date, sources))
    tables["sentiment_state"] = {"schema_version": 1, "trade_date": trade_date, **computed}
    tables["risk_signals"] = {"schema_version": 1, "trade_date": trade_date, "ebb_risk": computed.get("ebb_risk_check", {}), "crash": computed.get("crash_signals", {})}
    tables["participation"] = {"schema_version": 1, "trade_date": trade_date, **computed.get("participation_check", {})}
    tables["screening_candidates"] = _screening_table(trade_date, sources, computed)
    tables.update(_trend_tables(trade_date, quantx_dir, computed, themes["theme_rankings"]))
    return tables
