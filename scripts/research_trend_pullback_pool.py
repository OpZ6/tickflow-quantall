"""Full-history trend-pullback candidate study without trade execution.

Run from backend: uv run --frozen python ../scripts/research_trend_pullback_pool.py
"""
import json
import os
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/trend-pullback/v1"
DOCS = ROOT / "docs/research/stock-pools/trend-pullback"
START = "2016-01-04"
END = "2026-09-11"
BSE_START = np.datetime64("2021-11-15")
HORIZONS = (1, 2, 3, 5, 10, 20, 40, 60)
SUPPORTS = (10, 20, 60)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def eligibility_matrix(dates, symbols):
    """Exclude pre-exchange NEEQ quotes stored under later .BJ symbols."""
    result = np.ones((len(dates), len(symbols)), dtype=bool)
    bj_columns = np.array([symbol.endswith(".BJ") for symbol in symbols])
    if bj_columns.any():
        result[:, bj_columns] = np.asarray(dates, dtype="datetime64[D]")[:, None] >= BSE_START
    return result


def rolling_features(frame):
    """Build signal-day features with strict market-session continuity."""
    exprs = []
    for n in SUPPORTS:
        exprs.extend([
            pl.col("close").rolling_mean(n, min_samples=n).over("symbol").alias(f"ma{n}"),
            (pl.col("idx") - pl.col("idx").shift(n - 1).over("symbol") == n - 1)
            .fill_null(False).alias(f"complete_ma{n}"),
        ])
    exprs.extend([
        pl.col("volume").shift(1).rolling_mean(20, min_samples=20).over("symbol").alias("prior_volume20"),
        pl.col("close").shift(1).rolling_max(20, min_samples=20).over("symbol").alias("prior_close_high20"),
        pl.col("low").shift(1).rolling_min(3, min_samples=3).over("symbol").alias("prior_low3"),
        (pl.col("idx") - pl.col("idx").shift(20).over("symbol") == 20).fill_null(False).alias("complete_prior20"),
        pl.col("close").shift(20).over("symbol").alias("close20ago"),
        pl.col("close").shift(60).over("symbol").alias("close60ago"),
        (pl.col("idx") - pl.col("idx").shift(60).over("symbol") == 60).fill_null(False).alias("complete60"),
        pl.col("close").shift(1).over("symbol").alias("prev_close"),
        pl.col("low").shift(1).over("symbol").alias("prev_low"),
    ])
    result = frame.with_columns(exprs)
    result = result.with_columns([
        pl.when(pl.col(f"complete_ma{n}")).then(pl.col(f"ma{n}")).otherwise(None).alias(f"ma{n}")
        for n in SUPPORTS
    ])
    result = result.with_columns([
        pl.col(f"ma{n}").shift(1).over("symbol").alias(f"prev_ma{n}") for n in SUPPORTS
    ] + [
        pl.when((pl.col("idx") - pl.col("idx").shift(10).over("symbol") == 10).fill_null(False))
        .then(pl.col(f"ma{n}").shift(10).over("symbol")).alias(f"ma{n}_10ago") for n in (20, 60)
    ])
    return result.with_columns([
        pl.when(pl.col("complete_prior20") & (pl.col("prior_volume20") > 0))
        .then(pl.col("volume") / pl.col("prior_volume20")).alias("volume_ratio"),
        pl.when(pl.col("complete_prior20")).then(pl.col("close") / pl.col("close20ago") - 1).alias("pre_return20"),
        pl.when(pl.col("complete60")).then(pl.col("close") / pl.col("close60ago") - 1).alias("pre_return60"),
        pl.when(pl.col("complete_prior20")).then(pl.col("close") / pl.col("prior_close_high20") - 1).alias("drawdown20"),
    ])


def observation_episodes(events, max_age=20):
    """Latest fresh event owns the following observation window."""
    last = np.full(events.shape[1], -1000, dtype=np.int32)
    ages = np.full(events.shape, -1, dtype=np.int16)
    starts = np.full(events.shape, -1, dtype=np.int32)
    for i in range(events.shape[0]):
        last[events[i]] = i
        active = (last >= 0) & (i - last <= max_age)
        ages[i, active] = i - last[active]
        starts[i, active] = last[active]
    return ages, starts


