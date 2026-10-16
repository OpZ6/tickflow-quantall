from __future__ import annotations

import json

import polars as pl

from app.research_materials import smnc
from app.research_materials.builder import build_research_material_index, refresh_if_configured
from app.research_materials.repository import ResearchMaterialRepository, is_direct_research

_LIST_HTML = """
<html><body>
  <div class="post">
    <div class="entry-meta">发布于2026/9/15 15:30:00</div>
    <div id="short_text_37101">
      <p>9月15日复盘笔记：PCB/光模块/存储</p>
      <p>涨停股：超声电子、金安国纪</p>
    </div>
    <div id="full_text_37101">
      <p>9月15日复盘笔记：PCB/光模块/存储</p>
      <p>涨停股：超声电子、金安国纪；强势股：中际旭创</p>
    </div>
  </div>
  <div class="post">
    <div class="entry-meta">发布于2026/9/15 09:12:00</div>
    <div id="short_text_37102">
      <p>早盘提示：固态电池方向留意</p>
    </div>
  </div>
</body></html>
"""


def test_smnc_parse_and_normalize():
    entries = smnc.parse_html(_LIST_HTML)
    assert [entry["id"] for entry in entries] == ["37101", "37102"]
    assert entries[0]["created_at"].startswith("2026-09-15T15:30:00")
    assert entries[0]["url"].endswith("info.asp?id=37101")
    assert "超声电子" in entries[0]["content"]
    item = smnc.normalize_entry(entries[0])
    assert item["item_id"] == "smnc_37101"
    assert item["source"] == "smnc"
    assert item["content_hash"]


def test_smnc_update_offline_and_blocked(monkeypatch, tmp_path):
    assert smnc.update_items(tmp_path, allow_network=False)["status"] == "offline"
    monkeypatch.setattr(smnc, "fetch_page", lambda url: ("", "blocked_or_redirected: http://wired.meraki.com/"))
    result = smnc.update_items(tmp_path)
    assert result["status"].startswith("blocked_or_redirected")
    assert not (tmp_path / "research" / "items.json").exists()


def test_smnc_update_upserts_new_items(monkeypatch, tmp_path):
    monkeypatch.setattr(smnc, "fetch_page", lambda url: (_LIST_HTML, "ok") if url.endswith("page=1") else ("", "http_404"))
    result = smnc.update_items(tmp_path, max_pages=2)
    assert result["status"] in {"ok", "partial"}
    assert result["added"] == 2
    items = json.loads((tmp_path / "research" / "items.json").read_text(encoding="utf-8"))
    assert {item["item_id"] for item in items} == {"smnc_37101", "smnc_37102"}
    second = smnc.update_items(tmp_path, max_pages=2)
    assert second["added"] == 0
    assert second["updated"] == 0


def test_research_index_merges_smnc_materials(tmp_path):
    data_root = tmp_path / "data"
    research = data_root / "research"
    research.mkdir(parents=True)
    instruments = data_root / "instruments"
    instruments.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["000823.SZ", "002636.SZ", "300308.SZ"],
        "name": ["超声电子", "金安国纪", "中际旭创"],
    }).write_parquet(instruments / "instruments.parquet")
    items = [
        {
            "item_id": "smnc_37101", "source": "smnc", "source_id": "37101",
            "title": "9月15日复盘笔记：PCB/光模块/存储",
            "content_text": "涨停股：超声电子、金安国纪；强势股：中际旭创。PCB与光模块方向。",
            "created_at": "2026-09-15T15:30:00+08:00", "content_hash": "hash-1",
            "source_url": "http://smnc.juecan.com/info.asp?id=37101", "trading_day": "20260915",
        },
    ]
    (research / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    result = build_research_material_index(research, data_root)
    assert result["material_count"] == 1
    index = json.loads((data_root / "research_material_index" / "index.json").read_text(encoding="utf-8"))
    material = index["materials"][0]
    assert material["basis"] == "deterministic_smnc_extraction"
    assert set(material["companies"]) == {"超声电子", "金安国纪", "中际旭创"}
    assert "PCB／覆铜板" in material["concepts"]
    assert "光互联" in material["concepts"]
    # second build reuses the extraction cache
    cached = build_research_material_index(research, data_root)
    assert cached["material_count"] == 1


def test_smnc_topic_title_matches_fine_direction_without_old_concept_tag(tmp_path):
    from datetime import date

    root = tmp_path / "research_material_index"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({"materials": [{
        "item_id": "smnc_vna", "source": "smnc", "title": "矢量网络分析仪VNA行业变化",
        "created_at": "2026-09-23T12:49:05+08:00", "concepts": ["PCB／覆铜板"],
    }]}, ensure_ascii=False), encoding="utf-8")
    repo = ResearchMaterialRepository(tmp_path)
    assert [item["item_id"] for item in repo.query_topic("矢量网络分析仪", date(2026, 9, 23))] == ["smnc_vna"]
    assert [item["item_id"] for item in repo.query_topic("VNA矢量网络分析仪", date(2026, 9, 23))] == ["smnc_vna"]
    assert repo.query_topic("PCB／覆铜板", date(2026, 9, 23)) == []
    assert repo.query_topic("PCB／覆铜板", date(2026, 9, 23), aliases=["PCB概念"]) == []
    assert [item["item_id"] for item in repo.query_topic("电子测量", date(2026, 9, 23), aliases=["VNA"])] == ["smnc_vna"]
    assert repo.query_topic("矢量网络分析仪", date(2026, 9, 22)) == []


