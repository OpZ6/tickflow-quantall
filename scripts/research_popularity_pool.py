"""Historical popularity observation experiment; explicit archived evidence, no trades.

Run from backend: uv run --frozen python ../scripts/research_popularity_pool.py
"""
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/popularity/v2"
HORIZONS = (1, 2, 3, 5, 10, 20)


def path_labels(future):
    if not future or not all(p and all(p[k] is not None and p[k] > 0 and np.isfinite(p[k]) for k in ("open", "high", "low", "close")) for p in future):
        return None
    anchor = future[0]["open"]
    highs, lows = [p["high"] for p in future], [p["low"] for p in future]
    peak, trough = highs.index(max(highs)), lows.index(min(lows))
    return {"return":future[-1]["close"]/anchor-1, "mfe":max(highs)/anchor-1,
            "mae":min(lows)/anchor-1, "peak_day":peak+1,
            "path":"low_first" if trough<peak else "high_first" if trough>peak else "same_day_unknown"}


def summarize(rows, horizon, basis="open"):
    key = f"r{horizon}_{basis}"
    valid = [r for r in rows if r.get(key) is not None]
    if not valid:
        return {"n": 0, "dates": 0}
    groups = defaultdict(list)
    for r in valid:
        groups[r["date"]].append(r)
    values = np.array([r[key] for r in valid])
    means = [np.mean([r[key] for r in group]) for group in groups.values()]
    return {
        "n": len(valid), "dates": len(groups), "stocks": len({r["symbol"] for r in valid}),
        "mean": float(np.mean(means)), "median_sample": float(np.median(values)),
        "positive": float(np.mean([np.mean([r[key] > 0 for r in g]) for g in groups.values()])),
        "avg_win_sample": float(np.mean(values[values > 0])) if any(values > 0) else None,
        "avg_loss_sample": float(np.mean(values[values < 0])) if any(values < 0) else None,
        "p10_sample": float(np.quantile(values, .1)),
        "excess": float(np.mean([np.mean([r[key] - r[f"market{horizon}_{basis}"] for r in g]) for g in groups.values()])),
        "mfe": float(np.mean([np.mean([r[f"mfe{horizon}"] for r in g]) for g in groups.values()])),
        "mae": float(np.mean([np.mean([r[f"mae{horizon}"] for r in g]) for g in groups.values()])),
        "peak_day": float(np.mean([np.mean([r[f"peak_day{horizon}"] for r in g]) for g in groups.values()])),
        "low_first": float(np.mean([np.mean([r[f"path{horizon}"] == "low_first" for r in g]) for g in groups.values()])),
    }


def paired_difference(kept, removed, horizon=10):
    daily = [defaultdict(list), defaultdict(list)]
    for groups, rows in zip(daily, (kept,removed), strict=True):
        for r in rows:
            if r.get(f"r{horizon}_open") is not None:
                groups[r["date"]].append(r[f"r{horizon}_open"])
    days = sorted(set(daily[0]) & set(daily[1]))
    values = np.array([np.mean(daily[0][d])-np.mean(daily[1][d]) for d in days])
    if not len(values):
        return {"dates":0}
    # Moving blocks preserve correlated adjacent observation windows. Exploratory
    # intervals remain approximate with only a handful of 10-session blocks.
    block = min(10,len(values))
    rng = np.random.default_rng(20260913)
    samples = []
    for _ in range(1000):
        starts = rng.integers(0,len(values)-block+1,size=int(np.ceil(len(values)/block)))
        sample = np.concatenate([values[i:i+block] for i in starts])[:len(values)]
        samples.append(float(sample.mean()))
    return {"dates":len(days),"mean_difference":float(values.mean()),"positive_date_fraction":float(np.mean(values>0)),"block10_ci95":np.quantile(samples,[.025,.975]).tolist()}


