"""Full-history breakthrough candidate study, without trade execution.

Run from backend: uv run --frozen python ../scripts/research_breakthrough_pool.py
"""
import json
import time
from pathlib import Path

import numpy as np
import polars as pl
from research_popularity_pool import HORIZONS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/stock-pools/breakthrough/v1"
WINDOWS = (60, 100, 250)
START = "2016-01-04"
END = "2026-09-11"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def rolling_features(frame):
    """Strict prior market-session windows, excluding the observation day."""
    exprs = []
    for n in WINDOWS:
        for field in ("close", "high"):
            exprs.append(pl.col(field).shift(1).rolling_max(n, min_samples=n).over("symbol").alias(f"prior_{field}{n}"))
        exprs.append((pl.col("idx")-pl.col("idx").shift(n).over("symbol")==n).fill_null(False).alias(f"complete{n}"))
    for n in (10, 20, 60):
        exprs.extend([
            pl.col("close").rolling_mean(n,min_samples=n).over("symbol").alias(f"ma{n}"),
            (pl.col("idx")-pl.col("idx").shift(n-1).over("symbol")==n-1).fill_null(False).alias(f"ma_complete{n}"),
        ])
    exprs.extend([
        pl.col("high").shift(1).rolling_max(20,min_samples=20).over("symbol").alias("prior_high20"),
        pl.col("low").shift(1).rolling_min(20,min_samples=20).over("symbol").alias("prior_low20"),
        pl.when(pl.col("date")>=pl.lit(START).str.to_date()).then(pl.col("volume")).otherwise(None)
        .shift(1).rolling_mean(20,min_samples=20).over("symbol").alias("prior_volume20"),
        (pl.col("idx")-pl.col("idx").shift(20).over("symbol")==20).fill_null(False).alias("complete20"),
        pl.col("close").shift(20).over("symbol").alias("close20ago"),
    ])
    result = frame.with_columns(exprs)
    # Rolling means must not compress suspensions into adjacent market days.
    result = result.with_columns([
        pl.when(pl.col(f"ma_complete{n}")).then(pl.col(f"ma{n}")).otherwise(None).alias(f"ma{n}") for n in (10,20,60)
    ])
    result = result.with_columns([
        pl.when(pl.col(f"complete{n}")).then(pl.col(f"prior_{field}{n}")).otherwise(None).alias(f"prior_{field}{n}")
        for n in WINDOWS for field in ("close","high")
    ])
    result = result.with_columns([
        pl.col("ma20").shift(5).over("symbol").alias("ma20prev5"),
        pl.when(pl.col("complete20")).then(pl.col("prior_high20")/pl.col("prior_low20")-1).alias("width20"),
        pl.when(pl.col("complete20") & (pl.col("prior_volume20")>0)).then(pl.col("volume")/pl.col("prior_volume20")).alias("volume_ratio"),
        pl.when(pl.col("complete20")).then(pl.col("close")/pl.col("close20ago")-1).alias("return20past"),
    ])
    return result


def episodes(breakout, threshold, close, volume_ratio, max_age=19):
    """Consecutive breakthrough days share an episode; last breakout renews age."""
    shape = breakout.shape
    last = np.full(shape[1], -1000, dtype=np.int32)
    start = last.copy()
    level = np.full(shape[1], np.nan, dtype=np.float32)
    event_volume = level.copy()
    age = np.full(shape,-1,dtype=np.int16)
    starts = np.full(shape,-1,dtype=np.int32)
    levels = np.full(shape,np.nan,dtype=np.float32)
    volumes = levels.copy()
    previous = np.zeros(shape[1],dtype=bool)
    for i in range(shape[0]):
        hit = breakout[i]
        fresh = hit & ~previous
        start[fresh] = i
        level[fresh] = threshold[i,fresh]
        event_volume[fresh] = volume_ratio[i,fresh]
        last[hit] = i
        active = (i-last<=max_age) & (last>=0)
        age[i,active] = i-last[active]
        starts[i,active] = start[active]
        levels[i,active] = level[active]
        volumes[i,active] = event_volume[active]
        previous = hit
    return age, starts, levels, volumes


def future_labels(open_, high, low, close):
    """Dense market-session labels; never consume signal close as the anchor."""
    t, s = close.shape
    anchor = np.full((t,s),np.nan,dtype=np.float32)
    anchor[:-1] = open_[1:]
    valid = np.isfinite(anchor) & (anchor>0)
    maxhigh = np.full_like(anchor,-np.inf)
    minlow = np.full_like(anchor,np.inf)
    peak = np.zeros((t,s),dtype=np.int8)
    trough = peak.copy()
    outputs = {}
    for h in range(1,max(HORIZONS)+1):
        hi, lo, terminal = np.full_like(anchor,np.nan), np.full_like(anchor,np.nan), np.full_like(anchor,np.nan)
        hi[:-h],lo[:-h],terminal[:-h] = high[h:],low[h:],close[h:]
        nextopen = np.full_like(anchor,np.nan)
        nextopen[:-h] = open_[h:]
        valid &= np.isfinite(hi) & (hi>0) & np.isfinite(lo) & (lo>0) & np.isfinite(terminal) & (terminal>0) & np.isfinite(nextopen) & (nextopen>0)
        peak[hi>maxhigh] = h
        trough[lo<minlow] = h
        maxhigh = np.fmax(maxhigh,hi)
        minlow = np.fmin(minlow,lo)
        if h in HORIZONS:
            with np.errstate(invalid="ignore",divide="ignore"):
                outputs[h] = {"return":np.where(valid,terminal/anchor-1,np.nan),
                              "mfe":np.where(valid,maxhigh/anchor-1,np.nan),
                              "mae":np.where(valid,minlow/anchor-1,np.nan),
                              "peak":np.where(valid,peak,0),
                              "path":np.where(valid,np.sign(peak-trough),0).astype(np.int8)}
    return outputs


