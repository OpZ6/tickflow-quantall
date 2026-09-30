from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.market_lab import router
from app.quantx_data.new_high_clusters import load_security_memberships, load_ths_memberships
from app.services.ext_data import ExtConfig, ExtConfigStore, ExtField
from app.services.market_lab import _aggregate_sector_returns, _attach_dimension
from app.stock_pools.topic_cluster import build_topic_assignment
from app.stock_pools.topics import topic_labels


def test_ths_preserves_names_excludes_foreign_sources_and_keeps_quantx_default(tmp_path):
    store = ExtConfigStore(tmp_path)
    for config_id, field, value in [
        ("ext_gn_ths", "所属概念", "AI PC;WiFi 6;DRG/DIP;人工智能;高股息精选;沪股通"),
        ("ext_hy_ths", "所属同花顺行业", "信息技术-计算机设备-其他设备"),
        ("foreign", "所属概念", "电力"),
    ]:
        store.upsert(ExtConfig(id=config_id, label=config_id, mode="snapshot",
                              fields=[ExtField(name="symbol", dtype="string"), ExtField(name=field, dtype="string")]))
        path = tmp_path / "ext_data" / config_id / "part.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"symbol": ["000001.SZ"], field: [value]}).write_parquet(path)
    result = load_ths_memberships(tmp_path)
    assert result["concept"]["000001"] == {"AI PC", "WiFi 6", "DRG/DIP", "人工智能"}
    assert result["attribute"]["000001"] == {"高股息精选"}
    assert result["industry_level2"]["000001"] == {"计算机设备"}
    assert "电力" in load_security_memberships(tmp_path)["concept"]["000001"]


def test_topic_matching_does_not_bridge_compounds_or_similar_names():
    terms = ["人工智能", "电力人工智能", "电力", "液冷储能", "储能", "液冷", "Micro LED", "OLED", "创新药", "F5G", "5G"]
    rows = [{"symbol": f"{2 * i + j + 1:06d}", "evidence_source": "ths_hot_concepts", "match_text": term}
            for i, term in enumerate(terms) for j in range(2)]
    result = build_topic_assignment(rows)
    assert result.label_of["人工智能"] == "人工智能"
    assert result.label_of["电力人工智能"] == "电力人工智能"
    assert result.label_of["液冷储能"] == "液冷储能"
    assert result.label_of["储能"] == "储能"
    assert result.label_of["Micro LED"] == "Micro LED"
    assert result.label_of["OLED"] == "OLED"
    assert result.label_of["F5G"] != result.label_of["5G"]
    assert topic_labels("Micro LED") == []
    assert topic_labels("CRO") == ["创新药\uff0fCRO"]
    composite = build_topic_assignment([
        {"symbol": code, "evidence_source": "ths_hot_concepts", "match_text": "创新药+电力"}
        for code in ["000001", "000002"]])
    assert set(composite.topics["000001"]) == {"创新药\uff0fCRO", "电力"}


def test_ths_replaces_inherited_vendor_classification(monkeypatch, tmp_path):
    monkeypatch.setattr("app.quantx_data.new_high_clusters.load_ths_memberships", lambda _: {
        "industry_level2": {"000001": {"计算机设备"}}, "concept": {"000001": {"人工智能"}}})
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    rows = pl.DataFrame({"symbol": ["000001.SZ"], "industry": ["电力"], "concept": ["其他来源"]})
    assert _attach_dimension(repo, rows, "industry", ths_only=True)["industry"].to_list() == ["计算机设备"]
    assert _attach_dimension(repo, rows, "concept", ths_only=True)["concept"].to_list() == ["人工智能"]


def test_multi_concept_return_does_not_shift_between_duplicate_stock_rows():
    rows = pl.DataFrame([{"symbol": "000001.SZ", "date": date(2026, 9, 28) + timedelta(days=i),
                          "concept": label, "close": price}
                         for i, price in enumerate([10., 11., 12.1]) for label in ["人工智能", "AI PC"]])
    out = _aggregate_sector_returns(rows, "concept")
    assert out.height == 4
    assert out["return_pct"].to_list() == pytest.approx([10.] * 4)


def test_market_lab_api_uses_ths_by_default_and_validates_taxonomy(monkeypatch):
    calls = []
    def radar(*args, **kwargs):
        calls.append(kwargs)
        return {"available": True, "rows": []}
    monkeypatch.setattr("app.api.market_lab.sector_radar_from_repo", radar)
    app = FastAPI()
    app.state.repo = object()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/market-lab/sector-radar").status_code == 200
        assert calls[-1]["ths_only"] is True
        assert client.get("/api/market-lab/sector-radar?taxonomy=source").status_code == 200
        assert calls[-1]["ths_only"] is False
        assert client.get("/api/market-lab/sector-radar?taxonomy=wrong").status_code == 422
