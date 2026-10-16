"""Point-in-time review of published stock-pool observations."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from app.market_facts.repository import MarketFactRepository
from app.stock_pools.evolution import LOW_STAGES, _comparison_quality
from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.rules import SOURCE_META

GROUPS = ("all", "new", "reentry", "stage", "source", "topic", "unchanged")


def _usable(summary: dict | None) -> bool:
    quality = (summary or {}).get("source_quality") or {}
    return bool(summary and summary.get("status") == "complete"
                and quality.get("market_universe") in (None, "complete"))


def _stats(rows: list[dict]) -> dict[str, Any]:
    mature = [row for row in rows if row["outcome_status"] == "mature"]
    priced = [row["return_pct"] for row in mature if row["return_pct"] is not None]
    open_priced = [row["open_proxy_pct"] for row in mature if row["open_proxy_pct"] is not None]
    net_priced = [row["open_proxy_net_pct"] for row in mature if row["open_proxy_net_pct"] is not None]
    adverse = [row["max_adverse_pct"] for row in mature if row.get("max_adverse_pct") is not None]
    stages = Counter(row["target_stage"] or "未入池" for row in mature)
    return {
        "sample_count": len(rows), "matured_count": len(mature),
        "matured_dates": len({row["date"] for row in mature}), "priced_count": len(priced),
        "unique_symbols": len({row["symbol"] for row in mature}),
        "recorded_count": sum(row["snapshot_status"] == "recorded" for row in mature),
        "recorded_transition_count": sum(
            row["snapshot_status"] == "recorded" and row.get("prior_snapshot_status") == "recorded"
            for row in mature
        ),
        "pending_count": sum(row["outcome_status"] == "pending" for row in rows),
        "unavailable_count": sum(row["outcome_status"] == "unavailable" for row in rows),
        "retained_count": sum(row["target_stage"] is not None for row in mature),
        "up_count": sum(value > 0 for value in priced),
        "up_rate_pct": round(sum(value > 0 for value in priced) / len(priced) * 100, 2) if priced else None,
        "priced_dates": len({row["date"] for row in mature if row["return_pct"] is not None}),
        "mean_adverse_pct": round(sum(adverse) / len(adverse), 2) if adverse else None,
        "adverse_count": len(adverse),
        "mean_return_pct": round(sum(priced) / len(priced), 2) if priced else None,
        "median_return_pct": round(median(priced), 2) if priced else None,
        "open_proxy_count": len(open_priced),
        "mean_open_proxy_pct": round(sum(open_priced) / len(open_priced), 2) if open_priced else None,
        "median_open_proxy_pct": round(median(open_priced), 2) if open_priced else None,
        "mean_open_proxy_net_pct": round(sum(net_priced) / len(net_priced), 2) if net_priced else None,
        "median_open_proxy_net_pct": round(median(net_priced), 2) if net_priced else None,
        "target_stages": dict(stages),
    }


def _snapshot_status(basis: str, manifest: dict | None, next_day: str | None) -> str:
    if basis != "first_published":
        return "replay"
    if not manifest or not next_day:
        return "unknown"
    try:
        published = datetime.fromisoformat(manifest["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            return "unknown"
        anchor_close = datetime.combine(date.fromisoformat(manifest["trade_date"]), time(15), ZoneInfo("Asia/Shanghai"))
        cutoff = datetime.combine(date.fromisoformat(next_day), time(9, 30), ZoneInfo("Asia/Shanghai"))
        published_local = published.astimezone(cutoff.tzinfo)
        return "early" if published_local < anchor_close else "recorded" if published_local <= cutoff else "late"
    except (KeyError, ValueError, TypeError):
        return "unknown"


def build_review(repo: StockPoolRepository, kline_repo: Any, trade_date: date, window: int, horizon: int,
                 cost_bps: int = 0) -> dict | None:
    as_of = trade_date.isoformat()
    as_of_summary, as_of_candidates, _, _ = repo.get_review_snapshot(as_of)
    if as_of_summary is None or as_of_candidates is None:
        return None
    reference_version = as_of_summary.get("rule_version")
    dates = [day for day in repo.list_dates() if day <= as_of]
    calendar = MarketFactRepository(repo.root.parent).get_trading_calendar(
        date.fromisoformat(dates[0]), trade_date + timedelta(days=15), as_of=trade_date,
    ) if dates else None
    open_days = (
        sorted(str(day)[:10] for day, is_open in calendar.select("trade_date", "is_open").iter_rows() if is_open)
        if calendar is not None and not calendar.is_empty() else []
    )
    next_open = dict(pairwise(open_days))
    open_index = {day: index for index, day in enumerate(open_days)}
    snapshots = {day: repo.get_review_snapshot(day) for day in dates}
    day_statuses = {
        day: _snapshot_status(snapshots[day][3], snapshots[day][2], next_open.get(day))
        for day in dates
    }
    summaries = {day: snapshots[day][0] for day in dates}
    candidates = {day: snapshots[day][1] for day in dates}
    pools = {day: {row["symbol"]: row for row in candidates[day] or []} for day in dates}
    available = {day: candidates[day] is not None for day in dates}
    observations: list[dict] = []
    skipped: list[dict] = []
    seen_in_version: set[str] = set()
    prior_version: str | None = None
    anchor_days = set(dates[-window:])

    for index, day in enumerate(dates):
        summary = summaries[day]
        version = summary.get("rule_version") if summary else None
        if version != reference_version:
            if day in anchor_days:
                skipped.append({"date": day, "reason": "incompatible"})
            seen_in_version.clear()
            prior_version = version
            continue
        if version != prior_version or not _usable(summary) or not available[day]:
            seen_in_version.clear()
        previous_day = dates[index - 1] if index else None
        previous_summary = summaries[previous_day] if previous_day else None
        comparison = (_comparison_quality(summary, previous_summary, "hot")
                      if previous_day and available[previous_day] and summary else "unavailable")
        if not _usable(summary) or not available[day] or comparison != "complete":
            if day in anchor_days:
                skipped.append({"date": day, "reason": "quality" if not _usable(summary) else comparison})
            if _usable(summary) and available[day]:
                seen_in_version.update(pools[day])
            prior_version = version
            continue
        if day not in anchor_days:
            seen_in_version.update(pools[day])
            prior_version = version
            continue

        before_pool = pools[previous_day]
        entry_day = dates[index + 1] if index + 1 < len(dates) else None
        for symbol, row in pools[day].items():
            before = before_pool.get(symbol)
            old_sources = set(before.get("source_ids") or []) if before else set()
            new_sources = set(row.get("source_ids") or [])
            names = dict(zip(row.get("source_ids") or [], row.get("sources") or [], strict=False))
            old_names = dict(zip(before.get("source_ids") or [], before.get("sources") or [], strict=False)) if before else {}
            added = [names.get(source, source) for source in sorted(new_sources - old_sources)]
            removed = [old_names.get(source, source) for source in sorted(old_sources - new_sources)]
            labels = ["all"]
            if before is None:
                labels.append("reentry" if symbol in seen_in_version else "new")
            else:
                if before.get("primary_stage") != row.get("primary_stage"):
                    labels.append("stage")
                if old_sources != new_sources:
                    labels.append("source")
                if set(before.get("topics") or []) != set(row.get("topics") or []):
                    labels.append("topic")
                if len(labels) == 1:
                    labels.append("unchanged")

            target_index = index + horizon
            target_day = dates[target_index] if target_index < len(dates) else None
            calendar_target_index = open_index[day] + horizon if day in open_index else len(open_days)
            expected_target_day = open_days[calendar_target_index] if calendar_target_index < len(open_days) else None
            outcome_status = "pending" if target_day is None else "mature"
            if ((target_day and open_days and expected_target_day != target_day)
                    or (target_day is None and expected_target_day and expected_target_day <= as_of)):
                outcome_status = "unavailable"
            path = [{"date": day, "stage": row.get("primary_stage"), "present": True}]
            if target_day:
                for path_day in dates[index + 1:target_index + 1]:
                    next_summary = summaries[path_day]
                    if (not available[path_day] or not _usable(next_summary)
                            or next_summary.get("rule_version") != version):
                        outcome_status = "unavailable"
                        break
                    next_row = pools[path_day].get(symbol)
                    path.append({"date": path_day, "stage": next_row.get("primary_stage") if next_row else None,
                                 "present": next_row is not None})
            path_statuses = [day_statuses[path_day] for path_day in dates[index:target_index + 1]] if target_day else [day_statuses[day]]
            snapshot_status = next((status for status in ("replay", "late", "early", "unknown") if status in path_statuses), "recorded")
            observations.append({
                "date": day, "symbol": symbol, "name": row.get("name") or symbol,
                "labels": labels, "stage": row.get("primary_stage"),
                "previous_stage": before.get("primary_stage") if before else None,
                "source_ids": sorted(new_sources),
                "added_source_ids": sorted(new_sources - old_sources),
                "removed_source_ids": sorted(old_sources - new_sources),
                "sources": row.get("sources") or [], "added_sources": added, "removed_sources": removed,
                "research_count": row.get("research_count") or 0,
                "research_breakdown": row.get("research_breakdown") or {},
                "research_breakdown_available": "research_breakdown" in row,
                "topics": row.get("topics") or [], "price": row.get("price"),
                "snapshot_basis": snapshots[day][3], "snapshot_status": snapshot_status,
                "prior_snapshot_status": day_statuses.get(previous_day, "unknown"),
                "published_at": (snapshots[day][2] or {}).get("published_at"),
                "entry_date": entry_day,
                "target_date": target_day or (expected_target_day if outcome_status == "unavailable" else None),
                "target_stage": path[-1]["stage"] if outcome_status == "mature" else None,
                "outcome_status": outcome_status, "path": path, "return_pct": None,
                "open_proxy_pct": None, "open_proxy_net_pct": None,
                "max_adverse_pct": None, "max_favorable_pct": None,
            })
        seen_in_version.update(pools[day])
        prior_version = version

    mature = [row for row in observations if row["outcome_status"] == "mature"]
    eligible_by_day = {day: repo.get_review_eligible(day) for day in {row["date"] for row in mature}}
    outside_by_day: dict[str, list[float]] = {}
    if mature:
        symbols = sorted({row["symbol"] for row in mature} |
                         {symbol for eligible in eligible_by_day.values() for symbol in (eligible or [])})
        frame = kline_repo.get_daily_batch(symbols, date.fromisoformat(min(row["date"] for row in mature)), trade_date,
                                           columns=["symbol", "date", "open", "high", "low", "close"])
        prices: dict[tuple[str, str], dict] = {}
        if not frame.is_empty() and {"symbol", "date", "close"} <= set(frame.columns):
            prices = {(bar["symbol"], str(bar["date"])[:10]): bar for bar in frame.to_dicts()}
        for row in mature:
            anchor = (prices.get((row["symbol"], row["date"])) or {}).get("close")
            target = (prices.get((row["symbol"], row["target_date"])) or {}).get("close")
            entry = (prices.get((row["symbol"], row["entry_date"])) or {}).get("open")
            if anchor and target and anchor > 0 and target > 0:
                row["return_pct"] = round((target / anchor - 1) * 100, 2)
            if entry and target and entry > 0 and target > 0:
                gross_pct = (target / entry - 1) * 100
                row["open_proxy_pct"] = round(gross_pct, 2)
                row["open_proxy_net_pct"] = round(gross_pct - cost_bps / 100, 2)
                bars = [bar for (symbol, day), bar in prices.items()
                        if symbol == row["symbol"] and row["entry_date"] <= day <= row["target_date"]]
                lows = [bar["low"] for bar in bars if bar.get("low") is not None and bar["low"] > 0]
                highs = [bar["high"] for bar in bars if bar.get("high") is not None and bar["high"] > 0]
                row["max_adverse_pct"] = round((min(lows) / entry - 1) * 100, 2) if lows else None
                row["max_favorable_pct"] = round((max(highs) / entry - 1) * 100, 2) if highs else None
        for day, eligible in eligible_by_day.items():
            if eligible is None:
                continue
            index = dates.index(day)
            if index + horizon >= len(dates):
                continue
            entry_day, target_day = dates[index + 1], dates[index + horizon]
            outside = set(eligible) - set(pools[day])
            values = []
            for symbol in outside:
                entry = (prices.get((symbol, entry_day)) or {}).get("open")
                target = (prices.get((symbol, target_day)) or {}).get("close")
                if entry and target and entry > 0 and target > 0:
                    values.append((target / entry - 1) * 100)
            if values:
                outside_by_day[day] = values

    priced_by_day: dict[str, list[dict]] = defaultdict(list)
    for row in mature:
        priced_by_day[row["date"]].append(row)

    def with_comparison(selected_rows: list[dict], *, all_rows: bool = False) -> dict:
        stats = _stats(selected_rows)
        keys = {(row["date"], row["symbol"]) for row in selected_rows}
        for metric, field in (("return_pct", "peer_diff_pct"), ("open_proxy_pct", "peer_open_diff_pct")):
            differences = []
            if not all_rows:
                for day_rows in priced_by_day.values():
                    selected = [row[metric] for row in day_rows if (row["date"], row["symbol"]) in keys and row[metric] is not None]
                    others = [row[metric] for row in day_rows if (row["date"], row["symbol"]) not in keys and row[metric] is not None]
                    if selected and others:
                        differences.append(sum(selected) / len(selected) - sum(others) / len(others))
            stats[field] = round(sum(differences) / len(differences), 2) if differences else None
            stats["peer_days" if metric == "return_pct" else "peer_open_days"] = len(differences)
        outside_differences = []
        for day, day_rows in priced_by_day.items():
            selected = [row["open_proxy_pct"] for row in day_rows
                        if (row["date"], row["symbol"]) in keys and row["open_proxy_pct"] is not None]
            outside = outside_by_day.get(day)
            if selected and outside:
                outside_differences.append(sum(selected) / len(selected) - sum(outside) / len(outside))
        stats["eligible_diff_pct"] = round(sum(outside_differences) / len(outside_differences), 2) if outside_differences else None
        stats["eligible_days"] = len(outside_differences)
        return stats

    groups = {group: with_comparison([row for row in observations if group in row["labels"]], all_rows=group == "all") for group in GROUPS}
    source_stats = {
        source_id: {"label": meta[0], **with_comparison([row for row in observations if source_id in row["source_ids"]])}
        for source_id, meta in SOURCE_META.items()
    }
    added_source_stats = {
        source_id: {"label": meta[0], **with_comparison([row for row in observations if source_id in row["added_source_ids"]])}
        for source_id, meta in SOURCE_META.items()
    }
    combinations = sorted({tuple(row["source_ids"]) for row in observations if len(row["source_ids"]) >= 2})
    combination_stats = {
        "+".join(sources): {"label": "+".join(SOURCE_META[source][0] for source in sources),
                            **with_comparison([row for row in observations if tuple(row["source_ids"]) == sources])}
        for sources in combinations
    }
    transitions = sorted({f'{row["previous_stage"] or "未入池"} → {row["stage"]}' for row in observations})
    transition_stats = {
        transition: with_comparison([row for row in observations if f'{row["previous_stage"] or "未入池"} → {row["stage"]}' == transition])
        for transition in transitions
    }
    research_slices = {
        "direct": ("定向材料", lambda row: row["research_count"] > 0),
        "smnc_focused": ("SMNC标题单股", lambda row: row["research_breakdown"].get("smnc_focused", 0) > 0),
        "low_direct": ("低吸·定向材料", lambda row: row["stage"] in LOW_STAGES and row["research_count"] > 0),
        "low_without_direct": ("低吸·无定向材料", lambda row: row["stage"] in LOW_STAGES and row["research_count"] == 0),
        "low_smnc_focused": ("低吸·SMNC标题单股", lambda row: row["stage"] in LOW_STAGES and row["research_breakdown"].get("smnc_focused", 0) > 0),
    }
    research_stats = {
        key: {"label": label, **with_comparison([row for row in observations if predicate(row)])}
        for key, (label, predicate) in research_slices.items()
    }
    audit_counts = dict(Counter(row["snapshot_status"] for row in mature))
    return {
        "as_of_date": as_of, "window": window, "horizon": horizon,
        "return_basis": "adjusted_close_to_close",
        "open_proxy_basis": "next_trading_day_adjusted_open_to_target_close",
        "cost_bps": cost_bps,
        "audit_counts": audit_counts,
        "eligible_baseline_days": len(outside_by_day),
        "research_breakdown_observations": sum(row["research_breakdown_available"] for row in mature),
        "anchor_dates": sorted({row["date"] for row in observations}),
        "skipped_dates": skipped,
        "groups": groups,
        "attribution": {"sources": source_stats, "added_sources": added_source_stats,
                        "transitions": transition_stats, "research": research_stats, "combinations": combination_stats},
        "rows": sorted(observations, key=lambda row: (row["date"], row["symbol"]), reverse=True),
    }
