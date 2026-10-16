from datetime import date, timedelta

import polars as pl
import pytest

from app.market_facts.builders import FactValidationError
from app.market_facts.security_history import resolve_daily_security_eligibility

DAY = date(2026, 9, 8)


def calendar() -> pl.DataFrame:
    start = date(2026, 9, 1)
    return pl.DataFrame({
        "exchange": ["SSE"] * 8,
        "trade_date": [start + timedelta(days=offset) for offset in range(8)],
        "is_open": [True, True, True, True, False, False, True, True],
    })


def listing(
    symbol: str,
    *,
    listed_on: date | None = date(2026, 9, 1),
    delisted_on: date | None = None,
    status: str = "L",
    security_id: str | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "security_id": security_id or f"test:{symbol}",
        "exchange": "SSE",
        "list_date": listed_on,
        "delist_date": delisted_on,
        "source_status": status,
    }


def name_state(symbol: str, is_st_name: bool | None, reason: str = "available") -> dict:
    return {"symbol": symbol, "is_st_name": is_st_name, "reason": reason}


def resolve(listings: list[dict], names: list[dict], symbols: list[str], **kwargs) -> pl.DataFrame:
    return resolve_daily_security_eligibility(
        pl.DataFrame(listings),
        pl.DataFrame(names),
        calendar(),
        symbols,
        day=DAY,
        **kwargs,
    )


def test_eligible_requires_known_listing_age_and_non_st_name():
    row = resolve(
        [listing("600000.SH")],
        [name_state("600000.SH", False)],
        ["600000.SH"],
        exclude_new_days=5,
    ).row(0, named=True)
    assert row["eligibility"] == "eligible"
    assert row["listing_trade_days"] == 6
    assert row["listing_trade_days_lower_bound"] == 6
    assert row["listing_age_basis"] == "exact"
    assert row["reasons"] == []


def test_known_disqualifier_dominates_an_unrelated_unknown():
    row = resolve(
        [listing("600000.SH")],
        [name_state("600000.SH", None, "announcement_unknown")],
        ["600000.SH"],
        exclude_new_days=6,
    ).row(0, named=True)
    assert row["eligibility"] == "ineligible"
    assert row["reasons"] == ["new_listing", "unknown_name_state:announcement_unknown"]


def test_st_and_outside_lifecycle_are_ineligible():
    rows = resolve(
        [
            listing("600000.SH"),
            listing("600001.SH", delisted_on=date(2026, 9, 7), status="D"),
        ],
        [name_state("600000.SH", True), name_state("600001.SH", False)],
        ["600000.SH", "600001.SH"],
    ).to_dicts()
    assert [(row["eligibility"], row["reasons"]) for row in rows] == [
        ("ineligible", ["st_name"]),
        ("ineligible", ["outside_listing_lifecycle"]),
    ]


def test_missing_identity_or_name_remains_unknown():
    bad_calendar = calendar().filter(pl.col("trade_date") != date(2026, 9, 6))
    frame = resolve_daily_security_eligibility(
        pl.DataFrame([listing("600000.SH")]),
        pl.DataFrame([name_state("600000.SH", None, "no_name_interval")]),
        bad_calendar,
        ["600000.SH", "600002.SH"],
        day=DAY,
    )
    assert frame["eligibility"].to_list() == ["unknown", "unknown"]
    assert frame["reasons"].to_list() == [
        ["unknown_name_state:no_name_interval"],
        ["missing_listing_identity", "unknown_name_state:missing"],
    ]


def test_incomplete_calendar_cannot_prove_listing_age():
    bad_calendar = calendar().filter(pl.col("trade_date") != date(2026, 9, 6))
    row = resolve_daily_security_eligibility(
        pl.DataFrame([listing("600000.SH")]),
        pl.DataFrame([name_state("600000.SH", False)]),
        bad_calendar,
        ["600000.SH"],
        day=DAY,
        exclude_new_days=5,
    ).row(0, named=True)
    assert row["eligibility"] == "unknown"
    assert row["reasons"] == ["unknown_listing_trade_days"]


def test_old_listing_uses_only_a_verified_age_lower_bound():
    old = listing("600000.SH", listed_on=date(1999, 11, 10))
    known_old = resolve(
        [old],
        [name_state("600000.SH", False)],
        ["600000.SH"],
        exclude_new_days=5,
    ).row(0, named=True)
    assert known_old["eligibility"] == "eligible"
    assert known_old["listing_trade_days"] is None
    assert known_old["listing_trade_days_lower_bound"] == 6
    assert known_old["listing_age_basis"] == "lower_bound"

    insufficient = resolve(
        [old],
        [name_state("600000.SH", False)],
        ["600000.SH"],
        exclude_new_days=6,
    ).row(0, named=True)
    assert insufficient["eligibility"] == "unknown"
    assert insufficient["reasons"] == ["unknown_listing_trade_days"]


def test_disabled_new_listing_filter_does_not_require_calendar():
    row = resolve_daily_security_eligibility(
        pl.DataFrame([listing("600000.SH", listed_on=date(1999, 11, 10))]),
        pl.DataFrame([name_state("600000.SH", False)]),
        calendar().head(0),
        ["600000.SH"],
        day=DAY,
        exclude_new_days=0,
    ).row(0, named=True)
    assert row["eligibility"] == "eligible"
    assert row["listing_age_basis"] == "not_required"


def test_delisting_date_is_inclusive_and_reused_code_selects_one_lifecycle():
    listings = [
        listing(
            "600018.SH",
            listed_on=date(2026, 9, 1),
            delisted_on=DAY,
            status="D",
            security_id="old",
        ),
        listing("600018.SH", listed_on=date(2026, 9, 9), security_id="new"),
    ]
    row = resolve(listings, [name_state("600018.SH", False)], ["600018.SH"]).row(0, named=True)
    assert row["eligibility"] == "eligible"
    assert row["security_id"] == "old"


def test_future_delisting_does_not_remove_security_from_past_universe():
    row = resolve(
        [listing("600000.SH", delisted_on=date(2026, 9, 9), status="D")],
        [name_state("600000.SH", False)],
        ["600000.SH"],
    ).row(0, named=True)
    assert row["eligibility"] == "eligible"


def test_day_before_known_listing_is_outside_lifecycle():
    row = resolve(
        [listing("600000.SH", listed_on=date(2026, 9, 9))],
        [name_state("600000.SH", False)],
        ["600000.SH"],
    ).row(0, named=True)
    assert row["eligibility"] == "ineligible"
    assert row["reasons"] == ["outside_listing_lifecycle"]


def test_conflicting_active_lifecycles_and_duplicate_names_fail_closed():
    listings = [listing("600000.SH", security_id="a"), listing("600000.SH", security_id="b")]
    names = [name_state("600000.SH", False)]
    with pytest.raises(FactValidationError, match="multiple active"):
        resolve(listings, names, ["600000.SH"])
    with pytest.raises(FactValidationError, match="multiple name states"):
        resolve([listings[0]], names * 2, ["600000.SH"])


def test_negative_new_listing_threshold_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        resolve([], [], ["600000.SH"], exclude_new_days=-1)


def test_missing_input_columns_are_rejected_at_the_boundary():
    with pytest.raises(FactValidationError, match="listing snapshot missing columns"):
        resolve_daily_security_eligibility(
            pl.DataFrame({"symbol": ["600000.SH"]}),
            pl.DataFrame([name_state("600000.SH", False)]),
            calendar(),
            ["600000.SH"],
            day=DAY,
        )
