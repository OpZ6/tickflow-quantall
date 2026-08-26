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
from app.market_facts.repository import MarketFactRepository
from app.quantx_data import collectors
from app.quantx_data.catalog import build_catalog, load_tables
from app.quantx_data.migration import migrate_quantx_history
from app.quantx_data.multiday import build_multiday_snapshot, rebuild_multiday_snapshots
from app.quantx_data.pipeline import run_pipeline
from app.quantx_data.scheduler import _trade_date_today

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
        "zhangtingke": {"trade_date": trade_date, "status": "ok", "ladder_by_height": {"2": [{"code": "000001", "name": "甲", "limit_times": 2}]}, "ladder_stocks": [{"code": "000001", "name": "甲", "limit_times": 2}]},
        "zhangtingjun": {"trade_date": trade_date, "status": "ok"},
        "pywencai": {"trade_date": trade_date, "status": "ok", "limit_up": {"count": 1, "stocks": [{"code": "000001", "name": "甲", "limit_times": 2, "concepts": ["人工智能"]}], "ladder": {"2": ["甲"]}, "themes": [{"name": "人工智能", "count": 1}]}, "broken_board": {"count": 0, "stocks": []}, "limit_down": {"count": 0, "stocks": []}, "seal_rate": 100, "broken_rate": 0},
        "duanxianxia": {"trade_date": trade_date, "status": "ok"},
        "deepq": {"trade_date": trade_date, "status": "ok"},
        "legulegu": {"trade_date": trade_date, "status": "ok"},
        "quicktiny": {"trade_date": trade_date, "status": "ok"},
        "dabanke": {"trade_date": trade_date, "status": "ok"},
        "sector_fund_flow_s4": {"trade_date": trade_date, "status": "ok", "sectors": [{"name": "人工智能", "pct_chg": 1.2, "net_inflow_yi": 3.5}]},
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
        "market_state_daily",
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
    assert fact_repo.get_screening_candidates(date(2026, 8, 25))[
        "algorithm_version"
    ].to_list() == ["quantx-rule-screen-v1"]
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

    def offline_retry(module_name, trade_date, output_dir, source):
        if source != "pywencai":
            raise AssertionError(f"unexpected network retry: {source}")
        payload = json.loads((root / "quantx" / trade_date / "pywencai.json").read_text(encoding="utf-8"))
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "pywencai.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def observe(spec, *args, **kwargs):
        calls.append(spec.name)
        return original(spec, *args, **kwargs)

    monkeypatch.setattr(collectors, "_collect_legacy", offline_retry)
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
    assert snapshot["institution_continuity"]["industries"][0]["name"] == "人工智能"
    assert "review_decision" not in snapshot


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
    assert payload["schema_version"] == "tickflow-quantx-multiday-v1"
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
    assert payload["data_foundation"]["read_mode"] == "canonical_with_legacy_enrichment"
    breadth_status = payload["data_foundation"]["reconciliation"]["market_breadth_daily"]
    assert breadth_status["status"] == "mismatch"
    assert breadth_status["differences"]["up_count"] == {"canonical": 1, "legacy": 999}


def test_review_api_reads_published_snapshot_after_sources_are_removed(tmp_path):
    _fixture(tmp_path, "20260825")
    assert run_pipeline(tmp_path, "20260825", recompute=True)["status"] == "complete"
    date_dir = tmp_path / "quantx" / "20260825"
    for source in SOURCE_NAMES:
        (date_dir / f"{source}.json").unlink()

    app = FastAPI()
    app.include_router(quantx_router)
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    app.state.market_facts = MarketFactRepository(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/quantx/review/20260825/data")

    assert response.status_code == 200
    assert set(response.json()["sections"]) == {f"s{index}" for index in range(7)}
    assert response.json()["metric_strip"]["total_amount_yi"] == 2.3
    assert response.json()["sections"]["s1"]["margin"]["date"] == "20260824"


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
