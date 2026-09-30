"""THS constituent research: pressure/breadth, overlap and forward outcomes."""
# ruff: noqa: RUF001 -- Native punctuation in Chinese display labels.
from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import timedelta
from itertools import combinations
from statistics import mean, median
from threading import RLock
from time import monotonic

import polars as pl

from app.quantx_data.new_high_clusters import load_ths_memberships

_cache = OrderedDict()
_lock = RLock()


def concept_overlap(mapping: dict, selected: str = "", limit: int = 10) -> dict:
    groups = defaultdict(set)
    for code, labels in mapping.items():
        for label in labels:
            groups[label].add(code)
    names = sorted(groups)
    selected = selected or (names[0] if names else "")
    own = groups.get(selected, set())
    rows = []
    for label, members in groups.items():
        common = own & members
        if label == selected or not common:
            continue
        rows.append({"sector": label, "member_count": len(members), "common_count": len(common),
                     "jaccard_pct": len(common) / len(own | members) * 100,
                     "coverage_pct": len(common) / len(own) * 100,
                     "other_coverage_pct": len(common) / len(members) * 100,
                     "common_codes": sorted(common)})
    rows.sort(key=lambda r: (-r["jaccard_pct"], -r["common_count"], r["sector"]))
    shown = rows[:limit]
    edges = []
    for a, b in combinations([selected, *(r["sector"] for r in shown)], 2):
        common = groups[a] & groups[b]
        if common and (a == selected or len(common) / len(groups[a] | groups[b]) >= .15):
            edges.append({"source": a, "target": b, "common_count": len(common),
                          "jaccard_pct": len(common) / len(groups[a] | groups[b]) * 100})
    return {"available": bool(own), "concepts": names, "sector": selected,
            "member_count": len(own), "related_count": len(rows), "rows": shown, "edges": edges,
            "membership_basis": "latest_ths_snapshot", "detail": "完整THS成分；共享股票不代表概念同义，不用于自动归类。"}


def concept_overlap_from_repo(repo, selected="", limit=10):
    result = concept_overlap(load_ths_memberships(repo.store.data_dir)["concept"], selected, limit)
    instruments = repo.get_instruments()
    names = {r["symbol"].split(".")[0]: r.get("name") or r["symbol"] for r in instruments.to_dicts()}
    for row in result["rows"]:
        row["common_members"] = [{"code": code, "name": names.get(code, code)} for code in row["common_codes"]]
    return result


