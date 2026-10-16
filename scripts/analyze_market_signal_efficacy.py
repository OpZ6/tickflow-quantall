"""Recompute current risk rules from published repositories, without changing facts."""
# ruff: noqa: RUF001 -- Chinese report labels.
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def outcome(prices, days, day, horizon):
    index = days.index(day)
    if index + horizon >= len(days):
        return None
    anchor = prices.get(day)
    path = [prices.get(d) for d in days[index + 1:index + horizon + 1]]
    if not anchor or not anchor.get("close") or any(not bar or not bar.get("close") for bar in path):
        return None
    lows = [bar.get("low") for bar in path]
    return {"return_pct": (path[-1]["close"] / anchor["close"] - 1) * 100,
            "worst_pct": (min(lows) / anchor["close"] - 1) * 100 if all(v and v > 0 for v in lows) else None}


def summarize(rows):
    returns = [r["return_pct"] for r in rows]
    worst = [r["worst_pct"] for r in rows if r["worst_pct"] is not None]
    return {"n": len(rows), "mean_return_pct": mean(returns) if returns else None,
            "median_return_pct": median(returns) if returns else None,
            "down_pct": mean(v < 0 for v in returns) * 100 if returns else None,
            "mean_worst_pct": mean(worst) if worst else None, "worst_n": len(worst)}


def block_interval(rows, block=5, repeats=500):
    """Resample blocks of trading dates; keep condition and outcome paired."""
    rng = random.Random(42)
    differences = []
    for _ in range(repeats):
        sample = []
        while len(sample) < len(rows):
            start = rng.randrange(len(rows))
            sample.extend(rows[start:start + block])
        sample = sample[:len(rows)]
        chosen = [r["return_pct"] for r in sample if r["selected"]]
        others = [r["return_pct"] for r in sample if r["baseline"]]
        if chosen and others:
            differences.append(mean(chosen) - mean(others))
    differences.sort()
    return [differences[int((len(differences) - 1) * q)] for q in (.025, .975)] if differences else None


