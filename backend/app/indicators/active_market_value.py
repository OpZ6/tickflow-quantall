"""Bounded active-chip estimate, independent of the unauthenticated 0AMV proxies.

Amount: yuan; raw_close: unadjusted yuan/share; float_shares: ordinary shares.
The TDX source uses free float. Ordinary float therefore has its own version.
"""
from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese user-facing labels intentionally use native punctuation.
import math
from array import array
from datetime import date

import polars as pl

ALGORITHM_VERSION = "1amv-float-state-v2"
HALF_LIFE = 8
EXPONENT = 1.0
TURNOVER_FACTOR = 1.15
WARMUP = 120
DISPLAY_BARS = 30
AMV_PROFILES = {
    "research": {"h": 8, "gamma": 1.0, "kf": 1.15, "n": 250},
    "reconstructed": {"h": 10, "gamma": 1.15, "kf": 1.0, "n": 250},
}


def normalize_amv_profile(profile="research"):
    if profile not in AMV_PROFILES:
        raise ValueError("无效的 1AMV 参数口径")
    return profile, dict(AMV_PROFILES[profile])


def resolve_float_shares(rows: pl.DataFrame, instruments: pl.DataFrame, shares: pl.DataFrame) -> pl.DataFrame:
    """Use effective/announcement dates, never infer availability from report period.

Historical rows are reconstructed observations; latest shares are an explicit
fallback. Neither is advertised as verified point-in-time free float.
    """
    if rows.is_empty():
        return rows
    if {"symbol", "float_shares"} <= set(instruments.columns):
        latest = instruments.select("symbol", pl.col("float_shares").alias("_latest_float")).unique("symbol")
        rows = rows.join(latest, on="symbol", how="left")
    else:
        rows = rows.with_columns(pl.lit(None, dtype=pl.Float64).alias("_latest_float"))
    available = [pl.col(c).cast(pl.Date, strict=False) for c in ("effective_date", "announce_date") if c in shares.columns]
    if available and {"symbol", "float_shares"} <= set(shares.columns) and not shares.is_empty():
        # Announcements constrain availability even when an earlier effective date exists.
        available_date = pl.max_horizontal(available)
        history = shares.select("symbol", available_date.alias("_available_date"),
            pl.col("float_shares").cast(pl.Float64, strict=False).alias("_historical_float"))
        history = history.filter(pl.col("_available_date").is_not_null()
            & pl.col("_historical_float").is_finite() & (pl.col("_historical_float") > 0))
        history = history.unique(["symbol", "_available_date"], keep="last").sort(["symbol", "_available_date"])
        rows = rows.sort(["symbol", "date"]).join_asof(history, left_on="date", right_on="_available_date",
            by="symbol", strategy="backward", check_sortedness=False)
    else:
        rows = rows.with_columns(pl.lit(None, dtype=pl.Float64).alias("_historical_float"))
    public_columns = [c for c in rows.columns if not c.startswith("_") and c not in ("float_shares", "share_basis")]
    return rows.with_columns(pl.coalesce("_historical_float", "_latest_float").alias("float_shares"),
        pl.when(pl.col("_historical_float").is_not_null()).then(pl.lit("historical_reconstructed"))
        .otherwise(pl.lit("latest_float_proxy")).alias("share_basis")).select(*public_columns, "float_shares", "share_basis")


def _valid(value, *, positive=False):
    return isinstance(value, (int, float)) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def _change(now, previous):
    return (now / previous - 1) * 100 if previous is not None and previous > 0 else None


def _percentile(values, window=250):
    if len(values) < window or any(x is None for x in values[-window:]):
        return None
    current = values[-1]
    return 50 + 50 * sum((current > x) - (current < x) for x in values[-window:]) / window


def normalize_amv_params(params=None):
    params = params or {}
    if not isinstance(params, dict) or set(params) - {"h", "gamma", "kf", "n"}:
        raise ValueError("无效1AMV参数")
    defaults = {"h": HALF_LIFE, "gamma": EXPONENT, "kf": TURNOVER_FACTOR, "n": 250}
    bounds = {"h": (1, 30), "gamma": (.5, 2), "kf": (.5, 2), "n": (20, 250)}
    result = {}
    for key, default in defaults.items():
        value = params.get(key, default)
        low, high = bounds[key]
        if isinstance(value, bool) or not _valid(value) or not low <= value <= high:
            raise ValueError(f"1AMV {key}须在{low}至{high}之间")
        if key in {"h", "n"} and value != int(value):
            raise ValueError(f"1AMV {key}须为整数")
        result[key] = value
    return result