def future_labels(open_, high, low, close):
    """Use T+1 open as anchor and invalidate windows containing missing sessions."""
    anchor = np.full_like(close, np.nan, dtype=np.float32)
    anchor[:-1] = open_[1:]
    valid = np.isfinite(anchor) & (anchor > 0) & np.isfinite(close) & (close > 0)
    max_high = np.full_like(close, -np.inf, dtype=np.float32)
    min_low = np.full_like(close, np.inf, dtype=np.float32)
    peak_day = np.zeros(close.shape, dtype=np.int8)
    trough_day = np.zeros(close.shape, dtype=np.int8)
    outputs = {}
    for h in range(1, max(HORIZONS) + 1):
        hi = np.full_like(close, np.nan, dtype=np.float32)
        lo = np.full_like(close, np.nan, dtype=np.float32)
        terminal = np.full_like(close, np.nan, dtype=np.float32)
        next_open = np.full_like(close, np.nan, dtype=np.float32)
        hi[:-h], lo[:-h], terminal[:-h], next_open[:-h] = high[h:], low[h:], close[h:], open_[h:]
        valid &= (
            np.isfinite(hi) & (hi > 0) & np.isfinite(lo) & (lo > 0)
            & np.isfinite(terminal) & (terminal > 0) & np.isfinite(next_open) & (next_open > 0)
        )
        peak_day[hi > max_high] = h
        trough_day[lo < min_low] = h
        max_high = np.fmax(max_high, hi)
        min_low = np.fmin(min_low, lo)
        if h in HORIZONS:
            with np.errstate(invalid="ignore", divide="ignore"):
                outputs[h] = {
                    "return": np.where(valid, terminal / anchor - 1, np.nan),
                    "mfe": np.where(valid, max_high / anchor - 1, np.nan),
                    "mae": np.where(valid, min_low / anchor - 1, np.nan),
                    "peak": np.where(valid, peak_day, 0),
                    "low_first": np.where(valid, trough_day < peak_day, False),
                }
    return outputs


def _band(column, edges, names):
    expr = pl.when(pl.col(column).is_null()).then(pl.lit("unknown"))
    for edge, name in zip(edges, names, strict=False):
        expr = expr.when(pl.col(column) < edge).then(pl.lit(name))
    return expr.otherwise(pl.lit(names[-1]))


