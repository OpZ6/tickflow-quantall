from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.quantx import router as quantx_router
from app.api.quantx_data import router as quantx_data_router
from app.market_facts.registry import DatasetId
from app.market_facts.repository import MarketFactRepository
from app.quantx_data import collectors
from app.quantx_data.catalog import build_catalog, load_tables
from app.quantx_data.migration import migrate_quantx_history
from app.quantx_data.multiday import (
    _opportunity_radar,
    _window_signal,
    build_multiday_snapshot,
    rebuild_multiday_snapshots,
)
from app.quantx_data.new_high_clusters import (
    build_new_high_cluster_member_bundle,
    build_new_high_cluster_members,
    build_new_high_clusters,
)
from app.quantx_data.pipeline import run_pipeline
from app.quantx_data.scheduler import _trade_date_today
from app.services.ext_data import ExtConfig, ExtConfigStore, ExtField

SOURCE_NAMES = (
    "tushare", "akshare", "ths_hot", "zhangtingke", "zhangtingjun", "pywencai",
    "duanxianxia", "deepq", "legulegu", "quicktiny", "dabanke", "sector_fund_flow_s4",
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fixture(root: Path, trade_date: str = "20260825") -> Path:
    date_dir = root / "quantx" / trade_date
    selected_day = datetime.strptime(trade_date, "%Y%m%d")
    margin_dates = [
        (selected_day - timedelta(days=3)).strftime("%Y%m%d"),
        (selected_day - timedelta(days=1)).strftime("%Y%m%d"),
    ]
    daily = [
        {"ts_code": "000001.SZ", "close": 10, "pct_chg": 2.0, "amount": 100000},
        {"ts_code": "600000.SH", "close": 9, "pct_chg": -1.0, "amount": 80000},
        {"ts_code": "300001.SZ", "close": 20, "pct_chg": 0.0, "amount": 50000},
    ]
    payloads = {
        "tushare": {
            "trade_date": trade_date,
            "status": "ok",
            "daily": daily,
            "indexes": {"000001.SH": {"code": "000001.SH", "name": "上证指数", "close": 3000, "pct_chg": 0.5}},
            "trade_calendar": {
                "records": [
                    {"exchange": "SSE", "cal_date": trade_date, "is_open": 1, "pretrade_date": "20260824"},
                    {"exchange": "SSE", "cal_date": "20260826", "is_open": 0, "pretrade_date": trade_date},
                ]
            },
            "margin": {
                "history": [
                    {"date": margin_dates[0], "rzye_yi": 100.0, "rz_net_buy_yi": 1.0},
                    {"date": margin_dates[1], "rzye_yi": 102.0, "rz_net_buy_yi": 2.0},
                ]
            },
        },
        "akshare": {"trade_date": trade_date, "status": "ok", "sector_fund_flow": []},
        "ths_hot": {"trade_date": trade_date, "status": "ok", "reason_tags": [{"tag": "人工智能", "count": 2}], "stocks": [{"code": "000001", "name": "甲", "reason": "人工智能"}]},
        "zhangtingke": {"trade_date": trade_date, "status": "ok", "ladder_by_height": {"2": [{"code": "000001", "name": "甲", "limit_times": 2, "theme_name": "人工智能", "turnover_pct": 12.34, "amount_yi": 8.76}]}, "ladder_stocks": [{"code": "000001", "name": "甲", "limit_times": 2, "theme_name": "人工智能", "turnover_pct": 12.34, "amount_yi": 8.76}]},
        "zhangtingjun": {"trade_date": trade_date, "status": "ok"},
        "pywencai": {"trade_date": trade_date, "status": "ok", "limit_up": {"count": 1, "stocks": [{"code": "000001", "name": "甲", "limit_times": 2, "concepts": ["人工智能"]}], "ladder": {"2": ["甲"]}, "themes": [{"name": "人工智能", "count": 1}]}, "broken_board": {"count": 0, "stocks": []}, "limit_down": {"count": 0, "stocks": []}, "seal_rate": 100, "broken_rate": 0},
        "duanxianxia": {"trade_date": trade_date, "status": "ok"},
        "deepq": {"trade_date": trade_date, "status": "ok"},
        "legulegu": {
            "trade_date": trade_date,
            "status": "ok",
            "scraped_at": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T16:07:00+08:00",
            "width_api": {
                "ma_market_width_primary": {
                    "dates": [
                        f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
                    ],
                    "maMarketWidth": {
                        "801010.SI": [
                            {"value5": 75, "value10": 65, "value20": 55, "value60": 45}
                        ],
                        "801030.SI": [
                            {"value5": 25, "value10": 35, "value20": 45, "value60": 55}
                        ],
                    },
                }
            },
        },
        "quicktiny": {"trade_date": trade_date, "status": "ok"},
        "dabanke": {"trade_date": trade_date, "status": "ok"},
        "sector_fund_flow_s4": {"trade_date": trade_date, "status": "ok", "sectors": [{"name": "人工智能", "pct_chg": 1.2, "net_inflow_yi": 3.5}]},
    }
    payloads["pywencai"]["new_high_100d"] = {
        "status": "ok",
        "stocks": [
            {
                "code": "300002",
                "name": "新高样本",
                "pct_chg": 5.0,
                "concepts": ["百日新高"],
            }
        ],
    }
    for name in SOURCE_NAMES:
        _write(date_dir / f"{name}.json", payloads[name])
    parquet_dir = root / "kline_daily_enriched" / f"date={trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    parquet_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "date": [date(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:]))] * 3,
        "change_pct": [2.0, -1.0, 0.0],
        "amount": [100_000_000.0, 80_000_000.0, 50_000_000.0],
    }).write_parquet(parquet_dir / "part.parquet")
    return root