def write_results(report):
    lines = ["# 人气中温池v2数值结果", "", "由 `scripts/research_popularity_pool.py` 生成。方法、解释与决策见[分析报告](v2-analysis.md)。全部收益、超额及路径空间以信号次日开盘起算;1日为次日开盘至次日收盘。收益与超额用百分数/百分点表示。", ""]
    names = {"ths":"同花顺","xueqiu":"雪球","baidu":"百度","union_best_rank":"多源并集"}

    def pct(value):
        return "—" if value is None else f"{value*100:.2f}"

    def table(title, headers, rows):
        lines.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"]*len(headers)) + " |"])
        lines.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
        lines.append("")

    table("覆盖与规模",["来源","有效日期","不同股票","成员记录","每日中位数/P90","确认新入榜"],[[names[s],v["dates"],v["stocks"],v["rows"],f'{v["daily_median"]}/{v["daily_p90"]}',v["confirmed_entries"]] for s,v in report["size"].items()])
    table("完整覆盖期收益",["来源","周期/起算","收益%","超额百分点","正收益率%","成员/日期","成员P10%","平均盈利/亏损%"],[[names[s],h,pct(v.get("mean")),pct(v.get("excess")),pct(v.get("positive")),f'{v["n"]}/{v["dates"]}',pct(v.get("p10_sample")),f'{pct(v.get("avg_win_sample"))}/{pct(v.get("avg_loss_sample"))}'] for s,g in report["groups"].items() for h,v in g["all"].items()])
    table("三源共同覆盖期",["来源","交易日数","收益%","超额百分点","成员/日期"],[[names[s],h,pct(g[str(h)].get("mean")),pct(g[str(h)].get("excess")),f'{g[str(h)]["n"]}/{g[str(h)]["dates"]}'] for s,g in report["common_source_baselines"].items() for h in HORIZONS])
    factors = ("band:","direction:","trend:","limit:","overlap:","past_hot5:","age_band:","month:","environment:","theme_support:")
    table("全周期单因素分层",["来源","分层","交易日数","收益%","超额百分点","成员/日期"],[[names[s],k,h,pct(v[f"{h}_open"].get("mean")),pct(v[f"{h}_open"].get("excess")),f'{v[f"{h}_open"]["n"]}/{v[f"{h}_open"]["dates"]}'] for s,g in report["groups"].items() for k,v in g.items() if k.startswith(factors) for h in HORIZONS])
    table("确认新入榜事件与路径",["来源","交易日数","收益%","超额百分点","事件/日期","平均最大上涨/下探%","平均峰值日"],[[names[s],h,pct(v.get("mean")),pct(v.get("excess")),f'{v["n"]}/{v["dates"]}',f'{pct(v.get("mfe"))}/{pct(v.get("mae"))}',round(v.get("peak_day",0),2)] for s,g in report["groups"].items() for h in HORIZONS for v in [g["events"][f"{h}_open"]]])
    table("规则质量与机会损失",["来源","规则","保留%","保留/剔除10日收益%","保留/剔除P10%","大赢家保留%/原始记录数"],[[names[s],k,pct(v["retained_fraction"]),f'{pct(v["kept"]["10"].get("mean"))}/{pct(v["removed"]["10"].get("mean"))}',f'{pct(v["kept"]["10"].get("p10_sample"))}/{pct(v["removed"]["10"].get("p10_sample"))}',f'{pct(v["winner20pct_retention"])}/{v["winner_rows"]}'] for s,g in report["rules"].items() for k,v in g.items() if "kept" in v])
    table("同日规则对照",["来源","规则/对照","保留减剔除百分点","共同日期","10日期块95%区间百分点"],[[names[s],k,pct(v["paired10"].get("mean_difference")),v["paired10"]["dates"]," / ".join(pct(x) for x in v["paired10"].get("block10_ci95",[]))] for s,g in report["rules"].items() for k,v in g.items()])
    table("超短及中期同日规则对照",["来源","规则","交易日数","保留减剔除百分点","共同日期"],[[names[s],k,h,pct(v["paired"][str(h)].get("mean_difference")),v["paired"][str(h)]["dates"]] for s,g in report["rules"].items() for k,v in g.items() if "paired" in v for h in HORIZONS])
    table("共同期重叠来源",["来源数","10日收益%","超额百分点","成员/日期"],[[k,pct(v.get("mean")),pct(v.get("excess")),f'{v["n"]}/{v["dates"]}'] for k,v in report["common_source_overlap"].items()])
    table("题材同伴涨停支持同日对照",["来源","高支持减低支持百分点","共同日期","95%区间百分点"],[[names[s],pct(v.get("mean_difference")),v["dates"]," / ".join(pct(x) for x in v.get("block10_ci95",[]))] for s,v in report["common_theme_control10"].items()])
    (ROOT / "docs/research/stock-pools/popularity/v2-results.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    snapshots = sorted((ROOT / "data/quantx").glob("*/hot_rank_snapshot.json"))
    rows, coverage, rejected = [], [], defaultdict(int)
    for path in snapshots:
        payload = json.loads(path.read_text(encoding="utf-8"))
        day = date.fromisoformat(f"{path.parent.name[:4]}-{path.parent.name[4:6]}-{path.parent.name[6:]}")
        accepted = []
        for r in payload.get("records", []):
            source = r["source_root"]
            status = payload.get("source_status", {}).get(source, {})
            if status.get("adapter") == "existing_ths_hot":
                rejected["synthetic_fallback_rank"] += 1
                continue
            observed = str(r.get("observed_at") or "")
            if observed[:10] != str(day) or observed[11:16] < "15:00":
                rejected["unproved_close_availability"] += 1
                continue
            code = str(r.get("code", ""))
            if len(code) != 6 or not code.isdigit() or r.get("market_scope") != "a_share":
                rejected["non_a_share_code"] += 1
                continue
            rank = r.get("rank")
            if not rank or not 1 <= rank <= 200 or r.get("deprecated") or r.get("freshness") != "fresh":
                rejected["invalid_rank_or_stale"] += 1
                continue
            if code.startswith(("4", "8", "92")):
                symbol = code + ".BJ"
            elif code.startswith("6"):
                symbol = code + ".SH"
            elif code.startswith(("0", "3")):
                symbol = code + ".SZ"
            else:
                rejected["non_a_share_code"] += 1
                continue
            accepted.append({"date": str(day), "symbol": symbol, "source": source, "rank": int(rank),
                             "observed_at": observed, "evidence": str(path.relative_to(ROOT))})
        rows.extend(accepted)
        for source, status in payload.get("source_status", {}).items():
            selected = [r for r in accepted if r["source"] == source]
            coverage.append({"date": str(day), "source": source, "status": status.get("status"),
                             "accepted": len(selected), "max_rank": max((r["rank"] for r in selected), default=None)})
    assert rows, "No usable direct close snapshots"
    assert len({(r['date'], r['source'], r['symbol']) for r in rows}) == len(rows)
    start, end = min(r["date"] for r in rows), "2026-09-11"
    files = [p for p in (ROOT / "data/kline_daily_enriched").glob("date=*/*.parquet")
             if "date=2026-03-01" <= p.parent.name <= f"date={end}"]
    frame = pl.scan_parquet(files).select("date", "symbol", "open", "high", "low", "close", "consecutive_limit_ups").collect().sort("symbol", "date")
    assert frame.select(pl.struct("symbol", "date").n_unique()).item() == frame.height
    # Global session grid: missing/suspended bars never shift a 5-day label to day 6.
    calendar = sorted({str(d) for d in frame["date"]})
    positions = {d: i for i, d in enumerate(calendar)}
    prices = {(str(r["date"]), r["symbol"]): r for r in frame.to_dicts()}
    symbols = sorted(set(frame["symbol"]))
    environment = {}
    for day in sorted({r["date"] for r in rows}):
        i = positions[day]
        values = []
        if i >= 20:
            for symbol in symbols:
                a, b = prices.get((calendar[i-20],symbol)), prices.get((day,symbol))
                if a and b and a["close"] and b["close"]:
                    values.append(b["close"]/a["close"]-1)
        environment[day] = "positive20" if values and np.mean(values)>0 else "nonpositive20" if values else "unknown"
    # Archived daily theme membership; support is contemporaneous limit-up breadth,
    # not future sector return or today's sector composition projected backward.
    theme_support = {}
    for day in sorted({r["date"] for r in rows}):
        member_path = ROOT / f"data/theme_member_daily/date={day}/part.parquet"
        limit_path = ROOT / f"data/limit_event_daily/date={day}/part.parquet"
        if not member_path.exists() or not limit_path.exists():
            continue
        members = pl.read_parquet(member_path).to_dicts()
        limits = {r["symbol"].split(".")[0] for r in pl.read_parquet(limit_path).to_dicts() if r["event_type"] == "limit_up"}
        theme_stocks = defaultdict(set)
        symbol_themes = defaultdict(set)
        for item in members:
            code = item["symbol"].split(".")[0]
            theme_stocks[item["theme_id"]].add(code)
            symbol_themes[code].add(item["theme_id"])
        for symbol, themes in symbol_themes.items():
            count = max(len((theme_stocks[t] & limits)-{symbol}) for t in themes)
            theme_support[day,symbol] = "peer_limit2+" if count >= 2 else "peer_limit0-1"
    market = {}
    for day in sorted({r["date"] for r in rows}):
        i = positions[day]
        for h in HORIZONS:
            if i + h >= len(calendar):
                continue
            for basis in ("open",):
                returns = []
                for symbol in symbols:
                    a = prices.get((calendar[i+1], symbol))
                    b = prices.get((calendar[i+h], symbol))
                    if a and b and a[basis] and b["close"]:
                        returns.append(b["close"] / a[basis] - 1)
                market[day, h, basis] = float(np.mean(returns))
    prior, ledger = {}, []
    source_days = {s:{c["date"] for c in coverage if c["source"]==s and c["accepted"]>0} for s in {r["source"] for r in rows}}
    overlap = defaultdict(set)
    for r in rows:
        overlap[r["date"], r["symbol"]].add(r["source"])
    for r in sorted(rows, key=lambda r: (r["date"], r["source"], r["symbol"])):
        day, symbol, source = r["date"], r["symbol"], r["source"]
        i = positions[day]
        bar = prices.get((day, symbol))
        before = prior.get((source, symbol))
        consecutive = before is not None and positions[before["date"]] == i-1
        r["age"] = before["age"] + 1 if consecutive else 1
        r["entry_status"] = "continuation" if consecutive else "confirmed_entry" if i>0 and calendar[i-1] in source_days[source] else "left_censored_or_gap"
        r["age_status"] = "continuous" if consecutive else "first_observed_or_reentry"
        r["direction"] = "up" if consecutive and r["rank"] < before["rank"] else "down" if consecutive and r["rank"] > before["rank"] else "flat" if consecutive else "unknown"
        r["band"] = "1-20" if r["rank"] <= 20 else "21-50" if r["rank"] <= 50 else "51-100" if r["rank"] <= 100 else "101-200"
        r["overlap"] = str(len(overlap[day, symbol]))
        r["environment"] = environment[day]
        r["theme_support"] = theme_support.get((day,symbol.split(".")[0]),"unknown")
        r["past_hot5"] = "unknown"
        if i >= 5:
            hist = [p for p in ledger if p["source"] == source and p["symbol"] == symbol and positions[p["date"]] >= i-5]
            available_days = {c["date"] for c in coverage if c["source"] == source and c["accepted"] > 0}
            if set(calendar[i-5:i]).issubset(available_days):
                r["past_hot5"] = "yes" if any(p["rank"] <= 20 for p in hist) else "no"
        histbars = [prices.get((d, symbol)) for d in calendar[max(0,i-24):i+1]]
        r["trend"] = "unknown"
        if len(histbars) == 25 and all(p and p["close"] for p in histbars):
            ma20 = np.mean([p["close"] for p in histbars[-20:]])
            prevma = np.mean([p["close"] for p in histbars[-25:-5]])
            r["trend"] = "healthy" if bar["close"] >= ma20 and ma20 > prevma else "weak" if bar["close"] < ma20 and ma20 <= prevma else "mixed"
        r["limit"] = "closed_limit" if bar and bar["consecutive_limit_ups"] else "other" if bar else "missing"
        for h in HORIZONS:
            for basis in ("open",):
                r[f"r{h}_{basis}"] = None
            r[f"mfe{h}"] = r[f"mae{h}"] = None
            if i+h >= len(calendar):
                continue
            future = [prices.get((d, symbol)) for d in calendar[i+1:i+h+1]]
            labels = path_labels(future)
            if labels is None:
                continue
            r[f"r{h}_open"] = labels["return"]
            r[f"market{h}_open"] = market[day,h,"open"]
            r[f"mfe{h}"] = labels["mfe"]
            r[f"mae{h}"] = labels["mae"]
            r[f"peak_day{h}"] = labels["peak_day"]
            r[f"path{h}"] = labels["path"]
        prior[source,symbol] = r
        ledger.append(r)
    for r in ledger:
        r["age_band"] = "1" if r["age"] == 1 else "2-3" if r["age"] <= 3 else "4-5" if r["age"] <= 5 else "6+"
        r["month"] = r["date"][:7]
    report = {"protocol": "popularity-v2; next-open 1/2/3/5/10/20 session price-path labels; exploration only",
              "entry_basis":"next_session_open", "horizons":list(HORIZONS),
              "window": [start, max(r["date"] for r in rows)], "price_end": end,
              "rejected": dict(rejected), "source_coverage": {}, "groups": {}, "rules": {}}
    for source in sorted({c["source"] for c in coverage}):
        c = [r for r in coverage if r["source"] == source and r["accepted"]]
        report["source_coverage"][source] = {"dates": len(c), "first": min((r["date"] for r in c), default=None), "last": max((r["date"] for r in c), default=None), "max_rank": max((r["max_rank"] for r in c), default=None)}
    # Union is counted once per stock/day; use best rank only for a separately named union view.
    union = {}
    for r in ledger:
        key = r["date"], r["symbol"]
        if key not in union or r["rank"] < union[key]["rank"]:
            union[key] = dict(r)
    union_prior = {}
    union_days = {r["date"] for r in rows}
    for r in sorted(union.values(), key=lambda r:(r["date"],r["symbol"])):
        i = positions[r["date"]]
        previous = union_prior.get(r["symbol"])
        consecutive = previous is not None and positions[previous["date"]] == i-1
        r["age"] = previous["age"]+1 if consecutive else 1
        r["entry_status"] = "continuation" if consecutive else "confirmed_entry" if i>0 and calendar[i-1] in union_days else "left_censored_or_gap"
        r["age_band"] = "1" if r["age"]==1 else "2-3" if r["age"]<=3 else "4-5" if r["age"]<=5 else "6+"
        r["direction"] = "up" if consecutive and r["rank"]<previous["rank"] else "down" if consecutive and r["rank"]>previous["rank"] else "flat" if consecutive else "unknown"
        r["past_hot5"] = "unknown"
        if i>=5 and set(calendar[i-5:i]).issubset(union_days):
            r["past_hot5"] = "yes" if any(union.get((d,r["symbol"]),{}).get("rank",201)<=20 for d in calendar[i-5:i]) else "no"
        union_prior[r["symbol"]] = r
    views = {s: [r for r in ledger if r["source"] == s] for s in sorted({r["source"] for r in ledger})}
    views["union_best_rank"] = list(union.values())
    for source, book in views.items():
        groups = {"all": book, "events": [r for r in book if r["entry_status"] == "confirmed_entry"]}
        for factor in ("band", "direction", "trend", "limit", "overlap", "past_hot5", "age_band", "month", "environment", "theme_support"):
            groups.update({f"{factor}:{value}": [r for r in book if r[factor] == value] for value in sorted({r[factor] for r in book})})
        groups.update({f"band_trend:{band}:{trend}": [r for r in book if r["band"] == band and r["trend"] == trend] for band in ("1-20", "21-50", "51-100") for trend in ("healthy", "mixed", "weak")})
        report["groups"][source] = {k: {f"{h}_{basis}": summarize(v,h,basis) for h in HORIZONS for basis in ("open",)} for k,v in groups.items()}
        sizes = defaultdict(int)
        for r in book:
            sizes[r["date"]] += 1
        report.setdefault("size", {})[source] = {"rows": len(book), "stocks": len({r["symbol"] for r in book}), "dates": len(sizes), "daily_median": float(np.median(list(sizes.values()))), "daily_p90": float(np.quantile(list(sizes.values()),.9)), "observed_starts":sum(r["age"]==1 for r in book), "confirmed_entries":len(groups["events"]), "observed_age_median": float(np.median([r["age"] for r in book]))}
        report["rules"][source] = {}
        for name, predicate in {"mid21_100": lambda r:r["rank"]>20, "mid_healthy":lambda r:r["rank"]>20 and r["trend"]=="healthy", "mid_not_weak":lambda r:r["rank"]>20 and r["trend"]!="weak", "exclude_past_hot5":lambda r:r["rank"]>20 and r["past_hot5"]=="no"}.items():
            kept, removed = [r for r in book if predicate(r)], [r for r in book if not predicate(r)]
            winners = [r for r in book if r.get("r10_open") is not None and r["r10_open"] >= .2]
            report["rules"][source][name] = {"retained_fraction":len(kept)/len(book), "winner20pct_retention":sum(predicate(r) for r in winners)/len(winners) if winners else None, "winner_rows":len(winners), "kept":{str(h):summarize(kept,h) for h in HORIZONS}, "removed":{str(h):summarize(removed,h) for h in HORIZONS}, "monthly":{m:{"kept":summarize([r for r in kept if r["month"]==m],10),"removed":summarize([r for r in removed if r["month"]==m],10)} for m in sorted({r["month"] for r in book})}}
            report["rules"][source][name]["paired10"] = paired_difference(kept,removed)
            report["rules"][source][name]["paired"] = {str(h):paired_difference(kept,removed,h) for h in HORIZONS}
        mid_no = [r for r in book if r["rank"]>20 and r["past_hot5"]=="no"]
        mid_yes = [r for r in book if r["rank"]>20 and r["past_hot5"]=="yes"]
        report["rules"][source]["known_mid_hot5_control"] = {"no":summarize(mid_no,10),"yes":summarize(mid_yes,10),"paired10":paired_difference(mid_no,mid_yes)}
        report["rules"][source]["known_mid_hot5_control"]["paired"] = {str(h):paired_difference(mid_no,mid_yes,h) for h in HORIZONS}
    common = set.intersection(*(source_days[s] for s in views if s in source_days))
    report["common_source_dates"] = sorted(common)
    report["common_source_baselines"] = {s:{str(h):summarize([r for r in b if r["date"] in common],h) for h in HORIZONS} for s,b in views.items()}
    report["common_source_overlap"] = {v:summarize([r for r in union.values() if r["date"] in common and r["overlap"]==v],10) for v in ("1","2","3")}
    report["common_theme_control10"] = {s:paired_difference([r for r in b if r["theme_support"]=="peer_limit2+"],[r for r in b if r["theme_support"]=="peer_limit0-1"]) for s,b in views.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(ledger, infer_schema_length=None).write_parquet(OUT / "daily-ledger.parquet")
    pl.DataFrame([r for r in ledger if r["age"]==1], infer_schema_length=None).write_parquet(OUT / "event-ledger.parquet")
    pl.DataFrame(list(union.values()), infer_schema_length=None).write_parquet(OUT / "union-ledger.parquet")
    (OUT / "coverage.json").write_text(json.dumps(coverage,indent=2)+"\n",encoding="utf-8")
    (OUT / "analysis.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    write_results(report)
    print(json.dumps({"coverage":report["source_coverage"], "size":report["size"], "rejected":report["rejected"], "baseline10":{s:g["all"]["10_open"] for s,g in report["groups"].items()}},indent=2))


if __name__ == "__main__":
    main()
