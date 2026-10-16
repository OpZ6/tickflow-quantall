from datetime import date, timedelta

import polars as pl
import pytest

from app.market_facts.security_history import listing_trade_days


def calendar():
    # Friday listing, weekend, then two trading days.
    return pl.DataFrame({
        "exchange": ["SSE"] * 5,
        "trade_date": [date(2026, 9, 4) + timedelta(days=i) for i in range(5)],
        "is_open": [True, False, False, True, True],
    })


@pytest.mark.parametrize("day,expected", [(3, None), (4, 1), (5, 1), (6, 1), (7, 2), (8, 3)])
def test_listing_day_and_weekend_boundaries(day, expected):
    assert listing_trade_days(calendar(), exchange="SSE", listed_on=date(2026, 9, 4),
                              day=date(2026, 9, day)) == expected


@pytest.mark.parametrize("missing_day", [4, 5, 8])
def test_missing_open_or_closed_day_does_not_guess_age(missing_day):
    frame = calendar().filter(pl.col("trade_date") != date(2026, 9, missing_day))
    assert listing_trade_days(frame, exchange="SSE", listed_on=date(2026, 9, 4), day=date(2026, 9, 8)) is None


def test_exchange_and_listing_date_are_required():
    assert listing_trade_days(calendar(), exchange="SZSE", listed_on=date(2026, 9, 4), day=date(2026, 9, 8)) is None
    assert listing_trade_days(calendar(), exchange="SSE", listed_on=None, day=date(2026, 9, 8)) is None


def test_unknown_or_closed_listing_day_is_not_age_zero():
    for value in (None, False):
        frame = calendar().with_columns(
            pl.when(pl.col("trade_date") == date(2026, 9, 4)).then(pl.lit(value)).otherwise(pl.col("is_open")).alias("is_open")
        )
        assert listing_trade_days(frame, exchange="SSE", listed_on=date(2026, 9, 4), day=date(2026, 9, 8)) is None


def test_conflicting_calendar_versions_require_resolution_first():
    frame = pl.concat([calendar(), calendar().head(1)])
    with pytest.raises(ValueError, match="duplicate"):
        listing_trade_days(frame, exchange="SSE", listed_on=date(2026, 9, 4), day=date(2026, 9, 8))


def test_first_n_days_are_excluded_including_threshold_day():
    ages = [listing_trade_days(calendar(), exchange="SSE", listed_on=date(2026, 9, 4),
                               day=date(2026, 9, day)) for day in (4, 7, 8)]
    assert [age > 2 for age in ages] == [False, False, True]
