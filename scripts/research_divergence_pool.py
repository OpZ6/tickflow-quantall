"""First/second-board divergence study using the active-character ledger."""
import json
from pathlib import Path

import polars as pl

from research_active_character_pool import rule_result, summaries
from research_trend_pullback_pool import write_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/divergence/v1"
DOCS = ROOT / "docs/research/stock-pools/divergence"
HORIZONS = (1, 2, 3, 5, 10, 20)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    active = pl.read_parquet(ROOT / "data/research/stock-pools/active-character/v1/daily-ledger.parquet").filter(
        pl.col("sample_kind") == "active")
    limits = pl.read_parquet(ROOT / "data/research/stock-pools/active-character/v1/limit-day-ledger.parquet")
    anchors = (limits.filter(pl.col("board_height").is_in([1, 2])).select(
        "symbol", pl.col("date").alias("event_date"), pl.col("idx").alias("event_idx"),
        pl.col("close_right").alias("event_close"), pl.col("low").alias("event_low"),
        pl.col("board_height"), pl.col("one_price_limit").alias("event_one_price")))
    offsets = pl.DataFrame({"event_age": list(range(1, 11))})
    expanded = anchors.join(offsets, how="cross").with_columns((pl.col("event_idx") + pl.col("event_age")).alias("idx"))
    current_columns = ["symbol", "date", "idx", "open", "high", "low", "close", "volume_ratio", "trend_context",
        "environment", "top100_amount", "recent_breakthrough", "pullback_event", "limit_age", "year",
        *[f"{prefix}{h}{suffix}" for h in HORIZONS for prefix, suffix in (
            ("r", "_open"), ("market", "_open"), ("mfe", ""), ("mae", ""))]]
    observations = expanded.join(active.select(current_columns), on=["symbol", "idx"], how="inner", validate="m:1")
    observations = observations.with_columns([
        (pl.col("close") / pl.col("event_close") - 1).alias("event_drawdown"),
        (pl.col("close") < pl.col("event_low")).alias("broke_event_low"),
        (pl.col("limit_age") == 0).alias("current_relimit"),
        (pl.col("close") < pl.col("event_close")).alias("has_pullback"),
        (pl.col("close") / pl.col("open") - 1).alias("current_day_return"),
    ]).with_columns([
        pl.when(pl.col("event_drawdown") >= 0).then(pl.lit("above_anchor"))
        .when(pl.col("event_drawdown") >= -.05).then(pl.lit("0--5%"))
        .when(pl.col("event_drawdown") >= -.10).then(pl.lit("-5--10%"))
        .when(pl.col("event_drawdown") >= -.15).then(pl.lit("-10--15%"))
        .otherwise(pl.lit("<-15%")).alias("pullback_depth"),
        pl.when(pl.col("event_age") == 1).then(pl.lit("1"))
        .when(pl.col("event_age") <= 3).then(pl.lit("2-3"))
        .when(pl.col("event_age") <= 5).then(pl.lit("4-5")).otherwise(pl.lit("6-10")).alias("age_band"),
        pl.when(pl.col("volume_ratio").is_null()).then(pl.lit("unknown"))
        .when(pl.col("volume_ratio") < .8).then(pl.lit("<0.8"))
        .when(pl.col("volume_ratio") < 1.2).then(pl.lit("0.8-1.2"))
        .when(pl.col("volume_ratio") < 2).then(pl.lit("1.2-2")).otherwise(pl.lit("2+")).alias("volume_band"),
        pl.when(pl.col("current_day_return") < -.03).then(pl.lit("down"))
        .when(pl.col("current_day_return") <= .03).then(pl.lit("flat"))
        .otherwise(pl.lit("up")).alias("day_state"),
    ])
    observations.write_parquet(OUT / "event-observation-ledger.parquet")
    # Product view uses the latest eligible first/second-board anchor for each stock/date.
    daily = observations.sort("event_idx", descending=True).unique(["symbol", "date"], keep="first").sort("date", "symbol")
    daily.write_parquet(OUT / "daily-ledger.parquet")
    anchors.write_parquet(OUT / "event-ledger.parquet")
    coverage = {"source": "active-character-v1", "anchor_rows": anchors.height, "observation_rows": observations.height,
        "daily_rows": daily.height, "stocks": daily["symbol"].n_unique(), "first_date": str(daily["date"].min()),
        "last_date": str(daily["date"].max()), "anchor": "closed first or second board",
        "event_ages": "1-10 market sessions", "entry_basis": "next_session_open", "horizons": list(HORIZONS),
        "bse_pre_launch": "excluded upstream", "one_price_anchor": "retained as a factor"}
    write_json(OUT / "coverage.json", coverage)
    return coverage