def compute_stock_amv(observations, *, params=None):
    """Causal per-bar kernel shared by stock charts and fixed-cohort analysis.

    Missing/invalid observations reset state; observed zero amount decays it.
    H is the zero-turnover half-life. KF modifies q, not output scale.
    """
    p = normalize_amv_params(params)
    warmup = max(WARMUP, int(p["h"] * 12))
    decay, state, count, ema = 2 ** (-1 / p["h"]), 0., 0, 0.
    history = []
    for row in observations:
        if row is None or not all((_valid(row.get("raw_close"), positive=True),
                _valid(row.get("float_shares"), positive=True), _valid(row.get("amount")))):
            history.append(None)
            state, count, ema = 0., 0, 0.
            continue
        mv = row["raw_close"] * row["float_shares"]
        if not math.isfinite(mv) or mv <= 0:
            history.append(None)
            state, count, ema = 0., 0, 0.
            continue
        u = -math.expm1(-p["kf"] * row["amount"] / mv)
        state = u + decay * (1 - u) * state
        ema = row["amount"] if not count else ema + (row["amount"] - ema) / 10
        count += 1
        history.append({"amv_yi": mv * state ** p["gamma"] / 1e8, "float_mv_yi": mv / 1e8,
            "active_share_pct": state ** p["gamma"] * 100, "amount_proxy_yi": ema / 1e7,
            "close": row.get("close"), "share_basis": row.get("share_basis", "unknown")}
            if count >= warmup else None)
    return history


def prepare_active_market_value(rows: pl.DataFrame, trading_days: list[date], symbols: list[str], names: dict[str, str], *, params=None) -> dict:
    """Calculate each stock once; retain compact columns for board aggregation.

    Only the last 250 mature observations are needed for the percentile and
    30-session chart. The recursive kernel still consumes the entire warmup.
    """
    days, wanted = sorted(set(trading_days)), sorted(set(symbols))
    p = normalize_amv_params(params)
    prepared = {"days": days[-p["n"]:], "histories": {}, "members": {}, "capital": {}, "parameters": p}
    if not days or not {"symbol", "date", "raw_close", "amount", "float_shares"} <= set(rows.columns):
        return prepared
    rows = rows.filter(pl.col("symbol").is_in(wanted) & pl.col("date").is_in(days)).sort(["symbol", "date"])
    if rows.select("symbol", "date").is_duplicated().any():
        raise ValueError("AMV输入存在重复证券交易日")
    first = max(0, len(days) - DISPLAY_BARS)
    for key, frame in rows.partition_by("symbol", as_dict=True).items():
        symbol = key[0]
        by_date = {row["date"]: row for row in frame.iter_rows(named=True)}
        last = by_date.get(days[-1], {})
        if _valid(last.get("raw_close"), positive=True) and _valid(last.get("float_shares"), positive=True):
            mv = last["raw_close"] * last["float_shares"] / 1e8
            if math.isfinite(mv):
                prepared["capital"][symbol] = mv
        history = compute_stock_amv([by_date.get(day) for day in days], params=p)
        if len(days) < 6 or any(x is None for x in history[first:]):
            continue
        current, prev, past5 = history[-1], history[-2], history[-6]
        prepared["members"][symbol] = {"symbol": symbol, "name": names.get(symbol, symbol),
            **{k: v for k, v in current.items() if k != "close"},
            "amv_change_yi": current["amv_yi"] - prev["amv_yi"],
            "amv_change_pct": _change(current["amv_yi"], prev["amv_yi"]),
            "amv_change_5d_pct": _change(current["amv_yi"], past5["amv_yi"]),
            "active_share_change_5d_pp": current["active_share_pct"] - past5["active_share_pct"],
            "percentile_250": _percentile([x["active_share_pct"] if x else None for x in history], p["n"]),
            "price_change_5d_pct": _change(current["close"], past5["close"]) if _valid(current["close"], positive=True) else None}
        columns = {field: array("d", (x[field] if x else math.nan for x in history[-250:]))
                   for field in ("amv_yi", "float_mv_yi", "amount_proxy_yi")}
        base_close = history[first]["close"]
        columns["price_index"] = array("d", (x["close"] / base_close * 100
            if x and _valid(x["close"], positive=True) and _valid(base_close, positive=True) else math.nan
            for x in history[-250:]))
        prepared["histories"][symbol] = columns
    return prepared


