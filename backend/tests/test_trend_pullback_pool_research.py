"""Causality, event reset and next-open label checks for trend-pullback research."""
import importlib
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest


@pytest.fixture
def research(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("research_trend_pullback_pool")


def test_rolling_ma_requires_contiguous_market_sessions(research):
    values = np.arange(1, 82, dtype=float)
    frame = pl.DataFrame({"symbol": ["TEST"] * len(values),
        "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(len(values))],
        "idx": np.arange(len(values)), "open": values, "high": values + 1, "low": values - 1,
        "close": values, "volume": np.full(len(values), 100.0)})
    complete = research.rolling_features(frame)
    assert complete["ma60"][58] is None
    assert complete["ma60"][59] == pytest.approx(np.mean(values[:60]))
    missing = research.rolling_features(frame.filter(pl.col("idx") != 40))
    assert missing.filter(pl.col("idx") == 60)["ma60"].item() is None


def test_latest_event_resets_observation_age(research):
    events = np.zeros((30, 1), dtype=bool)
    events[[2, 10], 0] = True
    age, starts = research.observation_episodes(events)
    assert age[2, 0] == 0 and starts[2, 0] == 2
    assert age[9, 0] == 7 and starts[9, 0] == 2
    assert age[10, 0] == 0 and starts[10, 0] == 10
    assert age[29, 0] == 19


def test_next_open_labels_include_ultrashort_and_invalidate_gaps(research):
    open_ = np.array([1, 100, 109, 114] + [114] * 70, dtype=float).reshape(-1, 1)
    close = np.array([900, 110, 115, 105] + [110] * 70, dtype=float).reshape(-1, 1)
    high, low = np.maximum(open_, close) + 2, np.minimum(open_, close) - 5
    labels = research.future_labels(open_, high, low, close)
    assert labels[1]["return"][0, 0] == pytest.approx(.1)
    assert labels[2]["return"][0, 0] == pytest.approx(.15)
    assert labels[3]["return"][0, 0] == pytest.approx(.05)
    open_[2, 0] = np.nan
    missing = research.future_labels(open_, high, low, close)
    assert np.isfinite(missing[1]["return"][0, 0])
    assert np.isnan(missing[2]["return"][0, 0])
    assert np.isnan(missing[60]["return"][0, 0])


def test_pre_bse_neeq_quotes_are_not_eligible_market_rows(research):
    dates = [date(2021, 11, 12), date(2021, 11, 15)]
    eligible = research.eligibility_matrix(dates, ["600000.SH", "830001.BJ"])
    assert eligible.tolist() == [[True, False], [True, True]]
