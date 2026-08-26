from __future__ import annotations

import json
from pathlib import Path

from app.quantx_data.catalog import build_catalog, load_tables
from app.quantx_data import collectors
from app.quantx_data.pipeline import run_pipeline


SOURCE_NAMES = (
    "tushare", "akshare", "ths_hot", "zhangtingke", "zhangtingjun", "pywencai",
    "duanxianxia", "deepq", "legulegu", "quicktiny", "dabanke", "sector_fund_flow_s4",
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fixture(root: Path, trade_date: str = "20260825") -> Path:
    date_dir = root / "quantx" / trade_date
    daily = [
        {"ts_code": "000001.SZ", "close": 10, "pct_chg": 2.0, "amount": 100000},
        {"ts_code": "600000.SH", "close": 9, "pct_chg": -1.0, "amount": 80000},
        {"ts_code": "300001.SZ", "close": 20, "pct_chg": 0.0, "amount": 50000},
    ]
    payloads = {
        "tushare": {"trade_date": trade_date, "status": "ok", "daily": daily, "indexes": {"000001.SH": {"code": "000001.SH", "name": "上证指数", "close": 3000, "pct_chg": 0.5}}},
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
    return root


def test_pipeline_publishes_structured_snapshot_without_editorial_artifacts(tmp_path):
    root = _fixture(tmp_path)
    result = run_pipeline(root, "20260825", recompute=True)
    assert result["status"] == "complete"
    assert result["stages"][-1] == "published"
    date_dir = root / "quantx" / "20260825"
    assert (date_dir / "market_overview.json").exists()
    assert (date_dir / "screening_candidates.json").exists()
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


def test_recompute_is_offline_and_fails_when_required_snapshot_is_missing(tmp_path, monkeypatch):
    root = _fixture(tmp_path)
    (root / "quantx" / "20260825" / "tushare.json").unlink()

    def network_must_not_run(*args, **kwargs):
        raise AssertionError("recompute attempted network collection")

    monkeypatch.setattr(collectors, "_collect_tushare", network_must_not_run)
    monkeypatch.setattr(collectors, "_collect_legacy", network_must_not_run)
    result = run_pipeline(root, "20260825", recompute=True)
    assert result["status"] == "failed"
    assert any("tushare" in error for error in result["errors"])


def test_failed_run_keeps_last_published_tables(tmp_path):
    root = _fixture(tmp_path)
    first = run_pipeline(root, "20260825", recompute=True)
    assert first["status"] == "complete"
    date_dir = root / "quantx" / "20260825"
    before = (date_dir / "market_overview.json").read_text(encoding="utf-8")
    (date_dir / "tushare.json").unlink()
    (date_dir / "normalized" / "tushare.json").unlink()
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
