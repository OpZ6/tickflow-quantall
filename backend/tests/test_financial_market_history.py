from datetime import date

import polars as pl

from app.services.financial_sync import _merge_market_core, _report_periods


def test_report_periods_start_at_2012_and_exclude_future():
    periods = _report_periods(2010, date(2012, 8, 1))
    assert periods == [date(2012, 3, 31), date(2012, 6, 30)]


def test_bulk_core_does_not_replace_richer_tushare_row():
    existing = pl.DataFrame({
        "symbol": ["600519.SH"],
        "period_end": [date(2026, 6, 30)],
        "announce_date": [date(2026, 8, 20)],
        "source": ["tushare"],
        "revenue": [100.0],
        "rd_expense": [8.0],
    })
    fresh = pl.DataFrame({
        "symbol": ["600519.SH"],
        "period_end": [date(2026, 6, 30)],
        "announce_date": [date(2026, 8, 21)],
        "source": ["akshare_eastmoney"],
        "revenue": [101.0],
    })
    merged = _merge_market_core(existing, fresh)
    assert merged.height == 1
    assert merged["source"].item() == "tushare"
    assert merged["rd_expense"].item() == 8.0


def test_bulk_core_refreshes_existing_akshare_row():
    existing = pl.DataFrame({
        "symbol": ["000001.SZ"],
        "period_end": [date(2026, 6, 30)],
        "source": ["akshare_eastmoney"],
        "revenue": [100.0],
    })
    fresh = existing.with_columns(pl.lit(110.0).alias("revenue"))
    merged = _merge_market_core(existing, fresh)
    assert merged.height == 1
    assert merged["revenue"].item() == 110.0
