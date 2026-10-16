from datetime import UTC, date, datetime

import polars as pl
import pytest

from app.market_facts.builders import (
    FactValidationError,
    build_trading_calendar_history_batch,
)
from app.market_facts.registry import DatasetId, get_dataset, get_route, validate_registry_contracts
from app.market_facts.repository import MarketFactRepository
from app.market_facts.security_history import build_security_history_batch, resolve_security_names
from app.market_facts.storage import FactPublication
from app.quantx_data.collectors import SOURCE_MANAGER
from app.quantx_data.security_snapshots import snapshot_manager

DAY = date(2026, 9, 7)


def page(endpoint):
    if endpoint == "stock_basic":
        rows = [dict(ts_code="600000.SH", symbol="600000", exchange="SSE", name="浦发银行",
                     list_status="L", list_date="19991110", delist_date=None)]
    else:
        rows = [dict(ts_code="600000.SH", name="浦发银行", start_date="19991110",
                     end_date=None, ann_date=None)]
    return dict(status="ok", source="tushare_client_chain", scraped_at="2026-09-07T03:00:00+00:00",
                request=dict(endpoint=endpoint, params=dict(list_status="L")), rows=rows)


@pytest.mark.parametrize("endpoint,dataset", [
    ("stock_basic", DatasetId.SECURITY_LISTING_HISTORY),
    ("namechange", DatasetId.SECURITY_NAME_HISTORY),
])
def test_batch_publication_and_explicit_snapshot_read(tmp_path, endpoint, dataset):
    batch = build_security_history_batch(endpoint, [page(endpoint)], snapshot_date=DAY, run_id="test")
    assert batch.frame.schema == dict(get_dataset(dataset).storage_schema)
    assert batch.frame["quality_level"].item() == "reconstructed"
    publication = FactPublication(tmp_path, "test")
    publication.stage([batch])
    publication.commit()
    publication.finalize()
    repo = MarketFactRepository(tmp_path)
    read = repo.get_security_listing_snapshot if endpoint == "stock_basic" else repo.get_security_name_snapshot
    assert read(DAY).equals(batch.frame)
    assert read(date(2020, 1, 1)).is_empty()  # no implicit future-snapshot fallback


def test_source_is_registered_but_not_daily_selected():
    assert validate_registry_contracts() == []
    source = get_route(DatasetId.SECURITY_NAME_HISTORY).sources[0]
    assert source in snapshot_manager().spec_by_name
    assert source not in SOURCE_MANAGER.spec_by_name


def test_listing_publication_preserves_reused_code_identities(tmp_path):
    from test_security_listing_history import port_pages

    batch = build_security_history_batch("stock_basic", port_pages(), snapshot_date=DAY, run_id="identity")
    publication = FactPublication(tmp_path, "identity")
    publication.stage([batch])
    publication.commit()
    publication.finalize()
    frame = MarketFactRepository(tmp_path).get_security_listing_snapshot(DAY)
    assert frame.height == frame["security_id"].n_unique() == 2
    assert frame["symbol"].n_unique() == 1
    assert set(frame["source_record_id"]) == {"600018.SH", "T600018.SH"}
    assert frame["schema_version"].to_list() == [2, 2]


@pytest.mark.parametrize("snapshot_date", [date(2020, 1, 1), date(2026, 9, 8)])
def test_snapshot_cannot_be_backdated_or_forward_dated(snapshot_date):
    with pytest.raises(FactValidationError, match="observation date"):
        build_security_history_batch("namechange", [page("namechange")], snapshot_date=snapshot_date, run_id="test")


def test_empty_snapshot_cannot_erase_prior_data():
    with pytest.raises(FactValidationError, match="empty"):
        build_security_history_batch("namechange", [], snapshot_date=DAY, run_id="test")


def test_failed_replacement_keeps_previous_snapshot(tmp_path):
    batch = build_security_history_batch("namechange", [page("namechange")], snapshot_date=DAY, run_id="first")
    publication = FactPublication(tmp_path, "first")
    publication.stage([batch])
    publication.commit()
    publication.finalize()
    replacement = FactPublication(tmp_path, "second")
    replacement.stage([batch])
    original_replace = replacement._replace

    def fail_staged(source, target):
        if ".fact_runs" in str(source):
            raise OSError("simulated publication failure")
        return original_replace(source, target)

    replacement._replace = fail_staged
    with pytest.raises(OSError):
        replacement.commit()
    assert MarketFactRepository(tmp_path).get_security_name_snapshot(DAY).equals(batch.frame)


def name_frame(ann_date="19991109"):
    payload = page("namechange")
    payload["rows"][0]["ann_date"] = ann_date
    return build_security_history_batch("namechange", [payload], snapshot_date=DAY, run_id="query").frame


def test_reconstruction_must_be_explicit():
    frame = name_frame()
    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    strict = resolve_security_names(frame, ["600000.SH"], cutoff=cutoff).row(0, named=True)
    assert strict["name"] is None
    assert strict["is_st_name"] is None
    assert strict["reason"] == "not_recorded_by_cutoff"
    reconstructed = resolve_security_names(frame, ["600000.SH"], cutoff=cutoff, allow_reconstructed=True).row(0, named=True)
    assert reconstructed["name"] == "浦发银行"
    assert reconstructed["knowledge_basis"] == "reconstructed"


