from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def normalize_company(value: str) -> str:
    return str(value or "").replace(" ", "").replace("*ST", "").replace("ST", "").strip()


def _local_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp.astimezone(SHANGHAI).date() if timestamp.tzinfo else timestamp.date()


def _available_in_window(item: dict[str, Any], earliest: date, target_date: date) -> bool:
    created = _local_date(item.get("created_at"))
    available = _local_date(item["available_at"] if "available_at" in item else item.get("captured_at") or item.get("created_at"))
    return created is not None and available is not None and earliest <= created <= target_date and available <= target_date


def is_direct_research(item: dict[str, Any]) -> bool:
    return item.get("match_basis") == "focused" or (
        item.get("match_basis") == "audited" and item.get("material_role") in {"primary", "supporting"}
    )


class ResearchMaterialRepository:
    """Read the local, publication-approved research index."""

    def __init__(self, data_root: Path) -> None:
        self.path = Path(data_root).resolve() / "research_material_index" / "index.json"
        self._cache: dict[str, Any] | None = None
        self._title_labels: dict[str, set[str]] = {}
        self._active_cache: dict[tuple[date, int], list[dict[str, Any]]] = {}

    def load(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if not self.path.is_file():
            return {"status": "unavailable", "materials": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self._cache = payload if isinstance(payload, dict) else {"status": "unavailable", "materials": []}
        return self._cache

    def _active_materials(self, target_date: date, lookback_days: int) -> list[dict[str, Any]]:
        key = (target_date, lookback_days)
        if key not in self._active_cache:
            earliest = target_date - timedelta(days=lookback_days)
            self._active_cache[key] = [
                item for item in self.load().get("materials", [])
                if _available_in_window(item, earliest, target_date)
            ]
        return self._active_cache[key]

    def query_company(self, company: str, target_date: date, *, lookback_days: int = 14, limit: int | None = 3) -> list[dict[str, Any]]:
        normalized = normalize_company(company)
        matches = []
        for item in self._active_materials(target_date, lookback_days):
            companies = {normalize_company(value) for value in item.get("companies", [])}
            if normalized in companies:
                if item.get("source") == "smnc" and item.get("basis") != "audited_publication":
                    title_companies = item.get("title_companies")
                    if title_companies is None:
                        title = normalize_company(str(item.get("title") or ""))
                        title_companies = [value for value in item.get("companies", []) if normalize_company(value) in title]
                    in_title = normalized in {normalize_company(value) for value in title_companies}
                    primary = {normalize_company(value) for value in item.get("primary_title_companies", [])}
                    match_basis = (
                        "focused" if normalized in primary or (in_title and not primary and len(title_companies) == 1)
                        else "basket" if in_title and not primary else "mention"
                    )
                else:
                    match_basis = "audited"
                excerpts = item.get("company_excerpts") or {}
                matches.append({
                    **{key: value for key, value in item.items() if key != "company_excerpts"},
                    "match_basis": match_basis,
                    "match_excerpt": excerpts.get(company) or excerpts.get(normalized) or item.get("takeaway") or "",
                })
        matches.sort(key=lambda item: (
            4 if is_direct_research(item) and item["match_basis"] == "audited"
            else 3 if item["match_basis"] == "focused"
            else 2 if item["match_basis"] == "audited"
            else 1 if item["match_basis"] == "basket" else 0,
            int(item.get("priority_score") or 0),
            item.get("created_at") or "", item.get("item_id") or "",
        ), reverse=True)
        return matches[:limit] if limit is not None else matches

    def query_topic(self, topic: str, target_date: date, *, aliases: list[str] | None = None,
                    lookback_days: int = 14, limit: int = 2) -> list[dict[str, Any]]:
        from app.stock_pools.topics import topic_labels

        direct_terms = {topic, re.sub(r"^[A-Z]{2,5}(?=[\u4e00-\u9fff]{4})", "", topic)}
        alias_terms = {
            normalized for alias in (aliases or [])
            if len(normalized := re.sub(r"(概念|板块)$", "", alias).strip()) >= 3
        }
        matches = []
        for item in self._active_materials(target_date, lookback_days):
            labels = {str(value).strip() for value in item.get("concepts", [])}
            title = str(item.get("title") or "")
            title_text = title
            for company in item.get("title_companies") or item.get("companies") or []:
                title_text = title_text.replace(str(company), "")
            direct_title = item.get("source") == "smnc" and any(
                len(term) >= 3 and term.casefold() in title_text.casefold() for term in direct_terms
            )
            alias_title = item.get("source") == "smnc" and any(
                term.casefold() in title_text.casefold() for term in alias_terms
            )
            if item.get("source") == "smnc" and item.get("basis") != "audited_publication":
                title_labels = self._title_labels.get(title_text)
                if title_labels is None:
                    title_labels = set(topic_labels(title_text))
                    self._title_labels[title_text] = title_labels
                basis = "title" if direct_title else "title_alias" if alias_title else "title_label" if topic in title_labels else ""
            else:
                basis = "audited" if topic in labels else "title" if direct_title else "title_alias" if alias_title else ""
            if basis:
                matches.append({**{key: value for key, value in item.items() if key != "company_excerpts"},
                                "topic_match_basis": basis})
        rank = {"audited": 4, "title": 3, "title_alias": 2, "title_label": 1}
        matches.sort(key=lambda item: (rank[item["topic_match_basis"]], int(item.get("priority_score") or 0),
                                       item.get("created_at") or ""), reverse=True)
        unique = []
        seen_titles = set()
        for item in matches:
            key = str(item.get("title") or "").strip().casefold()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            unique.append(item)
            if len(unique) == limit:
                break
        return unique
