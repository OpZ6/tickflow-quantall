"""Full-history liquidity-trend candidate study without trade execution.

Run from backend: uv run --frozen python ../scripts/research_liquidity_trend_pool.py
"""
import json
import os
from pathlib import Path

import numpy as np
import polars as pl
from research_trend_pullback_pool import (
    HORIZONS,
    future_labels,
    matched_paired,
    rule_result,
    summaries,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/liquidity-trend/v1"
DOCS = ROOT / "docs/research/stock-pools/liquidity-trend"
START = "2016-01-04"
END = "2026-09-11"
BSE_START = "2021-11-15"
THRESHOLDS = (50, 100, 200)


def _band(column, edges, names):
    expr = pl.when(pl.col(column).is_null()).then(pl.lit("unknown"))
    for edge, name in zip(edges, names, strict=False):
        expr = expr.when(pl.col(column) < edge).then(pl.lit(name))
    return expr.otherwise(pl.lit(names[-1]))


def build_rankings(paths):
    """Rank each daily partition deterministically by amount then symbol."""
    rows = []
    for path in paths:
        day = path.parent.name.removeprefix("date=")
        if day < START or day > END:
            continue
        frame = (pl.read_parquet(path, columns=["symbol", "date", "amount"])
                 .filter(pl.col("amount").is_finite() & (pl.col("amount") > 0)
                         & (~pl.col("symbol").str.ends_with(".BJ") | (pl.col("date") >= pl.lit(BSE_START).str.to_date())))
                 .sort(["amount", "symbol"], descending=[True, False]).head(500)
                 .with_row_index("amount_rank", offset=1))
        rows.append(frame)
    result = pl.concat(rows).with_columns(pl.col("amount_rank").cast(pl.Int16))
    if result.select(pl.struct("symbol", "date").n_unique()).item() != result.height:
        raise ValueError("duplicate ranking key")
    return result


def rolling_features(frame):
    exprs = []
    for n in (10, 20, 60):
        exprs.extend([
            pl.col("close").rolling_mean(n, min_samples=n).over("symbol").alias(f"ma{n}"),
            (pl.col("idx") - pl.col("idx").shift(n - 1).over("symbol") == n - 1)
            .fill_null(False).alias(f"complete_ma{n}"),
        ])
    exprs.extend([
        pl.col("volume").shift(1).rolling_mean(20, min_samples=20).over("symbol").alias("prior_volume20"),
        pl.col("close").shift(20).over("symbol").alias("close20ago"),
        pl.col("close").shift(60).over("symbol").alias("close60ago"),
        pl.col("close").shift(1).rolling_max(20, min_samples=20).over("symbol").alias("prior_high20"),
        pl.col("close").shift(1).over("symbol").alias("prev_close"),
        (pl.col("idx") - pl.col("idx").shift(20).over("symbol") == 20).fill_null(False).alias("complete20"),
        (pl.col("idx") - pl.col("idx").shift(60).over("symbol") == 60).fill_null(False).alias("complete60"),
    ])
    result = frame.with_columns(exprs).with_columns([
        pl.when(pl.col(f"complete_ma{n}")).then(pl.col(f"ma{n}")).otherwise(None).alias(f"ma{n}")
        for n in (10, 20, 60)
    ])
    return result.with_columns([
        pl.when((pl.col("idx") - pl.col("idx").shift(10).over("symbol") == 10).fill_null(False))
        .then(pl.col("ma20").shift(10).over("symbol")).alias("ma20_10ago"),
        pl.when((pl.col("idx") - pl.col("idx").shift(10).over("symbol") == 10).fill_null(False))
        .then(pl.col("ma60").shift(10).over("symbol")).alias("ma60_10ago"),
        pl.when(pl.col("complete20") & (pl.col("prior_volume20") > 0))
        .then(pl.col("volume") / pl.col("prior_volume20")).alias("volume_ratio"),
        pl.when(pl.col("complete20")).then(pl.col("close") / pl.col("close20ago") - 1).alias("return20_past"),
        pl.when(pl.col("complete60")).then(pl.col("close") / pl.col("close60ago") - 1).alias("return60_past"),
        pl.when(pl.col("complete20")).then(pl.col("close") / pl.col("prior_high20") - 1).alias("drawdown20"),
        (pl.col("close") / pl.col("prev_close") - 1).alias("return1_signal"),
    ])


def add_membership_ages(frame):
    """Consecutive market-session age for each nested rank threshold."""
    frame = frame.sort("symbol", "idx")
    symbols = frame["symbol"].to_numpy()
    indices = frame["idx"].to_numpy()
    ranks = frame["amount_rank"].to_numpy()
    columns = {}
    for threshold in THRESHOLDS:
        ages = np.full(frame.height, -1, dtype=np.int16)
        previous_symbol = None
        previous_idx = previous_age = -1000
        for i, (symbol, idx, rank) in enumerate(zip(symbols, indices, ranks, strict=True)):
            active = rank <= threshold
            if active:
                ages[i] = previous_age + 1 if symbol == previous_symbol and idx == previous_idx + 1 and previous_age >= 0 else 0
            previous_symbol, previous_idx, previous_age = symbol, idx, ages[i]
        columns[f"age_top{threshold}"] = ages
    return frame.with_columns([pl.Series(name, values) for name, values in columns.items()])


def classify(frame):
    return frame.with_columns([
        pl.when(pl.col("amount_rank") <= 50).then(pl.lit("1-50"))
        .when(pl.col("amount_rank") <= 100).then(pl.lit("51-100"))
        .when(pl.col("amount_rank") <= 200).then(pl.lit("101-200"))
        .otherwise(pl.lit("201-500")).alias("rank_band"),
        pl.when(
            (pl.col("close") > pl.col("ma10")) & (pl.col("ma10") > pl.col("ma20"))
            & (pl.col("ma20") > pl.col("ma60")) & (pl.col("ma20") > pl.col("ma20_10ago"))
            & (pl.col("ma60") > pl.col("ma60_10ago"))
        ).then(pl.lit("strong"))
        .when((pl.col("close") > pl.col("ma20")) & (pl.col("ma20") > pl.col("ma60")))
        .then(pl.lit("basic")).otherwise(pl.lit("nontrend")).alias("trend_context"),
        _band("drawdown20", [-.15, -.08, -.03], ["<-15%", "-15--8%", "-8--3%", "-3%+"]).alias("drawdown_band"),
        _band("return20_past", [0, .1, .3], ["negative", "0-10%", "10-30%", "30%+"]).alias("return20_band"),
        _band("volume_ratio", [.8, 1.2, 2], ["<0.8", "0.8-1.2", "1.2-2", "2+"]).alias("volume_band"),
        pl.when(pl.col("age_top100") < 0).then(pl.lit("outside"))
        .when(pl.col("age_top100") == 0).then(pl.lit("0"))
        .when(pl.col("age_top100") <= 2).then(pl.lit("1-2"))
        .when(pl.col("age_top100") <= 4).then(pl.lit("3-4"))
        .when(pl.col("age_top100") <= 9).then(pl.lit("5-9"))
        .otherwise(pl.lit("10+")).alias("top100_age_band"),
        ((pl.col("return1_signal") < 0) & (pl.col("volume_ratio") >= 1.5)).alias("volume_down"),
        (pl.col("close") > pl.col("ma20")).alias("above_ma20"),
        (pl.col("close") > pl.col("ma60")).alias("above_ma60"),
        (pl.col("ma60") > pl.col("ma60_10ago")).alias("ma60_rising"),
        pl.col("date").dt.year().cast(pl.String).alias("year"),
        pl.col("breakthrough_age").is_not_null().alias("recent_breakthrough"),
        pl.col("pullback_event").fill_null(False),
    ])


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    parts_dir = OUT / "parts"
    parts_dir.mkdir(exist_ok=True)
    paths = sorted((ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet"))
    paths = [path for path in paths if path.parent.name <= f"date={END}"]
    rankings = build_rankings(paths)
    rankings.write_parquet(OUT / "rankings-top500.parquet")
    scan = pl.scan_parquet(paths)
    dates = scan.select("date").unique().sort("date").collect()["date"].to_list()
    calendar = pl.DataFrame({"date": dates}).with_row_index("idx")
    rankings = rankings.join(calendar, on="date")
    symbols = scan.select("symbol").unique().sort("symbol").collect()["symbol"].to_list()
    total_prices = invalid_ohlc = adjustment_mismatch = 0

    for batch, beg in enumerate(range(0, len(symbols), 300)):
        selected = symbols[beg:beg + 300]
        prices = (scan.filter(pl.col("symbol").is_in(selected))
            .select("symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "raw_high", "raw_low", "consecutive_limit_ups")
            .collect().join(calendar, on="date").sort("symbol", "date"))
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

        def dense(field, shape=shape, row_idx=row_idx, col_idx=col_idx, prices=prices):
            values = np.full(shape, np.nan, dtype=np.float32)
            values[row_idx, col_idx] = prices[field].to_numpy()
            return values

        open_, high, low, close = [dense(field) for field in ("open", "high", "low", "close")]
        labels = future_labels(open_, high, low, close)
        candidates = rankings.filter(pl.col("symbol").is_in(selected)).join(
            prices.select("symbol", "date", "open", "high", "low", "close", "volume", "consecutive_limit_ups",
                          "ma10", "ma20", "ma60", "ma20_10ago", "ma60_10ago", "volume_ratio", "return20_past",
                          "return60_past", "drawdown20", "return1_signal"), on=["symbol", "date"], validate="1:1")
        ti = candidates["idx"].to_numpy()
        si = candidates["symbol"].replace_strict(mapping, return_dtype=pl.Int32).to_numpy()
        label_columns = {}
        for h, values in labels.items():
            label_columns.update({f"r{h}_open": values["return"][ti, si], f"mfe{h}": values["mfe"][ti, si],
                                  f"mae{h}": values["mae"][ti, si], f"peak_day{h}": values["peak"][ti, si],
                                  f"low_first{h}": values["low_first"][ti, si]})
        candidates.with_columns([pl.Series(name, values) for name, values in label_columns.items()]).with_columns(
            pl.col(pl.Float32).fill_nan(None)).write_parquet(parts_dir / f"part-{batch:03d}.parquet")
        print(f"batch {batch + 1}: {beg + len(selected)}/{len(symbols)} stocks, {candidates.height} ranked rows", flush=True)

    ledger = pl.scan_parquet(parts_dir / "*.parquet").collect()
    ledger = add_membership_ages(ledger)
    market_path = ROOT / "data/research/stock-pools/trend-pullback/v1/market-baseline.parquet"
    market = pl.read_parquet(market_path)
    if market["date"].to_list() != dates:
        raise ValueError("market baseline calendar mismatch")
    ledger = ledger.join(market, on="date", validate="m:1")
    breakthrough_path = ROOT / "data/research/stock-pools/breakthrough/v1/daily-ledger.parquet"
    breakthrough = (pl.scan_parquet(breakthrough_path).filter(pl.col("age_close60") >= 0)
                    .select("symbol", "date", pl.col("age_close60").alias("breakthrough_age")).collect())
    pullback_path = ROOT / "data/research/stock-pools/trend-pullback/v1/event-ledger.parquet"
    pullback = (pl.scan_parquet(pullback_path).filter(pl.col("trend_context") != "nontrend")
                .group_by("symbol", "date").agg(pl.lit(True).alias("pullback_event")).collect())
    ledger = (ledger.join(breakthrough, on=["symbol", "date"], how="left", validate="m:1")
              .join(pullback, on=["symbol", "date"], how="left", validate="m:1"))
    ledger = classify(ledger)
    ledger.write_parquet(OUT / "daily-ledger.parquet")
    event_books = []
    for threshold in THRESHOLDS:
        event_books.append(ledger.filter(pl.col(f"age_top{threshold}") == 0).with_columns(pl.lit(threshold).cast(pl.Int16).alias("threshold")))
    pl.concat(event_books).write_parquet(OUT / "event-ledger.parquet")
    coverage = {"price_first": str(dates[0]), "price_last": str(dates[-1]), "sessions": len(dates),
        "price_rows": total_prices, "stocks": len(symbols), "ranked_rows": ledger.height,
        "rank_first": str(ledger["date"].min()), "rank_last": str(ledger["date"].max()),
        "daily_rank_limit": 500, "ohlc_invalid": invalid_ohlc, "adjustment_bar_mismatch": adjustment_mismatch,
        "entry_basis": "next_session_open", "horizons": list(HORIZONS),
        "bse_signal_start": BSE_START, "pre_bse_neeq_quotes": "excluded from daily amount ranks",
        "historical_listing_universe": "cached symbols; completeness and delisted coverage unverified"}
    write_json(OUT / "coverage.json", coverage)
    return ledger, coverage


def spell_stats(book, threshold):
    active = book.filter(pl.col("amount_rank") <= threshold).sort("symbol", "idx")
    spells = (active.with_columns(((pl.col("idx").diff().over("symbol") != 1) | (pl.col(f"age_top{threshold}") == 0)).fill_null(True).alias("new"))
              .with_columns(pl.col("new").cum_sum().over("symbol").alias("run"))
              .group_by("symbol", "run").agg(pl.len().alias("length"), pl.col("idx").max().alias("last_idx")))
    return {"spells": spells.height, "length_median": spells["length"].median(), "length_p90": spells["length"].quantile(.9),
            "right_censored": spells.filter(pl.col("last_idx") == book["idx"].max()).height}


def heat_context(top100):
    """Compare archived popularity sources only on their observed dates."""
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
        book = (top100.filter(pl.col("date").is_in(dates.implode())).join(
            source_heat, on=["date", "symbol"], how="left").with_columns(
                pl.col("heat_band").fill_null("observed_outside"), pl.col("heat_band").is_not_null().alias("hot")))
        result[source] = {"coverage_dates": len(dates), "first": str(dates.min()), "last": str(dates.max()), "members": book.height,
            "groups": {value: summaries(book.filter(pl.col("heat_band") == value)) for value in sorted(book["heat_band"].unique().to_list())},
            "matched": {str(h): matched_paired(book, pl.col("hot"), ["rank_band", "trend_context"], h) for h in HORIZONS}}
    return result


def analyze(ledger, coverage):
    top200 = ledger.filter(pl.col("amount_rank") <= 200)
    top100 = ledger.filter(pl.col("amount_rank") <= 100)
    trend100 = top100.filter(pl.col("trend_context") != "nontrend")
    report = {"protocol": "liquidity-trend-v1", "scope": "exploration; no trade execution or independent validation",
              "coverage": coverage, "horizons": list(HORIZONS), "views": {}, "rules": {}, "matched_capacity": {}, "spells": {}}
    groups = {"top500": ledger, "top200": top200, "top100": top100, "top100_trend": trend100}
    for factor in ("rank_band", "trend_context", "drawdown_band", "return20_band", "volume_band", "top100_age_band",
                   "environment", "recent_breakthrough", "pullback_event"):
        for value in sorted(top200[factor].unique().to_list(), key=str):
            groups[f"top200|{factor}:{value}"] = top200.filter(pl.col(factor) == value)
    report["views"] = {name: summaries(book) for name, book in groups.items()}
    for name, book in (("top500", ledger), ("top200", top200), ("top100", top100), ("top100_trend", trend100)):
        sizes = book.group_by("date").len()
        report.setdefault("size", {})[name] = {"rows": book.height, "stocks": book["symbol"].n_unique(), "dates": sizes.height,
            "daily_median": sizes["len"].median(), "daily_p90": sizes["len"].quantile(.9)}
    for threshold in THRESHOLDS:
        report["spells"][str(threshold)] = spell_stats(ledger, threshold)
        entries = ledger.filter(pl.col(f"age_top{threshold}") == 0)
        report.setdefault("entries", {})[str(threshold)] = summaries(entries)
    rules = {
        "top50_within_top200": pl.col("amount_rank") <= 50,
        "top100_within_top200": pl.col("amount_rank") <= 100,
    }
    report["rules"].update({name: rule_result(top200, predicate) for name, predicate in rules.items()})
    trend_rules = {
        "trend_identity": pl.col("trend_context") != "nontrend", "strong_trend": pl.col("trend_context") == "strong",
        "above_ma20": pl.col("above_ma20"), "above_ma60": pl.col("above_ma60"), "ma60_rising": pl.col("ma60_rising"),
        "avoid_deep_drawdown": pl.col("drawdown20") >= -.15, "avoid_volume_down": ~pl.col("volume_down"),
        "top100_five_days": pl.col("age_top100") >= 4, "top100_ten_days": pl.col("age_top100") >= 9,
        "recent_breakthrough": pl.col("recent_breakthrough"),
        "pullback_event": pl.col("pullback_event"),
    }
    report["rules"].update({name: rule_result(top100, predicate) for name, predicate in trend_rules.items()})
    report["matched_capacity"] = {str(h): matched_paired(
        ledger, pl.col("amount_rank") <= 200, ["trend_context", "drawdown_band", "return20_band"], h) for h in HORIZONS}
    report["matched_capacity_by_environment"] = {environment: {str(h): matched_paired(
        ledger.filter(pl.col("environment") == environment), pl.col("amount_rank") <= 200,
        ["trend_context", "drawdown_band", "return20_band"], h) for h in HORIZONS}
        for environment in sorted(ledger["environment"].unique().to_list())}
    report["heat"] = heat_context(top100)
    report["annual_top100_trend"] = {year: summaries(trend100.filter(pl.col("year") == year))
                                     for year in sorted(trend100["year"].unique().to_list())}
    write_json(OUT / "analysis.json", report)
    write_results(report)
    return report


def pct(value):
    return "—" if value is None else f"{value * 100:.2f}"


def write_results(report):
    lines = ["# 流动性趋势池v1数值结果", "", "脚本生成。全部未来收益与路径从次日开盘起算。", ""]

    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
        lines.append("")

    table("规模", ["账本", "记录", "股票", "日期", "日规模中位数/P90"],
          [[name, value["rows"], value["stocks"], value["dates"], f'{value["daily_median"]}/{value["daily_p90"]}']
           for name, value in report["size"].items()])
    table("基线与分层", ["视角", "周期", "收益%", "超额百分点", "正收益率%", "P10%", "记录/日期"],
          [[name, h, pct(value.get("mean")), pct(value.get("excess")), pct(value.get("positive")), pct(value.get("p10_sample")),
            f'{value["n"]}/{value["dates"]}'] for name, periods in report["views"].items() for h, value in periods.items()])
    table("条件与机会损失", ["规则", "保留%", "10日保留/剔除超额", "大赢家保留%"],
          [[name, pct(value["retained"]), f'{pct(value["kept"]["10"].get("excess"))}/{pct(value["removed"]["10"].get("excess"))}',
            pct(value["winner_retention"])] for name, value in report["rules"].items()])
    table("同日条件差", ["规则", "周期", "保留减剔除百分点", "共同日期", "20日期块95%区间"],
          [[name, h, pct(value.get("difference")), value["dates"], " / ".join(pct(x) for x in value["block20_ci95"])]
           for name, rule in report["rules"].items() for h, value in rule["paired"].items()])
    table("容量身份匹配对照", ["周期", "前200减201-500百分点", "共同日期/状态格", "20日期块95%区间"],
          [[h, pct(value.get("difference")), f'{value["dates"]}/{value["cells"]}', " / ".join(pct(x) for x in value["block20_ci95"])]
           for h, value in report["matched_capacity"].items()])
    (DOCS / "v1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_samples(ledger):
    samples = ledger.sort(pl.struct("symbol", "date").hash(seed=20260914)).head(20)
    ranking = pl.read_parquet(OUT / "rankings-top500.parquet")
    assertions = 0
    for row in samples.to_dicts():
        expected = ranking.filter((pl.col("symbol") == row["symbol"]) & (pl.col("date") == row["date"]))
        assert expected.height == 1 and expected["amount_rank"].item() == row["amount_rank"]
        assertions += 2
    for threshold in THRESHOLDS:
        entries = ledger.filter(pl.col(f"age_top{threshold}") == 0).sort(pl.struct("symbol", "date").hash(seed=threshold)).head(10)
        for row in entries.to_dicts():
            previous = ledger.filter((pl.col("symbol") == row["symbol"]) & (pl.col("idx") == row["idx"] - 1))
            assert row["amount_rank"] <= threshold
            assert not previous.height or previous["amount_rank"].item() > threshold
            assertions += 2
    result = {"status": "passed", "samples": samples.height, "assertions": assertions,
              "thresholds": list(THRESHOLDS), "horizons": list(HORIZONS)}
    write_json(OUT / "verification.json", result)
    return result


def main():
    required = (OUT / "daily-ledger.parquet", OUT / "event-ledger.parquet", OUT / "coverage.json")
    if os.environ.get("REBUILD_STOCK_POOL") != "1" and all(path.exists() for path in required):
        ledger = pl.read_parquet(OUT / "daily-ledger.parquet")
        coverage = json.loads((OUT / "coverage.json").read_text(encoding="utf-8"))
        print("reusing completed v1 ledger", flush=True)
    else:
        ledger, coverage = build()
    report = analyze(ledger, coverage)
    verification = verify_samples(ledger)
    print(json.dumps({"coverage": coverage, "size": report["size"], "verification": verification}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
