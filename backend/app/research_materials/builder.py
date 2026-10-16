from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings
from app.research_materials.smnc import update_items
from app.stock_pools.topics import topic_labels

logger = logging.getLogger(__name__)


def _excerpt(audit: dict[str, Any]) -> str:
    takeaway = str(audit.get("core_takeaway") or "").strip()
    if takeaway:
        return takeaway
    evidence = audit.get("evidence") or []
    return str(evidence[0].get("anchor") or "").strip() if evidence else ""


def _latest_available_at(*values: Any) -> str:
    timestamps = []
    for value in values:
        if not value:
            continue
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        timestamps.append(timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC))
    return max(timestamps).isoformat() if timestamps else ""


def _instrument_names(data_root: Path) -> list[str]:
    path = Path(data_root) / "instruments" / "instruments.parquet"
    if not path.is_file():
        return []
    try:
        frame = pl.read_parquet(path, columns=["name"])
    except Exception:
        return []
    names = {str(name).strip() for name in frame["name"].to_list() if str(name or "").strip()}
    return sorted((name for name in names if len(name) >= 3), key=len, reverse=True)


def _load_company_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _company_excerpts(content: str, companies: list[str]) -> dict[str, str]:
    text = re.sub(r"\s+", " ", content).strip()
    excerpts = {}
    for name in companies:
        start = text.find(name)
        if start >= 0:
            excerpts[name] = text[max(0, start - 50):min(len(text), start + len(name) + 110)].strip()
    return excerpts


def _extract_smnc_facts(
    items: list[dict[str, Any]],
    data_root: Path,
) -> dict[str, dict[str, Any]]:
    """Extract company names and topic labels per item, cached by content hash.

    The full name scan is only needed once per item; later index rebuilds reuse
    the cache so a daily publication stays fast.
    """
    cache_path = Path(data_root) / "research" / "smnc_facts.json"
    cache = _load_company_cache(cache_path)
    names = _instrument_names(data_root)
    pattern = re.compile("|".join(re.escape(name) for name in names)) if names else None
    changed = False
    for item in items:
        key = str(item.get("content_hash") or item.get("item_id") or "")
        if not key or (key in cache and "title_companies" in cache[key] and "company_excerpts" in cache[key]):
            continue
        previous = cache.get(key) or {}
        text = str(item.get("content_text") or "")
        title = str(item.get("title") or "")
        title_companies = sorted(set(pattern.findall(title))) if pattern and title else []
        body_companies = previous.get("companies") if previous else (pattern.findall(text) if pattern and text else [])
        companies = sorted(set(body_companies or []) | set(title_companies))
        concepts = previous.get("concepts") if previous else topic_labels(text)
        cache[key] = {
            "companies": companies, "concepts": concepts, "title_companies": title_companies,
            "company_excerpts": _company_excerpts(text, companies),
        }
        changed = True
    if changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return cache


def _primary_title_companies(title: str, companies: list[str]) -> list[str]:
    marked = [
        name for name in companies
        if re.search(rf"(?:#|\uFF03)\s*{re.escape(name)}(?=\W|$)|{re.escape(name)}\s*[:\uFF1A]", title)
    ]
    return marked if len(marked) == 1 else []


def _smnc_materials(items: list[dict[str, Any]], facts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("content_hash") or item.get("item_id") or "")
        extracted = facts.get(key) or {}
        companies = [str(value) for value in extracted.get("companies", [])]
        concepts = [str(value) for value in extracted.get("concepts", [])]
        content = str(item.get("content_text") or "")
        title = str(item.get("title") or "")
        title_companies = [str(value) for value in extracted.get("title_companies", [])]
        materials.append({
            "item_id": item.get("item_id"),
            "source": "smnc",
            "title": title,
            "created_at": str(item.get("created_at") or ""),
            "available_at": str(item.get("captured_at") or ""),
            "source_url": str(item.get("source_url") or ""),
            "report_date": str(item.get("trading_day") or str(item.get("created_at") or "")[:10].replace("-", "")),
            "companies": companies,
            "title_companies": title_companies,
            "primary_title_companies": _primary_title_companies(title, title_companies),
            "company_excerpts": extracted.get("company_excerpts") or {},
            "concepts": concepts,
            "title_concepts": topic_labels(title),
            "takeaway": content[:200],
            "evidence": [],
            "quality_grade": None,
            "quality_confidence": None,
            "material_role": None,
            "priority_score": 0,
            "basis": "deterministic_smnc_extraction",
        })
    return materials


