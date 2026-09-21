"""Advance prototype inputs one session without rerunning future-return research."""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import polars as pl

from research_abnormal_surge_pool import rolling_features as surge_features
from research_active_character_pool import rolling_features as activity_features
from research_breakthrough_pool import rolling_features as breakout_features
from research_trend_pullback_pool import rolling_features as pullback_features


def build(day: dt.date, data_dir: Path, output: Path) -> None:
    paths = sorted(path for path in (data_dir / "kline_daily_enriched").glob("date=*/part.parquet") if path.parent.name <= f"date={day}")
    paths = paths[-320:]
    dates = [dt.date.fromisoformat(path.parent.name.removeprefix("date=")) for path in paths]
    if not dates or dates[-1] != day:
        raise ValueError("Requested daily K partition missing")
    previous = dates[-2]
    calendar = pl.DataFrame({"date": dates}).with_row_index("idx")
    study = data_dir / "research/stock-pools"

    def prior(pool: str, columns: list[str]) -> dict:
        frame = pl.scan_parquet(study / pool / "v1/daily-ledger.parquet").filter(pl.col("date") == previous).select(columns).collect()
        return {row["symbol"]: row for row in frame.to_dicts()}

    prior_breakout = prior("breakthrough", ["symbol", *[f"{prefix}_{basis}{window}" for prefix in ("age", "level") for basis in ("close", "high") for window in (60, 100, 250)]])
    prior_surge = prior("abnormal-surge", ["symbol", "sample_kind", "process_age"])
    prior_trend = prior("liquidity-trend", ["symbol", "age_top200"])
    prior_active = prior("active-character", ["symbol", "sample_kind", "limit_age", "last_limit_low"])
    if not prior_breakout:
        raise ValueError("Previous study checkpoint missing; cannot advance this date")
    last_three = dates[-4:-1]
    anchors = pl.scan_parquet(study / "divergence/v1/event-ledger.parquet").filter(pl.col("event_date").is_in(last_three)).collect().sort("event_date", descending=True).unique("symbol", keep="first")
    divergence_anchors = {row["symbol"]: row for row in anchors.to_dicts()}
    repairs = pl.scan_parquet(study / "failed-limit-repair/v1/daily-ledger.parquet").filter((pl.col("date") == previous) & (pl.col("event_age") < 3)).select("symbol", "event_date", "event_age", "event_low").collect().sort("event_age").unique("symbol", keep="first")
    repair_anchors = {row["symbol"]: row for row in repairs.to_dicts()}
    today = pl.read_parquet(paths[-1])
    ranks = today.filter(pl.col("amount").is_finite() & (pl.col("amount") > 0)).sort(["amount", "symbol"], descending=[True, False]).with_row_index("amount_rank", offset=1)
    rank_by_symbol = dict(zip(ranks["symbol"].to_list(), ranks["amount_rank"].to_list(), strict=True))
    symbols = today["symbol"].unique().sort().to_list()
    books = {name: [] for name in ("breakthrough", "abnormal-surge", "liquidity-trend", "divergence", "failed-limit-repair", "trend-pullback", "active-character")}
    scan = pl.scan_parquet(paths)
    for begin in range(0, len(symbols), 500):
        selected = symbols[begin:begin + 500]
        bars = scan.filter(pl.col("symbol").is_in(selected)).select("symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "consecutive_limit_ups").collect().join(calendar, on="date").sort("symbol", "date")
        common = pullback_features(bars).filter(pl.col("date") == day)
        breaks = {row["symbol"]: row for row in breakout_features(bars).filter(pl.col("date") == day).to_dicts()}
        surges = {row["symbol"]: row for row in surge_features(bars).filter(pl.col("date") == day).to_dicts()}
        activities = {row["symbol"]: row for row in activity_features(bars.with_columns((pl.col("consecutive_limit_ups") > 0).alias("is_limit"))).filter(pl.col("date") == day).to_dicts()}
        for current in common.to_dicts():
            symbol = current["symbol"]
            close, low = current["close"], current["low"]
            breakout = breaks[symbol]
            before = prior_breakout.get(symbol, {})
            breakout_row = {"symbol": symbol, "date": day, "close": close, "volume_ratio": breakout["volume_ratio"]}
            for basis in ("close", "high"):
                for window in (60, 100, 250):
                    field = f"{basis}{window}"
                    level = breakout[f"prior_{field}"]
                    hit = level is not None and breakout[basis] > level
                    old_age = before.get(f"age_{field}", -1)
                    age = 0 if hit else old_age + 1 if old_age is not None and 0 <= old_age < 19 else -1
                    breakout_row[f"age_{field}"] = age
                    breakout_row[f"level_{field}"] = before.get(f"level_{field}") if hit and old_age == 0 or not hit and age >= 0 else level if hit else None
            books["breakthrough"].append(breakout_row)
            surge = surges[symbol]
            broad = (surge["return10_past"] or 0) >= .30 or (surge["return30_past"] or 0) >= .50
            old_surge = prior_surge.get(symbol, {})
            books["abnormal-surge"].append({"symbol": symbol, "date": day, "sample_kind": "surge" if broad else "control", "process_age": old_surge["process_age"] + 1 if broad and old_surge.get("sample_kind") == "surge" else 0 if broad else -1, "return10_past": surge["return10_past"], "return30_past": surge["return30_past"]})
            rank = rank_by_symbol.get(symbol, 99999)
            old_age = prior_trend.get(symbol, {}).get("age_top200", -1)
            books["liquidity-trend"].append({"symbol": symbol, "date": day, "close": close, "ma20": current["ma20"], "ma60": current["ma60"], "ma20_10ago": current["ma20_10ago"], "drawdown20": current["drawdown20"], "amount_rank": rank, "age_top200": old_age + 1 if rank <= 200 and old_age >= 0 else 0 if rank <= 200 else -1})
            active = activities[symbol]
            old_active = prior_active.get(symbol, {})
            is_limit = current["consecutive_limit_ups"] > 0
            age = 0 if is_limit else old_active["limit_age"] + 1 if old_active.get("sample_kind") == "active" and old_active["limit_age"] < 59 else -1
            last_low = low if is_limit else old_active.get("last_limit_low")
            books["active-character"].append({"symbol": symbol, "date": day, "sample_kind": "active" if age >= 0 else "control", "limit_age": age, "limit_count30": active["limit_count30"], "close": close, "ma20": active["ma20"], "drawdown20": active["drawdown20"], "last_limit_low": last_low})
            anchor = divergence_anchors.get(symbol)
            if anchor and age >= 0:
                books["divergence"].append({"symbol": symbol, "date": day, "event_date": anchor["event_date"], "event_age": dates.index(day) - dates.index(anchor["event_date"]), "board_height": anchor["board_height"], "current_relimit": is_limit, "current_day_return": close / current["open"] - 1, "broke_event_low": close < anchor["event_low"], "event_low": anchor["event_low"], "close": close, "low": low, "high": current["high"]})
            anchor = repair_anchors.get(symbol)
            if anchor:
                books["failed-limit-repair"].append({"symbol": symbol, "date": day, "event_date": anchor["event_date"], "event_age": anchor["event_age"] + 1, "event_low": anchor["event_low"], "broke_event_low": close < anchor["event_low"], "day_return": close / current["open"] - 1, "volume_ratio": current["volume_ratio"], "close": close, "low": low, "high": current["high"]})
            for support in (10, 20):
                ma, previous_ma = current[f"ma{support}"], current[f"prev_ma{support}"]
                if ma is not None and previous_ma is not None and current["prev_low"] is not None and low <= ma * 1.01 and current["high"] >= ma * .99 and current["prev_low"] > previous_ma * 1.01:
                    context = "basic" if current["ma20"] is not None and current["ma60"] is not None and close > current["ma20"] > current["ma60"] else "nontrend"
                    books["trend-pullback"].append({"symbol": symbol, "date": day, "age": 0, "support": support, "event_volume_ratio": current["volume_ratio"], "event_close": close, "event_support_ma": ma, "trend_context": context, "event_breakthrough_age": breakout_row["age_close60"] if breakout_row["age_close60"] >= 0 else None})
        print(f"daily inputs: {min(begin + 500, len(symbols))}/{len(symbols)}", flush=True)
    for pool, rows in books.items():
        path = output / pool / "v1/daily-ledger.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            raise ValueError(f"No input records for {pool}; do not publish a falsely complete pool")
        pl.DataFrame(rows, infer_schema_length=None).write_parquet(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    build(dt.datetime.strptime(args.date.replace("-", ""), "%Y%m%d").date(), Path(args.data_dir), Path(args.output))
