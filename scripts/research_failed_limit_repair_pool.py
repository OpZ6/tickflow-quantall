"""Daily-bar failed-limit and subsequent repair study."""
import gc
import json
import os
from pathlib import Path

import numpy as np
import polars as pl

from research_active_character_pool import rule_result, summaries
from research_trend_pullback_pool import eligibility_matrix, future_labels, write_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/failed-limit-repair/v1"
DOCS = ROOT / "docs/research/stock-pools/failed-limit-repair"
START, END = "2016-01-04", "2026-09-11"
HORIZONS = (1, 2, 3, 5, 10, 20)


def limit_rates(symbols, dates):
    rates = np.full(len(symbols), .10, dtype=np.float32)
    text = symbols.astype(str)
    codes = np.char.partition(text, ".")[:, 0]
    rates[np.char.endswith(text, ".BJ")] = .30
    rates[(np.char.startswith(codes, "300") | np.char.startswith(codes, "301")) & (dates >= np.datetime64("2020-08-24"))] = .20
    rates[(np.char.startswith(codes, "688") | np.char.startswith(codes, "689")) & (dates >= np.datetime64("2019-07-22"))] = .20
    return rates


def build():
    OUT.mkdir(parents=True, exist_ok=True); parts = OUT / "parts"; parts.mkdir(exist_ok=True)
    paths = sorted(path for path in (ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet") if path.parent.name <= f"date={END}")
    scan = pl.scan_parquet(paths)
    dates = scan.select("date").unique().sort("date").collect()["date"].to_list()
    calendar = pl.DataFrame({"date": dates}).with_row_index("idx")
    start_idx = calendar.filter(pl.col("date") >= pl.lit(START).str.to_date())["idx"].min()
    symbols = scan.select("symbol").unique().sort("symbol").collect()["symbol"].to_list()
    total = 0
    for batch, beg in enumerate(range(0, len(symbols), 300)):
        selected = symbols[beg:beg + 300]
        prices = (scan.filter(pl.col("symbol").is_in(selected)).select("symbol", "date", "open", "high", "low", "close",
            "volume", "raw_close", "raw_high", "consecutive_limit_ups").collect().join(calendar, on="date").sort("symbol", "date")
            .with_columns([pl.col("raw_close").shift(1).over("symbol").alias("prev_raw_close"),
                (pl.col("date").rank("ordinal").over("symbol") - 1).cast(pl.Int32).alias("listing_age"),
                pl.col("consecutive_limit_ups").shift(1).over("symbol").fill_null(0).alias("prev_board"),
                pl.col("volume").shift(1).rolling_mean(20, min_samples=20).over("symbol").alias("prior_volume20"),
                *[pl.col("close").rolling_mean(n, min_samples=n).over("symbol").alias(f"ma{n}") for n in (10, 20, 60)]])
            .with_columns((pl.col("volume") / pl.col("prior_volume20")).alias("volume_ratio")))
        mapping = {symbol: i for i, symbol in enumerate(selected)}
        ri = prices["idx"].to_numpy(); ci = prices["symbol"].replace_strict(mapping, return_dtype=pl.Int32).to_numpy()
        shape = (len(dates), len(selected)); eligible = eligibility_matrix(dates, selected)
        def dense(field):
            a = np.full(shape, np.nan, dtype=np.float32); a[ri, ci] = prices[field].to_numpy(); return a
        arrays = {f: dense(f) for f in ("open", "high", "low", "close", "raw_high", "prev_raw_close", "volume_ratio", "ma10", "ma20", "ma60", "prev_board", "listing_age")}
        closed = np.zeros(shape, bool); closed[ri, ci] = prices["consecutive_limit_ups"].to_numpy() > 0
        sym_grid = np.broadcast_to(np.asarray(selected)[None, :], shape)
        date_grid = np.broadcast_to(np.asarray(dates, dtype="datetime64[D]")[:, None], shape)
        rates = limit_rates(sym_grid.ravel(), date_grid.ravel()).reshape(shape)
        theoretical = np.round(arrays["prev_raw_close"] * (1 + rates) + 1e-8, 2)
        failed = eligible & (arrays["listing_age"] >= 20) & ~closed & np.isfinite(theoretical) & (arrays["raw_high"] >= theoretical - .005)
        failed[:start_idx] = False
        labels = future_labels(arrays["open"], arrays["high"], arrays["low"], arrays["close"])
        ei, es = np.nonzero(failed)
        rows = []
        for age in range(0, 6):
            ti = ei + age; valid = ti < len(dates); ti = ti[valid]; si = es[valid]; event_i = ei[valid]
            present = np.isfinite(arrays["close"][ti, si]); ti = ti[present]; si = si[present]; event_i = event_i[present]
            repaired = np.array([closed[e + 1:t + 1, s].any() for e, t, s in zip(event_i, ti, si)], dtype=bool)
            data = {"symbol": np.asarray(selected)[si], "date": np.asarray(dates, dtype="datetime64[D]")[ti], "idx": ti.astype(np.int32),
                "event_date": np.asarray(dates, dtype="datetime64[D]")[event_i], "event_idx": event_i.astype(np.int32),
                "event_age": np.full(len(ti), age, np.int8), "attempt_height": (arrays["prev_board"][event_i, si] + 1).astype(np.int16),
                "event_close": arrays["close"][event_i, si], "event_low": arrays["low"][event_i, si],
                "open": arrays["open"][ti, si], "high": arrays["high"][ti, si], "low": arrays["low"][ti, si], "close": arrays["close"][ti, si],
                "ma10": arrays["ma10"][ti, si], "ma20": arrays["ma20"][ti, si], "ma60": arrays["ma60"][ti, si],
                "volume_ratio": arrays["volume_ratio"][ti, si], "current_relimit": closed[ti, si], "repaired_since_event": repaired}
            for h in HORIZONS:
                v = labels[h]; data.update({f"r{h}_open": v["return"][ti, si], f"mfe{h}": v["mfe"][ti, si], f"mae{h}": v["mae"][ti, si]})
            rows.append(pl.DataFrame(data).with_columns(pl.col(pl.Float32).fill_nan(None)))
        part = pl.concat(rows); total += part.height; part.write_parquet(parts / f"part-{batch:03d}.parquet")
        print(f"batch {batch + 1}: {beg + len(selected)}/{len(symbols)} stocks, {part.height} rows", flush=True)
        gc.collect()
    book = pl.scan_parquet(parts / "*.parquet").collect()
    market = pl.read_parquet(ROOT / "data/research/stock-pools/trend-pullback/v1/market-baseline.parquet").select(
        "date", "environment", *[f"market{h}_open" for h in HORIZONS])
    book = book.join(market, on="date", validate="m:1").with_columns([
        (pl.col("close") < pl.col("event_low")).alias("broke_event_low"),
        (pl.col("close") / pl.col("event_close") - 1).alias("event_return"),
        (pl.col("close") / pl.col("open") - 1).alias("day_return"),
        pl.when(pl.col("attempt_height") == 1).then(pl.lit("first")).when(pl.col("attempt_height") == 2).then(pl.lit("second")).otherwise(pl.lit("third_plus")).alias("attempt_band"),
        pl.when(pl.col("event_age") == 0).then(pl.lit("0")).when(pl.col("event_age") <= 3).then(pl.lit("1-3")).otherwise(pl.lit("4-5")).alias("age_band"),
        pl.when(pl.col("volume_ratio") < .8).then(pl.lit("<0.8")).when(pl.col("volume_ratio") < 1.2).then(pl.lit("0.8-1.2"))
        .when(pl.col("volume_ratio") < 2).then(pl.lit("1.2-2")).otherwise(pl.lit("2+")).alias("volume_band"),
        pl.when((pl.col("close") > pl.col("ma10")) & (pl.col("ma10") > pl.col("ma20")) & (pl.col("ma20") > pl.col("ma60")))
        .then(pl.lit("strong")).when((pl.col("close") > pl.col("ma20")) & (pl.col("ma20") > pl.col("ma60")))
        .then(pl.lit("basic")).otherwise(pl.lit("nontrend")).alias("trend_context"),
        pl.col("date").dt.year().cast(pl.String).alias("year")])
    book.write_parquet(OUT / "event-observation-ledger.parquet")
    events = book.filter(pl.col("event_age") == 0); events.write_parquet(OUT / "event-ledger.parquet")
    daily = book.filter(pl.col("event_age") > 0).sort("event_idx", descending=True).unique(["symbol", "date"], keep="first").sort("date", "symbol")
    daily.write_parquet(OUT / "daily-ledger.parquet")
    coverage = {"price_rows": int(scan.select(pl.len()).collect().item()), "stocks": len(symbols), "event_rows": events.height,
        "observation_rows": book.height, "daily_rows": daily.height, "first_event": str(events["event_date"].min()), "last_event": str(events["event_date"].max()),
        "definition": "daily high touched board/date theoretical limit and close was not limit-up", "listing_first_20_sessions": "excluded",
        "st_5pct": "not covered",
        "event_ages": "0-5", "entry_basis": "next_session_open", "horizons": list(HORIZONS), "bse_pre_launch": "excluded"}
    write_json(OUT / "coverage.json", coverage); return coverage


def analyze(coverage):
    events = pl.read_parquet(OUT / "event-ledger.parquet"); daily = pl.read_parquet(OUT / "daily-ledger.parquet")
    report = {"protocol": "failed-limit-repair-v1", "coverage": coverage, "views": {}, "rules": {}}
    report["views"]["events"] = summaries(events); report["views"]["daily_1_5"] = summaries(daily)
    for factor in ("attempt_band", "age_band", "current_relimit", "repaired_since_event", "broke_event_low", "volume_band", "trend_context", "environment"):
        for value in sorted((v for v in daily[factor].unique().to_list() if v is not None), key=str):
            report["views"][f"daily|{factor}:{value}"] = summaries(daily.filter(pl.col(factor) == value))
    rules = {"first_attempt": pl.col("attempt_height") == 1, "second_attempt": pl.col("attempt_height") == 2,
        "age_1_3": pl.col("event_age") <= 3, "holds_event_low": ~pl.col("broke_event_low"), "shrink_volume": pl.col("volume_ratio") < .8,
        "current_relimit": pl.col("current_relimit"), "repaired_since_event": pl.col("repaired_since_event"),
        "day_not_down": pl.col("day_return") >= -.03}
    for name, pred in rules.items(): report["rules"][name] = rule_result(daily, pred)
    report["repair_rate"] = {band: {"rows": events.filter(pl.col("attempt_band") == band).height,
        "within5": daily.filter((pl.col("attempt_band") == band) & (pl.col("event_age") == 5))["repaired_since_event"].mean()}
        for band in sorted(events["attempt_band"].unique())}
    report["annual_events"] = {year: summaries(events.filter(pl.col("year") == year)) for year in sorted(events["year"].unique())}
    sizes = daily.group_by("date").len(); report["size"] = {"rows": daily.height, "stocks": daily["symbol"].n_unique(), "dates": sizes.height,
        "daily_median": sizes["len"].median(), "daily_p90": sizes["len"].quantile(.9)}
    write_json(OUT / "analysis.json", report); write_results(report); return report


def pct(v): return "—" if v is None else f"{v * 100:.2f}"


def write_results(report):
    lines = ["# 炸板修复池v1数值结果", "", "脚本生成；未来收益从下一交易日开盘起算。", ""]
    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(x) for x in row) + " |" for row in rows); lines.append("")
    table("分层", ["视角", "周期", "收益%", "超额百分点", "记录/日期"], [[name, h, pct(v.get("mean")), pct(v.get("excess")), f'{v["n"]}/{v["dates"]}']
        for name, periods in report["views"].items() for h, v in periods.items()])
    table("条件", ["规则", "保留%", "10日保留/剔除超额", "大赢家保留%"], [[name, pct(v["retained"]),
        f'{pct(v["kept"]["10"].get("excess"))}/{pct(v["removed"]["10"].get("excess"))}', pct(v["winner_retention"])] for name, v in report["rules"].items()])
    (DOCS / "v1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify():
    b = pl.read_parquet(OUT / "event-observation-ledger.parquet"); s = b.sort(pl.struct("symbol", "event_date").hash(seed=9)).head(30)
    assert s.filter(~pl.col("event_age").is_between(0, 5)).is_empty(); assert s.filter(pl.col("attempt_height") < 1).is_empty()
    result = {"status": "passed", "samples": s.height, "assertions": s.height * 2}; write_json(OUT / "verification.json", result); return result


def main():
    req = [OUT / "daily-ledger.parquet", OUT / "event-ledger.parquet", OUT / "coverage.json"]
    coverage = json.loads(req[2].read_text(encoding="utf-8")) if os.environ.get("REBUILD_STOCK_POOL") != "1" and all(p.exists() for p in req) else build()
    report = analyze(coverage); print(json.dumps({"coverage": coverage, "size": report["size"], "verification": verify()}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
