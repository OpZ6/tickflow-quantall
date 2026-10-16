"""Breakthrough event study: prior volume structure and next-open confirmation."""
import time

import numpy as np
import polars as pl
from research_breakthrough_pool import (
    END,
    HORIZONS,
    ROOT,
    START,
    WINDOWS,
    summaries,
    write_json,
)

OUT = ROOT / "data/research/stock-pools/breakthrough/v2"
BASE = ROOT / "data/research/stock-pools/breakthrough/v1"


def features(frame):
    """All T features are causal; the gap alone becomes known at T+1 open."""
    frame = frame.sort("symbol","idx")
    frame = frame.with_columns(pl.when(pl.col("date")>=pl.lit(START).str.to_date()).then(pl.col("volume")).alias("unit_volume"))
    expr = []
    for n in (5,10,20,25,30,40,21,61,*WINDOWS):
        expr.append((pl.col("idx")-pl.col("idx").shift(n).over("symbol")==n).fill_null(False).alias(f"full{n}"))
    for n in WINDOWS:
        expr.append(pl.col("high").shift(1).rolling_max(n,min_samples=n).over("symbol").alias(f"prior_high{n}"))
    for n in (5,10,20):
        expr.append(pl.col("unit_volume").shift(1).rolling_mean(n,min_samples=n).over("symbol").alias(f"pre_mean{n}"))
    expr.extend([
        pl.col("unit_volume").shift(6).rolling_mean(20,min_samples=20).over("symbol").alias("older_mean5"),
        pl.col("unit_volume").shift(11).rolling_mean(20,min_samples=20).over("symbol").alias("older_mean10"),
        pl.col("close").shift(1).over("symbol").alias("prior_close"),
        pl.col("close").shift(21).over("symbol").alias("close21ago"),
        pl.col("close").shift(61).over("symbol").alias("close61ago"),
        pl.col("open").shift(-1).over("symbol").alias("next_open"),
        (pl.col("idx").shift(-1).over("symbol")-pl.col("idx")==1).fill_null(False).alias("next_day_present"),
    ])
    frame = frame.with_columns(expr).with_columns(
        pl.when(pl.col("full20")&(pl.col("pre_mean20")>0)).then(pl.col("unit_volume")/pl.col("pre_mean20")).alias("volume_ratio"))
    frame = frame.with_columns([
        pl.when(pl.col("volume_ratio").is_not_null()).then((pl.col("volume_ratio")>=2).cast(pl.Float64)).alias("spike"),
        pl.when(pl.col("full25")&(pl.col("older_mean5")>0)).then(pl.col("pre_mean5")/pl.col("older_mean5")).alias("pre_quiet5"),
        pl.when(pl.col("full30")&(pl.col("older_mean10")>0)).then(pl.col("pre_mean10")/pl.col("older_mean10")).alias("pre_quiet10"),
        pl.when(pl.col("full21")).then(pl.col("prior_close")/pl.col("close21ago")-1).alias("pre_return20"),
        pl.when(pl.col("full61")).then(pl.col("prior_close")/pl.col("close61ago")-1).alias("pre_return60"),
        pl.when(pl.col("next_day_present")).then(pl.col("next_open")/pl.col("close")-1).alias("gap"),
        pl.when(pl.col("high")>pl.col("low")).then((pl.col("high")-pl.col("close"))/(pl.col("high")-pl.col("low"))).alias("upper_wick"),
    ])
    return frame.with_columns([
        pl.when(pl.col("full40")).then(pl.col("spike").shift(1).rolling_sum(20,min_samples=20).over("symbol")).alias("pre_spikes20"),
        *[pl.when(pl.col(f"full{n}")).then(pl.col(f"prior_high{n}")).alias(f"prior_high{n}") for n in WINDOWS],
    ])


def band(column, edges, names):
    expr = pl.when(pl.col(column).is_null()).then(pl.lit("unknown"))
    for edge,name in zip(edges,names,strict=False):
        expr = expr.when(pl.col(column)<edge).then(pl.lit(name))
    return expr.otherwise(pl.lit(names[-1]))