def industry_daily(history: pl.DataFrame, mapping: dict, days: list) -> pl.DataFrame:
    """Require contiguous sessions for returns, moving averages and comparisons."""
    if history.is_empty() or not days:
        return pl.DataFrame()
    sessions = pl.DataFrame({"date": days, "_session": range(len(days))})
    data = history.select("symbol", "date", "close", "high", "low", "amount").join(sessions, on="date")
    data = data.with_columns(pl.when(pl.col("close").is_finite() & (pl.col("close") > 0)).then(pl.col("close")).alias("close"))
    data = data.sort(["symbol", "date"]).with_columns(
        pl.col("close").rolling_mean(20).over("symbol").alias("_ma20"),
        pl.col("_session").shift(19).over("symbol").alias("_start20"),
        pl.col("_session").shift(1).over("symbol").alias("_prior_session"),
        pl.col("close").shift(1).over("symbol").alias("_prior_close"),
    ).with_columns(
        pl.when((pl.col("_session") - pl.col("_prior_session") == 1)
                & (pl.col("close") > 0) & (pl.col("_prior_close") > 0))
        .then(pl.col("close") / pl.col("_prior_close") - 1).alias("_return"),
        pl.when((pl.col("_session") - pl.col("_start20") == 19) & (pl.col("_ma20") > 0))
        .then(pl.col("close") > pl.col("_ma20")).alias("_above"),
        pl.when(pl.col("amount").is_finite() & pl.col("high").is_finite() & pl.col("low").is_finite()
                & (pl.col("amount") >= 0) & (pl.col("high") >= pl.col("low"))
                & (pl.col("close") >= pl.col("low")) & (pl.col("close") <= pl.col("high")))
        .then(pl.when(pl.col("high") > pl.col("low"))
              .then((2 * pl.col("close") - pl.col("high") - pl.col("low"))
                    / (pl.col("high") - pl.col("low")) * pl.col("amount"))
              .otherwise(0)).alias("_pressure"),
    )
    market = data.group_by("date").agg(pl.col("_return").mean().alias("market_return"))
    pairs = [(code, label) for code, labels in mapping.items() for label in labels]
    if not pairs:
        return pl.DataFrame()
    groups = pl.DataFrame(pairs, schema={"_code": pl.String, "sector": pl.String}, orient="row")
    totals = groups.group_by("sector").len().rename({"len": "member_count"})
    joined = data.with_columns(pl.col("symbol").str.split(".").list.first().alias("_code")).join(groups, on="_code")
    daily = joined.group_by(["sector", "date", "_session"]).agg(
        pl.col("_return").mean().alias("return"), pl.col("_return").count().alias("return_members"),
        (pl.col("_above").mean() * 100).alias("breadth_pct"),
        pl.col("_above").count().alias("breadth_members"),
        pl.col("_pressure").sum().alias("pressure_yuan"),
        pl.col("amount").filter(pl.col("_pressure").is_not_null()).sum().alias("amount_yuan"),
        pl.col("_pressure").count().alias("pressure_members"),
    ).join(totals, on="sector").join(market, on="date").sort(["sector", "date"])
    daily = daily.with_columns(
        pl.col("breadth_pct").shift(5).over("sector").alias("_breadth5"),
        pl.col("breadth_members").shift(5).over("sector").alias("_breadth_members5"),
        pl.col("_session").shift(5).over("sector").alias("_session5"),
        pl.col("pressure_yuan").rolling_sum(5).over("sector").alias("_pressure5"),
        pl.col("amount_yuan").rolling_sum(5).over("sector").alias("_amount5"),
        pl.col("_session").shift(4).over("sector").alias("_start5"),
        pl.col("pressure_members").rolling_min(5).over("sector").alias("_pressure_members5"),
    ).with_columns(
        pl.when((pl.col("_session") - pl.col("_session5") == 5)
                & (pl.col("breadth_members") / pl.col("member_count") >= .8)
                & (pl.col("_breadth_members5") / pl.col("member_count") >= .8))
        .then(pl.col("breadth_pct") - pl.col("_breadth5")).alias("breadth_change_5d_pp"),
        pl.when((pl.col("_session") - pl.col("_start5") == 4) & (pl.col("_amount5") > 0)
                & (pl.col("_pressure_members5") / pl.col("member_count") >= .8))
        .then(pl.col("_pressure5") / pl.col("_amount5") * 100).alias("pressure_5d_pct"),
    )
    return daily