def test_pipeline_publishes_structured_snapshot_without_editorial_artifacts(tmp_path):
    root = _fixture(tmp_path)
    result = run_pipeline(root, "20260825", recompute=True)
    assert result["status"] == "complete"
    assert result["stages"][-1] == "published"
    date_dir = root / "quantx" / "20260825"
    assert (date_dir / "market_overview.json").exists()
    assert (date_dir / "screening_candidates.json").exists()
    assert (date_dir / "review_data.json").exists()
    assert not (date_dir / "review.html").exists()
    status = json.loads((date_dir / "_pipeline_status.json").read_text(encoding="utf-8"))
    assert status["llm"] is False
    manifest = json.loads((date_dir / "_data_manifest.json").read_text(encoding="utf-8"))
    assert manifest["llm"] is False
    assert manifest["calculation_version"] == "quantx-data-v1"
    assert manifest["artifact_count"] > 10
    assert manifest["sources"]["tushare"]["raw_sha256"]
    assert manifest["sources"]["tushare"]["normalized_sha256"]
    assert manifest["sources"]["tushare"]["raw_sha256"] != manifest["sources"]["tushare"]["normalized_sha256"]
    assert {item["dataset_id"] for item in manifest["fact_artifacts"]} == {
        "trading_calendar",
        "market_breadth_daily",
        "market_liquidity_daily",
        "margin_daily",
        "limit_event_daily",
        "limit_ladder_daily",
        "theme_observation_daily",
        "theme_member_daily",
        "sector_flow_daily",
        "sector_breadth_daily",
        "market_state_daily",
        "market_signal_daily",
        "screening_candidate_daily",
    }
    fact_repo = MarketFactRepository(root)
    assert fact_repo.get_market_breadth(date(2026, 8, 25))["up_count"].to_list() == [1]
    assert fact_repo.get_market_breadth(date(2026, 8, 25))["source"].to_list() == ["tickflow_enriched_aggregate"]
    assert fact_repo.get_market_liquidity(date(2026, 8, 25))[
        "total_amount_yi"
    ].to_list() == [2.3]
    assert fact_repo.get_margin_history(
        date(2026, 8, 20), date(2026, 8, 25), as_of=date(2026, 8, 25)
    )["financing_balance_yi"].to_list() == [100.0, 102.0]
    assert fact_repo.get_limit_events(date(2026, 8, 25))["symbol"].to_list() == ["000001"]
    assert fact_repo.get_limit_ladder(date(2026, 8, 25)).select(
        "board_height", "symbol"
    ).rows() == [(2, "000001")]
    assert fact_repo.get_theme_members(date(2026, 8, 25))["symbol"].to_list() == [
        "000001"
    ]
    state = fact_repo.get_market_state(date(2026, 8, 25)).row(0, named=True)
    assert state["algorithm_version"] == "quantx-data-v1"
    assert state["quality_level"] == "derived"
    assert set(
        fact_repo.get_screening_candidates(date(2026, 8, 25))[
            "algorithm_version"
        ].to_list()
    ) == {"quantx-rule-screen-v1", "pywencai-new-high-v1"}
    assert fact_repo.is_trading_day(date(2026, 8, 26)) is False


def test_scheduler_uses_canonical_calendar_and_local_partition_evidence(tmp_path):
    root = _fixture(tmp_path)
    assert run_pipeline(root, "20260825", recompute=True)["status"] == "complete"

    assert _trade_date_today(root, today=date(2026, 8, 25)) == "20260825"
    assert _trade_date_today(root, today=date(2026, 8, 26)) is None
    assert _trade_date_today(root, today=date(2026, 8, 27)) is None

    partition = root / "kline_daily" / "date=2026-08-27"
    partition.mkdir(parents=True)
    pl.DataFrame({"date": [date(2026, 8, 27)], "close": [1.0]}).write_parquet(
        partition / "part.parquet"
    )
    assert _trade_date_today(root, today=date(2026, 8, 27)) == "20260827"


def test_pipeline_is_idempotent_and_catalog_uses_pipeline_status(tmp_path):
    root = _fixture(tmp_path)
    first = run_pipeline(root, "20260825", recompute=True)
    overview_before = json.loads((root / "quantx" / "20260825" / "market_overview.json").read_text(encoding="utf-8"))
    second = run_pipeline(root, "20260825", recompute=True)
    overview_after = json.loads((root / "quantx" / "20260825" / "market_overview.json").read_text(encoding="utf-8"))
    assert first["status"] == second["status"] == "complete"
    assert overview_before == overview_after
    catalog = build_catalog(root / "quantx")
    assert catalog["stats"]["complete"] == 1
    tables = load_tables(root / "quantx", "20260825")
    assert tables["market_overview"]["trade_date"] == "20260825"
    assert "sections" not in tables


def test_recompute_uses_tickflow_breadth_when_tushare_snapshot_is_missing(tmp_path, monkeypatch):
    root = _fixture(tmp_path)
    (root / "quantx" / "20260825" / "tushare.json").unlink()

    def network_must_not_run(*args, **kwargs):
        raise AssertionError("recompute attempted network collection")

    monkeypatch.setattr(collectors, "_collect_tushare", network_must_not_run)
    monkeypatch.setattr(collectors, "_collect_legacy", network_must_not_run)
    result = run_pipeline(root, "20260825", recompute=True)
    assert result["status"] == "degraded"
    assert any("tushare" in warning for warning in result["warnings"])
    breadth = MarketFactRepository(root).get_market_breadth(date(2026, 8, 25))
    assert breadth["source"].to_list() == ["tickflow_enriched_aggregate"]


