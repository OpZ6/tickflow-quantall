from __future__ import annotations

import gzip
import json
from datetime import date
from types import SimpleNamespace

import polars as pl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.data_sources import router as data_sources_router
from app.market_facts.builders import build_initial_fact_batches
from app.market_facts.registry import DatasetId, get_dataset, get_route
from app.market_facts.repository import MarketFactRepository
from app.market_facts.snapshots import SourceSnapshotStore
from app.market_facts.storage import FactPublication


def _sources(trade_date: str = "20260825") -> dict[str, dict]:
    return {
        "tushare": {
            "trade_date": trade_date,
            "scraped_at": "2026-08-25T16:01:00+08:00",
            "daily": [
                {"ts_code": "000001.SZ", "pct_chg": 2.0},
                {"ts_code": "600000.SH", "pct_chg": -1.0},
                {"ts_code": "300001.SZ", "pct_chg": 0.0},
            ],
        },
        "pywencai": {
            "trade_date": trade_date,
            "scraped_at": "2026-08-25T16:02:00+08:00",
            "limit_up": {
                "stocks": [
                    {
                        "code": "000001",
                        "name": "甲",
                        "limit_times": 2,
                    }
                ],
                "themes": [{"name": "人工智能", "count": 1}],
            },
            "broken_board": {
                "stocks": [{"code": "600000", "name": "乙"}],
            },
            "limit_down": {
                "stocks": [{"code": "830001", "name": "丙"}],
            },
        },
        "zhangtingke": {
            "trade_date": trade_date,
            "ladder_stocks": [
                {"code": "000001", "name": "甲", "limit_times": 2}
            ],
        },
        "ths_hot": {
            "trade_date": trade_date,
            "scraped_at": "2026-08-25T16:03:00+08:00",
            "reason_tags": [
                {"tag": "人工智能", "count": 3},
                {"tag": "机器人", "count": 2},
            ],
        },
        "deepq": {
            "trade_date": trade_date,
            "scraped_at": "2026-08-25T16:04:00+08:00",
            "latest_day": {
                "date": "2026/08/25",
                "sectors": [
                    {
                        "rank": 1,
                        "sectorName": "人工智能",
                        "stocksCount": 8,
                        "heatValue": 90,
                    }
                ],
            },
        },
        "sector_fund_flow_s4": {
            "trade_date": trade_date,
            "scraped_at": "2026-08-25T16:05:00+08:00",
            "sectors": [
                {
                    "code": "000910",
                    "name": "专用设备",
                    "pct_chg": 1.7,
                    "net_inflow_yi": 41.54,
                    "amount_yi": 422.46,
                }
            ],
        },
        "akshare": {
            "trade_date": trade_date,
            "scraped_at": "2026-08-25T16:06:00+08:00",
            "sector_fund_flow": [
                {
                    "name": "通信设备",
                    "pct_chg": 1.57,
                    "net_inflow_yi": 48.98,
                }
            ],
        },
    }


def test_initial_dataset_registry_declares_contracts_and_routes() -> None:
    dataset_ids = {
        DatasetId.MARKET_BREADTH_DAILY,
        DatasetId.LIMIT_EVENT_DAILY,
        DatasetId.THEME_OBSERVATION_DAILY,
        DatasetId.SECTOR_FLOW_DAILY,
    }

    for dataset_id in dataset_ids:
        spec = get_dataset(dataset_id)
        assert spec.schema_version == 1
        assert "trade_date" in spec.required_columns
        assert spec.partition_keys == ("trade_date",)

    breadth_route = get_route(DatasetId.MARKET_BREADTH_DAILY)
    assert breadth_route.sources[:2] == ("tickflow_enriched_aggregate", "tushare")
    limit_route = get_route(DatasetId.LIMIT_EVENT_DAILY)
    assert limit_route.sources[:2] == ("pywencai", "zhangtingke")


def test_fact_builders_normalize_breadth_and_limit_events() -> None:
    batches = build_initial_fact_batches("20260825", _sources(), "run-1")
    by_id = {batch.dataset_id: batch for batch in batches}

    breadth = by_id[DatasetId.MARKET_BREADTH_DAILY].frame.to_dicts()
    assert breadth == [
        {
            "trade_date": date(2026, 8, 25),
            "market": "CN_A",
            "up_count": 1,
            "down_count": 1,
            "flat_count": 1,
            "total_count": 3,
            "up_ratio_pct": 33.33,
            "advance_decline": 0,
            "source": "tushare",
            "source_record_id": "tushare:20260825:CN_A",
            "observed_at": "2026-08-25T16:01:00+08:00",
            "ingested_at": breadth[0]["ingested_at"],
            "run_id": "run-1",
            "schema_version": 1,
                "quality_level": "fallback",
                "is_fallback": True,
        }
    ]

    events = by_id[DatasetId.LIMIT_EVENT_DAILY].frame.sort(
        ["event_type", "symbol"]
    )
    assert events.select("symbol", "exchange", "event_type", "board_height").to_dicts() == [
        {
            "symbol": "600000",
            "exchange": "SSE",
            "event_type": "broken_board",
            "board_height": None,
        },
        {
            "symbol": "830001",
            "exchange": "BSE",
            "event_type": "limit_down",
            "board_height": None,
        },
        {
            "symbol": "000001",
            "exchange": "SZSE",
            "event_type": "limit_up",
            "board_height": 2,
        },
    ]
    assert events["source"].unique().to_list() == ["pywencai"]
    assert events["is_fallback"].to_list() == [False, False, False]

    themes = by_id[DatasetId.THEME_OBSERVATION_DAILY].frame
    assert set(themes["source"].to_list()) == {"ths_hot", "pywencai", "deepq"}
    ai_rows = themes.filter(pl.col("theme_name") == "人工智能")
    assert set(ai_rows["strength"].to_list()) == {1.0, 3.0, 90.0}

    flows = by_id[DatasetId.SECTOR_FLOW_DAILY].frame
    assert set(flows["source"].to_list()) == {"sector_fund_flow_s4", "akshare"}
    assert flows.filter(pl.col("source") == "sector_fund_flow_s4")["is_fallback"].item() is False
    assert flows.filter(pl.col("source") == "akshare")["is_fallback"].item() is True


