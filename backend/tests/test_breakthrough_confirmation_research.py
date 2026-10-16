"""Prior-volume causality, next-session alignment and confirmation boundaries."""
import importlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest


@pytest.fixture
def research(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/"scripts"))
    return importlib.import_module("research_breakthrough_confirmation")


def prices(volume):
    n=len(volume)
    return pl.DataFrame({"symbol":["A"]*n,"idx":np.arange(n),
        "date":[date(2016,1,4)+timedelta(days=i) for i in range(n)],
        "open":[100.]*n,"high":[110.]*n,"low":[90.]*n,"close":[100.]*n,
        "volume":volume,"consecutive_limit_ups":[0]*n})


def test_quiet_period_uses_nonoverlapping_history_and_excludes_breakout(research):
    volume=[100.]*80
    volume[45:50]=[50.]*5
    volume[50]=1000.
    f=research.features(prices(volume)).filter(pl.col("idx")==50).row(0,named=True)
    assert f["pre_quiet5"]==pytest.approx(.5)
    assert f["volume_ratio"]==pytest.approx(1000/87.5)
    assert f["pre_spikes20"]==0
    volume[50:]=[99999.]*30
    changed=research.features(prices(volume)).filter(pl.col("idx")==50).row(0,named=True)
    for field in ("pre_quiet5","pre_quiet10","pre_spikes20","pre_return20","pre_return60"):
        assert changed[field]==f[field]


def test_historical_spike_uses_its_own_prior_mean(research):
    volume=[100.]*80
    volume[35]=300.
    volume[50]=1000.
    f=research.features(prices(volume))
    assert f.filter(pl.col("idx")==35)["volume_ratio"].item()==3
    assert f.filter(pl.col("idx")==50)["pre_spikes20"].item()==1
    assert f.filter(pl.col("idx")==51)["pre_spikes20"].item()==2


def test_historical_high_excludes_signal_high_and_requires_full_sessions(research):
    frame=prices([100.]*80).with_columns(pl.when(pl.col("idx")==60).then(999.).otherwise(pl.col("high")).alias("high"))
    f=research.features(frame)
    assert f.filter(pl.col("idx")==60)["prior_high60"].item()==110
    assert f.filter(pl.col("idx")==61)["prior_high60"].item()==999
    gap=research.features(frame.filter(pl.col("idx")!=30))
    assert gap.filter(pl.col("idx")==60)["prior_high60"].item() is None


def test_missing_market_session_is_not_skipped_for_gap_or_prior_volume(research):
    frame=prices([100.]*80).filter(pl.col("idx")!=51)
    f=research.features(frame)
    assert f.filter(pl.col("idx")==50)["gap"].item() is None
    assert f.filter(pl.col("idx")==52)["pre_quiet5"].item() is None
    assert f.filter(pl.col("idx")==52)["pre_spikes20"].item() is None


def test_gap_uses_next_open_and_old_volume_units_remain_unknown(research):
    frame=prices([100.]*80).with_columns(pl.when(pl.col("idx")==51).then(102.).otherwise(pl.col("open")).alias("open"))
    f=research.features(frame)
    assert f.filter(pl.col("idx")==50)["gap"].item()==pytest.approx(.02)
    assert f.filter(pl.col("idx")==79)["gap"].item() is None
    old=frame.with_columns((pl.col("date")-timedelta(days=365)).alias("date"))
    assert research.features(old)["volume_ratio"].null_count()==old.height


def test_missing_is_distinct_from_zero_spikes_and_fixed_band_edges(research):
    frame=pl.DataFrame({"gap":[None,-.04,-.02,0.,.02,.04,.06]})
    result=frame.select(research.band("gap",[-.03,-.01,.01,.03,.05],
        ["<-3%","-3--1%","-1-1%","1-3%","3-5%","5%+"]).alias("band"))
    assert result["band"].to_list()==["unknown","<-3%","-3--1%","-1-1%","1-3%","3-5%","5%+"]
    assert research.ci([])==[]
    assert research.ci([.01,.01])==[]
    assert research.ci([.01]*50)==pytest.approx([.01,.01])


def test_sparse_matched_dates_do_not_produce_false_precision(research):
    frame=pl.DataFrame({"date":["A"]*6,"group":[True]*3+[False]*3,
        "control":["same"]*6,"r1_open":[.2]*3+[.1]*3})
    result=research.matched_difference(frame,pl.col("group"),["control"],1)
    assert result["difference"]==pytest.approx(.1)
    assert result["dates"]==1
    assert result["block20_ci95"]==[]
    assert result["ci_status"]=="insufficient_dates"
    pair=research.paired(frame,pl.col("group"),1)
    assert pair["difference"]==pytest.approx(.1)
    assert pair["block20_ci95"]==[]
