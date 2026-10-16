"""Full-history active-character candidate study without trade execution.

Run from backend: uv run --frozen python ../scripts/research_active_character_pool.py
"""
import gc
import json
import os
from pathlib import Path

import numpy as np
import polars as pl
from research_trend_pullback_pool import (
    block_ci,
    eligibility_matrix,
    matched_paired,
    write_json,
)
from research_trend_pullback_pool import (
    future_labels as long_future_labels,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/active-character/v1"
DOCS = ROOT / "docs/research/stock-pools/active-character"
START = "2016-01-04"
END = "2026-09-11"
BSE_START = np.datetime64("2021-11-15")
HORIZONS = (1, 2, 3, 5, 10, 20)


def _band(column, edges, names):
    expr = pl.when(pl.col(column).is_null()).then(pl.lit("unknown"))
    for edge, name in zip(edges, names, strict=False):
        expr = expr.when(pl.col(column) < edge).then(pl.lit(name))
    return expr.otherwise(pl.lit(names[-1]))


def rolling_features(frame):
    exprs = []
    for n in (10, 20, 60):
        exprs.extend([
            pl.col("close").rolling_mean(n, min_samples=n).over("symbol").alias(f"ma{n}"),
            (pl.col("idx") - pl.col("idx").shift(n - 1).over("symbol") == n - 1)
            .fill_null(False).alias(f"complete_ma{n}"),
        ])
    for n in (30, 60):
        exprs.extend([
            pl.col("is_limit").cast(pl.Int16).rolling_sum(n, min_samples=n).over("symbol").alias(f"limit_count{n}"),
            (pl.col("idx") - pl.col("idx").shift(n - 1).over("symbol") == n - 1)
            .fill_null(False).alias(f"complete{n}"),
        ])
    exprs.extend([
        pl.col("volume").shift(1).rolling_mean(20, min_samples=20).over("symbol").alias("prior_volume20"),
        pl.col("close").shift(20).over("symbol").alias("close20ago"),
        pl.col("close").shift(1).rolling_max(20, min_samples=20).over("symbol").alias("prior_high20"),
        (pl.col("idx") - pl.col("idx").shift(20).over("symbol") == 20).fill_null(False).alias("complete_prior20"),
    ])
    result = frame.with_columns(exprs).with_columns([
        pl.when(pl.col(f"complete_ma{n}")).then(pl.col(f"ma{n}")).otherwise(None).alias(f"ma{n}")
        for n in (10, 20, 60)
    ] + [
        pl.when(pl.col(f"complete{n}")).then(pl.col(f"limit_count{n}")).otherwise(None).alias(f"limit_count{n}")
        for n in (30, 60)
    ])
    return result.with_columns([
        pl.when((pl.col("idx") - pl.col("idx").shift(10).over("symbol") == 10).fill_null(False))
        .then(pl.col("ma20").shift(10).over("symbol")).alias("ma20_10ago"),
        pl.when(pl.col("complete_prior20") & (pl.col("prior_volume20") > 0))
        .then(pl.col("volume") / pl.col("prior_volume20")).alias("volume_ratio"),
        pl.when(pl.col("complete_prior20")).then(pl.col("close") / pl.col("close20ago") - 1).alias("return20_past"),
        pl.when(pl.col("complete_prior20")).then(pl.col("close") / pl.col("prior_high20") - 1).alias("drawdown20"),
    ])


def activity_state(limit_hits, max_age=59):
    """Track latest limit-up and logical consecutive-board campaign start."""
    last = np.full(limit_hits.shape[1], -1000, dtype=np.int32)
    campaign = last.copy()
    previous = np.zeros(limit_hits.shape[1], dtype=bool)
    age = np.full(limit_hits.shape, -1, dtype=np.int16)
    campaign_age = np.full(limit_hits.shape, -1, dtype=np.int16)
    last_rows = np.full(limit_hits.shape, -1, dtype=np.int32)
    campaign_rows = np.full(limit_hits.shape, -1, dtype=np.int32)
    for i in range(limit_hits.shape[0]):
        hit = limit_hits[i]
        fresh = hit & ~previous
        campaign[fresh] = i
        last[hit] = i
        active = (last >= 0) & (i - last <= max_age)
        age[i, active] = i - last[active]
        campaign_age[i, active] = i - campaign[active]
        last_rows[i, active] = last[active]
        campaign_rows[i, active] = campaign[active]
        previous = hit
    return age, campaign_age, last_rows, campaign_rows


def classify(frame):
    return frame.with_columns([
        pl.when(pl.col("sample_kind") == "control").then(pl.lit("control_no_limit60"))
        .when(pl.col("limit_age") <= 29).then(pl.lit("active30"))
        .otherwise(pl.lit("active31-60")).alias("pool_window"),
        pl.when(pl.col("limit_age") < 0).then(pl.lit("control"))
        .when(pl.col("limit_age") == 0).then(pl.lit("0"))
        .when(pl.col("limit_age") <= 3).then(pl.lit("1-3"))
        .when(pl.col("limit_age") <= 10).then(pl.lit("4-10"))
        .when(pl.col("limit_age") <= 20).then(pl.lit("11-20"))
        .when(pl.col("limit_age") <= 29).then(pl.lit("21-29"))
        .otherwise(pl.lit("30-59")).alias("freshness_band"),
        pl.when(pl.col("limit_count30").is_null()).then(pl.lit("unknown"))
        .when(pl.col("limit_count30") <= 1).then(pl.lit("1"))
        .when(pl.col("limit_count30") == 2).then(pl.lit("2"))
        .otherwise(pl.lit("3+")).alias("frequency30_band"),
        pl.when(pl.col("limit_count60").is_null()).then(pl.lit("unknown"))
        .when(pl.col("limit_count60") <= 1).then(pl.lit("1"))
        .when(pl.col("limit_count60") == 2).then(pl.lit("2"))
        .otherwise(pl.lit("3+")).alias("frequency60_band"),
        pl.when(
            (pl.col("close") > pl.col("ma10")) & (pl.col("ma10") > pl.col("ma20"))
            & (pl.col("ma20") > pl.col("ma60")) & (pl.col("ma20") > pl.col("ma20_10ago"))
        ).then(pl.lit("strong"))
        .when((pl.col("close") > pl.col("ma20")) & (pl.col("ma20") > pl.col("ma60")))
        .then(pl.lit("basic")).otherwise(pl.lit("nontrend")).alias("trend_context"),
        _band("return20_past", [0, .1, .3], ["negative", "0-10%", "10-30%", "30%+"]).alias("return20_band"),
        _band("drawdown20", [-.15, -.08, -.03], ["<-15%", "-15--8%", "-8--3%", "-3%+"]).alias("drawdown_band"),
        _band("volume_ratio", [.8, 1.2, 2], ["<0.8", "0.8-1.2", "1.2-2", "2+"]).alias("volume_band"),
        pl.when(pl.col("sample_kind") == "control").then(pl.lit("control"))
        .when(pl.col("close") < pl.col("last_limit_low") * .999).then(pl.lit("below_event_low"))
        .when(pl.col("close") < pl.col("ma20")).then(pl.lit("below_ma20"))
        .when(pl.col("close") >= pl.col("last_limit_close")).then(pl.lit("above_event_close"))
        .otherwise(pl.lit("between_event_and_ma20")).alias("current_state"),
        (pl.col("amount_rank") <= 100).fill_null(False).alias("top100_amount"),
        (pl.col("amount_rank") <= 200).fill_null(False).alias("top200_amount"),
        pl.col("breakthrough_age").is_not_null().alias("recent_breakthrough"),
        pl.col("pullback_event").fill_null(False),
        pl.col("date").dt.year().cast(pl.String).alias("year"),
    ])


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    parts_dir = OUT / "parts"
    parts_dir.mkdir(exist_ok=True)
    paths = sorted((ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet"))
    paths = [path for path in paths if path.parent.name <= f"date={END}"]
    scan = pl.scan_parquet(paths)
    dates = scan.select("date").unique().sort("date").collect()["date"].to_list()
    calendar = pl.DataFrame({"date": dates}).with_row_index("idx")
    start_idx = calendar.filter(pl.col("date") >= pl.lit(START).str.to_date())["idx"].min()
    symbols = scan.select("symbol").unique().sort("symbol").collect()["symbol"].to_list()
    total_prices = invalid_ohlc = adjustment_mismatch = 0

    for batch, beg in enumerate(range(0, len(symbols), 300)):
        selected = symbols[beg:beg + 300]
        prices = (scan.filter(pl.col("symbol").is_in(selected))
            .select("symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "raw_high", "raw_low", "consecutive_limit_ups")
            .collect().join(calendar, on="date").sort("symbol", "date")
            .with_columns(((pl.col("consecutive_limit_ups") > 0)
                & (~pl.col("symbol").str.ends_with(".BJ") | (pl.col("date") >= pl.lit(str(BSE_START)).str.to_date())))
                .alias("is_limit")))
        total_prices += prices.height
        bad = prices.select(((pl.col("high") < pl.col("low")) | (pl.col("high") < pl.col("close"))
            | (pl.col("low") > pl.col("close")) | (pl.col("high") < pl.col("open")) | (pl.col("low") > pl.col("open"))).sum()).item()
        mismatch = prices.select((((pl.col("high") / pl.col("raw_high") - pl.col("close") / pl.col("raw_close")).abs() > 1e-5)
            | ((pl.col("low") / pl.col("raw_low") - pl.col("close") / pl.col("raw_close")).abs() > 1e-5)).sum()).item()
        invalid_ohlc += bad
        adjustment_mismatch += mismatch
        if bad or mismatch:
            raise ValueError("OHLC or within-bar adjustment factors inconsistent")
        prices = rolling_features(prices)
        mapping = {symbol: i for i, symbol in enumerate(selected)}
        row_idx = prices["idx"].to_numpy()
        col_idx = prices["symbol"].replace_strict(mapping, return_dtype=pl.Int32).to_numpy()
        shape = (len(dates), len(selected))
        eligible = eligibility_matrix(dates, selected)

        def dense(field, shape=shape, row_idx=row_idx, col_idx=col_idx, prices=prices):
            values = np.full(shape, np.nan, dtype=np.float32)
            values[row_idx, col_idx] = prices[field].to_numpy()
            return values

        arrays = {field: dense(field) for field in (
            "open", "high", "low", "close", "ma10", "ma20", "ma60", "ma20_10ago", "limit_count30", "limit_count60",
            "volume_ratio", "return20_past", "drawdown20",
        )}
        limit_hits = np.zeros(shape, dtype=bool)
        limit_hits[row_idx, col_idx] = prices["is_limit"].to_numpy()
        limit_hits &= eligible
        age, campaign_age, last_rows, campaign_rows = activity_state(limit_hits)
        labels = long_future_labels(arrays["open"], arrays["high"], arrays["low"], arrays["close"])
        complete60 = np.isfinite(arrays["limit_count60"])
        global_cols = beg + np.arange(len(selected), dtype=np.int64)
        hash_sample = ((np.arange(len(dates), dtype=np.int64)[:, None] * 1315423911
                        + global_cols[None, :] * 2654435761) % 10) == 0
        controls = complete60 & (arrays["limit_count60"] == 0) & hash_sample & eligible
        chosen = (age >= 0) | controls
        chosen[:start_idx] = False
        ti, si = np.nonzero(chosen)
        event_i = last_rows[ti, si]
        is_active = age[ti, si] >= 0

        def current(field, arrays=arrays, ti=ti, si=si):
            return arrays[field][ti, si]

        event_close = np.full(len(ti), np.nan, dtype=np.float32)
        event_low = np.full(len(ti), np.nan, dtype=np.float32)
        event_close[is_active] = arrays["close"][event_i[is_active], si[is_active]]
        event_low[is_active] = arrays["low"][event_i[is_active], si[is_active]]
        data = {"symbol": np.asarray(selected)[si], "date": np.asarray(dates, dtype="datetime64[D]")[ti], "idx": ti.astype(np.int32),
            "sample_kind": np.where(is_active, "active", "control"), "limit_age": age[ti, si],
            "campaign_age": campaign_age[ti, si], "last_limit_idx": event_i, "campaign_idx": campaign_rows[ti, si],
            "last_limit_close": event_close, "last_limit_low": event_low,
            **{field: current(field) for field in ("open", "high", "low", "close", "ma10", "ma20", "ma60", "ma20_10ago",
                "limit_count30", "limit_count60", "volume_ratio", "return20_past", "drawdown20")}}
        for h in HORIZONS:
            values = labels[h]
            data.update({f"r{h}_open": values["return"][ti, si], f"mfe{h}": values["mfe"][ti, si],
                f"mae{h}": values["mae"][ti, si], f"peak_day{h}": values["peak"][ti, si], f"low_first{h}": values["low_first"][ti, si]})
        pl.DataFrame(data).with_columns(pl.col(pl.Float32).fill_nan(None)).write_parquet(parts_dir / f"part-{batch:03d}.parquet")
        print(f"batch {batch + 1}: {beg + len(selected)}/{len(symbols)} stocks, {len(ti)} rows", flush=True)

    ledger = pl.scan_parquet(parts_dir / "*.parquet").collect()
    market = pl.read_parquet(ROOT / "data/research/stock-pools/trend-pullback/v1/market-baseline.parquet").select(
        "date", "environment", *[f"market{h}_open" for h in HORIZONS])
    ledger = ledger.join(market, on="date", validate="m:1")
    liquidity = pl.read_parquet(ROOT / "data/research/stock-pools/liquidity-trend/v1/daily-ledger.parquet").select(
        "symbol", "date", pl.col("amount_rank"))
    breakthrough = (pl.scan_parquet(ROOT / "data/research/stock-pools/breakthrough/v1/daily-ledger.parquet")
        .filter(pl.col("age_close60") >= 0).select("symbol", "date", pl.col("age_close60").alias("breakthrough_age")).collect())
    pullback = (pl.scan_parquet(ROOT / "data/research/stock-pools/trend-pullback/v1/event-ledger.parquet")
        .filter(pl.col("trend_context") != "nontrend").group_by("symbol", "date").agg(pl.lit(True).alias("pullback_event")).collect())
    ledger = (ledger.join(liquidity, on=["symbol", "date"], how="left", validate="m:1")
        .join(breakthrough, on=["symbol", "date"], how="left", validate="m:1")
        .join(pullback, on=["symbol", "date"], how="left", validate="m:1"))
    ledger = classify(ledger)
    ledger.write_parquet(OUT / "daily-ledger.parquet")
    ledger.filter((pl.col("sample_kind") == "active") & (pl.col("campaign_age") == 0)).write_parquet(OUT / "event-ledger.parquet")
    coverage = {"price_first": str(dates[0]), "price_last": str(dates[-1]), "sessions": len(dates), "price_rows": total_prices,
        "stocks": len(symbols), "rows": ledger.height, "active_rows": ledger.filter(pl.col("sample_kind") == "active").height,
        "control_rows": ledger.filter(pl.col("sample_kind") == "control").height, "control_sample_rate": 0.1,
        "signal_first": START, "signal_last": END, "limit_definition": "consecutive_limit_ups > 0",
        "ohlc_invalid": invalid_ohlc, "adjustment_bar_mismatch": adjustment_mismatch,
        "bse_signal_start": str(BSE_START), "pre_bse_neeq_quotes": "excluded from activity and controls",
        "entry_basis": "next_session_open", "horizons": list(HORIZONS),
        "historical_listing_universe": "cached symbols; completeness and delisted coverage unverified"}
    write_json(OUT / "coverage.json", coverage)
    return coverage


def stats(frame, h):
    key = f"r{h}_open"
    valid = frame.filter(pl.col(key).is_not_null())
    if not valid.height:
        return {"n": 0, "dates": 0}
    daily = valid.group_by("date").agg(pl.col(key).mean().alias("mean"),
        (pl.col(key) - pl.col(f"market{h}_open")).mean().alias("excess"), (pl.col(key) > 0).mean().alias("positive"),
        pl.col(f"mfe{h}").mean().alias("mfe"), pl.col(f"mae{h}").mean().alias("mae"))
    values = valid[key]
    return {"n": valid.height, "dates": daily.height, "stocks": valid["symbol"].n_unique(),
        "mean": daily["mean"].mean(), "excess": daily["excess"].mean(), "positive": daily["positive"].mean(),
        "median_sample": values.median(), "p10_sample": values.quantile(.1, interpolation="linear"),
        "avg_win_sample": values.filter(values > 0).mean(), "avg_loss_sample": values.filter(values < 0).mean(),
        "mfe": daily["mfe"].mean(), "mae": daily["mae"].mean()}


def summaries(frame):
    return {str(h): stats(frame, h) for h in HORIZONS}


def paired(frame, predicate, h):
    key = f"r{h}_open"
    valid = frame.filter(pl.col(key).is_not_null())
    kept = valid.filter(predicate).group_by("date").agg(pl.col(key).mean().alias("kept"))
    removed = valid.filter(~predicate).group_by("date").agg(pl.col(key).mean().alias("removed"))
    both = kept.join(removed, on="date").sort("date")
    values = (both["kept"] - both["removed"]).to_numpy()
    return {"dates": both.height, "difference": float(values.mean()) if len(values) else None,
        "block20_ci95": block_ci(values)}


def rule_result(book, predicate):
    known = book.filter(predicate.is_not_null())
    kept, removed = known.filter(predicate), known.filter(~predicate)
    winners = known.filter(pl.col("r10_open") >= .2)
    return {"known": known.height, "retained": kept.height / known.height if known.height else None,
        "winner_rows": winners.height, "winner_retention": winners.filter(predicate).height / winners.height if winners.height else None,
        "kept": summaries(kept), "removed": summaries(removed),
        "paired": {str(h): paired(known, predicate, h) for h in HORIZONS},
        "yearly10": {year: {"kept": stats(kept.filter(pl.col("year") == year), 10),
            "removed": stats(removed.filter(pl.col("year") == year), 10)} for year in sorted(known["year"].unique().to_list())}}


def heat_context(active30):
    path = ROOT / "data/research/stock-pools/popularity/v2/daily-ledger.parquet"
    if not path.exists():
        return {}
    heat = pl.read_parquet(path)
    if heat.schema["date"] == pl.String:
        heat = heat.with_columns(pl.col("date").str.to_date())
    result = {}
    for source in sorted(heat["source"].unique().to_list()):
        source_heat = heat.filter(pl.col("source") == source).select("date", "symbol", pl.col("band").alias("heat_band"))
        dates = source_heat["date"].unique()
        book = (active30.filter(pl.col("date").is_in(dates.implode())).join(source_heat, on=["date", "symbol"], how="left")
            .with_columns(pl.col("heat_band").fill_null("observed_outside"), pl.col("heat_band").is_not_null().alias("hot")))
        result[source] = {"coverage_dates": len(dates), "members": book.height,
            "groups": {value: summaries(book.filter(pl.col("heat_band") == value)) for value in sorted(book["heat_band"].unique().to_list())},
            "matched": {str(h): matched_paired(book, pl.col("hot"), ["freshness_band", "trend_context"], h) for h in HORIZONS}}
    return result


def matched_identity_lazy(active_predicate=None):
    if active_predicate is None:
        active_predicate = pl.col("pool_window") == "active30"
    result = {}
    for h in HORIZONS:
        key = f"r{h}_open"
        cells = (pl.scan_parquet(OUT / "daily-ledger.parquet")
            .filter(((pl.col("sample_kind") == "control") | active_predicate) & pl.col(key).is_not_null())
            .group_by("date", "trend_context", "drawdown_band", "return20_band", "sample_kind")
            .agg(pl.col(key).mean().alias("mean"), pl.len().alias("n")).collect(engine="streaming"))
        active = cells.filter((pl.col("sample_kind") == "active") & (pl.col("n") >= 3))
        control = cells.filter((pl.col("sample_kind") == "control") & (pl.col("n") >= 3))
        both = active.join(control, on=["date", "trend_context", "drawdown_band", "return20_band"], suffix="_control")
        daily = both.group_by("date").agg((pl.col("mean") - pl.col("mean_control")).mean().alias("difference")).sort("date")
        values = daily["difference"].to_numpy()
        result[str(h)] = {"dates": daily.height, "cells": both.height,
            "difference": float(values.mean()) if len(values) else None, "block20_ci95": block_ci(values),
            "minimum_each_side": 3, "control_sample_rate": .1}
    return result


def analysis_columns():
    return ["symbol", "date", "idx", "sample_kind", "pool_window", "limit_age", "campaign_age", "limit_count30",
        "limit_count60", "last_limit_low", "close", "ma20", "ma20_10ago", "freshness_band", "frequency30_band",
        "frequency60_band", "trend_context", "current_state", "drawdown_band", "return20_band", "volume_band",
        "environment", "top100_amount", "recent_breakthrough", "pullback_event", "year",
        *[f"{prefix}{h}{suffix}" for h in HORIZONS for prefix, suffix in (
            ("r", "_open"), ("market", "_open"), ("mfe", ""), ("mae", ""))]]


def analyze(coverage):
    columns = analysis_columns()
    scan = pl.scan_parquet(OUT / "daily-ledger.parquet")
    events = pl.read_parquet(OUT / "event-ledger.parquet", columns=columns)
    report = {"protocol": "active-character-v1", "scope": "exploration; no trade execution or independent validation",
        "coverage": coverage, "horizons": list(HORIZONS), "views": {}, "rules": {}}
    active60 = scan.filter(pl.col("sample_kind") == "active").select(columns).collect()
    report["views"]["active60"] = summaries(active60)
    report["views"]["active30"] = summaries(active60.filter(pl.col("limit_age") <= 29))
    report["views"]["campaign_events"] = summaries(events)
    for age in range(0, 6):
        report["views"][f"active60|limit_age:{age}"] = summaries(active60.filter(pl.col("limit_age") == age))
    for factor in ("freshness_band", "frequency30_band", "frequency60_band", "trend_context", "current_state", "drawdown_band",
                   "return20_band", "volume_band", "environment", "top100_amount", "recent_breakthrough", "pullback_event"):
        for value in sorted(active60[factor].unique().to_list(), key=str):
            selection = active60.filter(pl.col(factor) == value)
            report["views"][f"active60|{factor}:{value}"] = summaries(selection)
            del selection
    del active60
    gc.collect()

    controls = scan.filter(pl.col("sample_kind") == "control").select(columns).collect()
    report["views"]["controls10pct"] = summaries(controls)
    del controls
    gc.collect()
    for name, predicate in (("active60", pl.col("sample_kind") == "active"),
                            ("active30", pl.col("pool_window") == "active30"),
                            ("controls10pct", pl.col("sample_kind") == "control")):
        book = scan.filter(predicate)
        sizes = book.group_by("date").len().collect(engine="streaming")
        counts = book.select(pl.len().alias("rows"), pl.col("symbol").approx_n_unique().alias("stocks")).collect(engine="streaming").row(0, named=True)
        report.setdefault("size", {})[name] = {**counts, "dates": sizes.height,
            "daily_median": sizes["len"].median(), "daily_p90": sizes["len"].quantile(.9)}
    event_sizes = events.group_by("date").len()
    report["size"]["campaign_events"] = {"rows": events.height, "stocks": events["symbol"].n_unique(), "dates": event_sizes.height,
        "daily_median": event_sizes["len"].median(), "daily_p90": event_sizes["len"].quantile(.9)}

    active30 = scan.filter(pl.col("pool_window") == "active30").select(columns).collect()
    age1 = active30.filter(pl.col("limit_age") == 1)
    for factor in ("frequency30_band", "frequency60_band", "trend_context", "current_state", "drawdown_band",
                   "return20_band", "volume_band", "environment", "top100_amount", "recent_breakthrough", "pullback_event"):
        for value in sorted(age1[factor].unique().to_list(), key=str):
            report["views"][f"age1|{factor}:{value}"] = summaries(age1.filter(pl.col(factor) == value))
    rules = {"age1": pl.col("limit_age") == 1, "age1_3": pl.col("limit_age").is_between(1, 3),
        "fresh_5": pl.col("limit_age") <= 5, "fresh_10": pl.col("limit_age") <= 10,
        "frequency30_2plus": pl.col("limit_count30") >= 2, "frequency60_3plus": pl.col("limit_count60") >= 3,
        "non_downtrend": pl.col("trend_context") != "nontrend", "above_ma20": pl.col("close") > pl.col("ma20"),
        "ma20_rising": pl.col("ma20") > pl.col("ma20_10ago"), "holds_event_low": pl.col("close") >= pl.col("last_limit_low"),
        "top100_amount": pl.col("top100_amount"), "recent_breakthrough": pl.col("recent_breakthrough"),
        "pullback_event": pl.col("pullback_event")}
    for name, predicate in rules.items():
        report["rules"][name] = rule_result(active30, predicate)
        gc.collect()
    report["matched_identity"] = matched_identity_lazy()
    report["matched_age1"] = matched_identity_lazy(pl.col("limit_age") == 1)
    report["annual_active30"] = {year: summaries(active30.filter(pl.col("year") == year)) for year in sorted(active30["year"].unique().to_list())}
    report["annual_age1"] = {year: summaries(active30.filter((pl.col("year") == year) & (pl.col("limit_age") == 1)))
                             for year in sorted(active30["year"].unique().to_list())}
    limit_days = (pl.scan_parquet(ROOT / "data/kline_daily_enriched/date=*/part.parquet")
        .filter((pl.col("date") <= pl.lit(END).str.to_date()) & (pl.col("consecutive_limit_ups") > 0))
        .select("symbol", "date", "open", "high", "low", "close",
                pl.col("consecutive_limit_ups").alias("board_height")).collect()
        .with_columns((pl.col("high") == pl.col("low")).alias("one_price_limit")))
    age0 = (active30.filter(pl.col("limit_age") == 0).join(limit_days, on=["symbol", "date"], validate="1:1")
        .with_columns(pl.when(pl.col("board_height") == 1).then(pl.lit("first"))
            .when(pl.col("board_height") == 2).then(pl.lit("second")).otherwise(pl.lit("third_plus")).alias("board_band")))
    age0.write_parquet(OUT / "limit-day-ledger.parquet")
    report["limit_days"] = {"all": summaries(age0), **{
        value: summaries(age0.filter(pl.col("board_band") == value)) for value in sorted(age0["board_band"].unique().to_list())}}
    report["limit_day_higher_board"] = rule_result(age0, pl.col("board_height") >= 2)
    report["limit_day_one_price"] = rule_result(age0, pl.col("one_price_limit"))
    report["limit_day_higher_nonflat"] = rule_result(age0, (pl.col("board_height") >= 2) & ~pl.col("one_price_limit"))
    report["heat"] = heat_context(active30)
    write_json(OUT / "analysis.json", report)
    write_results(report)
    return report


def pct(value):
    return "—" if value is None else f"{value * 100:.2f}"


def write_results(report):
    lines = ["# 股性活跃池v1数值结果", "", "脚本生成。全部未来收益与路径从次日开盘起算。", ""]

    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
        lines.append("")

    table("规模", ["账本", "记录", "股票", "日期", "日规模中位数/P90"],
        [[name, value["rows"], value["stocks"], value["dates"], f'{value["daily_median"]}/{value["daily_p90"]}'] for name, value in report["size"].items()])
    table("基线与分层", ["视角", "周期", "收益%", "超额百分点", "正收益率%", "P10%", "记录/日期"],
        [[name, h, pct(value.get("mean")), pct(value.get("excess")), pct(value.get("positive")), pct(value.get("p10_sample")),
          f'{value["n"]}/{value["dates"]}'] for name, periods in report["views"].items() for h, value in periods.items()])
    table("条件与机会损失", ["规则", "保留%", "10日保留/剔除超额", "大赢家保留%"],
        [[name, pct(value["retained"]), f'{pct(value["kept"]["10"].get("excess"))}/{pct(value["removed"]["10"].get("excess"))}',
          pct(value["winner_retention"])] for name, value in report["rules"].items()])
    table("同日条件差", ["规则", "周期", "保留减剔除百分点", "共同日期", "20日期块95%区间"],
        [[name, h, pct(value.get("difference")), value["dates"], " / ".join(pct(x) for x in value["block20_ci95"])]
         for name, rule in report["rules"].items() for h, value in rule["paired"].items()])
    table("活跃身份匹配对照", ["周期", "活跃减非活跃百分点", "共同日期/状态格", "20日期块95%区间"],
        [[h, pct(value.get("difference")), f'{value["dates"]}/{value["cells"]}', " / ".join(pct(x) for x in value["block20_ci95"])]
         for h, value in report["matched_identity"].items()])
    table("涨停后第1日匹配对照", ["周期", "活跃减非活跃百分点", "共同日期/状态格", "20日期块95%区间"],
        [[h, pct(value.get("difference")), f'{value["dates"]}/{value["cells"]}', " / ".join(pct(x) for x in value["block20_ci95"])]
         for h, value in report["matched_age1"].items()])
    table("涨停当日板位", ["板位", "周期", "收益%", "超额百分点", "记录/日期"],
        [[name, h, pct(value.get("mean")), pct(value.get("excess")), f'{value["n"]}/{value["dates"]}']
         for name, periods in report["limit_days"].items() for h, value in periods.items()])
    table("涨停当日可交易性拆解", ["规则", "保留%", "10日保留/剔除超额", "大赢家保留%"],
        [[name, pct(value["retained"]), f'{pct(value["kept"]["10"].get("excess"))}/{pct(value["removed"]["10"].get("excess"))}',
          pct(value["winner_retention"])] for name, value in (
              ("二板及以上", report["limit_day_higher_board"]),
              ("一字涨停", report["limit_day_one_price"]),
              ("非一字二板及以上", report["limit_day_higher_nonflat"]))])
    (DOCS / "v1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_samples():
    scan = pl.scan_parquet(OUT / "daily-ledger.parquet")
    events = scan.filter((pl.col("sample_kind") == "active") & (pl.col("campaign_age") == 0)).sort(
        pl.struct("symbol", "date").hash(seed=20260914)).head(20).collect()
    assertions = 0
    for row in events.to_dicts():
        assert row["limit_age"] == 0 and row["campaign_age"] == 0
        assert (row["limit_count60"] is None or row["limit_count60"] >= 1) and row["last_limit_idx"] == row["idx"]
        assertions += 4
    controls = scan.filter(pl.col("sample_kind") == "control").sort(pl.struct("symbol", "date").hash(seed=7)).head(20).collect()
    for row in controls.to_dicts():
        assert row["limit_age"] == -1 and row["limit_count60"] == 0
        assertions += 2
    result = {"status": "passed", "event_samples": events.height, "control_samples": controls.height,
        "assertions": assertions, "horizons": list(HORIZONS)}
    write_json(OUT / "verification.json", result)
    return result


def main():
    required = (OUT / "daily-ledger.parquet", OUT / "event-ledger.parquet", OUT / "coverage.json")
    if os.environ.get("REBUILD_STOCK_POOL") != "1" and all(path.exists() for path in required):
        coverage = json.loads((OUT / "coverage.json").read_text(encoding="utf-8"))
        print("reusing completed v1 ledger", flush=True)
    else:
        coverage = build()
    report = analyze(coverage)
    verification = verify_samples()
    print(json.dumps({"coverage": coverage, "size": report["size"], "verification": verification}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