def classify(frame):
    return frame.with_columns([
        pl.col("date").dt.year().cast(pl.String).alias("year"),
        band("gap",[-.03,-.01,.01,.03,.05],["<-3%","-3--1%","-1-1%","1-3%","3-5%","5%+"]).alias("gap_band"),
        band("volume_ratio",[.8,1.5,3],["<0.8","0.8-1.5","1.5-3","3+"]).alias("volume_band"),
        *[band(f"pre_quiet{n}",[.8,1.2],["quiet<0.8","normal0.8-1.2","active1.2+"]).alias(f"quiet{n}_band") for n in (5,10)],
        band("pre_spikes20",[.5,1.5],["0","1","2+"]).alias("pre_spikes_band"),
        band("break_strength",[.01,.03,.05],["0-1%","1-3%","3-5%","5%+"]).alias("strength_band"),
        pl.when(pl.col("high")==pl.col("low")).then(pl.lit("flat"))
        .otherwise(band("upper_wick",[.20000001,.50000001],["0-20%","20-50%","50%+"])).alias("wick_band"),
        *[band(f"pre_return{n}",[0,.1,.3],["negative","0-10%","10-30%","30%+"]).alias(f"runup{n}_band") for n in (20,60)],
        pl.when(pl.col("consecutive_limit_ups").is_null()).then(pl.lit("unknown"))
        .when(pl.col("consecutive_limit_ups")>0).then(pl.lit("closed_limit")).otherwise(pl.lit("other")).alias("limit_state"),
    ]).with_columns(pl.when(pl.col("prior_high_threshold").is_null()).then(pl.lit("unknown"))
        .when(pl.col("close")>pl.col("prior_high_threshold")).then(pl.lit("above_prior_high"))
        .otherwise(pl.lit("close_high_only")).alias("clear_high_band"))


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    events = pl.read_parquet(BASE/"event-ledger.parquet").filter(pl.col("basis")=="close").drop("volume_ratio","width20")
    calendar = pl.read_parquet(BASE/"market-baseline.parquet").with_row_index("idx")
    stocks = sorted(events["symbol"].unique().to_list())
    scan = pl.scan_parquet(ROOT/"data/kline_daily_enriched/date=*/part.parquet").filter(pl.col("date")<=pl.lit(END).str.to_date())
    parts = []
    for beg in range(0,len(stocks),300):
        selected = stocks[beg:beg+300]
        prices = scan.filter(pl.col("symbol").is_in(selected)).select("symbol","date","open","high","low","close","volume","consecutive_limit_ups").collect().join(calendar.select("date","idx"),on="date")
        f = features(prices).select("symbol","date","idx","open","high","low","close","volume_ratio","pre_quiet5","pre_quiet10","pre_spikes20","pre_return20","pre_return60","gap","next_open","upper_wick","consecutive_limit_ups",*[f"prior_high{n}" for n in WINDOWS])
        part = events.filter(pl.col("symbol").is_in(selected)).join(f,on=["symbol","date"],how="left",validate="m:1")
        assert part["idx"].null_count()==0
        parts.append(part)
        print(f"features {min(beg+300,len(stocks))}/{len(stocks)} stocks",flush=True)
    ledger = pl.concat(parts).join(calendar.drop("idx"),on="date",how="left",validate="m:1").with_columns([
        (pl.col("close")/pl.col("breakthrough_level")-1).alias("break_strength"),
        pl.coalesce([pl.when(pl.col("window")==n).then(pl.col(f"prior_high{n}")) for n in WINDOWS]).alias("prior_high_threshold"),
    ]).drop(*[f"prior_high{n}" for n in WINDOWS])
    ledger = classify(ledger)
    assert ledger.select(pl.struct("symbol","date","window").n_unique()).item()==ledger.height
    ledger.write_parquet(OUT/"event-ledger.parquet")
    write_json(OUT/"coverage.json",{"rows":ledger.height,"stocks":len(stocks),"first":str(ledger["date"].min()),"last":str(ledger["date"].max()),"parent":"breakthrough/v1","price_end":END,"entry_basis":"next_session_open","signal_features_known":"T close","gap_known":"T+1 open","missing_gap":ledger["gap"].null_count(),"missing_prior_spikes":ledger["pre_spikes20"].null_count()})
    return ledger


