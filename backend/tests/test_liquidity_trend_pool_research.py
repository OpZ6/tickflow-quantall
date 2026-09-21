"""Ranking and membership-age checks for liquidity-trend research."""
import importlib
from datetime import date

import polars as pl
import pytest


@pytest.fixture
def research(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("research_liquidity_trend_pool")


def test_daily_amount_ranking_uses_symbol_as_stable_tie_break(tmp_path, research):
    path = tmp_path / "date=2026-01-05" / "part.parquet"
    path.parent.mkdir()
    pl.DataFrame({"symbol": ["B", "A", "C", "830001.BJ"], "date": [date(2026, 1, 5)] * 4,
                  "amount": [100.0, 100.0, 50.0, 200.0]}).write_parquet(path)
    ranked = research.build_rankings([path])
    assert ranked.sort("amount_rank")["symbol"].to_list() == ["830001.BJ", "A", "B", "C"]

    old_path = tmp_path / "date=2021-11-12" / "part.parquet"
    old_path.parent.mkdir()
    pl.DataFrame({"symbol": ["600000.SH", "830001.BJ"], "date": [date(2021, 11, 12)] * 2,
                  "amount": [10.0, 1000.0]}).write_parquet(old_path)
    assert research.build_rankings([old_path])["symbol"].to_list() == ["600000.SH"]


def test_threshold_ages_reset_after_exit_or_calendar_gap(research):
    frame = pl.DataFrame({"symbol": ["A"] * 6, "idx": [1, 2, 3, 4, 6, 7],
                          "amount_rank": [80, 70, 120, 90, 60, 55]})
    result = research.add_membership_ages(frame)
    assert result["age_top100"].to_list() == [0, 1, -1, 0, 0, 1]
    assert result["age_top50"].to_list() == [-1, -1, -1, -1, -1, -1]