def test_smnc_topic_background_ignores_company_name_and_deduplicates_title(tmp_path):
    from datetime import date

    root = tmp_path / "research_material_index"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({"materials": [
        {"item_id": "company", "source": "smnc", "title": "国邦医药：业务更新",
         "title_companies": ["国邦医药"], "created_at": "2026-09-23T12:00:00+08:00"},
        {"item_id": "first", "source": "smnc", "title": "微波光子雷达进展",
         "created_at": "2026-09-23T13:00:00+08:00"},
        {"item_id": "repost", "source": "smnc", "title": "微波光子雷达进展",
         "created_at": "2026-09-23T14:00:00+08:00"},
    ]}, ensure_ascii=False), encoding="utf-8")
    repo = ResearchMaterialRepository(tmp_path)
    assert repo.query_topic("医疗／医药", date(2026, 9, 23)) == []
    assert [item["item_id"] for item in repo.query_topic("微波光子雷达", date(2026, 9, 23))] == ["repost"]


def test_smnc_fine_title_is_indexed_without_known_company_or_concept(tmp_path):
    from datetime import date

    research = tmp_path / "research"
    research.mkdir()
    items = [{
        "item_id": "smnc_new", "source": "smnc", "title": "微波光子雷达行业进展",
        "content_text": "微波光子雷达测试取得进展", "created_at": "2026-09-23T12:00:00+08:00",
        "captured_at": "2026-09-23T05:00:00+00:00",
        "content_hash": "new-theme-hash", "source_url": "http://smnc.juecan.com/info.asp?id=1",
    }]
    (research / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    result = build_research_material_index(research, tmp_path)
    assert result["material_count"] == 1
    repo = ResearchMaterialRepository(tmp_path)
    assert [item["item_id"] for item in repo.query_topic("微波光子雷达", date(2026, 9, 23))] == ["smnc_new"]


def test_research_materials_wait_until_locally_available(tmp_path):
    from datetime import date

    research = tmp_path / "research"
    research.mkdir()
    instruments = tmp_path / "instruments"
    instruments.mkdir()
    pl.DataFrame({"symbol": ["000001.SZ"], "name": ["甲公司"]}).write_parquet(instruments / "instruments.parquet")
    items = [
        {"item_id": "smnc_late", "source": "smnc", "title": "甲公司微波光子雷达进展",
         "content_text": "甲公司微波光子雷达进展", "created_at": "2026-09-15T14:00:00+08:00",
         "captured_at": "2026-09-15T17:00:00+00:00", "content_hash": "late-smnc"},
        {"item_id": "audited_late", "source": "zsxq_mark", "title": "甲公司光互联研究",
         "created_at": "2026-09-15T14:00:00+08:00"},
        {"item_id": "smnc_uncaptured", "source": "smnc", "title": "甲公司未经采集时间核对",
         "content_text": "甲公司", "created_at": "2026-09-15T14:00:00+08:00",
         "content_hash": "uncaptured-smnc"},
    ]
    (research / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    publication = tmp_path / "20260915" / "research"
    publication.mkdir(parents=True)
    (publication / "publication_manifest.json").write_text(json.dumps({
        "schema_version": 5, "status": "complete", "published_at": "2026-09-17T01:00:00+00:00",
    }), encoding="utf-8")
    (publication / "research_classification.json").write_text(json.dumps({"items": [{
        "item_id": "audited_late", "keep": True, "kind": "theme",
        "companies": [{"name": "甲公司"}], "concepts": [{"name": "光互联"}],
        "material_role": "primary", "priority_score": 1,
    }]}, ensure_ascii=False), encoding="utf-8")
    build_research_material_index(research, tmp_path)
    repo = ResearchMaterialRepository(tmp_path)
    assert repo.query_company("甲公司", date(2026, 9, 15)) == []
    assert repo.query_topic("微波光子雷达", date(2026, 9, 15)) == []
    assert [item["item_id"] for item in repo.query_company("甲公司", date(2026, 9, 16))] == ["smnc_late"]
    assert [item["item_id"] for item in repo.query_company("甲公司", date(2026, 9, 17))] == ["audited_late", "smnc_late"]
    assert [item["item_id"] for item in repo.query_topic("光互联", date(2026, 9, 17))] == ["audited_late"]


def test_smnc_company_mentions_do_not_rank_as_focused_material(tmp_path):
    from datetime import date

    root = tmp_path / "research_material_index"
    root.mkdir()
    materials = [
        {"item_id": "market", "source": "smnc", "title": "上午板块梳理", "created_at": "2026-09-24",
         "companies": ["甲公司", "乙公司", "丙公司", "丁公司", "戊公司", "己公司"], "takeaway": "甲公司等多只股票上涨", "priority_score": 0},
        {"item_id": "focused", "source": "smnc", "title": "甲公司业务更新", "created_at": "2026-09-23",
         "companies": ["甲公司"], "takeaway": "甲公司订单变化", "priority_score": 0},
        {"item_id": "lead_mention", "source": "smnc", "title": "行业更新", "created_at": "2026-09-23",
         "companies": ["甲公司", "乙公司"], "takeaway": "甲公司等多家企业受关注", "priority_score": 0},
        {"item_id": "audited", "source": "zsxq_mark", "basis": "audited_publication", "title": "专题研究",
         "created_at": "2026-09-22", "companies": ["甲公司"], "material_role": "primary", "priority_score": 1},
    ]
    (root / "index.json").write_text(json.dumps({"materials": materials}, ensure_ascii=False), encoding="utf-8")
    matches = ResearchMaterialRepository(tmp_path).query_company("甲公司", date(2026, 9, 24), limit=4)
    assert [item["item_id"] for item in matches] == ["audited", "focused", "market", "lead_mention"]
    assert [item["match_basis"] for item in matches] == ["audited", "focused", "mention", "mention"]


def test_smnc_title_separates_single_subject_from_multi_stock_basket(tmp_path):
    from datetime import date

    research = tmp_path / "research"
    research.mkdir()
    instruments = tmp_path / "instruments"
    instruments.mkdir()
    pl.DataFrame({"symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
                  "name": ["甲公司", "乙公司", "丙公司"]}).write_parquet(instruments / "instruments.parquet")
    items = [
        {"item_id": "basket", "source": "smnc", "title": "甲公司、乙公司产业链交流",
         "content_text": "产能更新", "created_at": "2026-09-24T14:00:00+08:00",
         "captured_at": "2026-09-24T07:00:00+00:00", "content_hash": "basket-hash"},
        {"item_id": "focused", "source": "smnc", "title": "丙公司订单更新",
         "content_text": "订单更新", "created_at": "2026-09-24T14:00:00+08:00",
         "captured_at": "2026-09-24T07:00:00+00:00", "content_hash": "focused-hash"},
        {"item_id": "marked", "source": "smnc", "title": "【研究团队】#甲公司：订单更新，对比乙公司",
         "content_text": "订单更新", "created_at": "2026-09-24T14:00:00+08:00",
         "captured_at": "2026-09-24T07:00:00+00:00", "content_hash": "marked-hash"},
    ]
    (research / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    build_research_material_index(research, tmp_path)
    repo = ResearchMaterialRepository(tmp_path)
    assert [(item["item_id"], item["match_basis"]) for item in repo.query_company("甲公司", date(2026, 9, 24))] == [
        ("marked", "focused"), ("basket", "basket"),
    ]
    assert [(item["item_id"], item["match_basis"]) for item in repo.query_company("乙公司", date(2026, 9, 24))] == [
        ("basket", "basket"), ("marked", "mention"),
    ]
    assert repo.query_company("丙公司", date(2026, 9, 24))[0]["match_basis"] == "focused"


def test_company_excerpt_and_direct_research_exclude_basket_and_counter(tmp_path):
    from datetime import date

    research = tmp_path / "research"
    research.mkdir()
    instruments = tmp_path / "instruments"
    instruments.mkdir()
    pl.DataFrame({"symbol": ["000001.SZ", "000002.SZ"], "name": ["甲公司", "乙公司"]}).write_parquet(
        instruments / "instruments.parquet"
    )
    items = [{
        "item_id": "smnc_basket", "source": "smnc", "title": "甲公司与乙公司产业链更新",
        "content_text": "甲公司订单等待验证。乙公司订单已经落地。",
        "created_at": "2026-09-24T14:00:00+08:00", "captured_at": "2026-09-24T07:00:00+00:00",
        "content_hash": "basket-excerpt",
    }]
    (research / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    build_research_material_index(research, tmp_path)
    repo = ResearchMaterialRepository(tmp_path)
    first = repo.query_company("乙公司", date(2026, 9, 24))[0]
    assert first["match_basis"] == "basket"
    assert "乙公司订单已经落地" in first["match_excerpt"]
    assert "company_excerpts" not in first
    assert not is_direct_research(first)
    assert not is_direct_research({"match_basis": "audited", "material_role": "counter"})
    assert is_direct_research({"match_basis": "audited", "material_role": "primary"})
    assert is_direct_research({"match_basis": "focused"})


def test_refresh_keeps_local_items_when_blocked(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    research = data_root / "research"
    research.mkdir(parents=True)
    (research / "items.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(smnc, "fetch_page", lambda url: ("", "blocked_or_redirected: http://wired.meraki.com/"))
    assert refresh_if_configured(data_root) is True
    assert (data_root / "research_material_index" / "index.json").is_file()
