from datetime import date

import pytest

from app.quantx_data.security_name_history import (
    announcement_shadow_rows,
    inspect_name_pages,
    invalid_name_source_codes,
    normalize_name_pages,
    summarize_name_history,
)


def record(start="20070514", end="20151117", name="自仪股份", ann="20070513"):
    return dict(ts_code="600848.SH", name=name, start_date=start, end_date=end, ann_date=ann)


def page(rows):
    return dict(status="ok", request={"endpoint": "namechange"}, source="tushare_client_chain",
                scraped_at="2026-09-07T03:00:00+00:00", rows=rows)


def test_inclusive_end_st_transition_and_unknown_announcement():
    frame = normalize_name_pages([page([
        record("20061026", "20070513", "ST自仪", "20061025"),
        record(), record("20151118", None, "上海临港", None),
    ])])
    rows = frame.to_dicts()
    assert rows[0]["valid_to_exclusive"] == rows[1]["valid_from"] == date(2007, 5, 14)
    assert [row["is_st_name"] for row in rows] == [True, False, False]
    assert rows[0]["available_from"] == date(2006, 10, 26)
    assert rows[2]["available_from"] is None
    assert rows[2]["valid_to_exclusive"] is None
    assert rows[2]["coverage_until"] == date(2026, 9, 7)
    assert set(frame["quality_level"]) == {"reconstructed"}
    assert summarize_name_history(frame)["unknown_announcements"] == 1


def test_late_announcement_does_not_become_early_knowledge():
    frame = normalize_name_pages([page([record(ann="20070601")])])
    assert frame["available_from"].item() == date(2007, 6, 2)
    assert frame["valid_from"].item() == date(2007, 5, 14)


def test_gaps_are_counted_not_filled():
    frame = normalize_name_pages([page([record(end="20080101"), record("20100101", None, "新名")])])
    assert summarize_name_history(frame)["internal_interval_gaps"] == 1
    assert frame["valid_to_exclusive"][0] == date(2008, 1, 2)


@pytest.mark.parametrize("rows", [
    [record(), record()],
    [record(), record("20150101", None)],
    [record(end=None), record("20160101", None)],
    [record(start="20070230")],
    [record(start=None)],
    [record(start="20160101", end="20150101")],
    [record(ann="bad")],
    [record(name="")],
])
def test_invalid_or_conflicting_intervals_fail_closed(rows):
    with pytest.raises(ValueError):
        normalize_name_pages([page(rows)])


def test_empty_is_missing_not_complete():
    result = summarize_name_history(normalize_name_pages([]))
    assert result["status"] == "missing"
    assert result["production_published"] is False


def test_observation_is_beijing_date_and_never_backdated():
    payload = page([record()])
    payload["scraped_at"] = "2026-09-06T20:00:00+00:00"
    assert normalize_name_pages([payload])["coverage_until"].item() == date(2026, 9, 7)
    payload["scraped_at"] = "2026-09-06T20:00:00"
    with pytest.raises(ValueError, match="timezone"):
        normalize_name_pages([payload])


def test_invalid_source_code_is_reported_but_normalization_still_fails_closed():
    invalid = record()
    invalid["ts_code"] = "X19363.SH"
    pages = [page([record(), invalid, invalid])]

    assert invalid_name_source_codes(pages) == [
        {"source_symbol": "X19363.SH", "rows": 2}
    ]
    with pytest.raises(ValueError, match=r"X19363\.SH"):
        normalize_name_pages(pages)


def test_overlap_error_identifies_security_and_interval_starts():
    rows = [
        record(start="20260725", end=None, name="富邦新材", ann="20260725"),
        record(start="20260818", end=None, name="富邦新材", ann="20260725"),
    ]
    for row in rows:
        row["ts_code"] = "600768.SH"

    with pytest.raises(
        ValueError,
        match=r"600768\.SH 2026-07-25 -> 2026-08-18",
    ):
        normalize_name_pages([page(rows)])


def test_proposal_date_shadow_is_dropped_only_with_exact_effective_boundary():
    old = record(
        start="20061226", end="20260817", name="宁波富邦", ann="20061221"
    )
    shadow = record(
        start="20260725", end=None, name="富邦新材", ann="20260725"
    )
    effective = record(
        start="20260818", end=None, name="富邦新材", ann="20260725"
    )
    pages = [page([effective, shadow, old])]

    assert announcement_shadow_rows(pages) == [{
        "source_symbol": "600848.SH",
        "name": "富邦新材",
        "ann_date": "2026-07-25",
        "shadow_start": "2026-07-25",
        "effective_start": "2026-08-18",
        "prior_name": "宁波富邦",
        "prior_end": "2026-08-17",
    }]
    frame = normalize_name_pages(pages)
    assert frame["name"].to_list() == ["宁波富邦", "富邦新材"]
    assert frame["valid_to_exclusive"][0] == frame["valid_from"][1]


def test_proposal_date_overlap_without_prior_name_boundary_still_fails_closed():
    shadow = record(
        start="20260725", end=None, name="富邦新材", ann="20260725"
    )
    effective = record(
        start="20260818", end=None, name="富邦新材", ann="20260725"
    )
    pages = [page([effective, shadow])]

    assert announcement_shadow_rows(pages) == []
    with pytest.raises(ValueError, match="overlapping"):
        normalize_name_pages(pages)


def test_inspection_keeps_invalid_code_rejected_but_audits_valid_remainder():
    old = record(end="20260817", name="宁波富邦")
    shadow = record(
        start="20260725", end=None, name="富邦新材", ann="20260725"
    )
    effective = record(
        start="20260818", end=None, name="富邦新材", ann="20260725"
    )
    invalid = record()
    invalid["ts_code"] = "X19363.SH"

    result = inspect_name_pages([page([old, shadow, effective, invalid])])

    assert result["status"] == "rejected_invalid_source_codes"
    assert result["invalid_source_codes"] == [
        {"source_symbol": "X19363.SH", "rows": 1}
    ]
    assert result["valid_code_rows_diagnostic"]["status"] == "normalized_unverified"
    assert result["valid_code_rows_diagnostic"]["rows"] == 2
    assert result["production_published"] is False