def test_required_limit_dataset_uses_fallback_when_pywencai_is_missing(tmp_path):
    root = _fixture(tmp_path)
    date_dir = root / "quantx" / "20260825"
    (date_dir / "pywencai.json").unlink()

    result = run_pipeline(root, "20260825", recompute=True)

    assert result["status"] == "degraded"
    assert any("limit_event_daily" in warning for warning in result["warnings"])
    events = MarketFactRepository(root).get_limit_events(date(2026, 8, 25))
    assert events["source"].unique().to_list() == ["zhangtingke"]
    assert events["is_fallback"].all()


def test_failed_run_keeps_last_published_tables(tmp_path):
    root = _fixture(tmp_path)
    first = run_pipeline(root, "20260825", recompute=True)
    assert first["status"] == "complete"
    date_dir = root / "quantx" / "20260825"
    before = (date_dir / "market_overview.json").read_text(encoding="utf-8")
    (date_dir / "tushare.json").unlink()
    (date_dir / "normalized" / "tushare.json").unlink()
    (
        root
        / "kline_daily_enriched"
        / "date=2026-08-25"
        / "part.parquet"
    ).unlink()
    failed = run_pipeline(root, "20260825", recompute=True)
    assert failed["status"] == "failed"
    assert (date_dir / "market_overview.json").read_text(encoding="utf-8") == before
    assert json.loads((date_dir / "_pipeline_status.json").read_text(encoding="utf-8"))["status"] == "failed"


def test_source_retry_keeps_full_source_contract(tmp_path, monkeypatch):
    root = _fixture(tmp_path)
    initial = run_pipeline(root, "20260825", recompute=True)
    assert initial["status"] == "complete"
    calls: list[str] = []
    original = collectors.collect_source

    def offline_retry(spec, trade_date, output_dir):
        if spec.name != "pywencai":
            raise AssertionError(f"unexpected network retry: {spec.name}")
        payload = json.loads((root / "quantx" / trade_date / "pywencai.json").read_text(encoding="utf-8"))
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "pywencai.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def observe(spec, *args, **kwargs):
        calls.append(spec.name)
        return original(spec, *args, **kwargs)

    monkeypatch.setattr("app.quantx_data.source_manager._collect_with_timeout", offline_retry)
    monkeypatch.setattr("app.quantx_data.pipeline.collect_source", observe)
    retried = run_pipeline(root, "20260825", retry_sources=["pywencai"])
    assert retried["status"] == "complete"
    assert calls == list(SOURCE_NAMES)
    assert (root / "quantx" / "20260825" / "market_overview.json").exists()


def test_multiday_snapshot_contains_all_deterministic_dashboard_sections(tmp_path):
    quantx_dir = tmp_path / "quantx"
    for index, trade_date in enumerate(("20260819", "20260820", "20260821", "20260824", "20260825"), start=1):
        _fixture(tmp_path, trade_date)
        result = run_pipeline(tmp_path, trade_date, recompute=True)
        assert result["status"] == "complete"
        iso_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
        state_path = tmp_path / "market_state_daily" / f"date={iso_date}" / "part.parquet"
        pl.read_parquet(state_path).with_columns(
            pl.lit(20 + index * 10).alias("market_heat_score"),
            pl.lit(30 + index * 8).alias("up_ratio_pct"),
        ).write_parquet(state_path)
        sector_path = tmp_path / "sector_flow_daily" / f"date={iso_date}" / "part.parquet"
        pl.read_parquet(sector_path).filter(
            pl.col("source") == "sector_fund_flow_s4"
        ).head(1).with_columns(
            pl.lit("人工智能").alias("sector_id"),
            pl.lit("人工智能").alias("sector_name"),
            pl.lit(float(index)).alias("pct_chg"),
            pl.lit(index * 2.0).alias("net_inflow_yi"),
            pl.lit(100.0 + index).alias("amount_yi"),
        ).write_parquet(sector_path)

    snapshot = build_multiday_snapshot(quantx_dir, "20260825")

    assert snapshot["llm"] is False
    assert set(snapshot["window_signals"]) == {"5", "10", "20"}
    assert snapshot["window_signals"]["5"]["market"]["direction"] == "升温"
    assert len(snapshot["calendar"]) == 5
    assert snapshot["window_statistics"]["5"]["market_heat"]["max"] == 70
    assert snapshot["theme_lifecycle"]["current"][0]["name"] == "人工智能"
    assert snapshot["factor_attribution"][0]["name"] == "人工智能"
    assert set(snapshot["opportunity_radar"]) >= {"themes", "sectors", "stocks", "coverage_confidence"}
    continuity = snapshot["sector_flow_continuity"]
    assert continuity["industries"][0]["name"] == "人工智能"
    assert continuity["semantics"] == "sector_flow_and_rule_candidates"
    assert continuity["basis"] == (
        "sector_flow_daily.net_inflow_yi + screening_candidate_daily"
    )
    assert "core_stocks" not in continuity
    assert "institution_continuity" not in snapshot
    assert snapshot["data_coverage"]["sector_flow_days"] == 5
    assert "institution_days" not in snapshot["data_coverage"]
    assert "review_decision" not in snapshot