def test_fact_publication_is_idempotent_and_repository_reads_canonical_data(tmp_path) -> None:
    batches = build_initial_fact_batches("20260825", _sources(), "run-1")
    publication = FactPublication(tmp_path, "run-1")
    publication.stage(batches)
    publication.commit()
    publication.finalize()

    repo = MarketFactRepository(tmp_path)
    breadth = repo.get_market_breadth(date(2026, 8, 25))
    events = repo.get_limit_events(date(2026, 8, 25))
    themes = repo.get_theme_observations(date(2026, 8, 25))
    flows = repo.get_sector_flows(date(2026, 8, 25))
    assert breadth["up_count"].to_list() == [1]
    assert set(events["event_type"].to_list()) == {
        "limit_up",
        "broken_board",
        "limit_down",
    }
    assert not themes.is_empty()
    assert not flows.is_empty()

    second = FactPublication(tmp_path, "run-2")
    second.stage(build_initial_fact_batches("20260825", _sources(), "run-2"))
    second.commit()
    second.finalize()
    assert repo.get_market_breadth(date(2026, 8, 25)).height == 1
    assert repo.get_limit_events(date(2026, 8, 25)).height == 3
    assert repo.get_theme_observations(date(2026, 8, 25)).height == themes.height
    assert repo.get_sector_flows(date(2026, 8, 25)).height == flows.height


def test_fact_publication_rolls_back_all_partitions_on_commit_failure(tmp_path, monkeypatch) -> None:
    initial = FactPublication(tmp_path, "run-1")
    initial.stage(build_initial_fact_batches("20260825", _sources(), "run-1"))
    initial.commit()
    initial.finalize()
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("part.parquet")
    }

    publication = FactPublication(tmp_path, "run-2")
    publication.stage(build_initial_fact_batches("20260825", _sources(), "run-2"))
    real_replace = publication._replace
    calls = 0

    def fail_second_target(source, target):
        nonlocal calls
        if str(source).endswith("part.parquet") and ".fact_runs" in str(source):
            calls += 1
            if calls == 2:
                raise OSError("simulated second partition failure")
        return real_replace(source, target)

    monkeypatch.setattr(publication, "_replace", fail_second_target)
    try:
        publication.commit()
    except OSError as exc:
        assert "simulated" in str(exc)
    else:
        raise AssertionError("publication should fail")

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("part.parquet")
        if ".fact_runs" not in path.parts
    }
    assert after == before


def test_source_snapshot_store_compresses_and_deduplicates_raw_payload(tmp_path) -> None:
    store = SourceSnapshotStore(tmp_path)
    payload = {"trade_date": "20260825", "rows": [{"code": "000001"}]}

    first = store.record(
        source_id="tushare",
        dataset_ids=(DatasetId.MARKET_BREADTH_DAILY,),
        trade_date="20260825",
        run_id="run-1",
        payload=payload,
    )
    second = store.record(
        source_id="tushare",
        dataset_ids=(DatasetId.MARKET_BREADTH_DAILY,),
        trade_date="20260825",
        run_id="run-2",
        payload=payload,
    )

    assert first.sha256 == second.sha256
    blobs = list((tmp_path / "source_snapshots" / "blobs").glob("*.json.gz"))
    assert len(blobs) == 1
    assert json.loads(gzip.decompress(blobs[0].read_bytes())) == payload
    metadata = list(
        (
            tmp_path
            / "source_snapshots"
            / "tushare"
            / DatasetId.MARKET_BREADTH_DAILY
            / "trade_date=2026-08-25"
        ).glob("*.meta.json")
    )
    assert len(metadata) == 2
    assert json.loads(metadata[0].read_text(encoding="utf-8"))["blob_sha256"] == first.sha256


def test_repository_returns_typed_empty_frames_for_missing_partitions(tmp_path) -> None:
    repo = MarketFactRepository(tmp_path)

    breadth = repo.get_market_breadth(date(2026, 8, 25))
    events = repo.get_limit_events(date(2026, 8, 25))

    assert breadth.is_empty()
    assert breadth.schema[get_dataset(DatasetId.MARKET_BREADTH_DAILY).primary_key[0]] == pl.Date
    assert events.is_empty()
    assert events.schema["symbol"] == pl.String


def test_data_source_management_api_exposes_contracts_without_secrets(tmp_path) -> None:
    app = FastAPI()
    app.include_router(data_sources_router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))

    with TestClient(app) as client:
        datasets = client.get("/api/data-sources/datasets")
        sources = client.get("/api/data-sources/sources")
        routes = client.get("/api/data-sources/routes")
        health = client.get("/api/data-sources/health")

    assert datasets.status_code == sources.status_code == routes.status_code == 200
    assert health.status_code == 200
    assert {item["dataset_id"] for item in datasets.json()["datasets"]} == {
        item.value for item in DatasetId
    }
    route = next(
        item for item in routes.json()["routes"]
        if item["dataset_id"] == DatasetId.LIMIT_EVENT_DAILY.value
    )
    assert route["sources"][0] == "pywencai"
    source = next(item for item in sources.json()["sources"] if item["source_id"] == "tushare")
    assert source["credentials_ref"] == "TUSHARE_TOKEN"
    assert "token" not in source
    assert health.json()["latest_trade_date"] is None