def classify(frame):
    support = pl.col("support")
    return frame.with_columns([
        pl.when(
            (pl.col("event_close") > pl.col("event_ma10"))
            & (pl.col("event_ma10") > pl.col("event_ma20"))
            & (pl.col("event_ma20") > pl.col("event_ma60"))
            & (pl.col("event_ma20") > pl.col("event_ma20_10ago"))
            & (pl.col("event_ma60") > pl.col("event_ma60_10ago"))
        ).then(pl.lit("strong"))
        .when((pl.col("event_close") > pl.col("event_ma20")) & (pl.col("event_ma20") > pl.col("event_ma60")))
        .then(pl.lit("basic")).otherwise(pl.lit("nontrend")).alias("trend_context"),
        _band("event_volume_ratio", [.8, 1.2, 2], ["<0.8", "0.8-1.2", "1.2-2", "2+"]).alias("volume_band"),
        _band("event_pre_return20", [0, .1, .3], ["negative", "0-10%", "10-30%", "30%+"]).alias("return20_band"),
        _band("event_pre_return60", [0, .2, .5], ["negative", "0-20%", "20-50%", "50%+"]).alias("return60_band"),
        _band("event_drawdown20", [-.15, -.08, -.03], ["<-15%", "-15--8%", "-8--3%", "-3%+"]).alias("drawdown_band"),
        _band("event_high_age20", [3, 6, 11], ["0-2", "3-5", "6-10", "11-19"]).alias("pullback_days_band"),
        pl.when(pl.col("age") == 0).then(pl.lit("0"))
        .when(pl.col("age") <= 3).then(pl.lit("1-3"))
        .when(pl.col("age") <= 5).then(pl.lit("4-5"))
        .when(pl.col("age") <= 10).then(pl.lit("6-10"))
        .otherwise(pl.lit("11-20")).alias("age_band"),
        pl.when(pl.col("event_close_location") >= .65).then(pl.lit("upper"))
        .when(pl.col("event_close_location") >= .35).then(pl.lit("middle"))
        .otherwise(pl.lit("lower")).alias("close_location_band"),
        pl.when(pl.col("event_lower_wick") >= .35).then(pl.lit("long"))
        .when(pl.col("event_lower_wick") >= .15).then(pl.lit("medium"))
        .otherwise(pl.lit("short")).alias("lower_wick_band"),
        pl.when(pl.col("close") < pl.col("event_low") * .999).then(pl.lit("below_event_low"))
        .when(pl.col("close") < pl.col("support_ma") * .99).then(pl.lit("below_support"))
        .when(pl.col("close") >= pl.col("ma10")).then(pl.lit("above_ma10"))
        .otherwise(pl.lit("holding_support")).alias("current_state"),
        pl.when(support == 10).then(pl.lit("MA10"))
        .when(support == 20).then(pl.lit("MA20")).otherwise(pl.lit("MA60")).alias("support_label"),
        pl.col("date").dt.year().cast(pl.String).alias("year"),
        (
            (pl.col("event_close_location") >= .65)
            & pl.col("event_close_up") & pl.col("event_not_new_low3")
            & (pl.col("event_close") >= pl.col("event_support_ma") * .99)
        ).alias("stable_close"),
        pl.col("event_breakthrough_age").is_not_null().alias("recent_breakthrough"),
    ])


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = OUT / "parts"
    parts.mkdir(exist_ok=True)
    paths = sorted((ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet"))
    paths = [p for p in paths if p.parent.name <= f"date={END}"]
    scan = pl.scan_parquet(paths)
    dates = scan.select("date").unique().sort("date").collect()["date"].to_list()
    calendar = pl.DataFrame({"date": dates}).with_row_index("idx")
    start_idx = calendar.filter(pl.col("date") >= pl.lit(START).str.to_date())["idx"].min()
    symbols = scan.select("symbol").unique().sort("symbol").collect()["symbol"].to_list()
    market_sums = {h: np.zeros(len(dates), dtype=np.float64) for h in HORIZONS}
    market_counts = {h: np.zeros(len(dates), dtype=np.int64) for h in HORIZONS}
    environment_sum = np.zeros(len(dates), dtype=np.float64)
    environment_count = np.zeros(len(dates), dtype=np.int64)
    source_rows = []
    total_prices = invalid_ohlc = adjustment_mismatch = 0

    for batch, beg in enumerate(range(0, len(symbols), 300)):
        selected = symbols[beg:beg + 300]
        frame = (
            scan.filter(pl.col("symbol").is_in(selected))
            .select("symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "raw_high", "raw_low")
            .collect().join(calendar, on="date").sort("symbol", "date")
        )
        total_prices += frame.height
        if frame.select(pl.struct("symbol", "date").n_unique()).item() != frame.height:
            raise ValueError("duplicate stock/date prices")
        bad = frame.select(((pl.col("high") < pl.col("low")) | (pl.col("high") < pl.col("close"))
                            | (pl.col("low") > pl.col("close")) | (pl.col("high") < pl.col("open"))
                            | (pl.col("low") > pl.col("open"))).sum()).item()
        mismatch = frame.select((((pl.col("high") / pl.col("raw_high") - pl.col("close") / pl.col("raw_close")).abs() > 1e-5)
                                 | ((pl.col("low") / pl.col("raw_low") - pl.col("close") / pl.col("raw_close")).abs() > 1e-5)).sum()).item()
        invalid_ohlc += bad
        adjustment_mismatch += mismatch
        if bad or mismatch:
            raise ValueError("OHLC or within-bar adjustment factors inconsistent")
        spans = frame.group_by("symbol").agg(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"), pl.len().alias("bars"))
        source_rows.extend([{**r, "first": str(r["first"]), "last": str(r["last"])} for r in spans.to_dicts()])
        frame = rolling_features(frame)
        mapping = {symbol: i for i, symbol in enumerate(selected)}
        row_idx = frame["idx"].to_numpy()
        col_idx = frame["symbol"].replace_strict(mapping, return_dtype=pl.Int32).to_numpy()
        shape = (len(dates), len(selected))
        eligible = eligibility_matrix(dates, selected)

        def dense(field, shape=shape, row_idx=row_idx, col_idx=col_idx, frame=frame):
            values = np.full(shape, np.nan, dtype=np.float32)
            values[row_idx, col_idx] = frame[field].to_numpy()
            return values

        arrays = {field: dense(field) for field in (
            "open", "high", "low", "close", "volume_ratio", "pre_return20", "pre_return60", "drawdown20",
            "prev_close", "prev_low", "prior_low3", "prior_close_high20", "ma10", "ma20", "ma60", "prev_ma10", "prev_ma20",
            "prev_ma60", "ma20_10ago", "ma60_10ago",
        )}
        labels = future_labels(arrays["open"], arrays["high"], arrays["low"], arrays["close"])
        past = arrays["pre_return20"]
        past_valid = np.isfinite(past) & eligible
        environment_sum += np.where(past_valid, past, 0).sum(axis=1, dtype=np.float64)
        environment_count += past_valid.sum(axis=1)
        for h, values in labels.items():
            valid = np.isfinite(values["return"]) & eligible
            market_sums[h] += np.where(valid, values["return"], 0).sum(axis=1, dtype=np.float64)
            market_counts[h] += valid.sum(axis=1)

        high_age = np.full(shape, np.nan, dtype=np.float32)
        close = arrays["close"]
        if len(dates) >= 21:
            windows = np.lib.stride_tricks.sliding_window_view(close, 20, axis=0)
            complete = np.all(np.isfinite(windows), axis=2)
            positions = np.argmax(np.where(np.isfinite(windows), windows, -np.inf), axis=2)
            high_age[20:] = np.where(complete[:-1], 19 - positions[:-1], np.nan)

        output_parts = []
        for support in SUPPORTS:
            ma = arrays[f"ma{support}"]
            prev_ma = arrays[f"prev_ma{support}"]
            touch = (
                np.isfinite(arrays["low"]) & np.isfinite(arrays["high"]) & np.isfinite(ma)
                & (arrays["low"] <= ma * 1.01) & (arrays["high"] >= ma * .99)
            )
            prior_above = np.isfinite(arrays["prev_low"]) & np.isfinite(prev_ma) & (arrays["prev_low"] > prev_ma * 1.01)
            events = touch & prior_above & eligible
            events[:start_idx] = False
            age, starts = observation_episodes(events)
            ti, si = np.nonzero(age >= 0)
            event_i = starts[ti, si]

            def current(field, arrays=arrays, ti=ti, si=si):
                return arrays[field][ti, si]

            def frozen(field, arrays=arrays, event_i=event_i, si=si):
                return arrays[field][event_i, si]

            data = {
                "symbol": np.asarray(selected)[si], "date": np.asarray(dates, dtype="datetime64[D]")[ti],
                "idx": ti.astype(np.int32), "support": np.full(len(ti), support, dtype=np.int8),
                "age": age[ti, si], "event_idx": event_i,
                "open": current("open"), "high": current("high"), "low": current("low"), "close": current("close"),
                "ma10": current("ma10"), "ma20": current("ma20"), "ma60": current("ma60"), "support_ma": ma[ti, si],
                "event_open": frozen("open"), "event_high": frozen("high"), "event_low": frozen("low"), "event_close": frozen("close"),
                "event_support_ma": ma[event_i, si], "event_ma10": frozen("ma10"), "event_ma20": frozen("ma20"),
                "event_ma60": frozen("ma60"), "event_ma20_10ago": frozen("ma20_10ago"), "event_ma60_10ago": frozen("ma60_10ago"),
                "event_volume_ratio": frozen("volume_ratio"), "event_pre_return20": frozen("pre_return20"),
                "event_pre_return60": frozen("pre_return60"), "event_drawdown20": frozen("drawdown20"),
                "event_high_age20": high_age[event_i, si],
                "event_close_up": frozen("close") >= frozen("prev_close"),
                "event_not_new_low3": frozen("low") >= frozen("prior_low3"),
            }
            event_range = data["event_high"] - data["event_low"]
            data["event_close_location"] = np.divide(data["event_close"] - data["event_low"], event_range,
                                                       out=np.full(len(ti), np.nan, dtype=np.float32), where=event_range > 0)
            lower_body = np.minimum(data["event_open"], data["event_close"])
            data["event_lower_wick"] = np.divide(lower_body - data["event_low"], event_range,
                                                   out=np.full(len(ti), np.nan, dtype=np.float32), where=event_range > 0)
            for h, values in labels.items():
                data.update({
                    f"r{h}_open": values["return"][ti, si], f"mfe{h}": values["mfe"][ti, si],
                    f"mae{h}": values["mae"][ti, si], f"peak_day{h}": values["peak"][ti, si],
                    f"low_first{h}": values["low_first"][ti, si],
                })
            output_parts.append(pl.DataFrame(data).with_columns(pl.col(pl.Float32).fill_nan(None)))
        pl.concat(output_parts).write_parquet(parts / f"part-{batch:03d}.parquet")
        print(f"batch {batch + 1}: {beg + len(selected)}/{len(symbols)} stocks, {sum(x.height for x in output_parts)} members", flush=True)

    market = {"date": dates}
    for h in HORIZONS:
        market[f"market{h}_open"] = np.divide(market_sums[h], market_counts[h],
                                               out=np.full(len(dates), np.nan), where=market_counts[h] > 0)
        market[f"market_count{h}"] = market_counts[h]
    past_market = np.divide(environment_sum, environment_count, out=np.full(len(dates), np.nan), where=environment_count > 0)
    market["environment"] = np.where(np.isnan(past_market), "unknown", np.where(past_market > 0, "positive20", "nonpositive20"))
    market_frame = pl.DataFrame(market).with_columns(pl.col(pl.Float64).fill_nan(None))
    market_frame.write_parquet(OUT / "market-baseline.parquet")
    ledger = pl.scan_parquet(parts / "*.parquet").join(market_frame.lazy(), on="date").collect()
    breakthrough_path = ROOT / "data/research/stock-pools/breakthrough/v1/daily-ledger.parquet"
    if breakthrough_path.exists():
        breakthrough = (pl.scan_parquet(breakthrough_path).filter(pl.col("age_close60") >= 0)
                        .select("symbol", "date", pl.col("age_close60").alias("event_breakthrough_age")).collect())
        ledger = ledger.join(breakthrough, on=["symbol", "date"], how="left", validate="m:1")
        breakthrough_status = "joined_breakthrough_v1"
    else:
        ledger = ledger.with_columns(pl.lit(None, dtype=pl.Int16).alias("event_breakthrough_age"))
        breakthrough_status = "unavailable"
    ledger = classify(ledger)
    if ledger.select(pl.struct("symbol", "date", "support").n_unique()).item() != ledger.height:
        raise ValueError("duplicate daily ledger key")
    ledger.write_parquet(OUT / "daily-ledger.parquet")
    ledger.filter(pl.col("age") == 0).write_parquet(OUT / "event-ledger.parquet")
    write_json(OUT / "security-coverage.json", source_rows)
    coverage = {
        "price_first": str(dates[0]), "price_last": str(dates[-1]), "sessions": len(dates),
        "price_rows": total_prices, "stocks": len(symbols), "signal_first": START, "signal_last": END,
        "ohlc_invalid": invalid_ohlc, "adjustment_bar_mismatch": adjustment_mismatch,
        "strict_market_session_continuity": True, "historical_listing_universe": "cached symbols; completeness and delisted coverage unverified",
        "breakthrough_cross_label": breakthrough_status, "entry_basis": "next_session_open", "horizons": list(HORIZONS),
        "bse_signal_start": str(BSE_START), "pre_bse_neeq_quotes": "excluded from signals and market baseline",
    }
    write_json(OUT / "coverage.json", coverage)
    return coverage


def stats(frame, h):
    key = f"r{h}_open"
    valid = frame.filter(pl.col(key).is_not_null() & pl.col(key).is_finite())
    if not valid.height:
        return {"n": 0, "dates": 0}
    daily = valid.group_by("date").agg(
        pl.col(key).mean().alias("mean"), (pl.col(key) - pl.col(f"market{h}_open")).mean().alias("excess"),
        (pl.col(key) > 0).mean().alias("positive"), pl.col(f"mfe{h}").mean().alias("mfe"),
        pl.col(f"mae{h}").mean().alias("mae"), pl.col(f"peak_day{h}").mean().alias("peak_day"),
        pl.col(f"low_first{h}").mean().alias("low_first"),
    )
    values = valid[key]
    wins, losses = values.filter(values > 0), values.filter(values < 0)
    return {
        "n": valid.height, "dates": daily.height, "stocks": valid["symbol"].n_unique(),
        "mean": daily["mean"].mean(), "excess": daily["excess"].mean(), "positive": daily["positive"].mean(),
        "median_sample": values.median(), "p10_sample": values.quantile(.1, interpolation="linear"),
        "avg_win_sample": wins.mean(), "avg_loss_sample": losses.mean(), "mfe": daily["mfe"].mean(),
        "mae": daily["mae"].mean(), "peak_day": daily["peak_day"].mean(), "low_first": daily["low_first"].mean(),
    }


def summaries(frame):
    return {str(h): stats(frame, h) for h in HORIZONS}


def block_ci(values):
    values = np.asarray(values, dtype=float)
    if len(values) < 40:
        return []
    block = min(20, len(values))
    rng = np.random.default_rng(20260914)
    starts = rng.integers(0, len(values) - block + 1, size=(500, int(np.ceil(len(values) / block))))
    samples = values[(starts[..., None] + np.arange(block)).reshape(500, -1)[:, :len(values)]].mean(axis=1)
    return np.quantile(samples, [.025, .975]).tolist()


def paired(frame, predicate, h):
    key = f"r{h}_open"
    valid = frame.filter(pl.col(key).is_not_null())
    kept = valid.filter(predicate).group_by("date").agg(pl.col(key).mean().alias("kept"))
    removed = valid.filter(~predicate).group_by("date").agg(pl.col(key).mean().alias("removed"))
    both = kept.join(removed, on="date").sort("date")
    values = (both["kept"] - both["removed"]).to_numpy()
    return {"dates": both.height, "difference": float(values.mean()) if len(values) else None,
            "positive_dates": float(np.mean(values > 0)) if len(values) else None, "block20_ci95": block_ci(values)}


def matched_paired(frame, predicate, controls, h):
    """Compare same-date cells while holding named event states fixed."""
    key = f"r{h}_open"
    cells = (frame.filter(pl.col(key).is_not_null()).with_columns(predicate.alias("kept"))
             .group_by("date", *controls, "kept").agg(pl.col(key).mean().alias("mean"), pl.len().alias("n")))
    kept = cells.filter(pl.col("kept") & (pl.col("n") >= 3))
    removed = cells.filter(~pl.col("kept") & (pl.col("n") >= 3))
    both = kept.join(removed, on=["date", *controls], suffix="_removed")
    daily = both.group_by("date").agg((pl.col("mean") - pl.col("mean_removed")).mean().alias("difference")).sort("date")
    values = daily["difference"].to_numpy()
    return {"dates": daily.height, "cells": both.height, "difference": float(values.mean()) if len(values) else None,
            "block20_ci95": block_ci(values), "minimum_each_side": 3, "controls": controls}


def rule_result(book, predicate):
    known = book.filter(predicate.is_not_null())
    kept, removed = known.filter(predicate), known.filter(~predicate)
    winners = known.filter(pl.col("r10_open") >= .2)
    return {
        "known": known.height, "retained": kept.height / known.height if known.height else None,
        "winner_rows": winners.height, "winner_retention": winners.filter(predicate).height / winners.height if winners.height else None,
        "kept": summaries(kept), "removed": summaries(removed),
        "paired": {str(h): paired(known, predicate, h) for h in HORIZONS},
        "yearly10": {year: {"kept": stats(kept.filter(pl.col("year") == year), 10),
                             "removed": stats(removed.filter(pl.col("year") == year), 10)}
                     for year in sorted(known["year"].unique().to_list())},
    }


def context_analysis(core):
    """Short common-date heat and archived theme context; missing stays unknown."""
    result = {"heat": {}, "theme": {}}
    heat_path = ROOT / "data/research/stock-pools/popularity/v2/daily-ledger.parquet"
    if heat_path.exists():
        heat = pl.read_parquet(heat_path).with_columns(pl.col("date").str.to_date())
        for source in sorted(heat["source"].unique().to_list()):
            source_heat = heat.filter(pl.col("source") == source).select(
                "date", "symbol", pl.col("band").alias("heat_band"))
            valid_dates = source_heat["date"].unique()
            book = (core.filter(pl.col("date").is_in(valid_dates.implode())).join(
                source_heat, on=["date", "symbol"], how="left").with_columns(
                    pl.col("heat_band").fill_null("observed_outside"),
                    pl.col("heat_band").is_not_null().alias("hot"),
                ))
            groups = {value: summaries(book.filter(pl.col("heat_band") == value))
                      for value in sorted(book["heat_band"].unique().to_list())}
            result["heat"][source] = {
                "coverage_dates": len(valid_dates), "first": str(valid_dates.min()), "last": str(valid_dates.max()),
                "events": book.height, "groups": groups,
                "matched": {str(h): matched_paired(book, pl.col("hot"), ["support_label", "volume_band"], h) for h in HORIZONS},
            }

    from collections import defaultdict
    records, archived_dates = [], []
    for member_path in sorted((ROOT / "data/theme_member_daily").glob("date=*/part.parquet")):
        day = member_path.parent.name.removeprefix("date=")
        limit_path = ROOT / f"data/limit_event_daily/date={day}/part.parquet"
        if day > END or not limit_path.exists():
            continue
        members = pl.read_parquet(member_path).to_dicts()
        limit_codes = {row["symbol"].split(".")[0] for row in pl.read_parquet(limit_path).to_dicts()
                       if row["event_type"] == "limit_up"}
        theme_stocks, stock_themes = defaultdict(set), defaultdict(set)
        for row in members:
            code = row["symbol"].split(".")[0]
            theme_stocks[row["theme_id"]].add(code)
            stock_themes[code].add(row["theme_id"])
        if not stock_themes:
            continue
        archived_dates.append(day)
        for code, themes in stock_themes.items():
            peers = max(len((theme_stocks[theme] & limit_codes) - {code}) for theme in themes)
            records.append({"date": day, "code": code, "theme_support": "peer_limit2+" if peers >= 2 else "peer_limit0-1"})
    if records:
        theme = pl.DataFrame(records).with_columns(pl.col("date").str.to_date())
        valid_dates = pl.Series("date", archived_dates).str.to_date().unique()
        book = (core.filter(pl.col("date").is_in(valid_dates.implode())).with_columns(
            pl.col("symbol").str.slice(0, 6).alias("code")).join(theme, on=["date", "code"], how="inner"))
        result["theme"] = {"coverage_dates": len(valid_dates), "first": min(archived_dates), "last": max(archived_dates),
            "labeled_events": book.height, "coverage_note": "archived theme members only; unlabeled stocks remain unknown",
            "groups": {value: summaries(book.filter(pl.col("theme_support") == value))
                       for value in sorted(book["theme_support"].unique().to_list())}}
    return result


def lazy_member_views():
    """Aggregate the large observation ledger without materializing it."""
    base = pl.scan_parquet(OUT / "daily-ledger.parquet").filter(pl.col("trend_context") != "nontrend")
    result = {"core_daily_members": {}}
    for h in HORIZONS:
        key = f"r{h}_open"
        cells = (base.filter(pl.col(key).is_not_null()).group_by("date", "age_band", "current_state").agg(
            pl.len().alias("n"), pl.col(key).mean().alias("mean"),
            (pl.col(key) - pl.col(f"market{h}_open")).mean().alias("excess"),
            (pl.col(key) > 0).mean().alias("positive"), pl.col(f"mfe{h}").mean().alias("mfe"),
            pl.col(f"mae{h}").mean().alias("mae"), pl.col(f"peak_day{h}").mean().alias("peak_day"),
            pl.col(f"low_first{h}").mean().alias("low_first"),
        ).collect(engine="streaming"))

        def aggregate(groups, cells=cells):
            daily_groups = ["date", *groups]
            daily = cells.group_by(*daily_groups).agg(
                pl.col("n").sum(),
                *[((pl.col(metric) * pl.col("n")).sum() / pl.col("n").sum()).alias(metric)
                  for metric in ("mean", "excess", "positive", "mfe", "mae", "peak_day", "low_first")],
            )
            final = daily.group_by(*groups).agg(
                pl.col("n").sum().alias("n"), pl.len().alias("dates"),
                *[pl.col(metric).mean().alias(metric)
                  for metric in ("mean", "excess", "positive", "mfe", "mae", "peak_day", "low_first")],
            ) if groups else daily.select(
                pl.col("n").sum().alias("n"), pl.len().alias("dates"),
                *[pl.col(metric).mean().alias(metric)
                  for metric in ("mean", "excess", "positive", "mfe", "mae", "peak_day", "low_first")],
            )
            return final

        overall = aggregate([]).row(0, named=True)
        result["core_daily_members"][str(h)] = overall
        for group, prefix in ((["age_band"], "members|age_band"), (["current_state"], "members|current_state")):
            for row in aggregate(group).to_dicts():
                value = row.pop(group[0])
                result.setdefault(f"{prefix}:{value}", {})[str(h)] = row
    return result


def analyze(coverage):
    event_columns = [
        "symbol", "date", "support", "trend_context", "volume_band", "return20_band", "return60_band",
        "drawdown_band", "pullback_days_band", "close_location_band", "lower_wick_band", "environment",
        "recent_breakthrough", "stable_close", "support_label", "year", "event_close_up", "event_not_new_low3",
        "event_close", "event_low", "event_support_ma",
        *[f"{prefix}{h}{suffix}" for h in HORIZONS for prefix, suffix in (
            ("r", "_open"), ("market", "_open"), ("mfe", ""), ("mae", ""), ("peak_day", ""), ("low_first", ""))],
    ]
    events = (pl.read_parquet(OUT / "event-ledger.parquet", columns=event_columns)
              .with_columns([
                  (pl.col("event_close") >= pl.col("event_support_ma") * .99).alias("event_above_support"),
                  (pl.col("event_low") / pl.col("event_support_ma") - 1).alias("touch_depth"),
              ]).with_columns(
                  _band("touch_depth", [-.05, -.02, 0], ["<-5%", "-5--2%", "-2-0%", "0%+"]).alias("touch_depth_band")
              ))
    core = events.filter(pl.col("trend_context") != "nontrend")
    report = {"protocol": "trend-pullback-v1", "scope": "exploration; no trade execution or independent validation",
              "coverage": coverage, "horizons": list(HORIZONS), "views": {}, "rules": {}, "size": {}}
    groups = {"all_wide_events": events, "core_events": core}
    for factor in ("support_label", "trend_context", "volume_band", "return20_band", "return60_band", "drawdown_band",
                   "pullback_days_band", "touch_depth_band", "close_location_band", "lower_wick_band", "environment", "recent_breakthrough"):
        for value in sorted(events[factor].unique().to_list(), key=str):
            groups[f"events|{factor}:{value}"] = events.filter(pl.col(factor) == value)
    report["views"] = {name: summaries(book) for name, book in groups.items()}
    report["views"].update(lazy_member_views())
    for name, book in (("wide_events", events), ("core_events", core)):
        sizes = book.group_by("date").len()
        report["size"][name] = {"rows": book.height, "stocks": book["symbol"].n_unique(), "dates": sizes.height,
                                        "daily_median": sizes["len"].median(), "daily_p90": sizes["len"].quantile(.9)}
    member_scan = pl.scan_parquet(OUT / "daily-ledger.parquet").filter(pl.col("trend_context") != "nontrend")
    member_sizes = member_scan.group_by("date").len().collect(engine="streaming")
    member_count = member_scan.select(pl.len().alias("rows"), pl.col("symbol").approx_n_unique().alias("stocks")).collect(engine="streaming").row(0, named=True)
    report["size"]["core_daily_members"] = {**member_count, "dates": member_sizes.height,
        "daily_median": member_sizes["len"].median(), "daily_p90": member_sizes["len"].quantile(.9)}
    spells = (member_scan.group_by("symbol", "support", "event_idx").agg(
        pl.len().alias("length"), pl.col("idx").max().alias("last_idx")).collect(engine="streaming"))
    report["observation"] = {"spells": spells.height, "length_median": spells["length"].median(),
                             "length_p90": spells["length"].quantile(.9), "right_censored": spells.filter(pl.col("last_idx") == coverage["sessions"] - 1).height}
    report["rules"]["trend_identity"] = rule_result(events, pl.col("trend_context") != "nontrend")
    report["rules"]["strong_trend"] = rule_result(core, pl.col("trend_context") == "strong")
    report["rules"]["shrink_volume"] = rule_result(core, pl.col("volume_band") == "<0.8")
    report["rules"]["close_up"] = rule_result(core, pl.col("event_close_up"))
    report["rules"]["not_new_low3"] = rule_result(core, pl.col("event_not_new_low3"))
    report["rules"]["above_support"] = rule_result(core, pl.col("event_above_support"))
    report["rules"]["upper_close"] = rule_result(core, pl.col("close_location_band") == "upper")
    report["rules"]["long_lower_wick"] = rule_result(core, pl.col("lower_wick_band") == "long")
    report["rules"]["stable_close"] = rule_result(core, pl.col("stable_close"))
    report["rules"]["shrink_and_stable"] = rule_result(core, (pl.col("volume_band") == "<0.8") & pl.col("stable_close"))
    report["rules"]["strong_and_shrink"] = rule_result(core, (pl.col("trend_context") == "strong") & (pl.col("volume_band") == "<0.8"))
    report["rules"]["ma20_and_shrink"] = rule_result(core, (pl.col("support") == 20) & (pl.col("volume_band") == "<0.8"))
    report["rules"]["ma60_and_shrink"] = rule_result(core, (pl.col("support") == 60) & (pl.col("volume_band") == "<0.8"))
    report["rules"]["recent_breakthrough"] = rule_result(core, pl.col("recent_breakthrough"))
    report["rules"]["positive_environment"] = rule_result(core, pl.col("environment") == "positive20")
    for support in SUPPORTS:
        report["rules"][f"support_ma{support}"] = rule_result(core, pl.col("support") == support)
    report["matched_identity"] = {str(h): matched_paired(
        events, pl.col("trend_context") != "nontrend", ["support_label", "volume_band"], h) for h in HORIZONS}
    report["context"] = context_analysis(core)
    union = core.sort("support", descending=True).unique(["symbol", "date"], keep="first")
    report["union_core_events"] = summaries(union)
    report["annual_core"] = {year: summaries(core.filter(pl.col("year") == year)) for year in sorted(core["year"].unique().to_list())}
    write_json(OUT / "analysis.json", report)
    write_results(report)
    return report


def _pct(value):
    return "—" if value is None else f"{value * 100:.2f}"


def write_results(report):
    lines = ["# 趋势回踩池v1数值结果", "", "脚本生成。完整解读见分析报告, 全部收益与路径从次日开盘起算。", ""]

    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
        lines.append("")

    table("规模", ["账本", "记录", "股票", "日期", "日规模中位数/P90"],
          [[k, v["rows"], v["stocks"], v["dates"], f'{v["daily_median"]}/{v["daily_p90"]}'] for k, v in report["size"].items()])
    table("基线与全部分层", ["视角", "周期", "收益%", "超额百分点", "正收益率%", "P10%", "MFE/MAE%", "记录/日期"],
          [[name, h, _pct(v.get("mean")), _pct(v.get("excess")), _pct(v.get("positive")), _pct(v.get("p10_sample")),
            f'{_pct(v.get("mfe"))}/{_pct(v.get("mae"))}', f'{v["n"]}/{v["dates"]}']
           for name, periods in report["views"].items() for h, v in periods.items()])
    table("拟条件质量与机会损失", ["规则", "保留%", "10日保留/剔除收益%", "10日保留/剔除超额", "大赢家保留%"],
          [[name, _pct(v["retained"]), f'{_pct(v["kept"]["10"].get("mean"))}/{_pct(v["removed"]["10"].get("mean"))}',
            f'{_pct(v["kept"]["10"].get("excess"))}/{_pct(v["removed"]["10"].get("excess"))}', _pct(v["winner_retention"])]
           for name, v in report["rules"].items()])
    table("同日条件对照", ["规则", "周期", "保留减剔除百分点", "共同日期", "20日期块95%区间"],
          [[name, h, _pct(v.get("difference")), v["dates"], " / ".join(_pct(x) for x in v["block20_ci95"])]
           for name, rule in report["rules"].items() for h, v in rule["paired"].items()])
    (DOCS / "v1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_samples():
    samples = (pl.scan_parquet(OUT / "event-ledger.parquet")
        .sort(pl.struct("symbol", "date", "support").hash(seed=20260914)).group_by("support").head(5).collect())
    symbols = samples["symbol"].unique().to_list()
    prices = (pl.scan_parquet(ROOT / "data/kline_daily_enriched/date=*/part.parquet")
              .filter(pl.col("symbol").is_in(symbols) & (pl.col("date") <= pl.lit(END).str.to_date()))
              .select("symbol", "date", "open", "high", "low", "close").collect())
    dates = pl.read_parquet(OUT / "market-baseline.parquet")["date"].to_list()
    date_index = {day: i for i, day in enumerate(dates)}
    by_stock = {symbol: {} for symbol in symbols}
    for row in prices.to_dicts():
        by_stock[row["symbol"]][date_index[row["date"]]] = row
    assertions = 0
    for row in samples.to_dicts():
        bars = by_stock[row["symbol"]]
        i, support = row["idx"], row["support"]
        assert row["event_idx"] == i and row["age"] == 0
        ma = np.mean([bars[j]["close"] for j in range(i - support + 1, i + 1)])
        prior_ma = np.mean([bars[j]["close"] for j in range(i - support, i)])
        assert bars[i]["low"] <= ma * 1.01 and bars[i]["high"] >= ma * .99
        assert bars[i - 1]["low"] > prior_ma * 1.01
        assert np.isclose(ma, row["event_support_ma"], rtol=2e-6)
        assertions += 5
        for h in HORIZONS:
            future = [bars.get(j) for j in range(i + 1, i + h + 1)]
            if any(bar is None for bar in future):
                assert row[f"r{h}_open"] is None
            else:
                expected = future[-1]["close"] / future[0]["open"] - 1
                assert np.isclose(expected, row[f"r{h}_open"], atol=2e-6)
            assertions += 1
    result = {"status": "passed", "samples": samples.height, "assertions": assertions,
              "supports": list(SUPPORTS), "horizons": list(HORIZONS), "label_tolerance": 2e-6}
    write_json(OUT / "verification.json", result)
    return result


def main():
    required = (OUT / "daily-ledger.parquet", OUT / "event-ledger.parquet", OUT / "market-baseline.parquet", OUT / "coverage.json")
    if os.environ.get("REBUILD_STOCK_POOL") != "1" and all(path.exists() for path in required):
        coverage = json.loads((OUT / "coverage.json").read_text(encoding="utf-8"))
        print("reusing completed v1 ledgers", flush=True)
    else:
        coverage = build()
    report = analyze(coverage)
    verification = verify_samples()
    print(json.dumps({"coverage": coverage, "size": report["size"], "verification": verification}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