def test_window_theme_structure_is_calculated_from_each_selected_window():
    records = []
    for index in range(20):
        themes = [
            {"name": "长期主线", "rank_strength": 70.0, "source_count": 2},
        ]
        if index < 10:
            themes.append({"name": "旧题材", "rank_strength": 80.0, "source_count": 2})
        if index >= 10:
            themes.append({"name": "中期题材", "rank_strength": 60.0, "source_count": 2})
        if index >= 15:
            themes.append(
                {
                    "name": "新升温题材",
                    "rank_strength": float(20 + (index - 15) * 15),
                    "source_count": 1,
                }
            )
        records.append(
            {
                "trade_date": f"202608{index + 1:02d}",
                "metrics": {},
                "themes": themes,
                "market_activity": {},
            }
        )

    five = _window_signal(records, 5)["themes"]
    ten = _window_signal(records, 10)["themes"]
    twenty = _window_signal(records, 20)["themes"]

    assert {row["name"] for row in five["mainline"]} == {"长期主线", "中期题材", "新升温题材"}
    assert {row["name"] for row in ten["mainline"]} == {"长期主线", "中期题材"}
    assert {row["name"] for row in twenty["mainline"]} == {"长期主线"}
    assert {row["name"] for row in twenty["warming"]} == {"中期题材", "新升温题材"}
    assert {row["name"] for row in twenty["cooling"]} == {"旧题材"}
    assert five["observed_days"] == 5
    assert twenty["observed_days"] == 20
    assert "institution" not in _window_signal(records, 5)


def test_opportunity_radar_publishes_five_and_twenty_day_views():
    records = []
    for index in range(20):
        records.append(
            {
                "trade_date": f"202608{index + 1:02d}",
                "themes": [
                    {
                        "name": "人工智能",
                        "rank_strength": 60 + index,
                        "lifecycle": "continuing",
                        "leaders": [{"code": "300001", "name": "龙头样本"}],
                    }
                ],
                "market_activity": {
                    "sectors": [
                        {
                            "name": "计算机",
                            "net_inflow_yi": 2.0,
                            "pct_chg": 1.0,
                        }
                    ],
                    "rule_candidates": [
                        {
                            "code": "300002",
                            "name": "规则样本",
                            "priority": "核心",
                            "source": "deterministic_rule_screen",
                        }
                    ],
                },
            }
        )

    radar = _opportunity_radar(records)

    assert radar["schema_version"] == "opportunity-radar-v2"
    assert set(radar["windows"]) == {"5", "20"}
    assert radar["themes"] == radar["windows"]["5"]["themes"]
    assert radar["windows"]["5"]["valid_days"] == 5
    assert radar["windows"]["20"]["valid_days"] == 20
    assert radar["windows"]["5"]["sectors"][0]["net_inflow_sum_yi"] == 10.0
    assert radar["windows"]["20"]["sectors"][0]["net_inflow_sum_yi"] == 40.0
    assert radar["windows"]["20"]["stocks"][0]["active_days"] == 20
    assert radar["windows"]["20"]["stocks"][0]["priority"] == "核心"


def test_multiday_rebuild_uses_only_canonical_facts_after_publication(tmp_path):
    quantx_dir = tmp_path / "quantx"
    for trade_date in ("20260821", "20260824", "20260825"):
        _fixture(tmp_path, trade_date)
        assert run_pipeline(tmp_path, trade_date, recompute=True)["status"] == "complete"
        date_dir = quantx_dir / trade_date
        for path in date_dir.glob("*.json"):
            if path.name == "multiday_snapshot.json":
                path.unlink()
                continue
            if path.name not in {"_pipeline_status.json", "_data_manifest.json"}:
                path.unlink()

    snapshot = build_multiday_snapshot(quantx_dir, "20260825")

    assert snapshot["trade_date"] == "20260825"
    assert snapshot["data_coverage"]["window_days"] == 3
    assert snapshot["calendar"][-1]["trade_date"] == "20260825"
    assert snapshot["theme_lifecycle"]["current"]
    assert snapshot["opportunity_radar"]["stocks"]