def stat(frame, h):
    key = f"r{h}_open"
    valid = frame.filter(pl.col(key).is_not_null() & pl.col(key).is_finite())
    if not valid.height:
        return {"n":0,"dates":0}
    daily = valid.group_by("date").agg(
        pl.col(key).mean().alias("r"),
        (pl.col(key)-pl.col(f"market{h}_open")).mean().alias("excess"),
        (pl.col(key)>0).mean().alias("positive"),
        pl.col(f"mfe{h}").mean(),pl.col(f"mae{h}").mean(),
        pl.col(f"peak_day{h}").mean(),(pl.col(f"path{h}")==1).mean().alias("low_first"),
    )
    values = valid[key]
    wins,losses = values.filter(values>0),values.filter(values<0)
    return {"n":valid.height,"dates":daily.height,"stocks":valid["symbol"].n_unique(),
            "mean":daily["r"].mean(),"excess":daily["excess"].mean(),"positive":daily["positive"].mean(),
            "median_sample":values.median(),"p10_sample":values.quantile(.1,interpolation="linear"),
            "avg_win_sample":wins.mean(),"avg_loss_sample":losses.mean(),
            "mfe":daily[f"mfe{h}"].mean(),"mae":daily[f"mae{h}"].mean(),
            "peak_day":daily[f"peak_day{h}"].mean(),"low_first":daily["low_first"].mean()}


def paired(frame, predicate, h=10):
    key = f"r{h}_open"
    good = frame.filter(pl.col(key).is_not_null())
    a = good.filter(predicate).group_by("date").agg(pl.col(key).mean().alias("a"))
    b = good.filter(~predicate).group_by("date").agg(pl.col(key).mean().alias("b"))
    both = a.join(b,on="date").sort("date")
    if not both.height:
        return {"dates":0}
    values = (both["a"]-both["b"]).to_numpy()
    block = min(20,len(values))
    rng = np.random.default_rng(20260913)
    starts = rng.integers(0,len(values)-block+1,size=(500,int(np.ceil(len(values)/block))))
    samples = values[(starts[...,None]+np.arange(block)).reshape(500,-1)[:,:len(values)]].mean(axis=1)
    return {"dates":len(values),"difference":float(values.mean()),"positive_dates":float(np.mean(values>0)),
            "block20_ci95":np.quantile(samples,[.025,.975]).tolist()}


def summaries(frame):
    """Aggregate all fixed horizons together, retaining per-horizon maturity."""
    daily_expr, sample_expr = [], []
    for h in HORIZONS:
        r = pl.col(f"r{h}_open")
        valid = r.is_not_null()
        daily_expr.extend([
            r.count().alias(f"n{h}"), r.mean().alias(f"mean{h}"),
            (r-pl.col(f"market{h}_open")).mean().alias(f"excess{h}"),
            (r>0).mean().alias(f"positive{h}"),
            *[pl.col(f"{prefix}{h}").filter(valid).mean().alias(f"{prefix}{h}") for prefix in ("mfe","mae","peak_day")],
            (pl.col(f"path{h}")==1).filter(valid).mean().alias(f"low_first{h}"),
        ])
        sample_expr.extend([
            r.count().alias(f"n{h}"), pl.col("symbol").filter(valid).n_unique().alias(f"stocks{h}"),
            r.median().alias(f"median{h}"), r.quantile(.1,interpolation="linear").alias(f"p10{h}"),
            r.filter(r>0).mean().alias(f"win{h}"), r.filter(r<0).mean().alias(f"loss{h}"),
        ])
    daily = frame.group_by("date").agg(daily_expr)
    sample = frame.select(sample_expr).row(0,named=True)
    result = {}
    for h in HORIZONS:
        d = daily.filter(pl.col(f"n{h}")>0)
        result[str(h)] = {"n":sample[f"n{h}"],"dates":d.height}
        if not d.height:
            continue
        result[str(h)].update({"stocks":sample[f"stocks{h}"],
            **{name:d[f"{name}{h}"].mean() for name in ("mean","excess","positive","mfe","mae","peak_day","low_first")},
            "median_sample":sample[f"median{h}"],"p10_sample":sample[f"p10{h}"],
            "avg_win_sample":sample[f"win{h}"],"avg_loss_sample":sample[f"loss{h}"]})
    return result


