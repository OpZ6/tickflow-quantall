from __future__ import annotations

import json

import polars as pl

from app.research_materials import smnc
from app.research_materials.builder import build_research_material_index, refresh_if_configured

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


def test_refresh_keeps_local_items_when_blocked(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    research = data_root / "research"
    research.mkdir(parents=True)
    (research / "items.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(smnc, "fetch_page", lambda url: ("", "blocked_or_redirected: http://wired.meraki.com/"))
    assert refresh_if_configured(data_root) is True
    assert (data_root / "research_material_index" / "index.json").is_file()
