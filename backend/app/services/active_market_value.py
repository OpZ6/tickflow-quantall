"""Shared AMV research analysis through published repositories."""
from __future__ import annotations

from collections import OrderedDict, defaultdict

# ruff: noqa: RUF001 -- Chinese user-facing labels intentionally use native punctuation.
from datetime import date, timedelta
from threading import RLock
from time import monotonic

import polars as pl

from app.indicators.active_market_value import (
    ALGORITHM_VERSION,
    WARMUP,
    _change,
    _percentile,
    aggregate_active_market_value,
    compute_active_market_value,
    compute_stock_amv,
    normalize_amv_params,
    prepare_active_market_value,
    resolve_float_shares,
)
from app.market_facts.repository import MarketFactRepository
from app.quantx_data.new_high_clusters import load_ths_memberships as load_security_memberships

AMV_DIMENSIONS = ("concept", "industry_level1", "industry_level2")
_sector_cache = OrderedDict()
_sector_lock = RLock()


def _load_observations(repo, trade_date, selected, instruments, shares):
    start = trade_date - timedelta(days=650)
    rows = repo.get_daily_batch(selected, start, trade_date, columns=["symbol", "date", "raw_close", "close", "amount"])
    if not shares.is_empty() and "symbol" in shares.columns:
        shares = shares.filter(pl.col("symbol").is_in(selected))
    rows = resolve_float_shares(rows, instruments, shares)
    calendar = MarketFactRepository(repo.store.data_dir).get_trading_calendar(start, trade_date)
    if not calendar.is_empty() and calendar.height == (trade_date - start).days + 1 and calendar["is_open"].null_count() == 0:
        days = calendar.filter(pl.col("is_open"))["trade_date"].to_list()
        calendar_basis = "published_sse_calendar"
    else:
        index = repo.get_index_daily("000001.SH", start, trade_date, columns=["date"])
        days = index["date"].to_list() if not index.is_empty() and "date" in index.columns else []
        calendar_basis = "published_index_sessions"
        if not days:
            days = rows["date"].unique().to_list() if "date" in rows.columns else []
            calendar_basis = "observed_member_sessions_proxy"
    days = sorted(set(d for d in days if start <= d <= trade_date) | {trade_date})
    return rows, days, calendar_basis


def _describe(result, trade_date, calendar_basis, *, sector="", dimension="concept", unmapped=0):
    result = dict(result)
    if unmapped:
        result["requested_members"] += unmapped
        result["unknown_capital_members"] += unmapped
        result["market_cap_coverage_pct"] = None
        if result["status"] == "complete":
            result["status"] = "partial"
    return {**result, "trade_date": trade_date.isoformat(),
        "scope": "sector_latest_mapping" if sector else "selected_members", "unmapped_members": unmapped,
        "sector": sector or None, "dimension": dimension if sector else None, "calendar_basis": calendar_basis,
        "membership_basis": "latest_ext_snapshot_proxy" if sector else "caller_fixed_members",
        "share_history_basis": "effective_or_announcement_date_reconstructed",
        "notes": ["1AMV研究估计，普通流通股本口径；不是已还原的指南针0AMV。",
                  "研究优选H=8、γ=1.00、KF=1.15；KF作用于换手率，尚未用指南针原件校准。",
                  "固定成员回看；活跃增加不代表净流入。最新股本代理与成分缺失均单独披露。"]}