@pytest.mark.parametrize("ann_date,reason", [(None, "announcement_unknown"), ("20200101", "announcement_not_available")])
def test_reconstruction_does_not_bypass_announcement(ann_date, reason):
    result = resolve_security_names(name_frame(ann_date), ["600000.SH"], cutoff=datetime(2020, 1, 1, tzinfo=UTC), allow_reconstructed=True)
    assert result["reason"].item() == reason
    assert result["is_st_name"].item() is None


def test_recorded_mode_checks_ingestion_not_just_observation():
    frame = name_frame().with_columns(pl.lit("2026-09-07T05:00:00+00:00").alias("ingested_at"))
    early = resolve_security_names(frame, ["600000.SH"], cutoff=datetime(2026, 9, 7, 4, tzinfo=UTC))
    late = resolve_security_names(frame, ["600000.SH"], cutoff=datetime(2026, 9, 7, 6, tzinfo=UTC))
    assert early["reason"].item() == "not_recorded_by_cutoff"
    assert late["knowledge_basis"].item() == "recorded"


def test_open_name_does_not_extend_beyond_observation_coverage():
    result = resolve_security_names(name_frame(), ["600000.SH", "000001.SZ"], cutoff=datetime(2026, 9, 8, tzinfo=UTC), allow_reconstructed=True)
    assert result["reason"].to_list() == ["beyond_observed_coverage", "no_name_interval"]
    assert result["is_st_name"].null_count() == 2


def test_missing_repository_snapshot_returns_unknown(tmp_path):
    result = MarketFactRepository(tmp_path).get_security_names_at(
        ["600000.SH"], snapshot_date=DAY, cutoff=datetime(2020, 1, 1, tzinfo=UTC),
    )
    assert result["knowledge_basis"].item() == "unknown"


def test_repository_resolves_daily_eligibility_from_explicit_fact_versions(tmp_path):
    listing_batch = build_security_history_batch(
        "stock_basic", [page("stock_basic")], snapshot_date=DAY, run_id="eligibility"
    )
    name_payload = page("namechange")
    name_payload["rows"][0]["ann_date"] = "19991109"
    name_batch = build_security_history_batch(
        "namechange", [name_payload], snapshot_date=DAY, run_id="eligibility"
    )
    calendar_rows = []
    previous_open = None
    for offset, is_open in enumerate((1, 1, 1, 1, 0, 0, 1)):
        trade_date = date(2026, 9, 1 + offset)
        calendar_rows.append({
            "exchange": "SSE",
            "cal_date": trade_date.strftime("%Y%m%d"),
            "is_open": is_open,
            "pretrade_date": previous_open,
        })
        if is_open:
            previous_open = trade_date.strftime("%Y%m%d")
    calendar_batch = build_trading_calendar_history_batch(
        "20260907",
        {
            "scraped_at": "2026-09-07T10:00:00+08:00",
            "trade_calendar": {"records": calendar_rows},
        },
        "eligibility",
    )
    publication = FactPublication(tmp_path, "eligibility")
    publication.stage([listing_batch, name_batch, calendar_batch])
    publication.commit()
    publication.finalize()

    row = MarketFactRepository(tmp_path).get_daily_security_eligibility(
        ["600000.SH"],
        day=DAY,
        listing_snapshot_date=DAY,
        name_snapshot_date=DAY,
        calendar_as_of=DAY,
        cutoff=datetime(2026, 9, 7, 15, tzinfo=UTC),
        exclude_new_days=4,
        allow_reconstructed_names=True,
    ).row(0, named=True)
    assert row["eligibility"] == "eligible"
    assert row["listing_age_basis"] == "lower_bound"
    assert row["listing_trade_days_lower_bound"] == 5
    assert row["reasons"] == []


def test_repository_missing_partitions_fail_closed_and_cutoff_matches_day(tmp_path):
    repo = MarketFactRepository(tmp_path)
    row = repo.get_daily_security_eligibility(
        ["600000.SH"],
        day=DAY,
        listing_snapshot_date=DAY,
        name_snapshot_date=DAY,
        calendar_as_of=DAY,
        cutoff=datetime(2026, 9, 7, 15, tzinfo=UTC),
    ).row(0, named=True)
    assert row["eligibility"] == "unknown"
    assert row["reasons"] == [
        "missing_listing_identity",
        "unknown_name_state:no_name_interval",
    ]
    with pytest.raises(ValueError, match="Beijing date"):
        repo.get_daily_security_eligibility(
            ["600000.SH"],
            day=DAY,
            listing_snapshot_date=DAY,
            name_snapshot_date=DAY,
            calendar_as_of=DAY,
            cutoff=datetime(2026, 9, 8, 15, tzinfo=UTC),
        )


def test_conflicting_active_intervals_and_naive_cutoff_rejected():
    frame = name_frame()
    with pytest.raises(FactValidationError, match="multiple active"):
        resolve_security_names(pl.concat([frame, frame]), ["600000.SH"], cutoff=datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone"):
        resolve_security_names(frame, ["600000.SH"], cutoff=datetime(2020, 1, 1))
