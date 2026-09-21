from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def normalize_company(value: str) -> str:
    return str(value or "").replace(" ", "").replace("*ST", "").replace("ST", "").strip()


class ResearchMaterialRepository:
    """Read the local, publication-approved research index."""

    def __init__(self, data_root: Path) -> None:
        self.path = Path(data_root).resolve() / "research_material_index" / "index.json"

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"status": "unavailable", "materials": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"status": "unavailable", "materials": []}

    def query_company(self, company: str, target_date: date, *, lookback_days: int = 14, limit: int = 3) -> list[dict[str, Any]]:
        normalized = normalize_company(company)
        earliest = target_date - timedelta(days=lookback_days)
        matches = []
        for item in self.load().get("materials", []):
            try:
                created = date.fromisoformat(str(item.get("created_at") or "")[:10])
            except ValueError:
                continue
            companies = {normalize_company(value) for value in item.get("companies", [])}
            if normalized in companies and earliest <= created <= target_date:
                matches.append(item)
        matches.sort(key=lambda item: (int(item.get("priority_score") or 0), item.get("created_at") or "", item.get("item_id") or ""), reverse=True)
        return matches[:limit]

    def query_topic(self, topic: str, target_date: date, *, lookback_days: int = 14, limit: int = 2) -> list[dict[str, Any]]:
        earliest = target_date - timedelta(days=lookback_days)
        matches = []
        for item in self.load().get("materials", []):
            try:
                created = date.fromisoformat(str(item.get("created_at") or "")[:10])
            except ValueError:
                continue
            labels = {str(value).strip() for value in item.get("concepts", [])}
            if topic in labels and earliest <= created <= target_date:
                matches.append(item)
        matches.sort(key=lambda item: (int(item.get("priority_score") or 0), item.get("created_at") or ""), reverse=True)
        return matches[:limit]
