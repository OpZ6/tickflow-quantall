from datetime import date

import pytest

from app.quantx_data.security_listing_history import (
    normalize_listing_pages,
    summarize_listing_history,
)


def page(status="L", **changes):
    row = dict(ts_code="600000.SH", symbol="600000", exchange="SSE", name="浦发银行",
               list_status=status, list_date="19991110", delist_date=None)
    row.update(changes)
    return dict(status="ok", source="tushare_client_chain", scraped_at="2026-09-07T03:00:00+00:00",
                request=dict(endpoint="stock_basic", params=dict(list_status=status)), rows=[row])


def test_live_only_snapshot_is_not_full_history():
    pages = [page()]
    frame = normalize_listing_pages(pages)
    assert frame["list_date"].item() == date(1999, 11, 10)
    assert frame["delist_date"].item() is None
    report = summarize_listing_history(pages)
    assert report["missing_status_queries"] == ["D", "P", "G", "UN"]
    assert report["production_published"] is False


def test_retired_security_keeps_original_listing_date():
    frame = normalize_listing_pages([page("D", delist_date="20200101")])
    assert frame["list_date"].item() == date(1999, 11, 10)
    assert frame["delist_date"].item() == date(2020, 1, 1)
    assert frame["source_status"].item() == "D"


def test_unknown_dates_are_reported_not_invented():
    report = summarize_listing_history([page("D", list_date=None)])
    assert report["missing_listing_dates"] == 1
    assert report["retired_without_delisting_date"] == 1


@pytest.mark.parametrize("changes", [
    {"exchange": "SZSE"}, {"symbol": "000001"}, {"list_status": "D"},
    {"list_date": "19990230"}, {"delist_date": "19900101"}, {"name": ""},
])
def test_invalid_listing_evidence_is_rejected(changes):
    with pytest.raises(ValueError):
        normalize_listing_pages([page(**changes)])


def test_duplicate_status_rejected():
    with pytest.raises(ValueError, match="duplicate status"):
        normalize_listing_pages([page(), page()])


def test_empty_successful_status_response_is_distinct_from_missing_query():
    empty = page("P")
    empty["rows"] = []
    report = summarize_listing_history([page(), empty])
    assert "P" not in report["missing_status_queries"]
    assert "D" in report["missing_status_queries"]


def test_future_listing_status_is_visible_as_inconsistency():
    report = summarize_listing_history([page(list_date="20260908")])
    assert report["listed_with_future_listing_date"] == 1


def port_pages():
    return [
        page(ts_code="600018.SH", symbol="600018", name="上港集团", list_date="20061026"),
        page("D", ts_code="T600018.SH", symbol="T600018", name="上港集箱(退)",
             list_date="20000719", delist_date="20061020"),
    ]


def test_reused_trading_code_preserves_two_security_identities():
    frame = normalize_listing_pages(port_pages())
    assert frame.height == 2
    assert frame["symbol"].to_list() == ["600018.SH", "600018.SH"]
    assert set(frame["security_id"]) == {"tushare:600018.SH", "tushare:T600018.SH"}
    assert set(frame["source_symbol"]) == {"600018.SH", "T600018.SH"}


@pytest.mark.parametrize("changes", [
    {"ts_code": "T600000.SH", "symbol": "T600000"},
    {"list_date": "20000720"}, {"delist_date": None}, {"name": "other"},
])
def test_alias_requires_exact_verified_evidence(changes):
    pages = port_pages()
    pages[1]["rows"][0].update(changes)
    with pytest.raises(ValueError):
        normalize_listing_pages(pages)


def test_reused_code_with_overlapping_lifecycles_is_rejected():
    pages = port_pages()
    pages[0]["rows"][0]["list_date"] = "20061020"
    with pytest.raises(ValueError, match="overlapping"):
        normalize_listing_pages(pages)