def outcome(frame):
    return {"rows": frame.height, "dates": frame["date"].n_unique(), "relimit_now": frame["current_relimit"].mean(),
        "broke_low": frame["broke_event_low"].mean(), "returns": summaries(frame)}


def analyze(coverage):
    book = pl.read_parquet(OUT / "daily-ledger.parquet")
    report = {"protocol": "divergence-v1", "coverage": coverage, "views": {}, "rules": {}}
    report["views"]["wide"] = outcome(book)
    report["views"]["pullback"] = outcome(book.filter(pl.col("has_pullback")))
    report["views"]["classic_hold_low"] = outcome(book.filter(pl.col("has_pullback") & ~pl.col("broke_event_low")))
    for factor in ("board_height", "event_one_price", "pullback_depth", "age_band", "volume_band", "day_state",
                   "trend_context", "environment", "top100_amount", "recent_breakthrough", "pullback_event"):
        for value in sorted((v for v in book[factor].unique().to_list() if v is not None), key=str):
            report["views"][f"wide|{factor}:{value}"] = outcome(book.filter(pl.col(factor) == value))
    core = book.filter(pl.col("has_pullback"))
    rules = {"first_board": pl.col("board_height") == 1, "second_board": pl.col("board_height") == 2,
        "holds_event_low": ~pl.col("broke_event_low"), "depth_0_10": pl.col("event_drawdown").is_between(-.10, 0),
        "age_1_3": pl.col("event_age") <= 3, "shrink_volume": pl.col("volume_ratio") < .8,
        "day_not_down": pl.col("current_day_return") >= -.03, "non_one_price_anchor": ~pl.col("event_one_price"),
        "current_relimit": pl.col("current_relimit"), "top100_amount": pl.col("top100_amount")}
    for name, predicate in rules.items():
        report["rules"][name] = rule_result(core, predicate)
    report["annual_classic"] = {year: summaries(core.filter(~pl.col("broke_event_low") & (pl.col("year") == year)))
        for year in sorted(core["year"].unique().to_list())}
    sizes = book.group_by("date").len()
    report["size"] = {"rows": book.height, "stocks": book["symbol"].n_unique(), "dates": sizes.height,
        "daily_median": sizes["len"].median(), "daily_p90": sizes["len"].quantile(.9)}
    write_json(OUT / "analysis.json", report)
    write_results(report)
    return report


def pct(v):
    return "—" if v is None else f"{v * 100:.2f}"


def write_results(report):
    lines = ["# 分歧池v1数值结果", "", "脚本生成。全部未来收益从当前观察日的下一交易日开盘起算。", ""]
    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(x) for x in row) + " |" for row in rows); lines.append("")
    table("规模", ["记录", "股票", "日期", "日规模中位数/P90"], [[report["size"]["rows"], report["size"]["stocks"],
        report["size"]["dates"], f'{report["size"]["daily_median"]}/{report["size"]["daily_p90"]}']])
    table("视角", ["分层", "再封板率%", "破锚点低点率%", "周期", "收益%", "超额百分点", "记录/日期"],
        [[name, pct(v["relimit_now"]), pct(v["broke_low"]), h, pct(s.get("mean")), pct(s.get("excess")), f'{s["n"]}/{s["dates"]}']
         for name, v in report["views"].items() for h, s in v["returns"].items()])
    table("条件", ["规则", "保留%", "10日保留/剔除超额", "大赢家保留%"],
        [[name, pct(v["retained"]), f'{pct(v["kept"]["10"].get("excess"))}/{pct(v["removed"]["10"].get("excess"))}', pct(v["winner_retention"])]
         for name, v in report["rules"].items()])
    (DOCS / "v1-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify():
    book = pl.read_parquet(OUT / "daily-ledger.parquet")
    sample = book.sort(pl.struct("symbol", "date").hash(seed=5)).head(30)
    assert sample.filter(~pl.col("board_height").is_in([1, 2])).is_empty()
    assert sample.filter(~pl.col("event_age").is_between(1, 10)).is_empty()
    assert sample.filter(pl.col("broke_event_low") != (pl.col("close") < pl.col("event_low"))).is_empty()
    result = {"status": "passed", "samples": sample.height, "assertions": sample.height * 3}
    write_json(OUT / "verification.json", result)
    return result


def main():
    required = [OUT / "daily-ledger.parquet", OUT / "event-ledger.parquet", OUT / "coverage.json"]
    coverage = json.loads(required[2].read_text(encoding="utf-8")) if all(p.exists() for p in required) else build()
    report = analyze(coverage)
    print(json.dumps({"coverage": coverage, "size": report["size"], "verification": verify()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