def main():
    from app.market_facts.registry import DatasetId
    from app.market_facts.repository import MarketFactRepository
    from app.quantx_data.review_repository import QuantXReviewRepository
    from app.quantx_data.risk_radar import ALL_A_INDEX, MARKET_INDICES, SENTIMENT_INDICES
    from app.tickflow.repository import DataStore, KlineRepository

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    facts = MarketFactRepository(args.data_dir)
    fact_days = facts.available_dates(DatasetId.MARKET_STATE_DAILY)
    end = args.as_of or fact_days[-1]
    dates = [d for d in fact_days if d <= end]
    start = dates[0] - timedelta(days=60)
    repo = KlineRepository(DataStore(args.data_dir))
    datasets = (DatasetId.MARKET_BREADTH_DAILY, DatasetId.MARKET_STATE_DAILY,
                DatasetId.MARKET_LIQUIDITY_DAILY, DatasetId.LIMIT_LADDER_DAILY, DatasetId.LIMIT_EVENT_DAILY)
    frames = {key: facts.get_range(key, start, end) for key in datasets}

    class CachedFacts:
        def get_range(self, key, first, last):
            return frames[key].filter(pl.col("trade_date").is_between(first, last))

        def get_market_breadth(self, day):
            return self.get_range(DatasetId.MARKET_BREADTH_DAILY, day, day)

        def get_market_state(self, day):
            return self.get_range(DatasetId.MARKET_STATE_DAILY, day, day)

        def get_limit_ladder(self, day):
            return self.get_range(DatasetId.LIMIT_LADDER_DAILY, day, day)

        def get_limit_events(self, day):
            return self.get_range(DatasetId.LIMIT_EVENT_DAILY, day, day)

    symbols = list(MARKET_INDICES) + [ALL_A_INDEX] + [r[0] for r in SENTIMENT_INDICES]
    index_bars = repo.get_index_daily_batch(symbols, start, end, ["date", "close"])

    class CachedIndexes:
        def get_index_daily_batch(self, codes, first, last, columns):
            return index_bars.filter(pl.col("symbol").is_in(codes) & pl.col("date").is_between(first, last))

    view = QuantXReviewRepository(args.data_dir / "quantx", CachedFacts(), CachedIndexes())
    radars = {day: view._build_risk_radar(day) for day in dates}
    sessions = repo.get_index_daily("000001.SH", start, end, ["date"])
    days = sorted(set(sessions["date"].to_list()))
    all_a = repo.get_index_daily(ALL_A_INDEX, start, end, ["date", "close", "low"])
    prices = {r["date"]: r for r in all_a.to_dicts()}
    dimensions = {r["key"]: r["title"] for r in next(iter(radars.values()))["dimensions"]}
    tones = {day: {r["key"]: r["tone"] for r in radar["dimensions"]} for day, radar in radars.items()}
    summaries = []
    for key, title in dimensions.items():
        for color in ("amber", "red"):
            for mode in ("state_days", "first_entry"):
                for horizon in (1, 3, 5):
                    observations = []
                    pending = 0
                    for day in dates:
                        if day not in days or tones[day][key] is None:
                            continue
                        index = days.index(day)
                        prior = tones.get(days[index - 1], {}).get(key) if index else None
                        selected = tones[day][key] == color and (mode == "state_days" or (prior is not None and prior != color))
                        value = outcome(prices, days, day, horizon)
                        if value is None:
                            pending += int(selected)
                            continue
                        observations.append({**value, "selected": selected,
                                             "baseline": tones[day][key] != color})
                    selected = [r for r in observations if r["selected"]]
                    baseline = [r for r in observations if r["baseline"]]
                    s, b = summarize(selected), summarize(baseline)
                    summaries.append({"dimension": title, "key": key, "tone": color, "mode": mode,
                                      "horizon": horizon, "selected": s, "baseline": b, "pending_or_missing": pending,
                                      "mean_difference_pct": s["mean_return_pct"] - b["mean_return_pct"] if s["n"] and b["n"] else None,
                                      "difference_95_block_interval": block_interval(observations, block=max(5, horizon)) if s["n"] and b["n"] else None})
    result = {"algorithm_version": "risk-radar-v3", "as_of": str(end), "first_date": str(dates[0]),
              "fact_date_count": len(dates), "benchmark": ALL_A_INDEX, "method": "close-to-close; minimum future low versus signal close; first-entry requires known immediately prior trading day; 500 moving-block resamples, block>=5, seed42",
              "coverage": {title: dict(Counter(tones[day][key] or "missing" for day in dates)) for key, title in dimensions.items()},
              "summaries": summaries, "daily": [{"date": str(day), **radars[day]} for day in dates]}
    output = args.output or args.data_dir / "research" / f"market-signal-efficacy-{end:%Y%m%d}"
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# 当前风险画像规则历史检验", "", f"截至 {end}，{len(dates)} 个已发布事实日；规则 risk-radar-v3，基准中证全指。", "",
             "本次重算复用正式风险画像函数，未使用旧版退潮/崩塌信号，未修改原始事实或阈值。", "",
             "收益：观察日收盘到后续第N交易日收盘。期间最差变化：未来最低价相对观察日收盘，非峰谷最大回撤。首次进入要求前一交易日状态已知。", "",
             "对照为同维度非该颜色的日期；不控制观察日已发生的跌幅，不属于因果检验。连续日期与未来窗口重叠，均值差采用交易日块重采样区间。", "",
             "## 输入覆盖", "", "|维度|正常|关注|显著风险|缺失|", "|---|---:|---:|---:|---:|"]
    for title, counts in result["coverage"].items():
        lines.append(f"|{title}|{counts.get('green', 0)}|{counts.get('amber', 0)}|{counts.get('red', 0)}|{counts.get('missing', 0)}|")
    def fmt(v):
        return "—" if v is None else f"{v:+.2f}%"
    for mode, label in (("state_days", "全部状态日"), ("first_entry", "首次进入状态")):
        lines += ["", f"## {label}：3日结果", "", "|维度|状态|事件/日期数|平均收益|下跌比例|平均最差变化|对照收益|均值差95%块区间|", "|---|---|---:|---:|---:|---:|---:|---|"]
        for row in summaries:
            if row["mode"] != mode or row["horizon"] != 3:
                continue
            s, b, ci = row["selected"], row["baseline"], row["difference_95_block_interval"]
            interval = "—" if ci is None else f"[{fmt(ci[0])}, {fmt(ci[1])}]"
            lines.append(f"|{row['dimension']}|{'显著风险' if row['tone'] == 'red' else '关注'}|{s['n']}|{fmt(s['mean_return_pct'])}|{fmt(s['down_pct'])}|{fmt(s['mean_worst_pct'])}|{fmt(b['mean_return_pct'])}|{interval}|")
    lines += ["", "## 判读", "", "区间跨零表示本窗口无法确认均值差方向；事件少时不据此重设阈值。状态日结果与首次进入结果应一起看。红色提示描述当前风险，不要求其后必然继续下跌；当天跌幅与未来表现须分开解释。", "", "全部1/3/5日分组结果、逐日规则证据与输入缺失记录见 results.json。"]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "coverage": result["coverage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