def categorize(frame):
    return frame.with_columns([
        pl.col("date").dt.year().cast(pl.String).alias("year"),
        pl.when(pl.col("volume_ratio").is_null()).then(pl.lit("unknown"))
        .when(pl.col("volume_ratio")<.8).then(pl.lit("<0.8"))
        .when(pl.col("volume_ratio")<1.5).then(pl.lit("0.8-1.5"))
        .when(pl.col("volume_ratio")<3).then(pl.lit("1.5-3"))
        .otherwise(pl.lit("3+")).alias("volume_band"),
        pl.when(pl.col("width20").is_null()).then(pl.lit("unknown"))
        .when(pl.col("width20")<.1).then(pl.lit("<10%"))
        .when(pl.col("width20")<.2).then(pl.lit("10-20%"))
        .when(pl.col("width20")<.4).then(pl.lit("20-40%"))
        .otherwise(pl.lit("40%+")).alias("width_band"),
        pl.when(pl.col("ma20").is_null()|pl.col("ma20prev5").is_null()|pl.col("close").is_null()).then(pl.lit("unknown"))
        .when((pl.col("close")>=pl.col("ma20")) & (pl.col("ma20")>pl.col("ma20prev5"))).then(pl.lit("healthy"))
        .when((pl.col("close")<pl.col("ma20")) & (pl.col("ma20")<=pl.col("ma20prev5"))).then(pl.lit("weak"))
        .otherwise(pl.lit("mixed")).alias("trend"),
        pl.when(pl.col("close").is_null()|pl.col("ma20").is_null()).then(pl.lit("unknown"))
        .when(pl.col("close")/pl.col("ma20")-1<0).then(pl.lit("below_ma20"))
        .when(pl.col("close")/pl.col("ma20")-1<.05).then(pl.lit("0-5%"))
        .when(pl.col("close")/pl.col("ma20")-1<.15).then(pl.lit("5-15%"))
        .otherwise(pl.lit("15%+")).alias("ma20_distance"),
        pl.when(pl.col("limit_up").is_null()).then(pl.lit("unknown"))
        .when(pl.col("limit_up")>0).then(pl.lit("closed_limit"))
        .otherwise(pl.lit("other")).alias("limit_state"),
    ])


def view(frame, basis, window):
    suffix = f"{basis}{window}"
    return frame.filter(pl.col(f"age_{suffix}")>=0).with_columns([
        pl.col(f"age_{suffix}").alias("age"),
        (pl.col("idx")-pl.col(f"start_{suffix}")).alias("episode_age"),
        pl.when(pl.col("close").is_null()).then(pl.lit("unknown"))
        .when(pl.col("close")>=pl.col(f"level_{suffix}")).then(pl.lit("above_level"))
        .otherwise(pl.lit("below_level")).alias("position"),
        pl.col(f"event_volume_{suffix}").alias("event_volume_ratio"),
        (pl.col("idx")==pl.col(f"start_{suffix}")).alias("event_start"),
        pl.lit(basis).alias("basis"),pl.lit(window).alias("window"),
    ]).with_columns([
        pl.when(pl.col("age")==0).then(pl.lit("0"))
        .when(pl.col("age")<=3).then(pl.lit("1-3"))
        .when(pl.col("age")<=5).then(pl.lit("4-5"))
        .when(pl.col("age")<=10).then(pl.lit("6-10"))
        .otherwise(pl.lit("11-19")).alias("age_band"),
    ])


