"""Full-history abnormal-surge candidate study without trade execution.

Run from backend: uv run --frozen python ../scripts/research_abnormal_surge_pool.py
"""
import gc
import json
import os
from pathlib import Path

import numpy as np
import polars as pl

from research_active_character_pool import _band, rule_result, summaries
from research_trend_pullback_pool import block_ci, eligibility_matrix, future_labels, write_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/abnormal-surge/v1"
DOCS = ROOT / "docs/research/stock-pools/abnormal-surge"
START = "2016-01-04"
END = "2026-09-11"
BSE_START = np.datetime64("2021-11-15")
HORIZONS = (1, 2, 3, 5, 10, 20)


def process_ages(signal):
    ages = np.full(signal.shape, -1, dtype=np.int16)
    current = np.full(signal.shape[1], -1, dtype=np.int16)
    previous = np.zeros(signal.shape[1], dtype=bool)
    for i in range(signal.shape[0]):
        current = np.where(signal[i], np.where(previous, current + 1, 0), -1).astype(np.int16)
        ages[i] = current
        previous = signal[i]
    return ages


def rolling_features(frame):
    expressions = []
    for n in (3, 10, 20, 30, 60):
        expressions.extend([
            pl.col("close").shift(n).over("symbol").alias(f"close{n}ago"),
            (pl.col("idx") - pl.col("idx").shift(n).over("symbol") == n).fill_null(False).alias(f"complete{n}"),
        ])
    for n in (10, 20, 60):
        expressions.append(pl.col("close").rolling_mean(n, min_samples=n).over("symbol").alias(f"ma{n}"))
    return (frame.with_columns(expressions).with_columns([
        pl.when(pl.col(f"complete{n}")).then(pl.col("close") / pl.col(f"close{n}ago") - 1).alias(f"return{n}_past")
        for n in (3, 10, 20, 30, 60)
    ] + [
        pl.col("volume").shift(1).rolling_mean(20, min_samples=20).over("symbol").alias("prior_volume20"),
        pl.col("high").shift(1).rolling_max(20, min_samples=20).over("symbol").alias("prior_high20"),
        pl.col("raw_close").shift(1).over("symbol").alias("prev_raw_close"),
        pl.col("consecutive_limit_ups").cast(pl.Int16).rolling_sum(30, min_samples=30).over("symbol").alias("limit_count30"),
    ]).with_columns([
        pl.when(pl.col("complete20") & (pl.col("prior_volume20") > 0)).then(pl.col("volume") / pl.col("prior_volume20")).alias("volume_ratio"),
        pl.when(pl.col("complete20")).then(pl.col("close") / pl.col("prior_high20") - 1).alias("drawdown20"),
    ]))