def build_research_material_index(source_root: Path, data_root: Path) -> dict[str, Any]:
    """Ingest completed publications and local SMNC items into a read model.

    Audited publication materials win over the deterministic SMNC extraction
    for the same item; the deterministic layer keeps the stock pool working
    without the external research workflow.
    """
    source_root = Path(source_root).resolve()
    data_root = Path(data_root).resolve()
    items_path = source_root / "items.json"
    items_payload = json.loads(items_path.read_text(encoding="utf-8")) if items_path.is_file() else []
    items = items_payload.get("items", []) if isinstance(items_payload, dict) else items_payload
    library = {item["item_id"]: item for item in items if isinstance(item, dict) and item.get("item_id")}
    materials: dict[str, dict[str, Any]] = {}
    publications = []
    for manifest_path in sorted(source_root.parent.glob("*/research/publication_manifest.json")):
        report_date = manifest_path.parts[-3]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest.get("schema_version") != 5:
            continue
        classification_path = manifest_path.with_name("research_classification.json")
        if not classification_path.is_file():
            continue
        publications.append(report_date)
        classification = json.loads(classification_path.read_text(encoding="utf-8"))
        for audit in classification.get("items", []):
            item = library.get(audit.get("item_id"))
            if not item or not audit.get("keep") or audit.get("kind") != "theme":
                continue
            materials[item["item_id"]] = {
                "item_id": item["item_id"], "source": item.get("source"),
                "title": item.get("title") or "", "created_at": item.get("created_at") or "",
                "available_at": _latest_available_at(manifest.get("published_at"), item.get("captured_at")),
                "source_url": item.get("source_url") or "", "report_date": report_date,
                "companies": [str(value.get("name") or "") for value in audit.get("companies", []) if value.get("name")],
                "concepts": [str(value.get("name") or "") for value in audit.get("concepts", []) if value.get("name")],
                "takeaway": _excerpt(audit),
                "evidence": [str(value.get("anchor") or "") for value in (audit.get("evidence") or [])[:2]],
                "quality_grade": audit.get("quality_grade"),
                "quality_confidence": audit.get("quality_confidence"),
                "material_role": audit.get("material_role"),
                "priority_score": int(audit.get("priority_score") or 0),
                "basis": "audited_publication",
            }
    smnc_items = [item for item in library.values() if item.get("source") == "smnc"]
    facts = _extract_smnc_facts(smnc_items, data_root)
    for material in _smnc_materials(smnc_items, facts):
        materials.setdefault(str(material["item_id"]), material)
    payload = {
        "schema_version": 4, "status": "available" if materials else "unavailable",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "latest_publication": max(publications, default=None),
        "material_count": len(materials), "materials": list(materials.values()),
    }
    target = data_root / "research_material_index" / "index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    staging.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(staging, target)
    return {key: value for key, value in payload.items() if key != "materials"}


def refresh_if_configured(data_root: Path) -> bool:
    """Refresh the local SMNC items and rebuild the research material index.

    Called before stock-pool publication so candidates always use the latest
    completed Research materials. SMNC polling degrades softly: a blocked or
    unavailable network keeps the existing local items. The source defaults to
    the project-local ``data/research`` directory; set ``RESEARCH_SOURCE_DIR``
    to override with another location.
    """
    data_root = Path(data_root)
    source_dir = getattr(settings, "research_source_dir", None)
    if not source_dir:
        source_dir = data_root / "research"
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        logger.debug("research source dir not found, skipping index refresh: %s", source_dir)
        return False
    try:
        result = update_items(data_root, allow_network=True)
        if result.get("status") not in {"ok", "partial", "empty"}:
            logger.warning(
                "SMNC update not applied (%s); keeping local items. "
                "Route smnc.juecan.com through a proxy node if the local network blocks it.",
                result.get("status"),
            )
    except Exception:
        logger.exception("SMNC update failed; reusing local items")
    try:
        build_research_material_index(source_dir, data_root)
        logger.info("research material index refreshed from %s", source_dir)
        return True
    except Exception:
        logger.exception("research material index refresh failed")
        return False
