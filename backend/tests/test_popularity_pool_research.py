"""Verify weighting and matched-date contrasts in the observation experiment."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "popularity_research", Path(__file__).resolve().parents[2] / "scripts/research_popularity_pool.py"
)
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def row(day, value, symbol="000001.SZ"):
    return {"date": day, "symbol": symbol, "r5_open": value, "market5_open": .01,
            "mfe5": .2, "mae5": -.1, "peak_day5": 3, "path5": "low_first"}


def test_dates_are_equal_weighted_and_zero_is_valid():
    book = [row("2026-07-01", .1), row("2026-07-01", .3, "000002.SZ"),
            row("2026-07-02", 0), row("2026-07-03", None)]
    result = research.summarize(book,5)
    assert result["n"] == 3
    assert result["dates"] == 2
    assert result["mean"] == pytest.approx(.1)
    assert result["excess"] == pytest.approx(.09)
    assert result["positive"] == pytest.approx(.5)


def test_empty_and_unmatured_windows_stay_missing():
    assert research.summarize([],5) == {"n":0,"dates":0}
    assert research.summarize([row("2026-07-01",None)],5) == {"n":0,"dates":0}


def test_paired_contrast_uses_only_common_dates():
    kept = [{"date":"2026-07-01","r10_open":.2},
            {"date":"2026-07-02","r10_open":9}]
    removed = [{"date":"2026-07-01","r10_open":.1},
               {"date":"2026-07-03","r10_open":-9}]
    result = research.paired_difference(kept,removed)
    assert result["dates"] == 1
    assert result["mean_difference"] == pytest.approx(.1)
    assert result["block10_ci95"] == pytest.approx([.1,.1])


def test_next_open_anchor_applies_to_one_two_three_day_returns_and_paths():
    bars = [{"open":100,"high":112,"low":95,"close":110},
            {"open":109,"high":120,"low":105,"close":115},
            {"open":114,"high":118,"low":90,"close":105}]
    for h, expected in ((1,.10),(2,.15),(3,.05)):
        assert research.path_labels(bars[:h])["return"] == pytest.approx(expected)
    one = research.path_labels(bars[:1])
    assert one["mfe"] == pytest.approx(.12)
    assert one["mae"] == pytest.approx(-.05)
    assert one["path"] == "same_day_unknown"
    three = research.path_labels(bars)
    assert three["mfe"] == pytest.approx(.20)
    assert three["mae"] == pytest.approx(-.10)
    assert three["peak_day"] == 2
    assert three["path"] == "high_first"


def test_missing_or_invalid_next_open_window_is_unavailable():
    bar = {"open":100,"high":112,"low":95,"close":110}
    assert research.path_labels([]) is None
    assert research.path_labels([None]) is None
    assert research.path_labels([bar,None,bar]) is None
    for invalid in (None,0,-1,float("nan")):
        assert research.path_labels([{**bar,"open":invalid}]) is None