def _sector_batch(repo, trade_date):
    """One repository batch and one recursion per stock, shared by both pages.

    Bounded process cache, 5-minute TTL, keyed by published daily generation,
    constituent contents and capital inputs. The lock coalesces cold requests.
    """
    instruments, shares = repo.get_instruments(), repo.get_historical_shares()
    mapping = load_security_memberships(repo.store.data_dir)
    generation = repo.get_matrix_data_generation("stock")
    membership_key = tuple((dim, tuple((code, tuple(sorted(labels))) for code, labels in sorted(mapping.get(dim, {}).items())))
                           for dim in AMV_DIMENSIONS)
    key = (repo, trade_date, generation, hash(membership_key),
           instruments.hash_rows().sum() if instruments.height else 0, shares.hash_rows().sum() if shares.height else 0)
    with _sector_lock:
        cached = _sector_cache.get(key)
        if cached and monotonic() - cached[0] < 300:
            _sector_cache.move_to_end(key)
            return cached[1]
        names = dict(instruments.select("symbol", "name").iter_rows()) if {"symbol", "name"} <= set(instruments.columns) else {}
        symbols_by_code = {s.split(".")[0]: s for s in names}
        groups = {}
        selected = set()
        for dim in AMV_DIMENSIONS:
            sectors = defaultdict(set)
            for code, labels in mapping.get(dim, {}).items():
                for label in labels:
                    sectors[label].add(code)
            groups[dim] = {}
            for label, codes in sorted(sectors.items()):
                symbols = sorted(symbols_by_code[c] for c in codes if c in symbols_by_code)
                groups[dim][label] = (symbols, len(codes) - len(symbols))
                selected.update(symbols)
        rows, days, calendar_basis = _load_observations(repo, trade_date, sorted(selected), instruments, shares)
        batch = {"prepared": prepare_active_market_value(rows, days, sorted(selected), names),
                 "groups": groups, "results": {}, "days": days, "calendar_basis": calendar_basis}
        if repo.get_matrix_data_generation("stock") != generation:
            raise ValueError("日线数据正在更新，请稍后重试。")
        _sector_cache[key] = (monotonic(), batch)
        while len(_sector_cache) > 2:
            _sector_cache.popitem(last=False)
        return batch


def _sector_result(batch, trade_date, dimension, sector):
    with _sector_lock:
        key = (dimension, sector)
        if key not in batch["results"]:
            symbols, unmapped = batch["groups"][dimension][sector]
            result = aggregate_active_market_value(batch["prepared"], symbols)
            batch["results"][key] = _describe(result, trade_date, batch["calendar_basis"],
                                            sector=sector, dimension=dimension, unmapped=unmapped)
        return batch["results"][key]


def list_sector_activity(repo, trade_date=None, *, dimension="concept"):
    if dimension not in AMV_DIMENSIONS:
        raise ValueError("无效板块分类")
    trade_date = trade_date or repo.latest_enriched_date("stock") or repo.latest_daily_date()
    if trade_date is None:
        return {"available": False, "trade_date": None, "dimension": dimension, "rows": [], "available_dates": [],
                "detail": "暂无本地日线，无法计算板块活跃参与。"}
    batch = _sector_batch(repo, trade_date)
    rows = []
    for sector in batch["groups"][dimension]:
        result = _sector_result(batch, trade_date, dimension, sector)
        rows.append({k: result[k] for k in ("sector", "status", "requested_members", "covered_members", "unmapped_members",
                                           "market_cap_coverage_pct", "unknown_capital_members", "latest", "diagnosis")})
    rows.sort(key=lambda x: (-(x["latest"]["active_share_change_5d_pp"] if x["latest"] else -float("inf")), x["sector"]))
    return {"available": any(x["latest"] for x in rows), "trade_date": trade_date.isoformat(), "dimension": dimension,
            "algorithm_version": ALGORITHM_VERSION, "rows": rows,
            "available_dates": [d.isoformat() for d in batch["days"][-30:]],
            "detail": "最新概念/行业成分固定回看，普通流通股本估计；与股票池和THS板块压力排名共用完整成分。"}