def yearly(frame):
    expr = []
    for h in (1,2,3,10,20):
        expr.extend([pl.col(f"r{h}_open").count().alias(f"n{h}"),(pl.col(f"r{h}_open")-pl.col(f"market{h}_open")).mean().alias(f"excess{h}")])
    daily = frame.group_by("date","year").agg(expr)
    return {y:{str(h):{"dates":(d:=daily.filter((pl.col("year")==y)&(pl.col(f"n{h}")>0))).height,"n":int(d[f"n{h}"].sum()),"excess":d[f"excess{h}"].mean()} for h in (1,2,3,10,20)} for y in sorted(frame["year"].unique().to_list())}


def ci(values):
    values = np.asarray(values,dtype=float)
    if len(values)<40:
        return []
    block = 20
    rng = np.random.default_rng(20260913)
    starts = rng.integers(0,len(values),size=(500,int(np.ceil(len(values)/block))))
    indices=(starts[...,None]+np.arange(block)).reshape(500,-1)[:,:len(values)]%len(values)
    draws = values[indices].mean(axis=1)
    return np.quantile(draws,[.025,.975]).tolist()


def paired(frame,predicate,h):
    valid=frame.filter(pl.col(f"r{h}_open").is_not_null())
    a=valid.filter(predicate).group_by("date").agg(pl.col(f"r{h}_open").mean().alias("a"))
    b=valid.filter(~predicate).group_by("date").agg(pl.col(f"r{h}_open").mean().alias("b"))
    both=a.join(b,on="date").sort("date")
    differences=(both["a"]-both["b"]).to_numpy()
    return {"dates":both.height,"difference":float(differences.mean()) if both.height else None,
        "block20_ci95":ci(differences),"ci_status":"estimated" if both.height>=40 else "insufficient_dates"}


def excess_ci(frame,h):
    daily = frame.filter(pl.col(f"r{h}_open").is_not_null()).group_by("date").agg((pl.col(f"r{h}_open")-pl.col(f"market{h}_open")).mean().alias("excess")).sort("date")
    return ci(daily["excess"].to_numpy())


def matched_difference(frame,predicate,controls,h):
    """Exploratory same-date cell contrast; require three events on each side."""
    keys=["date",*controls]
    valid=frame.filter(pl.col(f"r{h}_open").is_not_null()&predicate.is_not_null())
    cells=valid.with_columns(predicate.alias("selected")).group_by(*keys,"selected").agg(pl.col(f"r{h}_open").mean().alias("mean"),pl.len().alias("n"))
    a=cells.filter(pl.col("selected")&(pl.col("n")>=3))
    b=cells.filter(~pl.col("selected")&(pl.col("n")>=3))
    both=a.join(b,on=keys,suffix="_other").with_columns((pl.col("mean")-pl.col("mean_other")).alias("difference"))
    daily=both.group_by("date").agg(pl.col("difference").mean()).sort("date")
    return {"dates":daily.height,"cells":both.height,"difference":daily["difference"].mean(),"block20_ci95":ci(daily["difference"].to_numpy()),"minimum_each_side":3,"ci_status":"estimated" if daily.height>=40 else "insufficient_dates"}