def test_multiday_rebuild_persists_versioned_snapshots_and_catalog_stays_compact(tmp_path):
    for trade_date in ("20260824", "20260825"):
        _fixture(tmp_path, trade_date)
        assert run_pipeline(tmp_path, trade_date, recompute=True)["status"] == "complete"

    result = rebuild_multiday_snapshots(tmp_path / "quantx")

    assert result["rebuilt"] == 2
    payload = json.loads((tmp_path / "quantx" / "20260825" / "multiday_snapshot.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "tickflow-quantx-multiday-v3"
    catalog = json.loads((tmp_path / "quantx" / "catalog.json").read_text(encoding="utf-8"))
    assert "window_signals" not in catalog["records"][-1]
    assert catalog["records"][-1]["multiday_available"] is True


def test_multiday_api_get_is_read_only_and_rebuild_is_explicit_post(tmp_path):
    _fixture(tmp_path, "20260825")
    assert run_pipeline(tmp_path, "20260825", recompute=True)["status"] == "complete"
    catalog_path = tmp_path / "quantx" / "catalog.json"
    before = catalog_path.stat().st_mtime_ns
    app = FastAPI()
    app.include_router(quantx_data_router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/quantx-data/catalog")
        assert response.status_code == 200
        assert catalog_path.stat().st_mtime_ns == before
        multiday = client.get("/api/quantx-data/multiday/20260825")
        assert multiday.status_code == 200
        assert multiday.json()["llm"] is False
        rebuilt = client.post("/api/quantx-data/catalog/rebuild?trade_date=20260825")
        assert rebuilt.status_code == 200
        assert rebuilt.json()["rebuilt"] == 1


def test_tables_api_reads_canonical_facts_and_reports_legacy_drift(tmp_path):
    _fixture(tmp_path, "20260825")
    assert run_pipeline(tmp_path, "20260825", recompute=True)["status"] == "complete"
    date_dir = tmp_path / "quantx" / "20260825"
    legacy_breadth = json.loads((date_dir / "market_breadth.json").read_text(encoding="utf-8"))
    legacy_breadth["up_count"] = 999
    _write(date_dir / "market_breadth.json", legacy_breadth)

    app = FastAPI()
    app.include_router(quantx_data_router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    app.state.market_facts = MarketFactRepository(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/quantx-data/20260825/tables")

    assert response.status_code == 200
    payload = response.json()
    assert payload["market_breadth"]["up_count"] == 1
    assert payload["market_liquidity"]["top5pct_amount_ratio_pct"] == 43.48
    assert payload["data_foundation"]["read_mode"] == "canonical_with_legacy_enrichment"
    breadth_status = payload["data_foundation"]["reconciliation"]["market_breadth_daily"]
    assert breadth_status["status"] == "mismatch"
    assert breadth_status["differences"]["up_count"] == {"canonical": 1, "legacy": 999}


def test_observability_api_reports_source_fact_view_and_publication_lineage(tmp_path):
    _fixture(tmp_path, "20260825")
    assert run_pipeline(tmp_path, "20260825", recompute=True)["status"] == "complete"
    app = FastAPI()
    app.include_router(quantx_data_router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    app.state.market_facts = MarketFactRepository(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/quantx-data/observability/20260825?pipeline_job_id=job-demo"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_job_id"] == "job-demo"
    assert payload["quantx_run_id"].startswith("20260825-")
    assert len(payload["sources"]) == 12
    assert len(payload["facts"]) == 13
    assert payload["fact_summary"]["present_partition_count"] == 13
    assert payload["view"]["schema_version"] == "quantx-review.v2"
    assert payload["view"]["fallback_count"] == 0
    assert payload["reconciliation"]["status"] == "ok"
    assert payload["multiday"]["published"] is True
    assert payload["catalog"]["published"] is True
    tushare = next(item for item in payload["sources"] if item["source_id"] == "tushare")
    assert tushare["required"] is True
    assert tushare["freshness"] == "reused"
    assert tushare["manifest_health"] == "present"


def test_review_api_reads_published_snapshot_after_sources_are_removed(tmp_path):
    _fixture(tmp_path, "20260825")
    assert run_pipeline(tmp_path, "20260825", recompute=True)["status"] == "complete"
    date_dir = tmp_path / "quantx" / "20260825"
    cached = json.loads((date_dir / "review_data.json").read_text(encoding="utf-8"))
    cached["metric_strip"]["up_count"] = 999
    cached["sections"]["s2"]["themes_pywencai"] = []
    cached["sections"]["s2"]["new_high"] = {
        "status": "unavailable",
        "stocks": [],
    }
    cached["sections"]["s1"]["congestion"] = {
        "latest": {"congestion_pct": 999},
        "table": [],
    }
    cached["sections"]["s1"]["kline_history"] = []
    cached["sections"]["s1"]["width_heat"] = [{"code": "poisoned", "ma20": 999}]
    cached["sections"]["s3"]["ladder_grid"] = []
    cached["sections"]["s3"]["advance_history"] = []
    cached["sections"]["s3"]["ebb_signals"] = []
    cached["sections"]["s3"]["crash_signals"] = []
    cached["sections"]["s2"]["participation"] = {"conditions": []}
    cached["sections"]["s2"]["ebb_risk"] = {"signal_count": 999}
    cached["sections"]["s4"]["sector_flow"] = {"top_in": [], "top_out": []}
    cached["sections"]["s5"]["candidates"] = []
    cached["sections"]["s6"]["position"] = {"band": "错误缓存"}
    cached["sections"]["s6"]["scenes"] = []
    cached["sections"]["s0"]["diagnosis"] = [{"name": "错误缓存"}]
    cached["sections"]["s0"]["risks"] = [{"name": "错误缓存"}]
    cached["sections"]["s3"]["emotion_zones"] = {
        "market_heat": "错误缓存",
        "short_term": "错误缓存",
        "trend": "错误缓存",
    }
    cached["emotion"]["height_trend"] = {"latest_max_board": 999}
    cached["emotion"]["daily_summary"] = "错误缓存"
    _write(date_dir / "review_data.json", cached)
    for source in SOURCE_NAMES:
        (date_dir / f"{source}.json").unlink()

    class FakeIndexRepository:
        def __init__(self, data_dir):
            self.store = SimpleNamespace(data_dir=data_dir)

        def get_index_daily(self, symbol, start, end, columns=None):
            if symbol == "000985.SH":
                dates = [date(2026, 7, 27) + timedelta(days=index) for index in range(30)]
                closes = [100.0 + index + index % 3 for index in range(30)]
                return pl.DataFrame(
                    {
                        "symbol": [symbol] * 30,
                        "date": dates,
                        "open": [value - 0.5 for value in closes],
                        "high": [value + 2.0 for value in closes],
                        "low": [value - 1.0 for value in closes],
                        "close": closes,
                        "volume": [1_000_000.0 + index for index in range(30)],
                    }
                )
            if symbol not in {
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000688.SH",
                "899050.BJ",
            }:
                return pl.DataFrame(
                    schema={"symbol": pl.String, "date": pl.Date, "close": pl.Float64}
                )
            return pl.DataFrame(
                {
                    "symbol": [symbol, symbol],
                    "date": [date(2026, 8, 24), date(2026, 8, 25)],
                    "close": [10.0, 11.0],
                }
            )

    app = FastAPI()
    app.include_router(quantx_router)
    app.state.repo = FakeIndexRepository(tmp_path)
    app.state.market_facts = MarketFactRepository(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/quantx/review/20260825/data")

    assert response.status_code == 200
    assert set(response.json()["sections"]) == {f"s{index}" for index in range(7)}
    assert response.json()["metric_strip"]["total_amount_yi"] == 2.3
    assert response.json()["metric_strip"]["up_count"] == 1
    assert response.json()["sections"]["s1"]["margin"]["date"] == "20260824"
    assert response.json()["sections"]["s2"]["themes_pywencai"]
    assert response.json()["sections"]["s2"]["new_high"]["status"] == "ok"
    assert response.json()["sections"]["s2"]["new_high"]["stocks"][0][
        "code"
    ] == "300002"
    assert set(response.json()["sections"]["s2"]["new_high"]["windows"]) == {
        "1",
        "5",
        "10",
        "20",
    }
    congestion = response.json()["sections"]["s1"]["congestion"]
    assert congestion["latest"]["congestion_pct"] == 43.48
    assert congestion["table"][-1][2:] == [1.0, 2.3, 43.48]
    assert response.json()["sections"]["s3"]["ladder_grid"]
    assert response.json()["sections"]["s3"]["ladder_detail"][0]["turnover_pct"] == 12.34
    assert response.json()["sections"]["s3"]["ladder_detail"][0]["amount_yi"] == 8.76
    height_history = response.json()["sections"]["s3"]["height_history"]
    assert height_history[-1]["date"] == "20260825"
    assert height_history[-1]["height"] == 2
    assert height_history[-1]["name"] == "甲"
    assert "sections.s3.ladder_detail" in response.json()["data_foundation"][
        "canonical_fields"
    ]
    assert "sections.s3.height_history" in response.json()["data_foundation"][
        "canonical_fields"
    ]
    assert "sections.s3.ladder_detail.supplemental_fields" not in response.json()[
        "data_foundation"
    ]["presentation_cache_fields"]
    assert response.json()["sections"]["s3"]["advance_history"][-1][
        "date"
    ] == "20260825"
    assert len(response.json()["sections"]["s3"]["ebb_signals"]) == 4
    assert len(response.json()["sections"]["s3"]["crash_signals"]) == 3
    assert len(response.json()["sections"]["s2"]["participation"]["conditions"]) == 4
    assert response.json()["sections"]["s2"]["ebb_risk"]["signal_count"] == 1
    assert response.json()["sections"]["s4"]["sector_flow"]["top_in"]
    assert response.json()["sections"]["s5"]["candidates"]
    assert len(response.json()["sections"]["s5"]["candidates"]) <= 10
    assert response.json()["sections"]["s5"]["candidate_funnel"][
        "algorithm_version"
    ] == "quantx-candidate-funnel-v1"
    assert "sections.s5.candidate_funnel" in response.json()["data_foundation"][
        "derived_fields"
    ]
    assert response.json()["sections"]["s6"]["position"]["band"] != "错误缓存"
    assert len(response.json()["sections"]["s6"]["scenes"]) == 3
    assert response.json()["sections"]["s0"]["diagnosis"][0]["name"] == "市场热度"
    assert response.json()["sections"]["s0"]["risks"][0]["name"] != "错误缓存"
    assert response.json()["sections"]["s3"]["emotion_zones"]["market_heat"] != "错误缓存"
    assert response.json()["emotion"]["height_trend"]["latest_max_board"] == 2
    assert response.json()["emotion"]["daily_summary"] != "错误缓存"
    index = response.json()["sections"]["s1"]["indexes"][0]
    assert index["code"] == "000001.SH"
    assert index["name"] == "上证指数"
    assert index["close"] == 11.0
    assert index["pct_chg"] == 10.0
    bse_50 = next(
        row
        for row in response.json()["sections"]["s1"]["indexes"]
        if row["code"] == "899050.BJ"
    )
    assert bse_50["name"] == "北证50"
    assert bse_50["close"] == 11.0
    assert bse_50["pct_chg"] == 10.0
    assert all(
        row["code"] != "899050.BJ"
        for row in response.json()["metric_strip"]["indexes"]
    )
    all_a = next(
        row
        for row in response.json()["sections"]["s1"]["indexes"]
        if row["code"] == "000985.CSI"
    )
    assert all_a["name"] == "中证全指"
    assert all_a["close"] == 131.0
    history = response.json()["sections"]["s1"]["kline_history"]
    assert len(history) == 30
    assert history[-1]["date"] == "20260825"
    assert history[-1]["ma5"] == 128.2
    assert history[-1]["cci5"] is not None
    assert response.json()["data_foundation"]["read_mode"] == "canonical_view_v2"
    assert "sections.s1.congestion" in response.json()["data_foundation"][
        "canonical_fields"
    ]
    assert "sections.s1.congestion" not in response.json()["data_foundation"][
        "presentation_cache_fields"
    ]
    assert "sections.s1.kline_history" in response.json()["data_foundation"][
        "canonical_fields"
    ]
    assert "sections.s1.kline_history" not in response.json()["data_foundation"][
        "presentation_cache_fields"
    ]
    width_heat = response.json()["sections"]["s1"]["width_heat"]
    assert [row["code"] for row in width_heat] == ["801010.SI", "801030.SI"]
    assert width_heat[0] == {
        "code": "801010.SI",
        "name": "农林牧渔",
        "ma5": 75.0,
        "ma10": 65.0,
        "ma20": 55.0,
        "ma60": 45.0,
    }
    assert "sections.s1.width_heat" in response.json()["data_foundation"][
        "canonical_fields"
    ]
    assert "sections.s1.width_heat" not in response.json()["data_foundation"][
        "presentation_cache_fields"
    ]
    foundation = response.json()["data_foundation"]
    assert foundation["schema_version"] == "quantx-review.v2"
    assert "sections.s0.diagnosis" in foundation["derived_fields"]
    assert "sections.s0.diagnosis" not in foundation["presentation_cache_fields"]
    assert foundation["presentation_cache_read"] is False
    assert foundation["source_json_read"] is False
    assert foundation["view_algorithm_version"] == "quantx-review-view-v1"
    assert foundation["derived_field_status"]["emotion.height_trend"][
        "status"
    ] == "available"
    assert foundation["fallback_fields"] == []
    assert foundation["implicit_cache_fields"] == []


def test_new_high_clusters_group_concepts_and_industry_windows(tmp_path):
    for trade_date in ("20260819", "20260820", "20260821", "20260824", "20260825"):
        _fixture(tmp_path, trade_date)
        assert run_pipeline(tmp_path, trade_date, recompute=True)["status"] == "complete"

    concept = ExtConfig(
        id="new_high_concepts",
        label="新高概念映射",
        mode="snapshot",
        fields=[
            ExtField("symbol", "string", "股票代码"),
            ExtField("concept", "string", "所属概念"),
        ],
    )
    industry = ExtConfig(
        id="new_high_industries",
        label="新高行业映射",
        mode="snapshot",
        fields=[
            ExtField("symbol", "string", "股票代码"),
            ExtField("industry", "string", "所属行业"),
        ],
    )
    store = ExtConfigStore(tmp_path)
    store.upsert(concept)
    store.upsert(industry)
    pl.DataFrame(
        {
            "symbol": ["300002.SZ"],
            "concept": ["百日新高;趋势股;人工智能;机器人"],
        }
    ).write_parquet(tmp_path / "ext_data" / concept.id / "part.parquet")
    pl.DataFrame(
        {
            "symbol": ["300002.SZ"],
            "industry": ["信息技术-软件开发-应用软件"],
        }
    ).write_parquet(tmp_path / "ext_data" / industry.id / "part.parquet")

    result = build_new_high_clusters(
        MarketFactRepository(tmp_path),
        date(2026, 8, 25),
    )

    assert result["total_stocks"] == 1
    assert result["coverage_pct"] == {
        "concept": 100.0,
        "industry_level1": 100.0,
        "industry_level2": 100.0,
    }
    today_concepts = result["windows"]["1"]["dimensions"]["concept"]
    assert {row["name"] for row in today_concepts} == {"人工智能", "机器人"}
    assert {row["weighted_share_pct"] for row in today_concepts} == {50.0}
    assert result["windows"]["5"]["dimensions"]["industry_level1"][0]["name"] == "信息技术"
    assert result["windows"]["5"]["dimensions"]["industry_level2"][0]["name"] == "软件开发"
    assert result["windows"]["5"]["dimensions"]["concept"][0]["status"] == "持续"

    members = build_new_high_cluster_members(
        MarketFactRepository(tmp_path),
        date(2026, 8, 25),
        dimension="concept",
        window=5,
        name="人工智能",
    )
    assert members["cluster_name"] == "人工智能"
    assert members["current_count"] == 1
    assert members["window_count"] == 1
    assert members["members"] == [
        {
            "code": "300002",
            "name": "新高样本",
            "pct_chg": 5.0,
            "current": True,
            "active_days": 5,
            "first_seen": "20260819",
            "last_seen": "20260825",
        }
    ]

    bundle = build_new_high_cluster_member_bundle(
        MarketFactRepository(tmp_path),
        date(2026, 8, 25),
    )
    assert bundle["mapping_semantics"] == "latest_ext_snapshot_proxy"
    assert bundle["datasets"]["concept|5|人工智能"] == members
    assert len(bundle["datasets"]) == 16

    app = FastAPI()
    app.include_router(quantx_data_router)
    app.state.market_facts = MarketFactRepository(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/api/quantx-data/new-high/20260825/members",
            params={"dimension": "concept", "window": 5, "name": "人工智能"},
        )
        bundle_response = client.get(
            "/api/quantx-data/new-high/20260825/member-bundle"
        )
    assert response.status_code == 200, response.text
    assert response.json()["members"][0]["code"] == "300002"
    assert bundle_response.status_code == 200, bundle_response.text
    assert bundle_response.json()["datasets"]["concept|5|人工智能"]["members"][0]["code"] == "300002"


def test_review_api_v2_survives_removed_json_and_rejects_retired_v1(tmp_path):
    _fixture(tmp_path, "20260825")
    assert run_pipeline(tmp_path, "20260825", recompute=True)["status"] == "complete"
    review_path = tmp_path / "quantx" / "20260825" / "review_data.json"

    class EmptyIndexRepository:
        def __init__(self, data_dir):
            self.store = SimpleNamespace(data_dir=data_dir)

        def get_index_daily(self, symbol, start, end, columns=None):
            return pl.DataFrame()

    app = FastAPI()
    app.include_router(quantx_router)
    app.state.repo = EmptyIndexRepository(tmp_path)
    app.state.market_facts = MarketFactRepository(tmp_path)

    with TestClient(app) as client:
        schema_response = client.get("/api/quantx/review/schema/v2")
        retired_v1 = client.get(
            "/api/quantx/review/20260825/data?view_version=v1"
        )
        review_path.unlink()
        canonical = client.get("/api/quantx/review/20260825/data")
        retired_v1_after_unlink = client.get(
            "/api/quantx/review/20260825/data?view_version=v1"
        )

    assert schema_response.status_code == 200
    assert schema_response.json()["schema"]["title"] == "QuantXReviewResponseV2"
    assert schema_response.json()["field_contracts"][
        "metric_strip.total_amount_yi"
    ]["unit"] == "CNY_100M"
    assert retired_v1.status_code == 422
    assert canonical.status_code == 200
    assert canonical.json()["data_foundation"]["schema_version"] == (
        "quantx-review.v2"
    )
    assert canonical.json()["data_foundation"]["source_json_read"] is False
    assert retired_v1_after_unlink.status_code == 422


def test_history_migration_is_dry_run_by_default_and_preserves_legacy(tmp_path):
    _fixture(tmp_path, "20260825")
    legacy_path = tmp_path / "quantx" / "20260825" / "tushare.json"
    legacy_before = legacy_path.read_bytes()

    preview = migrate_quantx_history(tmp_path)
    assert preview["dry_run"] is True
    assert preview["eligible"] == ["20260825"]
    assert not (tmp_path / "market_breadth_daily").exists()

    applied = migrate_quantx_history(tmp_path, apply=True)
    assert applied["migrated"] == ["20260825"]
    assert legacy_path.read_bytes() == legacy_before
    migration = json.loads(
        (tmp_path / "quantx" / "20260825" / "_market_facts_migration.json").read_text(encoding="utf-8")
    )
    assert set(migration["reconciliation"]) == {
        "market_breadth_daily",
        "market_liquidity_daily",
        "limit_event_daily",
        "theme_observation_daily",
        "sector_flow_daily",
    }
    assert migration["legacy_preserved"] is True
    assert (tmp_path / "quantx" / "20260825" / "review_data.json").is_file()
    assert MarketFactRepository(tmp_path).get_market_breadth(date(2026, 8, 25)).height == 1

    repeated = migrate_quantx_history(tmp_path, apply=True)
    assert repeated["skipped_existing"] == ["20260825"]


def test_history_migration_can_backfill_calendar_from_published_breadth(tmp_path):
    root = _fixture(tmp_path)
    assert run_pipeline(root, "20260825", recompute=True)["status"] == "complete"
    breadth_path = root / "market_breadth_daily" / "date=2026-08-25" / "part.parquet"
    breadth_before = breadth_path.read_bytes()
    for relative in (
        "quantx/20260825/tushare.json",
        "quantx/20260825/normalized/tushare.json",
    ):
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("trade_calendar", None)
        _write(path, payload)
    (root / "trading_calendar" / "date=2026-08-25" / "part.parquet").unlink()
    (root / "kline_daily_enriched" / "date=2026-08-25" / "part.parquet").unlink()

    preview = migrate_quantx_history(root)

    assert preview["eligible"] == ["20260825"]
    assert preview["skipped_incomplete"] == {}
    applied = migrate_quantx_history(root, apply=True)
    assert applied["migrated"] == ["20260825"]
    assert breadth_path.read_bytes() == breadth_before
    assert MarketFactRepository(root).is_trading_day(date(2026, 8, 25)) is True


def test_history_migration_rebuilds_only_selected_stale_dataset(tmp_path):
    root = _fixture(tmp_path)
    assert migrate_quantx_history(root, apply=True)["migrated"] == ["20260825"]
    breadth_path = root / "market_breadth_daily" / "date=2026-08-25" / "part.parquet"
    breadth_before = breadth_path.read_bytes()
    marker_path = root / "quantx" / "20260825" / "_market_facts_migration.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["dataset_versions"]["screening_candidate_daily"] = 1
    _write(marker_path, marker)

    preview = migrate_quantx_history(
        root,
        datasets=(DatasetId.SCREENING_CANDIDATE_DAILY,),
    )
    assert preview["eligible"] == ["20260825"]
    applied = migrate_quantx_history(
        root,
        apply=True,
        datasets=(DatasetId.SCREENING_CANDIDATE_DAILY,),
    )

    assert applied["migrated"] == ["20260825"]
    assert breadth_path.read_bytes() == breadth_before
    candidates = MarketFactRepository(root).get_screening_candidates(
        date(2026, 8, 25)
    )
    assert candidates.filter(pl.col("candidate_type") == "new_high_100d").height == 1
    repeated = migrate_quantx_history(
        root,
        apply=True,
        datasets=(DatasetId.SCREENING_CANDIDATE_DAILY,),
    )
    assert repeated["skipped_existing"] == ["20260825"]


def test_targeted_history_migration_does_not_publish_empty_partition(tmp_path):
    root = _fixture(tmp_path)
    legulegu_path = root / "quantx" / "20260825" / "legulegu.json"
    legulegu = json.loads(legulegu_path.read_text(encoding="utf-8"))
    legulegu["width_api"] = {}
    _write(legulegu_path, legulegu)

    result = migrate_quantx_history(
        root,
        apply=True,
        datasets=(DatasetId("sector_breadth_daily"),),
    )

    assert result["migrated"] == []
    assert result["skipped_incomplete"] == {
        "20260825": "no rows for targeted datasets: sector_breadth_daily"
    }
    assert not (root / "sector_breadth_daily" / "date=2026-08-25").exists()


def test_history_migration_accepts_legacy_legulegu_width_sidecar(tmp_path):
    root = _fixture(tmp_path)
    legulegu_path = root / "quantx" / "20260825" / "legulegu.json"
    legulegu = json.loads(legulegu_path.read_text(encoding="utf-8"))
    primary = legulegu.pop("width_api")["ma_market_width_primary"]
    _write(legulegu_path, legulegu)
    _write(
        root / "quantx" / "20260825" / "legulegu_width.json",
        {"https://legulegu.com/api/stockdata/member-ship/ma-market-width": primary},
    )

    result = migrate_quantx_history(
        root,
        apply=True,
        datasets=(DatasetId.SECTOR_BREADTH_DAILY,),
    )

    assert result["migrated"] == ["20260825"]
    frame = MarketFactRepository(root).get_sector_breadth(date(2026, 8, 25))
    assert frame.height == 2
    assert set(frame["dimension"].to_list()) == {"sw_level1"}