def forward_outcomes(daily: pl.DataFrame, days: list, horizon: int) -> dict:
    lookup = {(r["sector"], r["date"]): r for r in daily.to_dicts()}
    records = []
    pending = 0
    missing = 0
    for row in daily.to_dicts():
        if row["date"] not in days or row["breadth_change_5d_pp"] is None:
            continue
        index = days.index(row["date"])
        if index + horizon >= len(days):
            pending += 1
            continue
        path = [lookup.get((row["sector"], day)) for day in days[index + 1:index + horizon + 1]]
        if any(r is None or r["return"] is None or r["market_return"] is None
               or r["return_members"] / r["member_count"] < .8 for r in path):
            missing += 1
            continue
        sector_value = market_value = 1.0
        for item in path:
            sector_value *= 1 + item["return"]
            market_value *= 1 + item["market_return"]
        band = min(int(row["breadth_pct"] // 20), 4)
        expanding = row["breadth_change_5d_pp"] >= 0
        records.append({"date": str(row["date"]), "sector": row["sector"], "band": band,
                        "expanding": expanding, "return_pct": (sector_value - 1) * 100,
                        "excess_pct": (sector_value - market_value) * 100})

    def stats(rows):
        dates = defaultdict(list)
        for r in rows:
            dates[r["date"]].append(r["excess_pct"])
        return {"sample_count": len(rows), "date_count": len(dates),
                "mean_excess_pct": mean([mean(v) for v in dates.values()]) if dates else None,
                "median_return_pct": median(r["return_pct"] for r in rows) if rows else None,
                "outperform_pct": mean(r["excess_pct"] > 0 for r in rows) * 100 if rows else None}
    cells = [{"band": band, "expanding": expanding, **stats([r for r in records if r["band"] == band and r["expanding"] == expanding])}
             for band in range(5) for expanding in (False, True)]
    latest = daily.filter(pl.col("date") == days[-1]).to_dicts() if days else []
    sectors = []
    for row in latest:
        delta = row["breadth_change_5d_pp"]
        width = row["breadth_pct"]
        matched = [r for r in records if r["sector"] == row["sector"] and width is not None
                   and delta is not None and r["band"] == min(int(width // 20), 4) and r["expanding"] == (delta >= 0)]
        sectors.append({"sector": row["sector"], "breadth_pct": width,
                        "breadth_change_5d_pp": delta, **stats(matched)})
    return {"cells": cells, "sectors": sectors, "pending_count": pending, "missing_count": missing,
            "matured_count": len(records), "first_date": min((r["date"] for r in records), default=None),
            "last_date": max((r["date"] for r in records), default=None)}


def sector_research(repo, dimension="industry_level1", as_of=None, horizon=5):
    _, latest = repo.get_enriched_latest()
    day = as_of or latest
    if day is None:
        return {"available": False, "detail": "本地暂无股票日线", "phase": [], "outcomes": None}
    mapping = load_ths_memberships(repo.store.data_dir).get(dimension, {})
    membership = tuple((code, tuple(sorted(labels))) for code, labels in sorted(mapping.items()))
    generation = repo.get_matrix_data_generation("stock")
    key = (repo, day, dimension, generation, membership)
    with _lock:
        cached = _cache.get(key)
        if cached and monotonic() - cached[0] < 300:
            daily, days = cached[1]
        else:
            start = day - timedelta(days=240)
            calendar = repo.get_index_daily("000001.SH", start, day, columns=["date"])
            days = sorted(set(calendar["date"].to_list())) if not calendar.is_empty() else []
            if not days or days[-1] != day:
                return {"available": False, "detail": "目标日或交易日历缺失", "phase": [], "outcomes": None}
            instruments = repo.get_instruments()
            symbols = [s for s in instruments["symbol"].to_list() if s.split(".")[0] in mapping]
            # The benchmark includes all stocks, rather than only mapped industries.
            history = repo.get_daily_batch(instruments["symbol"].to_list(), start, day,
                                          columns=["symbol", "date", "close", "high", "low", "amount"])
            if not symbols or history.is_empty():
                return {"available": False, "detail": "THS完整成分或日线缺失", "phase": [], "outcomes": None}
            daily = industry_daily(history, mapping, days)
            if daily.is_empty():
                return {"available": False, "detail": "没有可计算的行业成员", "phase": [], "outcomes": None}
            days = days[-120:]
            daily = daily.filter(pl.col("date").is_in(days))
            if repo.get_matrix_data_generation("stock") != generation:
                raise ValueError("日线正在发布，请稍后重试")
            _cache[key] = (monotonic(), (daily, days))
            while len(_cache) > 2:
                _cache.popitem(last=False)
    current = daily.filter(pl.col("date") == day).to_dicts()
    previous = {r["sector"]: r for r in daily.filter(pl.col("date") == days[-2]).to_dicts()} if len(days) > 1 else {}
    phase = []
    for row in current:
        old = previous.get(row["sector"], {})
        phase.append({"sector": row["sector"], "x": row["pressure_5d_pct"],
                      "y": row["breadth_change_5d_pp"], "previous_x": old.get("pressure_5d_pct"),
                      "previous_y": old.get("breadth_change_5d_pp"), "breadth_pct": row["breadth_pct"],
                      "amount_yi": row["amount_yuan"] / 1e8, "member_count": row["member_count"],
                      "breadth_members": row["breadth_members"], "pressure_members": row["pressure_members"]})
    return {"available": True, "trade_date": str(day), "dimension": dimension, "horizon": horizon,
            "membership_basis": "latest_ths_snapshot_proxy", "phase_basis": "clv_amount_pressure",
            "detail": "THS最新完整成员回看，非历史时点成分；成交压力不等于净流入。有效成员不足80%时不计算。",
            "phase": phase, "outcomes": forward_outcomes(daily, days, horizon)}