def analyze(ledger):
    report = {"protocol":"breakthrough-v2","scope":"exploration; no independent validation or trade execution","horizons":list(HORIZONS),"views":{},"annual":{},"rules":{},"diagnostics":{}}
    for n in WINDOWS:
        book = ledger.filter(pl.col("window")==n)
        key = f"close{n}"
        groups = {"all":pl.col("idx")>=0}
        factors = ("gap_band","volume_band","quiet5_band","quiet10_band","pre_spikes_band","strength_band","wick_band","runup20_band","runup60_band","limit_state","environment","clear_high_band")
        for factor in factors:
            for value in sorted(book[factor].unique().to_list()):
                groups[f"{factor}:{value}"] = pl.col(factor)==value
        for left,right in (("gap_band","volume_band"),("quiet5_band","volume_band"),("pre_spikes_band","volume_band")):
            for a,b in book.select(left,right).unique().sort(left,right).iter_rows():
                if a!="unknown" and b!="unknown":
                    groups[f"{left}:{a}|{right}:{b}"] = (pl.col(left)==a)&(pl.col(right)==b)
        report["views"][key] = {}
        report["annual"][key] = {}
        for name,predicate in groups.items():
            selected = book.filter(predicate)
            report["views"][key][name] = summaries(selected)
            report["annual"][key][name] = yearly(selected)
        # These five hypotheses were fixed before examining their results.
        hypotheses = {
            "volume_small_gap":(pl.col("volume_ratio").is_between(.8,3,closed="left")&pl.col("gap").is_between(.01,.03,closed="left"),["volume_ratio","gap"]),
            "quiet_then_volume":((pl.col("pre_quiet5")<.8)&pl.col("volume_ratio").is_between(1.5,3,closed="left"),["pre_quiet5","volume_ratio"]),
            "no_spike_then_volume":((pl.col("pre_spikes20")==0)&(pl.col("volume_ratio")>=1.5),["pre_spikes20","volume_ratio"]),
            "quiet_volume_small_gap":((pl.col("pre_quiet5")<.8)&pl.col("volume_ratio").is_between(1.5,3,closed="left")&pl.col("gap").is_between(.01,.03,closed="left"),["pre_quiet5","volume_ratio","gap"]),
            "small_break_low_wick":((pl.col("break_strength")<.03)&(pl.col("upper_wick")<=.20000001),["break_strength","upper_wick"]),
        }
        report["rules"][key] = {}
        for name,(predicate,fields) in hypotheses.items():
            known = book.drop_nulls(fields)
            kept,removed = known.filter(predicate),known.filter(~predicate)
            winners = known.filter(pl.col("r10_open")>=.2)
            report["rules"][key][name] = {"known_rows":known.height,"unknown_rows":book.height-known.height,"retained":kept.height/known.height,
                "winner_retention":kept.filter(pl.col("r10_open")>=.2).height/winners.height if winners.height else None,
                "kept":summaries(kept),"removed":summaries(removed),"paired":{str(h):paired(known,predicate,h) for h in HORIZONS},
                "kept_excess_ci":{str(h):excess_ci(kept,h) for h in HORIZONS},"annual_kept":yearly(kept),
                "annual_paired":{y:{str(h):paired(known.filter(pl.col("year")==y),predicate,h) for h in (1,3,10)} for y in sorted(known["year"].unique().to_list())},
                "nonlimit_kept":summaries(kept.filter(pl.col("limit_state")=="other")),
                "nonlimit_excess_ci":{str(h):excess_ci(kept.filter(pl.col("limit_state")=="other"),h) for h in HORIZONS},
                "nonlimit_annual":yearly(kept.filter(pl.col("limit_state")=="other")),
                "nonlimit_paired":{str(h):paired(known.filter(pl.col("limit_state")=="other"),predicate,h) for h in HORIZONS}}
        # Follow-up diagnostics selected after the first coarse tables: not holdouts.
        diagnostic_groups={
            "quiet_giant_volume":((pl.col("pre_quiet5")<.8)&(pl.col("volume_ratio")>=3),["pre_quiet5","volume_ratio"]),
            "low_gap_1_3":(pl.col("gap").is_between(-.03,-.01,closed="left"),["gap"]),
            "long_upper_wick":(pl.col("wick_band")=="50%+",["upper_wick"]),
            "one_spike_mid_volume":((pl.col("pre_spikes20")==1)&pl.col("volume_ratio").is_between(1.5,3,closed="left"),["pre_spikes20","volume_ratio"]),
        }
        report["diagnostics"][key]={}
        for name,(predicate,fields) in diagnostic_groups.items():
            known=book.drop_nulls(fields)
            kept=known.filter(predicate)
            report["diagnostics"][key][name]={"selection":"post-table exploratory diagnostic","kept":summaries(kept),
                "excess_ci":{str(h):excess_ci(kept,h) for h in HORIZONS},"annual":yearly(kept),
                "nonlimit":summaries(kept.filter(pl.col("limit_state")=="other"))}
        mid=book.filter(pl.col("volume_band")=="1.5-3").drop_nulls(["pre_quiet5","gap"])
        report["diagnostics"][key]["quiet_increment_mid_volume"]={str(h):matched_difference(mid,pl.col("pre_quiet5")<.8,["gap_band","limit_state"],h) for h in HORIZONS}
        giant=book.filter(pl.col("volume_band")=="3+").drop_nulls(["pre_quiet5","gap"])
        report["diagnostics"][key]["quiet_increment_giant_volume"]={str(h):matched_difference(giant,pl.col("pre_quiet5")<.8,["gap_band","limit_state"],h) for h in HORIZONS}
        wick_known=book.drop_nulls(["upper_wick","volume_ratio","gap"])
        report["diagnostics"][key]["wick_increment"]={str(h):matched_difference(wick_known,pl.col("wick_band")=="50%+",["gap_band","volume_band","limit_state"],h) for h in HORIZONS}
        report["diagnostics"][key]["wick_increment_clear_high"]={str(h):matched_difference(wick_known,pl.col("wick_band")=="50%+",["gap_band","volume_band","limit_state","clear_high_band"],h) for h in HORIZONS}
        print(f"analyzed {key}: {book.height} events, {len(groups)} groups",flush=True)
    write_json(OUT/"analysis.json",report)
    write_results(report)
    return report