def classify(frame):
    return frame.with_columns([
        pl.when((pl.col("return10_past") >= .30) & (pl.col("return30_past") >= .50)).then(pl.lit("both"))
        .when(pl.col("return10_past") >= .30).then(pl.lit("10d_only")).otherwise(pl.lit("30d_only")).alias("surge_driver"),
        _band("return10_past", [.30, .50, .80], ["<30%", "30-50%", "50-80%", "80%+"]).alias("return10_band"),
        _band("return30_past", [.50, 1.00, 1.50], ["<50%", "50-100%", "100-150%", "150%+"]).alias("return30_band"),
        _band("return3_past", [-.05, .03, .15], ["pullback_<-5%", "rest_-5-3%", "advance_3-15%", "accelerate_15%+"]).alias("recent_state"),
        _band("drawdown20", [-.15, -.08, -.03], ["<-15%", "-15--8%", "-8--3%", "-3%+"]).alias("drawdown_band"),
        _band("volume_ratio", [.8, 1.2, 2], ["<0.8", "0.8-1.2", "1.2-2", "2+"]).alias("volume_band"),
        _band("return20_past", [0, .10, .30, .60], ["negative", "0-10%", "10-30%", "30-60%", "60%+"]).alias("return20_band"),
        pl.when((pl.col("close") > pl.col("ma10")) & (pl.col("ma10") > pl.col("ma20")) & (pl.col("ma20") > pl.col("ma60")))
        .then(pl.lit("strong")).when((pl.col("close") > pl.col("ma20")) & (pl.col("ma20") > pl.col("ma60")))
        .then(pl.lit("basic")).otherwise(pl.lit("nontrend")).alias("trend_context"),
        pl.when(pl.col("process_age") == 0).then(pl.lit("0"))
        .when(pl.col("process_age") <= 3).then(pl.lit("1-3"))
        .when(pl.col("process_age") <= 10).then(pl.lit("4-10"))
        .when(pl.col("process_age") <= 20).then(pl.lit("11-20")).otherwise(pl.lit("21+")).alias("process_age_band"),
        pl.when(pl.col("closed_limit")).then(pl.lit("closed_limit"))
        .when(pl.col("failed_limit_approx")).then(pl.lit("failed_limit_approx"))
        .when(pl.col("return3_past") < -.05).then(pl.lit("pullback"))
        .when(pl.col("return3_past") < .03).then(pl.lit("rest")).otherwise(pl.lit("advance")).alias("current_state"),
        ((pl.col("return10_past") >= .50) | (pl.col("return30_past") >= 1.00)).alias("original_threshold"),
        (pl.col("amount_rank") <= 100).fill_null(False).alias("top100_amount"),
        (pl.col("limit_count30") > 0).fill_null(False).alias("active30"),
        pl.col("breakthrough_age").is_not_null().alias("recent_breakthrough"),
        pl.col("pullback_event").fill_null(False),
        pl.col("date").dt.year().cast(pl.String).alias("year"),
    ])


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = OUT / "parts"
    parts.mkdir(exist_ok=True)
    paths = sorted(path for path in (ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet") if path.parent.name <= f"date={END}")
    scan = pl.scan_parquet(paths)
    dates = scan.select("date").unique().sort("date").collect()["date"].to_list()
    calendar = pl.DataFrame({"date": dates}).with_row_index("idx")
    start_idx = calendar.filter(pl.col("date") >= pl.lit(START).str.to_date())["idx"].min()
    symbols = scan.select("symbol").unique().sort("symbol").collect()["symbol"].to_list()
    total_prices = invalid_ohlc = adjustment_mismatch = 0

    for batch, beg in enumerate(range(0, len(symbols), 300)):
        selected = symbols[beg:beg + 300]
        prices = (scan.filter(pl.col("symbol").is_in(selected)).select(
            "symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "raw_high", "raw_low", "consecutive_limit_ups")
            .collect().join(calendar, on="date").sort("symbol", "date"))
        total_prices += prices.height
        bad = prices.select(((pl.col("high") < pl.col("low")) | (pl.col("high") < pl.col("close")) | (pl.col("low") > pl.col("close"))
            | (pl.col("high") < pl.col("open")) | (pl.col("low") > pl.col("open"))).sum()).item()
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

        def dense(field):
            values = np.full(shape, np.nan, dtype=np.float32)
            values[row_idx, col_idx] = prices[field].to_numpy()
            return values

        fields = ("open", "high", "low", "close", "ma10", "ma20", "ma60", "return3_past", "return10_past", "return20_past",
                  "return30_past", "return60_past", "volume_ratio", "drawdown20", "limit_count30", "raw_high", "raw_close", "prev_raw_close")
        arrays = {field: dense(field) for field in fields}
        closed = np.zeros(shape, dtype=bool)
        closed[row_idx, col_idx] = prices["consecutive_limit_ups"].to_numpy() > 0
        broad = ((arrays["return10_past"] >= .30) | (arrays["return30_past"] >= .50)) & eligible
        complete = np.isfinite(arrays["return30_past"])
        ages = process_ages(broad)
        global_cols = beg + np.arange(len(selected), dtype=np.int64)
        control_sample = ((np.arange(len(dates), dtype=np.int64)[:, None] * 1315423911 + global_cols[None, :] * 2654435761) % 10) == 0
        controls = complete & ~broad & control_sample & eligible
        chosen = broad | controls
        chosen[:start_idx] = False
        ti, si = np.nonzero(chosen)
        labels = future_labels(arrays["open"], arrays["high"], arrays["low"], arrays["close"])
        next_i = np.minimum(ti + 1, len(dates) - 1)
        next_closed = closed[next_i, si] & (ti + 1 < len(dates))
        next_open_locked = (next_closed & np.isclose(arrays["open"][next_i, si], arrays["high"][next_i, si], rtol=0, atol=1e-5)
            & np.isclose(arrays["high"][next_i, si], arrays["close"][next_i, si], rtol=0, atol=1e-5))
        symbol_values = np.asarray(selected)[si]
        signal_dates = np.asarray(dates, dtype="datetime64[D]")[ti]
        # Board/date limit rates; ST 5% history is unavailable, so failed-limit is explicitly approximate.
        pct = np.full(len(ti), .10, dtype=np.float32)
        pct[np.char.endswith(symbol_values.astype(str), ".BJ")] = .30
        codes = np.char.partition(symbol_values.astype(str), ".")[:, 0]
        pct[((np.char.startswith(codes, "300") | np.char.startswith(codes, "301")) & (signal_dates >= np.datetime64("2020-08-24")))] = .20
        pct[((np.char.startswith(codes, "688") | np.char.startswith(codes, "689")) & (signal_dates >= np.datetime64("2019-07-22")))] = .20
        theoretical = np.round(arrays["prev_raw_close"][ti, si] * (1 + pct) + 1e-8, 2)
        failed = (~closed[ti, si]) & np.isfinite(theoretical) & (arrays["raw_high"][ti, si] >= theoretical - .005)
        data = {"symbol": symbol_values, "date": signal_dates, "idx": ti.astype(np.int32),
            "sample_kind": np.where(broad[ti, si], "surge", "control"), "process_age": ages[ti, si],
            "closed_limit": closed[ti, si], "failed_limit_approx": failed,
            "next_closed_limit": next_closed, "next_open_locked": next_open_locked,
            **{field: arrays[field][ti, si] for field in fields if field not in ("raw_high", "raw_close", "prev_raw_close")}}
        for h in HORIZONS:
            values = labels[h]
            data.update({f"r{h}_open": values["return"][ti, si], f"mfe{h}": values["mfe"][ti, si],
                f"mae{h}": values["mae"][ti, si], f"peak_day{h}": values["peak"][ti, si], f"low_first{h}": values["low_first"][ti, si]})
        pl.DataFrame(data).with_columns(pl.col(pl.Float32).fill_nan(None)).write_parquet(parts / f"part-{batch:03d}.parquet")
        print(f"batch {batch + 1}: {beg + len(selected)}/{len(symbols)} stocks, {len(ti)} rows", flush=True)

    ledger = pl.scan_parquet(parts / "*.parquet").collect()
    market = pl.read_parquet(ROOT / "data/research/stock-pools/trend-pullback/v1/market-baseline.parquet").select(
        "date", "environment", *[f"market{h}_open" for h in HORIZONS])
    liquidity = pl.read_parquet(ROOT / "data/research/stock-pools/liquidity-trend/v1/daily-ledger.parquet").select("symbol", "date", "amount_rank")
    breakthrough = (pl.scan_parquet(ROOT / "data/research/stock-pools/breakthrough/v1/daily-ledger.parquet")
        .filter(pl.col("age_close60") >= 0).select("symbol", "date", pl.col("age_close60").alias("breakthrough_age")).collect())
    pullback = (pl.scan_parquet(ROOT / "data/research/stock-pools/trend-pullback/v1/event-ledger.parquet")
        .filter(pl.col("trend_context") != "nontrend").group_by("symbol", "date").agg(pl.lit(True).alias("pullback_event")).collect())
    ledger = (ledger.join(market, on="date", validate="m:1").join(liquidity, on=["symbol", "date"], how="left", validate="m:1")
        .join(breakthrough, on=["symbol", "date"], how="left", validate="m:1")
        .join(pullback, on=["symbol", "date"], how="left", validate="m:1"))
    ledger = classify(ledger)
    ledger.write_parquet(OUT / "daily-ledger.parquet")
    ledger.filter((pl.col("sample_kind") == "surge") & (pl.col("process_age") == 0)).write_parquet(OUT / "event-ledger.parquet")
    coverage = {"price_first": str(dates[0]), "price_last": str(dates[-1]), "sessions": len(dates), "price_rows": total_prices,
        "stocks": len(symbols), "rows": ledger.height, "surge_rows": ledger.filter(pl.col("sample_kind") == "surge").height,
        "control_rows": ledger.filter(pl.col("sample_kind") == "control").height, "control_sample_rate": .1,
        "signal_first": START, "signal_last": END, "wide_definition": "return10>=30% OR return30>=50%",
        "original_definition": "return10>=50% OR return30>=100%", "failed_limit": "daily approximate; ST history unavailable",
        "ohlc_invalid": invalid_ohlc, "adjustment_bar_mismatch": adjustment_mismatch,
        "bse_signal_start": str(BSE_START), "pre_bse_neeq_quotes": "excluded from signals and controls",
        "entry_basis": "next_session_open", "horizons": list(HORIZONS),
        "historical_listing_universe": "cached symbols; completeness and delisted coverage unverified"}
    write_json(OUT / "coverage.json", coverage)
    return coverage


def paired_group(book, left, right, h):
    key = f"r{h}_open"
    cells = (book.filter(pl.col(key).is_not_null() & (left | right)).with_columns(
        pl.when(left).then(pl.lit("left")).otherwise(pl.lit("right")).alias("side"))
        .group_by("date", "side").agg(pl.col(key).mean().alias("mean"), pl.len().alias("n")))
    a = cells.filter(pl.col("side") == "left").select("date", pl.col("mean").alias("left"), pl.col("n").alias("left_n"))
    b = cells.filter(pl.col("side") == "right").select("date", pl.col("mean").alias("right"), pl.col("n").alias("right_n"))
    both = a.join(b, on="date").filter((pl.col("left_n") >= 3) & (pl.col("right_n") >= 3)).sort("date")
    values = (both["left"] - both["right"]).to_numpy()
    return {"dates": both.height, "difference": float(values.mean()) if len(values) else None, "block20_ci95": block_ci(values)}


def analyze(coverage):
    book = pl.read_parquet(OUT / "daily-ledger.parquet")
    surge = book.filter(pl.col("sample_kind") == "surge")
    events = surge.filter(pl.col("process_age") == 0)
    report = {"protocol": "abnormal-surge-v1", "scope": "exploration; no trade execution or independent validation",
        "coverage": coverage, "horizons": list(HORIZONS), "views": {}, "rules": {}, "boundary": {}}
    report["views"]["wide"] = summaries(surge)
    report["views"]["events"] = summaries(events)
    extreme10 = surge.filter((pl.col("return10_past") >= .80) & ~pl.col("closed_limit"))
    slow30_shrink = surge.filter((pl.col("return10_past") < .30) & (pl.col("return30_past") >= .50)
        & (pl.col("volume_ratio") < .80))
    report["views"]["extreme10_nonlimit"] = summaries(extreme10)
    report["views"]["slow30_shrink"] = summaries(slow30_shrink)
    for factor in ("surge_driver", "return10_band", "return30_band", "recent_state", "current_state", "process_age_band",
                   "trend_context", "drawdown_band", "volume_band", "environment", "original_threshold", "top100_amount",
                   "active30", "recent_breakthrough", "pullback_event"):
        for value in sorted((value for value in surge[factor].unique().to_list() if value is not None), key=str):
            report["views"][f"wide|{factor}:{value}"] = summaries(surge.filter(pl.col(factor) == value))
    rules = {"original_threshold": pl.col("original_threshold"), "rest": pl.col("recent_state") == "rest_-5-3%",
        "pullback": pl.col("recent_state") == "pullback_<-5%", "not_accelerating": pl.col("return3_past") < .15,
        "volume_below_1.2": pl.col("volume_ratio") < 1.2, "non_downtrend": pl.col("trend_context") != "nontrend",
        "closed_limit": pl.col("closed_limit"), "failed_limit_approx": pl.col("failed_limit_approx"),
        "entry_open_unlocked": ~pl.col("next_open_locked"),
        "top100_amount": pl.col("top100_amount"), "active30": pl.col("active30"),
        "recent_breakthrough": pl.col("recent_breakthrough"), "pullback_event": pl.col("pullback_event")}
    rules["extreme10_nonlimit"] = (pl.col("return10_past") >= .80) & ~pl.col("closed_limit")
    rules["slow30_shrink"] = ((pl.col("return10_past") < .30) & (pl.col("return30_past") >= .50)
        & (pl.col("volume_ratio") < .80))
    for name, predicate in rules.items():
        report["rules"][name] = rule_result(surge, predicate)
    # Local threshold comparisons limit extrapolation from very different prior-return states.
    report["boundary"]["10d_30_40_vs_20_30"] = {str(h): paired_group(book,
        (pl.col("return10_past") >= .30) & (pl.col("return10_past") < .40),
        (pl.col("return10_past") >= .20) & (pl.col("return10_past") < .30), h) for h in HORIZONS}
    report["boundary"]["30d_50_70_vs_30_50"] = {str(h): paired_group(book,
        (pl.col("return30_past") >= .50) & (pl.col("return30_past") < .70),
        (pl.col("return30_past") >= .30) & (pl.col("return30_past") < .50), h) for h in HORIZONS}
    report["annual_wide"] = {year: summaries(surge.filter(pl.col("year") == year)) for year in sorted(surge["year"].unique().to_list())}
    report["annual_extreme10_nonlimit"] = {year: summaries(extreme10.filter(pl.col("year") == year))
        for year in sorted(extreme10["year"].unique().to_list())}
    report["annual_slow30_shrink"] = {year: summaries(slow30_shrink.filter(pl.col("year") == year))
        for year in sorted(slow30_shrink["year"].unique().to_list())}
    for name, frame in (("wide", surge), ("events", events)):
        sizes = frame.group_by("date").len()
        report.setdefault("size", {})[name] = {"rows": frame.height, "stocks": frame["symbol"].n_unique(), "dates": sizes.height,
            "daily_median": sizes["len"].median(), "daily_p90": sizes["len"].quantile(.9)}
    write_json(OUT / "analysis.json", report)
    write_results(report)
    return report


def pct(value):
    return "—" if value is None else f"{value * 100:.2f}"


def write_results(report):
    lines = ["# 异动池v1数值结果", "", "脚本生成。全部未来收益与路径从次日开盘起算。", ""]
    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
        lines.append("")
    table("规模", ["账本", "记录", "股票", "日期", "日规模中位数/P90"],
        [[k, v["rows"], v["stocks"], v["dates"], f'{v["daily_median"]}/{v["daily_p90"]}'] for k, v in report["size"].items()])
    table("基线与分层", ["视角", "周期", "收益%", "超额百分点", "正收益率%", "P10%", "记录/日期"],
        [[name, h, pct(v.get("mean")), pct(v.get("excess")), pct(v.get("positive")), pct(v.get("p10_sample")), f'{v["n"]}/{v["dates"]}']
         for name, periods in report["views"].items() for h, v in periods.items()])
    table("条件与机会损失", ["规则", "保留%", "10日保留/剔除超额", "大赢家保留%"],
        [[name, pct(v["retained"]), f'{pct(v["kept"]["10"].get("excess"))}/{pct(v["removed"]["10"].get("excess"))}', pct(v["winner_retention"])]
         for name, v in report["rules"].items()])
    table("阈值邻域对照", ["对照", "周期", "越过阈值组减邻近组百分点", "共同日期", "20日期块95%区间"],
        [[name, h, pct(v.get("difference")), v["dates"], " / ".join(pct(x) for x in v["block20_ci95"])]
         for name, periods in report["boundary"].items() for h, v in periods.items()])
    (DOCS / "v1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_samples():
    book = pl.read_parquet(OUT / "daily-ledger.parquet")
    events = book.filter((pl.col("sample_kind") == "surge") & (pl.col("process_age") == 0)).sort(
        pl.struct("symbol", "date").hash(seed=20260914)).head(20)
    controls = book.filter(pl.col("sample_kind") == "control").sort(pl.struct("symbol", "date").hash(seed=7)).head(20)
    assertions = 0
    for row in events.to_dicts():
        assert row["return10_past"] >= .30 or row["return30_past"] >= .50
        assert row["process_age"] == 0
        assertions += 2
    for row in controls.to_dicts():
        assert row["return10_past"] < .30 and row["return30_past"] < .50
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