def aggregate_active_market_value(prepared: dict, symbols: list[str]) -> dict:
    """V_board=sum(V_i), a_board=sum(V_i)/sum(M_i), using one fixed cohort."""
    days, wanted = prepared["days"], sorted(set(symbols))
    params = prepared.get("parameters", normalize_amv_params())
    result = {"algorithm_version": ALGORITHM_VERSION, "official_0amv_verified": False,
        "capital_basis": "ordinary_float", "status": "unavailable",
        "parameters": {"half_life_sessions": params["h"], "exponent": params["gamma"],
                       "turnover_factor": params["kf"], "percentile_sessions": params["n"],
                       "warmup_sessions": max(WARMUP, int(params["h"] * 12))},
        "requested_members": len(wanted), "covered_members": 0, "series": [], "members": [], "excluded": [],
        "latest": None, "diagnosis": "缺少连续预热行情或目标日日线，暂不能计算。"}
    result["market_cap_coverage_pct"] = None
    result["unknown_capital_members"] = sum(s not in prepared["capital"] for s in wanted)
    histories = {s: prepared["histories"][s] for s in wanted if s in prepared["histories"]}
    result["members"] = [dict(prepared["members"][s]) for s in histories]
    result["excluded"] = [{"symbol": s, "reason": f"近30交易日缺日、无效输入或不足{WARMUP}日连续预热"}
                          for s in wanted if s not in histories]
    if not histories:
        return result
    first = max(0, len(days) - DISPLAY_BARS)
    result["covered_members"] = len(histories)
    result["status"] = "complete" if len(histories) == len(wanted) else "partial"
    members, aggregate = result["members"], []
    totals = {field: [sum(values) for values in zip(*(h[field] for h in histories.values()), strict=True)]
              for field in ("amv_yi", "float_mv_yi", "amount_proxy_yi", "price_index")}
    for i, day in enumerate(days):
        amv, mv = totals["amv_yi"][i], totals["float_mv_yi"][i]
        if not math.isfinite(amv) or not math.isfinite(mv):
            aggregate.append(None)
            continue
        price = totals["price_index"][i] / len(histories)
        aggregate.append({"date": day.isoformat(), "amv_yi": amv, "float_mv_yi": mv,
            "active_share_pct": amv / mv * 100, "amount_proxy_yi": totals["amount_proxy_yi"][i],
            "price_index": price if math.isfinite(price) else None})
    current, prev, past5 = aggregate[-1], aggregate[-2], aggregate[-6]
    moving = [x["amv_yi"] for x in aggregate[-10:] if x is not None]
    moving_average = sum(moving) / len(moving) if len(moving) == 10 else None
    current["relative_ma10_pct"] = (current["amv_yi"] / moving_average - 1) * 100 if moving_average else None
    for member in members:
        member["amv_share_pct"] = member["amv_yi"] / current["amv_yi"] * 100 if current["amv_yi"] > 0 else None
    if not result["unknown_capital_members"]:
        result["market_cap_coverage_pct"] = current["float_mv_yi"] / sum(prepared["capital"][s] for s in wanted) * 100
    result["latest"] = {**current, "amv_change_pct": _change(current["amv_yi"], prev["amv_yi"]),
        "amv_change_5d_pct": _change(current["amv_yi"], past5["amv_yi"]),
        "active_share_change_5d_pp": current["active_share_pct"] - past5["active_share_pct"],
        "price_change_5d_pct": _change(current["price_index"], past5["price_index"]) if current["price_index"] is not None else None,
        "expanding_members_5d": sum(x["active_share_change_5d_pp"] > 0 for x in members),
        "expanding_members_5d_pct": sum(x["active_share_change_5d_pp"] > 0 for x in members) / len(members) * 100,
        "top3_amv_share_pct": sum(sorted((x["amv_yi"] for x in members), reverse=True)[:3]) / current["amv_yi"] * 100 if current["amv_yi"] > 0 else None,
        "latest_float_proxy_members": sum(x["share_basis"] == "latest_float_proxy" for x in members),
        "percentile_250": _percentile([x["active_share_pct"] if x else None for x in aggregate], params["n"])}
    result["series"] = aggregate[first:]
    result["members"].sort(key=lambda x: (-x["amv_yi"], x["symbol"]))
    delta, price = result["latest"]["active_share_change_5d_pp"], result["latest"]["price_change_5d_pct"]
    if price is None:
        result["diagnosis"] = "价格参照缺失，仅观察活跃占比变化。"
    elif delta > 0 and price > 0:
        result["diagnosis"] = "近5日价格与活跃占比同步增强。"
    elif delta < 0 and price > 0:
        result["diagnosis"] = "近5日价格走强、活跃占比回落，关注参与是否收缩。"
    elif delta > 0 and price < 0:
        result["diagnosis"] = "近5日下跌伴随活跃增加，关注分歧换手与抛压。"
    elif delta < 0 and price < 0:
        result["diagnosis"] = "近5日价格与活跃占比同步回落。"
    else:
        result["diagnosis"] = "近5日价格或活跃占比持平。"
    return result


def compute_active_market_value(rows: pl.DataFrame, trading_days: list[date], symbols: list[str], names: dict[str, str], *, params=None) -> dict:
    return aggregate_active_market_value(prepare_active_market_value(rows, trading_days, symbols, names, params=params), symbols)