def write_results(report):
    def pct(v):
        return "—" if v is None else f"{v*100:.2f}"

    lines = ["# 突破池v2数值结果","","全部次日开盘起算。均值与超额日期等权。分位数按事件记录。定义见[v2协议](v2-protocol.md)。解读见[v2报告](v2-analysis.md)。","","| 窗口 | 分组 | 周期 | 收益% | 超额百分点 | 正收益率% | P10% | 事件/日期 |","| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for key,g in report["views"].items():
        for name,periods in g.items():
            for h,v in periods.items():
                lines.append(f"| {key} | {name} | {h} | {pct(v.get('mean'))} | {pct(v.get('excess'))} | {pct(v.get('positive'))} | {pct(v.get('p10_sample'))} | {v['n']}/{v['dates']} |")
    lines.extend(["","## 预设假设对照","","| 窗口 | 假设 | 周期 | 保留/赢家保留% | 保留超额百分点 | 超额95%区间 | 同日保留减剔除百分点 | 同日95%区间 | 保留事件/日期 |","| --- | --- | --- | --- | --- | --- | --- | --- | --- |"])
    for key,g in report["rules"].items():
        for name,r in g.items():
            for h,v in r["kept"].items():
                p=r["paired"][h]
                lines.append(f"| {key} | {name} | {h} | {pct(r['retained'])}/{pct(r['winner_retention'])} | {pct(v.get('excess'))} | {' / '.join(pct(x) for x in r['kept_excess_ci'][h])} | {pct(p.get('difference'))} | {' / '.join(pct(x) for x in p.get('block20_ci95',[]))} | {v['n']}/{v['dates']} |")
    lines.extend(["","## 已知非封板候选对照","","| 窗口 | 假设 | 周期 | 非封板保留超额百分点 | 95%区间 | 同日保留减剔除百分点 | 事件/日期 |","| --- | --- | --- | --- | --- | --- | --- |"])
    for key,g in report["rules"].items():
        for name,r in g.items():
            for h,v in r["nonlimit_kept"].items():
                lines.append(f"| {key} | {name} | {h} | {pct(v.get('excess'))} | {' / '.join(pct(x) for x in r['nonlimit_excess_ci'][h])} | {pct(r['nonlimit_paired'][h].get('difference'))} | {v['n']}/{v['dates']} |")
    lines.extend(["","## 首次粗分层后追加的关联诊断","","这些组在查看粗分层后选出。属于事后探索。不能作为独立验证。","","| 窗口 | 分组 | 周期 | 超额百分点 | 95%区间 | 事件/日期 |","| --- | --- | --- | --- | --- | --- |"])
    for key,g in report["diagnostics"].items():
        for name,r in g.items():
            if "kept" not in r:
                continue
            for h,v in r["kept"].items():
                lines.append(f"| {key} | {name} | {h} | {pct(v.get('excess'))} | {' / '.join(pct(x) for x in r['excess_ci'][h])} | {v['n']}/{v['dates']} |")
    lines.extend(["","## 相近状态中的增量诊断","","每个同日状态格两侧至少各3条事件。格等权后日期等权。","","| 窗口 | 增量 | 周期 | 差值百分点 | 95%区间 | 日期/格 |","| --- | --- | --- | --- | --- | --- |"])
    for key,g in report["diagnostics"].items():
        for name,r in g.items():
            if "kept" in r:
                continue
            for h,v in r.items():
                lines.append(f"| {key} | {name} | {h} | {pct(v.get('difference'))} | {' / '.join(pct(x) for x in v['block20_ci95'])} | {v['dates']}/{v['cells']} |")
    (ROOT/"docs/research/stock-pools/breakthrough/v2-results.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def verify():
    """Independently rebuild sampled volume features and price paths from bars."""
    from research_popularity_pool import path_labels
    ledger=pl.read_parquet(OUT/"event-ledger.parquet")
    sample=pl.concat([ledger.filter(pl.col("window")==n).sort(pl.struct("symbol","date").hash(seed=n)).head(10) for n in WINDOWS])
    sample=pl.concat([sample,ledger.sort("date",descending=True).head(3)]).unique(subset=["symbol","date","window"])
    stocks=sample["symbol"].unique().to_list()
    prices=pl.scan_parquet(ROOT/"data/kline_daily_enriched/date=*/part.parquet").filter(pl.col("symbol").is_in(stocks)&(pl.col("date")<=pl.lit(END).str.to_date())).select("symbol","date","open","high","low","close","volume").collect()
    calendar=pl.read_parquet(BASE/"market-baseline.parquet")["date"].to_list()
    index={day:i for i,day in enumerate(calendar)}
    by_stock={s:{} for s in stocks}
    for bar in prices.to_dicts():
        by_stock[bar["symbol"]][index[bar["date"]]]=bar
    assertions=0
    for row in sample.to_dicts():
        bars=by_stock[row["symbol"]]
        i=row["idx"]

        def mean_volume(a,b,bars=bars):
            items=[bars.get(j) for j in range(a,b)]
            if not items or any(v is None or str(v["date"])<START for v in items):
                return None
            return float(np.mean([v["volume"] for v in items]))

        pre20=mean_volume(i-20,i)
        expected={"volume_ratio":bars[i]["volume"]/pre20 if pre20 else None,
            "gap":bars[i+1]["open"]/bars[i]["close"]-1 if i+1 in bars else None,
            "upper_wick":(bars[i]["high"]-bars[i]["close"])/(bars[i]["high"]-bars[i]["low"]) if bars[i]["high"]>bars[i]["low"] else None}
        for n in (5,10):
            recent,older=mean_volume(i-n,i),mean_volume(i-n-20,i-n)
            expected[f"pre_quiet{n}"]=recent/older if recent is not None and older else None
        spike_count=0
        for j in range(i-20,i):
            avg=mean_volume(j-20,j)
            if avg is None or j not in bars:
                spike_count=None
                break
            spike_count+=int(bars[j]["volume"]/avg>=2)
        expected["pre_spikes20"]=spike_count
        for n in (20,60):
            expected[f"pre_return{n}"]=bars[i-1]["close"]/bars[i-n-1]["close"]-1 if all(j in bars for j in range(i-n-1,i+1)) else None
        for field,value in expected.items():
            assert (row[field] is None) if value is None else np.isclose(row[field],value,rtol=1e-10,atol=1e-10),(row["symbol"],row["date"],field)
            assertions+=1
        prior=[bars.get(j) for j in range(i-row["window"],i)]
        assert all(v is not None for v in prior)
        assert np.isclose(max(v["close"] for v in prior),row["breakthrough_level"],rtol=2e-6)
        assert np.isclose(max(v["high"] for v in prior),row["prior_high_threshold"],rtol=1e-10)
        assertions+=2
        for h in HORIZONS:
            future=[bars.get(j) for j in range(i+1,i+h+1)]
            label=path_labels(future) if all(v is not None for v in future) else None
            if label is None:
                assert row[f"r{h}_open"] is None
                assertions+=1
            else:
                for field,key in ((f"r{h}_open","return"),(f"mfe{h}","mfe"),(f"mae{h}","mae")):
                    assert np.isclose(row[field],label[key],atol=2e-6)
                    assertions+=1
    report={"status":"passed","samples":sample.height,"assertions":assertions,"checks":"prior-volume causality; market gaps; next-open price labels; inherited threshold","label_tolerance":2e-6}
    write_json(OUT/"verification.json",report)
    return report


def main():
    started=time.monotonic()
    analyze(build())
    print(verify(),flush=True)
    print(f"BREAKTHROUGH_CONFIRMATION_OK elapsed={time.monotonic()-started:.1f}s",flush=True)


if __name__=="__main__":
    main()