def build_samples():
    OUT.mkdir(parents=True,exist_ok=True)
    parts = OUT / "parts"
    parts.mkdir(exist_ok=True)
    paths = sorted((ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet"))
    paths = [p for p in paths if p.parent.name<=f"date={END}"]
    scan = pl.scan_parquet(paths)
    dates = sorted(scan.select("date").unique().collect()["date"].to_list())
    # Independent SSE calendar check; use observed future September sessions only
    # after the historical calendar snapshot's upper bound.
    calendar_snapshot = json.loads((ROOT / "data/research/calendar-20150101-20260907.json").read_text(encoding="utf-8"))
    expected = {date_string(r["cal_date"]) for r in calendar_snapshot["payload"]["trade_calendar"]["records"]
                if r["exchange"]=="SSE" and r["is_open"]==1 and "20150105"<=r["cal_date"]<="20260907"}
    observed = {str(d) for d in dates if str(d)<= "2026-09-07"}
    if expected!=observed:
        raise ValueError(f"Calendar mismatch: missing={sorted(expected-observed)}, extra={sorted(observed-expected)}")
    symbols = sorted(scan.select("symbol").unique().collect()["symbol"].to_list())
    calendar = pl.DataFrame({"date":dates,"idx":np.arange(len(dates),dtype=np.int32)})
    market_sums = {h:np.zeros(len(dates),dtype=np.float64) for h in HORIZONS}
    market_counts = {h:np.zeros(len(dates),dtype=np.int64) for h in HORIZONS}
    environment_sum,environment_count = np.zeros(len(dates)),np.zeros(len(dates),dtype=np.int64)
    diffusion = {n:np.zeros(len(dates),dtype=np.int64) for n in WINDOWS}
    eligible = {n:np.zeros(len(dates),dtype=np.int64) for n in WINDOWS}
    total, mismatch, invalid_ohlc = 0,0,0
    source_rows = []
    first,last = [],[]
    start_idx = np.searchsorted(np.array(dates,dtype="datetime64[D]"),np.datetime64(START))
    for batch,beg in enumerate(range(0,len(symbols),300)):
        selected = symbols[beg:beg+300]
        frame = scan.filter(pl.col("symbol").is_in(selected)).select("symbol","date","open","high","low","close","volume","raw_close","raw_high","raw_low","consecutive_limit_ups").collect().join(calendar,on="date").sort("symbol","date")
        total += frame.height
        if frame.select(pl.struct("symbol","date").n_unique()).item()!=frame.height:
            raise ValueError("Duplicated stock/date prices")
        sanity = frame.select(((pl.col("high")<pl.col("low")) | (pl.col("high")<pl.col("close")-.0001) | (pl.col("low")>pl.col("close")+.0001) | (pl.col("high")<pl.col("open")-.0001) | (pl.col("low")>pl.col("open")+.0001)).sum()).item()
        invalid_ohlc += sanity
        mismatch += frame.select((((pl.col("high")/pl.col("raw_high")-pl.col("close")/pl.col("raw_close")).abs()>1e-5) | ((pl.col("low")/pl.col("raw_low")-pl.col("close")/pl.col("raw_close")).abs()>1e-5)).sum()).item()
        if sanity or mismatch:
            raise ValueError("OHLC or within-bar adjustment factors inconsistent")
        spans = frame.group_by("symbol").agg(pl.col("date").min().alias("first"),pl.col("date").max().alias("last"),pl.len().alias("bars"))
        source_rows.extend([{**r,"first":str(r["first"]),"last":str(r["last"])} for r in spans.to_dicts()])
        first.extend(spans["first"].to_list())
        last.extend(spans["last"].to_list())
        frame = rolling_features(frame)
        mapping = {s:i for i,s in enumerate(selected)}
        row_idx = frame["idx"].to_numpy()
        col_idx = frame["symbol"].replace_strict(mapping,return_dtype=pl.Int32).to_numpy()
        shape = (len(dates),len(selected))

        def dense(field, shape=shape, row_idx=row_idx, col_idx=col_idx, frame=frame):
            values = np.full(shape,np.nan,dtype=np.float32)
            values[row_idx,col_idx] = frame[field].to_numpy()
            return values

        open_,high,low,close = [dense(k) for k in ("open","high","low","close")]
        vol = dense("volume_ratio")
        meta = {}
        active = np.zeros(shape,dtype=bool)
        for basis in ("close","high"):
            values = close if basis=="close" else high
            for n in WINDOWS:
                threshold = dense(f"prior_{basis}{n}")
                hit = np.isfinite(values) & np.isfinite(threshold) & (values>threshold)
                if basis=="close":
                    diffusion[n] += hit.sum(axis=1)
                    eligible[n] += (np.isfinite(values)&np.isfinite(threshold)).sum(axis=1)
                age,starts,levels,volumes = episodes(hit,threshold,close,vol)
                suffix = f"{basis}{n}"
                meta.update({f"age_{suffix}":age,f"start_{suffix}":starts,f"level_{suffix}":levels,f"event_volume_{suffix}":volumes})
                active |= age>=0
        active[:start_idx] = False
        labels = future_labels(open_,high,low,close)
        past = dense("return20past")
        valid = np.isfinite(past)
        environment_sum += np.where(valid,past,0).sum(axis=1,dtype=np.float64)
        environment_count += valid.sum(axis=1)
        ti,si = np.nonzero(active)
        data = {"symbol":np.array(selected)[si],"date":np.array(dates,dtype="datetime64[D]")[ti],"idx":ti.astype(np.int32)}
        for k in ("close","ma10","ma20","ma60","ma20prev5","width20","volume_ratio"):
            data[k] = dense(k)[ti,si]
        data["limit_up"] = dense("consecutive_limit_ups")[ti,si]
        data.update({k:v[ti,si] for k,v in meta.items()})
        for h,v in labels.items():
            valid = np.isfinite(v["return"]) & np.isfinite(close) & (close>0)
            market_sums[h] += np.where(valid,v["return"],0).sum(axis=1,dtype=np.float64)
            market_counts[h] += valid.sum(axis=1)
            data.update({f"r{h}_open":v["return"][ti,si],f"mfe{h}":v["mfe"][ti,si],f"mae{h}":v["mae"][ti,si],f"peak_day{h}":v["peak"][ti,si],f"path{h}":v["path"][ti,si]})
        pl.DataFrame(data).with_columns(pl.col(pl.Float32).fill_nan(None)).write_parquet(parts/f"part-{batch:03d}.parquet")
        print(f"samples batch {batch+1}: {beg+len(selected)}/{len(symbols)} stocks, {len(ti)} members",flush=True)
    market = {"date":dates}
    for h in HORIZONS:
        market[f"market{h}_open"] = np.divide(market_sums[h],market_counts[h],out=np.full(len(dates),np.nan),where=market_counts[h]>0)
        market[f"market_count{h}"] = market_counts[h]
    env = np.divide(environment_sum,environment_count,out=np.full(len(dates),np.nan),where=environment_count>0)
    market["environment"] = np.where(np.isnan(env),"unknown",np.where(env>0,"positive20","nonpositive20"))
    for n in WINDOWS:
        market[f"diffusion{n}"] = np.divide(diffusion[n],eligible[n],out=np.full(len(dates),np.nan),where=eligible[n]>0)
        market[f"eligible{n}"] = eligible[n]
    market_frame = pl.DataFrame(market).with_columns(pl.col(pl.Float64).fill_nan(None))
    market_frame.write_parquet(OUT/"market-baseline.parquet")
    pl.scan_parquet(parts/"*.parquet").join(market_frame.lazy(),on="date").sink_parquet(OUT/"daily-ledger.parquet")
    coverage = {"price_first":str(dates[0]),"price_last":str(dates[-1]),"sessions":len(dates),"rows":total,"stocks":len(symbols),
                "signal_first":START,"signal_last":END,"calendar_checked_through":"2026-09-07","later_calendar":"observed_all_market_daily_sessions",
                "ohlc_invalid":invalid_ohlc,"adjustment_bar_mismatch":mismatch,"strict_full_market_session_warmup":True,
                "volume_before_2016":"excluded from factor warmup", "historical_listing_universe":"cached symbols; completeness and delisted coverage unverified",
                "symbols_ending_before_price_end":sum(str(d)<END for d in last)}
    write_json(OUT/"coverage.json",coverage)
    write_json(OUT/"security-coverage.json",source_rows)
    return coverage


def date_string(value):
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def analyze(coverage):
    frame = categorize(pl.read_parquet(OUT/"daily-ledger.parquet"))
    report = {"protocol":"breakthrough-v1", "scope":"exploration, no independent validation or trade execution",
              "entry_basis":"next_session_open","horizons":list(HORIZONS),"coverage":coverage,"views":{},"rules":{},"heat":{}}
    events = []
    for basis in ("close","high"):
        for n in WINDOWS:
            book = view(frame,basis,n)
            key = f"{basis}{n}"
            groups = {"all":pl.col("idx")>=0,"events":pl.col("event_start")}
            for factor in ("age_band","volume_band","width_band","trend","position","ma20_distance","limit_state","environment","year"):
                for value in sorted(book[factor].unique().to_list()):
                    groups[f"{factor}:{value}"] = pl.col(factor)==value
            # Only the mechanism-motivated interaction: volume versus trend health.
            for volume in ("<0.8","0.8-1.5","1.5-3","3+"):
                groups[f"volume_trend:{volume}:healthy"] = (pl.col("volume_band")==volume)&(pl.col("trend")=="healthy")
            report["views"][key] = {}
            statistics = book.select("symbol","date",*[c for c in book.columns if c.startswith(("r1_","r2_","r3_","r5_","r10_","r20_","market","mfe","mae","peak_day","path"))])
            for name,predicate in groups.items():
                selection = statistics.filter(book.select(predicate.alias("selected"))["selected"])
                report["views"][key][name] = summaries(selection)
            episode_book = book.filter(pl.col("event_start"))
            sizes = book.group_by("date").len()
            report.setdefault("size",{})[key] = {"rows":book.height,"stocks":book["symbol"].n_unique(),"dates":sizes.height,
                                                   "daily_median":sizes["len"].median(),"daily_p90":sizes["len"].quantile(.9),
                                                   "events":episode_book.height,"episode_age_median":book["episode_age"].median()}
            if basis=="close":
                report["rules"][key] = {}
                predicates = {"age0_10":pl.col("age")<=10,"age0_5":pl.col("age")<=5,
                              "above_level":pl.col("position")=="above_level","healthy_trend":pl.col("trend")=="healthy",
                              "moderate_volume":pl.col("volume_band")=="0.8-1.5"}
                for name,predicate in predicates.items():
                    known = {"above_level":pl.col("position")!="unknown","healthy_trend":pl.col("trend")!="unknown",
                             "moderate_volume":pl.col("volume_band")!="unknown"}.get(name,pl.col("age")>=0)
                    eligible_book = book.filter(known)
                    kept,removed = eligible_book.filter(predicate),eligible_book.filter(~predicate)
                    winners = eligible_book.filter(pl.col("r10_open")>=.2)
                    report["rules"][key][name] = {"retained":kept.height/book.height,"winner_rows":winners.height,
                        "known_rows":eligible_book.height,"unknown_rows":book.height-eligible_book.height,
                        "winner_retention":winners.filter(predicate).height/winners.height if winners.height else None,
                        "kept":{str(h):stat(kept,h) for h in HORIZONS},"removed":{str(h):stat(removed,h) for h in HORIZONS},
                        "paired":{str(h):paired(eligible_book,predicate,h) for h in HORIZONS},
                        "yearly":{year:{"kept":stat(kept.filter(pl.col("year")==year),10),"removed":stat(removed.filter(pl.col("year")==year),10)} for year in sorted(book["year"].unique().to_list())}}
            event_book = episode_book.select("symbol","date","basis","window","episode_age","volume_ratio","width20",pl.col(f"level_{basis}{n}").alias("breakthrough_level"),*[c for c in book.columns if c.startswith(("r1_","r2_","r3_","r5_","r10_","r20_","mfe","mae","peak_day","path"))])
            events.append(event_book)
            print(f"analyzed {key}: {book.height} members, {episode_book.height} episodes",flush=True)
    pl.concat(events).write_parquet(OUT/"event-ledger.parquet")
    union = frame.filter(pl.any_horizontal([pl.col(f"age_close{n}")>=0 for n in WINDOWS]))
    report["union"] = {str(h):stat(union,h) for h in HORIZONS}
    sizes = union.group_by("date").len()
    report["union_size"] = {"rows":union.height,"stocks":union["symbol"].n_unique(),"dates":sizes.height,"daily_median":sizes["len"].median(),"daily_p90":sizes["len"].quantile(.9)}
    heat_path = ROOT / "data/research/stock-pools/popularity/v2/daily-ledger.parquet"
    if heat_path.exists():
        heat = pl.read_parquet(heat_path).select(pl.col("date").str.to_date(),"symbol","source","band","direction")
        for source in sorted(heat["source"].unique().to_list()):
            source_heat = heat.filter(pl.col("source")==source).select("date","symbol",pl.col("band").alias("heat_band"),pl.col("direction").alias("heat_direction"))
            heat_dates = source_heat["date"].unique()
            for n in WINDOWS:
                book = view(frame,"close",n).filter(pl.col("date").is_in(heat_dates.implode())).join(source_heat,on=["date","symbol"],how="left").with_columns(pl.col("heat_band").fill_null("observed_outside"))
                groups = {"all":book}
                for value in sorted(book["heat_band"].unique().to_list()):
                    groups[value] = book.filter(pl.col("heat_band")==value)
                result = {name:{str(h):stat(b,h) for h in HORIZONS} for name,b in groups.items()}
                # Hold current age, trend and limit state fixed in each same-day contrast.
                by = ["date","age_band","trend","limit_state"]
                for h in HORIZONS:
                    valid = book.filter(pl.col(f"r{h}_open").is_not_null()).with_columns((pl.col("heat_band")!="observed_outside").alias("hot"))
                    cells = valid.group_by(*by,"hot").agg(pl.col(f"r{h}_open").mean().alias("mean"),pl.len().alias("n"))
                    a,b = cells.filter(pl.col("hot")),cells.filter(~pl.col("hot"))
                    matched = a.join(b,on=by,suffix="_outside").with_columns((pl.col("mean")-pl.col("mean_outside")).alias("difference"))
                    daily = matched.group_by("date").agg(pl.col("difference").mean())
                    result[f"matched{h}"] = {"cells":matched.height,"dates":daily.height,"hot_minus_outside":daily["difference"].mean()}
                report["heat"][f"{source}_close{n}"] = result
    write_json(OUT/"analysis.json",report)
    write_results(report)
    return report


def write_results(report):
    lines = ["# 突破池v1数值结果", "", "脚本生成。解读与协议见[分析报告](v1-analysis.md)。全部未来收益与路径空间从次日开盘起算。mean/excess为日期等权;P10为成员口径。", ""]

    def pct(value):
        return "—" if value is None else f"{value*100:.2f}"

    def table(title,headers,rows):
        lines.extend([f"## {title}","","| "+" | ".join(headers)+" |","| "+" | ".join(["---"]*len(headers))+" |"])
        lines.extend("| "+" | ".join(str(v) for v in row)+" |" for row in rows)
        lines.append("")

    table("基础池规模",["口径/窗口","成员","股票","日期","日规模中位数/P90","事件"],[[key,v["rows"],v["stocks"],v["dates"],f'{v["daily_median"]}/{v["daily_p90"]}',v["events"]] for key,v in report["size"].items()])
    table("各窗口与事件基线",["视角","账本","周期","收益%","超额百分点","正收益率%","P10%","成员/日期","最大上涨/下探%"],[[key,kind,h,pct(v.get("mean")),pct(v.get("excess")),pct(v.get("positive")),pct(v.get("p10_sample")),f'{v["n"]}/{v["dates"]}',f'{pct(v.get("mfe"))}/{pct(v.get("mae"))}'] for key,g in report["views"].items() for kind in ("all","events") for h,v in g[kind].items()])
    table("全部分层",["视角","分层","周期","收益%","超额百分点","P10%","成员/日期"],[[key,k,h,pct(v.get("mean")),pct(v.get("excess")),pct(v.get("p10_sample")),f'{v["n"]}/{v["dates"]}'] for key,g in report["views"].items() for k,periods in g.items() if k not in ("all","events") for h,v in periods.items()])
    table("拟条件质量与机会损失",["视角","规则","保留%","保留/剔除10日收益%","保留/剔除P10%","10日大赢家保留%"],[[key,k,pct(v["retained"]),f'{pct(v["kept"]["10"].get("mean"))}/{pct(v["removed"]["10"].get("mean"))}',f'{pct(v["kept"]["10"].get("p10_sample"))}/{pct(v["removed"]["10"].get("p10_sample"))}',pct(v["winner_retention"])] for key,g in report["rules"].items() for k,v in g.items()])
    table("同日条件对照",["视角","规则","周期","保留减剔除百分点","共同日期","20日期块95%区间"],[[key,k,h,pct(v.get("difference")),v["dates"]," / ".join(pct(x) for x in v.get("block20_ci95",[]))] for key,g in report["rules"].items() for k,r in g.items() for h,v in r["paired"].items()])
    table("热度共同期对照",["来源/窗口","组","周期","收益%","超额百分点","成员/日期"],[[key,k,h,pct(v.get("mean")),pct(v.get("excess")),f'{v["n"]}/{v["dates"]}'] for key,g in report["heat"].items() for k,p in g.items() if not k.startswith("matched") for h,v in p.items()])
    table("热度同日相近状态增量",["来源/窗口","周期","榜内减已观测榜外百分点","共同日期/分层格"],[[key,k,pct(v["hot_minus_outside"]),f'{v["dates"]}/{v["cells"]}'] for key,g in report["heat"].items() for k,v in g.items() if k.startswith("matched")])
    (ROOT/"docs/research/stock-pools/breakthrough/v1-results.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def verify_samples():
    """Audit stored labels against original bars, independently of dense code."""
    from research_popularity_pool import path_labels
    ledger = pl.scan_parquet(OUT/"daily-ledger.parquet")
    samples = []
    for basis in ("close","high"):
        for n in WINDOWS:
            rows = ledger.filter(pl.col(f"age_{basis}{n}")>=0).sort(pl.struct("date","symbol").hash(seed=n)).head(5).collect().to_dicts()
            samples.extend((basis,n,row) for row in rows)
    factor_symbols = ["000001.SZ","600519.SH","300750.SZ","000002.SZ","601318.SH"]
    symbols = sorted({r["symbol"] for _,_,r in samples}|set(factor_symbols))
    prices = pl.scan_parquet(ROOT/"data/kline_daily_enriched/date=*/part.parquet").filter(pl.col("symbol").is_in(symbols)&(pl.col("date")<=pl.lit(END).str.to_date())).select("symbol","date","open","high","low","close","raw_close").collect()
    dates = pl.read_parquet(OUT/"market-baseline.parquet")["date"].to_list()
    index = {d:i for i,d in enumerate(dates)}
    by_stock = {s:{} for s in symbols}
    for bar in prices.to_dicts():
        by_stock[bar["symbol"]][index[bar["date"]]] = bar
    assertions = 0
    for basis,n,row in samples:
        bars = by_stock[row["symbol"]]
        i = row["idx"]

        def is_breakout(j, bars=bars, n=n, basis=basis):
            if j not in bars or any(k not in bars for k in range(j-n,j)):
                return False
            return bars[j][basis]>max(bars[k][basis] for k in range(j-n,j))

        hits = [j for j in range(max(0,i-19),i+1) if is_breakout(j)]
        assert hits and i-hits[-1]==row[f"age_{basis}{n}"], (basis,n,row["symbol"],row["date"],"age")
        start = hits[-1]
        while start>0 and is_breakout(start-1):
            start -= 1
        assert start==row[f"start_{basis}{n}"]
        level = max(bars[k][basis] for k in range(start-n,start))
        assert np.isclose(level,row[f"level_{basis}{n}"],rtol=2e-6)
        assertions += 3
        for h in HORIZONS:
            future = [bars.get(j) for j in range(i+1,i+h+1)]
            expected = path_labels(future) if all(b is not None for b in future) else None
            if expected is None:
                assert row[f"r{h}_open"] is None
                assertions += 1
                continue
            for key,field in (("return",f"r{h}_open"),("mfe",f"mfe{h}"),("mae",f"mae{h}")):
                assert np.isclose(expected[key],row[field],atol=2e-6), (row["symbol"],row["date"],h,key)
                assertions += 1
            assert expected["peak_day"]==row[f"peak_day{h}"]
            assertions += 1
    factors = pl.read_parquet(ROOT/"data/adj_factor/all.parquet")
    factor_rows = 0
    for s in factor_symbols:
        bars = prices.filter(pl.col("symbol")==s).sort("date")
        fs = factors.filter(pl.col("symbol")==s).sort("trade_date")
        cumulative = np.concatenate([[1.],np.cumprod(fs["ex_factor"].to_numpy())])
        pos = np.searchsorted(fs["trade_date"].to_numpy(),bars["date"].to_numpy(),side="right")
        expected = cumulative[pos]/cumulative[-1]
        actual = bars["close"].to_numpy()/bars["raw_close"].to_numpy()
        assert np.allclose(actual,expected,atol=1e-5)
        factor_rows += bars.height
    result = {"samples":len(samples),"assertions":assertions,"windows":list(WINDOWS),"bases":["close","high"],"status":"passed","label_tolerance":2e-6,
        "cached_adjustment_reconstruction":{"symbols":factor_symbols,"rows":factor_rows,"mismatch":0}}
    write_json(OUT/"verification.json",result)
    return result


def supplemental_analysis():
    """Event volume, MA proximity and dated thematic context; same wide ledger."""
    from collections import defaultdict
    report = json.loads((OUT/"analysis.json").read_text(encoding="utf-8"))
    frame = categorize(pl.read_parquet(OUT/"daily-ledger.parquet"))
    report["supplement"] = {}
    report["membership"] = {}
    report["observation_sizes"] = {}
    thematic = []
    thematic_dates = []
    for member_path in sorted((ROOT/"data/theme_member_daily").glob("date=*/part.parquet")):
        day = member_path.parent.name.removeprefix("date=")
        limit_path = ROOT/f"data/limit_event_daily/date={day}/part.parquet"
        if day>END or not limit_path.exists():
            continue
        members = pl.read_parquet(member_path).to_dicts()
        limits = {r["symbol"].split(".")[0] for r in pl.read_parquet(limit_path).to_dicts() if r["event_type"]=="limit_up"}
        stocks, themes = defaultdict(set), defaultdict(set)
        for r in members:
            code = r["symbol"].split(".")[0]
            stocks[r["theme_id"]].add(code)
            themes[code].add(r["theme_id"])
        if not themes:
            continue
        thematic_dates.append(day)
        for code,ts in themes.items():
            count = max(len((stocks[t]&limits)-{code}) for t in ts)
            thematic.append({"date":day,"code":code,"theme_support":"peer_limit2+" if count>=2 else "peer_limit0-1"})
    theme_frame = pl.DataFrame(thematic).with_columns(pl.col("date").str.to_date()) if thematic else None
    report["theme_coverage"] = {"dates":len(thematic_dates),"first":min(thematic_dates) if thematic_dates else None,"last":max(thematic_dates) if thematic_dates else None,
        "definition":"maximum same-day limit-up peers across archived member themes, excluding self; partial membership not exhaustive industry coverage"}
    for n in WINDOWS:
        book = view(frame,"close",n)
        key = f"close{n}"
        event_volume = pl.col("event_volume_ratio")
        book = book.with_columns(pl.when(event_volume.is_null()).then(pl.lit("unknown"))
            .when(event_volume<.8).then(pl.lit("<0.8")).when(event_volume<1.5).then(pl.lit("0.8-1.5"))
            .when(event_volume<3).then(pl.lit("1.5-3")).otherwise(pl.lit("3+")).alias("event_volume_band"))
        result = {}
        members = book.select("symbol","date","idx").sort("symbol","idx").with_columns(
            (pl.col("idx").diff().over("symbol")!=1).fill_null(True).alias("new_member"))
        members = members.with_columns(pl.col("new_member").cum_sum().over("symbol").alias("run"))
        spells = members.group_by("symbol","run").agg(pl.len().alias("length"),pl.col("idx").max().alias("last_idx"))
        end_idx = frame["idx"].max()
        complete_spells = spells.filter(pl.col("last_idx")<end_idx)
        inflow = members.group_by("date").agg(pl.col("new_member").sum().alias("new_count"))
        report["membership"][key] = {"spells":spells.height,"completed":complete_spells.height,
            "right_censored":spells.height-complete_spells.height,"completed_length_median":complete_spells["length"].median(),
            "completed_length_p90":complete_spells["length"].quantile(.9),"daily_new_median":inflow["new_count"].median(),
            "daily_new_p90":inflow["new_count"].quantile(.9),"left_boundary":"2016 start may left-censor membership spells"}
        report["observation_sizes"][key] = {}
        for age in (0,5,10,19):
            chosen = book.filter(pl.col("age")<=age)
            sizes = chosen.group_by("date").len()
            report["observation_sizes"][key][str(age)] = {"rows":chosen.height,"dates":sizes.height,"daily_median":sizes["len"].median(),"daily_p90":sizes["len"].quantile(.9)}
        for name,expr in {"<1%":pl.col(f"diffusion{n}")<.01,"1-5%":pl.col(f"diffusion{n}").is_between(.01,.05,closed="left"),"5%+":pl.col(f"diffusion{n}")>=.05}.items():
            result[f"diffusion:{name}"] = summaries(book.filter(expr))
        for value in sorted(book["event_volume_band"].unique().to_list()):
            selected = book.filter(pl.col("event_volume_band")==value)
            result[f"event_volume:{value}"] = summaries(selected)
            result[f"event_volume_first:{value}"] = summaries(selected.filter(pl.col("event_start")))
        for ma in (10,20,60):
            distance = pl.col("close")/pl.col(f"ma{ma}")-1
            for name,expr in {"near3pct":distance.abs()<=.03,"above3pct":distance>.03,"below3pct":distance<-.03}.items():
                result[f"ma{ma}:{name}"] = summaries(book.filter(expr))
        # Sensitivity to the first year and broad calendar periods, not holdout tests.
        for name,expr in {"without2016":pl.col("year")!="2016","2016-2020":pl.col("year")<="2020",
                          "2021-2023":pl.col("year").is_between(pl.lit("2021"),pl.lit("2023")),"2024-2026":pl.col("year")>="2024"}.items():
            result[f"period:{name}"] = summaries(book.filter(expr))
        for name,predicate in {"reduced_volume":pl.col("volume_ratio")<.8,
            "near_ma20":(pl.col("close")/pl.col("ma20")-1).abs()<=.03,
            "no_closed_limit":pl.col("limit_state")=="other",
            "narrow_width":pl.col("width20")<.1}.items():
            # Missing values are not silently counted as a removed known condition.
            complete = book.filter((pl.col("limit_state")!="unknown") if name=="no_closed_limit" else predicate.is_not_null())
            kept,removed = complete.filter(predicate),complete.filter(~predicate)
            winners = complete.filter(pl.col("r10_open")>=.2)
            result[f"rule:{name}"] = {"known_rows":complete.height,"retained":kept.height/complete.height,
                "winner_retention":winners.filter(predicate).height/winners.height if winners.height else None,
                "kept":summaries(kept),"removed":summaries(removed),"paired":{str(h):paired(complete,predicate,h) for h in HORIZONS},
                "yearly_paired10":{year:paired(complete.filter(pl.col("year")==year),predicate,10) for year in sorted(complete["year"].unique().to_list())}}
        if theme_frame is not None:
            themed = book.filter(pl.col("date").is_in(theme_frame["date"].unique().implode())).with_columns(pl.col("symbol").str.split(".").list.first().alias("code")).join(theme_frame,on=["date","code"],how="left").with_columns(pl.col("theme_support").fill_null("unknown"))
            result["theme:all_common_dates"] = summaries(themed)
            for value in ("peer_limit2+","peer_limit0-1","unknown"):
                result[f"theme:{value}"] = summaries(themed.filter(pl.col("theme_support")==value))
            known = themed.filter(pl.col("theme_support")!="unknown")
            result["theme_paired"] = {str(h):paired(known,pl.col("theme_support")=="peer_limit2+",h) for h in HORIZONS}
        report["supplement"][key] = result
        print(f"supplement analyzed {key}",flush=True)
    write_json(OUT/"analysis.json",report)
    write_results(report)
    lines = ["# 突破池v1补充分层", "", "同一宽池账本的追加探索。全部次日开盘起算。数值为百分比或超额百分点。日期等权。", "", "| 窗口 | 分组 | 周期 | 收益% | 超额百分点 | P10% | 成员/日期 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for key,g in report["supplement"].items():
        for name,periods in g.items():
            if name.startswith("rule:") or name=="theme_paired":
                continue
            for h,v in periods.items():
                values = ["—" if v.get(f) is None else f"{v[f]*100:.2f}" for f in ("mean","excess","p10_sample")]
                lines.append(f"| {key} | {name} | {h} | {' | '.join(values)} | {v['n']}/{v['dates']} |")
    lines.extend(["", "## 追加条件同日对照", "", "| 窗口 | 条件 | 周期 | 保留减剔除百分点 | 日期 | 20日期块95%区间 | 保留/赢家保留% |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for key,g in report["supplement"].items():
        for name,v in g.items():
            if not name.startswith("rule:"):
                continue
            for h,p in v["paired"].items():
                ci = "/".join(f"{c*100:.2f}" for c in p.get("block20_ci95",[]))
                lines.append(f"| {key} | {name} | {h} | {p.get('difference',0)*100:.2f} | {p['dates']} | {ci} | {v['retained']*100:.1f}/{v['winner_retention']*100:.1f} |")
    (ROOT/"docs/research/stock-pools/breakthrough/v1-supplement-results.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return report


def main():
    started = time.monotonic()
    coverage = build_samples()
    analyze(coverage)
    supplemental_analysis()
    print(verify_samples(),flush=True)
    print(f"BREAKTHROUGH_RESEARCH_OK elapsed={time.monotonic()-started:.1f}s",flush=True)


if __name__=="__main__":
    main()