def analyze_active_market_value(repo, trade_date: date, symbols: list[str], *, sector: str = "", dimension: str = "concept") -> dict:
    if sector:
        if dimension not in AMV_DIMENSIONS:
            raise ValueError("无效板块分类")
        batch = _sector_batch(repo, trade_date)
        if sector not in batch["groups"][dimension]:
            raise ValueError("找不到该板块的完整成分映射，请重新选择对应概念板块。")
        return _sector_result(batch, trade_date, dimension, sector)
    instruments = repo.get_instruments()
    names = dict(instruments.select("symbol", "name").iter_rows()) if {"symbol", "name"} <= set(instruments.columns) else {}
    selected = sorted(set(symbols))
    if not selected:
        raise ValueError("没有可分析的证券")
    if len(selected) > 1500:
        raise ValueError("成分超过1500只，请选择更具体的板块")
    shares = repo.get_historical_shares()
    rows, days, calendar_basis = _load_observations(repo, trade_date, selected, instruments, shares)
    result = compute_active_market_value(rows, days, selected, names)
    return _describe(result, trade_date, calendar_basis)


AMV_CHART_IDS = {"amv", "amvchg", "amvpct"}
AMV_CHART_FIELDS = {
    "amv": {"amv_yi": "amv_yi", "ma10": "amv_ma10", "bbi": "amv_bbi", "active_share_pct": "amv_active_pct"},
    "amvchg": {"change_pct": "amvchg_pct", "change_yi": "amvchg_yi", "active_share_pct": "amvchg_active_pct"},
    "amvpct": {"percentile": "amvpct_value", "active_share_pct": "amvpct_active_pct"},
}


def append_chart_amv(repo, rows: pl.DataFrame, configurations: dict):
    """Attach requested daily stock panes to the existing chart time axis.

    Uses unadjusted closes even when the main candles are qfq/hfq. No fact
    writes or upstream requests. As in TDX, a bar means an observed stock bar;
    absent halted bars are not synthesized. Invalid fields reset warmup.
    """
    if rows.is_empty():
        return rows, {}
    enriched = resolve_float_shares(rows, repo.get_instruments(), repo.get_historical_shares())
    observations = enriched.to_dicts()
    cache, metadata = {}, {}
    columns = []
    for indicator_id, params in configurations.items():
        p = normalize_amv_params(params)
        signature = (p["h"], p["gamma"], p["kf"])
        if signature not in cache:
            cache[signature] = compute_stock_amv(observations, params=p)
        history = cache[signature]
        output = {field: [] for field in AMV_CHART_FIELDS[indicator_id]}
        for i, current in enumerate(history):
            value = dict(current or {})
            previous = history[i - 1] if i else None
            if current and previous:
                value["change_yi"] = current["amv_yi"] - previous["amv_yi"]
                value["change_pct"] = _change(current["amv_yi"], previous["amv_yi"])
            if indicator_id == "amv" and current:
                means = {}
                for length in (3, 6, 9, 10, 12):
                    window = history[max(0, i - length + 1):i + 1]
                    means[length] = sum(x["amv_yi"] for x in window) / length if len(window) == length and all(window) else None
                value["ma10"] = means[10]
                value["bbi"] = sum(means[n] for n in (3, 6, 9, 12)) / 4 if all(means[n] is not None for n in (3, 6, 9, 12)) else None
            if indicator_id == "amvpct":
                window = history[max(0, i - int(p["n"]) + 1):i + 1]
                value["percentile"] = _percentile([x["active_share_pct"] if x else None for x in window], int(p["n"]))
            for field in output:
                output[field].append(value.get(field))
        columns.extend(pl.Series(AMV_CHART_FIELDS[indicator_id][field], values, dtype=pl.Float64)
                       for field, values in output.items())
        metadata[indicator_id] = {"algorithm_version": ALGORITHM_VERSION, "parameters": p,
            "capital_basis": "ordinary_float", "price_basis": "unadjusted",
            "bar_basis": "observed_stock_daily_bars", "latest_share_basis": observations[-1].get("share_basis"),
            "warmup_bars": max(WARMUP, int(p["h"] * 12)),
            "available": any(x is not None for x in output[next(iter(output))])}
    return rows.with_columns(columns), metadata
