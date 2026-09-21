"""Attach targeted, publication-approved SMNC research to current topic candidates."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from stock_pool_logic import topics


def _day(value: str) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None


def _excerpt(audit: dict) -> str:
    takeaway = str(audit.get("core_takeaway") or "").strip()
    if takeaway:
        return takeaway
    evidence = audit.get("evidence") or []
    return str(evidence[0].get("anchor") or "").strip() if evidence else ""


def enrich(payload: dict, research_root: Path) -> None:
    """Retrieve by exact candidate name from completed Research publications only."""
    target_day = dt.date.fromisoformat(payload["trade_date"])
    earliest = target_day - dt.timedelta(days=14)
    item_library = json.loads((research_root / "items.json").read_text(encoding="utf-8"))
    if isinstance(item_library, dict):
        item_library = item_library.get("items", [])
    source_items = {item["item_id"]: item for item in item_library if item.get("source") == "smnc"}
    approved: dict[str, dict] = {}
    publications = []
    for manifest_path in sorted(research_root.parent.glob("*/research/publication_manifest.json")):
        report_date = manifest_path.parts[-3]
        if len(report_date) != 8 or report_date > target_day.strftime("%Y%m%d"):
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete" or manifest.get("schema_version") != 5:
            continue
        classification_path = manifest_path.with_name("research_classification.json")
        if not classification_path.exists():
            continue
        publications.append(report_date)
        classification = json.loads(classification_path.read_text(encoding="utf-8"))
        for audit in classification.get("items", []):
            item = source_items.get(audit.get("item_id"))
            created = _day(str(item.get("created_at") or "")) if item else None
            if item and audit.get("keep") and audit.get("kind") == "theme" and created and earliest <= created <= target_day:
                approved[audit["item_id"]] = {"audit": audit, "item": item, "report_date": report_date}

    candidate_rows = [row for row in payload["rows"] if row["memberships"].get("logic")]
    direct_count = 0
    direct_item_ids = set()
    for row in payload["rows"]:
        matches = []
        if row in candidate_rows:
            normalized_name = row["name"].replace(" ", "").replace("*ST", "")
            current_topics = set(row["memberships"]["logic"])
            for item_id, record in approved.items():
                audit, item = record["audit"], record["item"]
                companies = {str(company.get("name") or "").replace(" ", "").replace("*ST", "") for company in audit.get("companies", [])}
                if normalized_name not in companies:
                    continue
                matched_topics = current_topics & set(topics(" ".join([item.get("title", ""), _excerpt(audit), *[str(concept.get("name") or "") for concept in audit.get("concepts", [])]])))
                score = int(audit.get("priority_score") or 0) + (4 if matched_topics else 0)
                matches.append({
                    "item_id": item_id, "title": item.get("title", ""), "created_at": item.get("created_at", ""),
                    "source_url": item.get("source_url", ""), "report_date": record["report_date"],
                    "quality_grade": audit.get("quality_grade"), "quality_confidence": audit.get("quality_confidence"),
                    "material_role": audit.get("material_role"), "takeaway": _excerpt(audit),
                    "evidence": [entry.get("anchor", "") for entry in (audit.get("evidence") or [])[:2]],
                    "concepts": [concept.get("name", "") for concept in audit.get("concepts", [])[:4]],
                    "matched_topics": sorted(matched_topics), "score": score,
                })
            matches.sort(key=lambda match: (match["score"], match["created_at"], match["item_id"]), reverse=True)
            matches = matches[:3]
        row["smnc_research"] = matches
        if matches:
            direct_count += 1
            direct_item_ids.update(match["item_id"] for match in matches)

    topic_item_ids = set()
    for cluster in (cluster for cluster in payload["clusters"] if cluster["dimension"] == "logic"):
        background = []
        for item_id, record in approved.items():
            audit, item = record["audit"], record["item"]
            labels = topics(" ".join([item.get("title", ""), _excerpt(audit), *[str(concept.get("name") or "") for concept in audit.get("concepts", [])]]))
            if cluster["name"] not in labels:
                continue
            background.append({
                "item_id": item_id, "title": item.get("title", ""), "created_at": item.get("created_at", ""),
                "source_url": item.get("source_url", ""), "report_date": record["report_date"],
                "quality_grade": audit.get("quality_grade"), "takeaway": _excerpt(audit),
                "evidence": [entry.get("anchor", "") for entry in (audit.get("evidence") or [])[:2]],
                "score": int(audit.get("priority_score") or 0),
            })
        background.sort(key=lambda match: (match["score"], match["created_at"], match["item_id"]), reverse=True)
        cluster["smnc_background"] = background[:2]
        topic_item_ids.update(match["item_id"] for match in cluster["smnc_background"])
    payload["smnc_metadata"] = {
        "status": "available" if approved else "unavailable", "mode": "candidate_targeted_retrieval",
        "target_scope": "only_current_topic_candidates", "lookback_start": earliest.isoformat(), "target_date": payload["trade_date"],
        "latest_publication": max(publications, default=None), "approved_material_count": len(approved),
        "candidate_scope_count": len(candidate_rows), "direct_stock_coverage": direct_count,
        "direct_item_count": len(direct_item_ids), "topic_background_item_count": len(topic_item_ids),
        "note": "仅检索当前交易题材候选的精确公司名，并补题材背景；来源必须属于完成态Research publication。SMNC是低证据等级研究线索，不改变召回、阶段或排序。",
    }
