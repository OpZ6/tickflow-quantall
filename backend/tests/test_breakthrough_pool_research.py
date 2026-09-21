"""Causality, calendar gaps, episode renewal and price-label checks."""
import importlib
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest


@pytest.fixture
def research(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("research_breakthrough_pool")


def test_new_high_excludes_today_and_requires_full_market_window(research):
    prices = np.arange(1,263,dtype=float)
    frame = pl.DataFrame({"symbol":["TEST"]*len(prices),
        "date":[date(2016,1,4)+timedelta(days=i) for i in range(len(prices))],
        "idx":np.arange(len(prices)),"close":prices,"high":prices+1,
        "low":prices-.5,"volume":[100.]*len(prices)})
    f = research.rolling_features(frame)
    assert f["prior_close60"][59] is None
    assert f["prior_close60"][60] == 60
    assert f["prior_close250"][250] == 250
    missing = research.rolling_features(frame.filter(pl.col("idx")!=200))
    assert missing.filter(pl.col("idx")==250)["prior_close60"].item() is None
    assert missing.filter(pl.col("idx")==261)["prior_close60"].item() == 261


def test_consecutive_new_highs_share_episode_and_last_hit_refreshes_age(research):
    hit = np.zeros((28,1),dtype=bool)
    hit[[0,1,2,7],0] = True
    levels = np.arange(28,dtype=float).reshape(-1,1)+100
    age,start,level,vol = research.episodes(hit,levels,levels,np.ones_like(levels))
    assert start[:3,0].tolist() == [0,0,0]
    assert age[:4,0].tolist() == [0,0,0,1]
    assert start[7,0] == 7
    assert level[6,0] == 100
    assert level[7,0] == 107
    assert age[26,0] == 19
    assert age[27,0] == -1
    assert vol[27,0] != vol[27,0]  # Expired state remains missing.


def test_next_open_labels_and_calendar_gap_do_not_skip_suspension(research):
    open_ = np.array([1,100,109,114]+[114]*20,dtype=float).reshape(-1,1)
    close = np.array([900,110,115,105]+[110]*20,dtype=float).reshape(-1,1)
    high = np.maximum(open_,close)+2
    low = np.minimum(open_,close)-5
    labels = research.future_labels(open_,high,low,close)
    for h,value in ((1,.1),(2,.15),(3,.05)):
        assert labels[h]["return"][0,0] == pytest.approx(value,abs=1e-6)
    assert labels[1]["mfe"][0,0] == pytest.approx(.12,abs=1e-6)
    assert labels[1]["mae"][0,0] == pytest.approx(-.05,abs=1e-6)
    open_[2,0] = np.nan
    missing = research.future_labels(open_,high,low,close)
    assert np.isfinite(missing[1]["return"][0,0])
    assert np.isnan(missing[2]["return"][0,0])
    assert np.isnan(missing[3]["return"][0,0])


def test_all_horizon_aggregation_matches_date_equal_weight_statistics(research):
    rows = []
    for day,symbol,value in (("2026-01-01","A",.1),("2026-01-01","B",.3),
                             ("2026-01-02","A",0.),("2026-01-03","A",None)):
        row = {"date":day,"symbol":symbol}
        for h in research.HORIZONS:
            row.update({f"r{h}_open":value,f"market{h}_open":.01,
                f"mfe{h}":.2 if value is not None else None,
                f"mae{h}":-.1 if value is not None else None,
                f"peak_day{h}":3 if value is not None else 0,f"path{h}":1 if value is not None else 0})
        rows.append(row)
    book = pl.DataFrame(rows)
    all_h = research.summaries(book)
    for h in research.HORIZONS:
        assert all_h[str(h)] == pytest.approx(research.stat(book,h))
        assert all_h[str(h)]["mean"] == pytest.approx(.1)
        assert all_h[str(h)]["excess"] == pytest.approx(.09)


def test_rule_comparison_excludes_unmatched_dates(research):
    frame = pl.DataFrame({"date":["A","A","B","C"],
        "kept":[True,False,True,False],"r10_open":[.2,.1,9.,-9.]})
    result = research.paired(frame,pl.col("kept"))
    assert result["dates"] == 1
    assert result["difference"] == pytest.approx(.1)
    assert result["block20_ci95"] == pytest.approx([.1,.1])
