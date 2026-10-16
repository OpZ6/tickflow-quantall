from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


class StockPoolRepository:
    """Read published stock-pool snapshots only."""

    def __init__(self, data_root: Path) -> None:
        self.root = Path(data_root).resolve() / "stock_pools"

    @staticmethod
    def normalize_date(value: str | date) -> str:
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:]}"
        return date.fromisoformat(text).isoformat()

    def date_dir(self, value: str | date) -> Path:
        return self.root / f"date={self.normalize_date(value)}"

    def first_date_dir(self, value: str | date) -> Path:
        return self.root / "first_published" / f"date={self.normalize_date(value)}"

    def list_dates(self) -> list[str]:
        if not self.root.exists():
            return []
        values: list[str] = []
        for path in self.root.glob("date=*"):
            try:
                values.append(date.fromisoformat(path.name[5:]).isoformat())
            except ValueError:
                continue
        return sorted(values)

    def latest_date(self) -> str | None:
        values = self.list_dates()
        return values[-1] if values else None

    def _read(self, value: str | date, name: str) -> Any:
        path = self.date_dir(value) / name
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_first(self, value: str | date, name: str) -> Any:
        path = self.first_date_dir(value) / name
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_review_snapshot(self, value: str | date) -> tuple[dict | None, list[dict] | None, dict | None, str]:
        manifest = self._read_first(value, "manifest.json")
        if isinstance(manifest, dict):
            summary = self._read_first(value, "summary.json")
            candidates = self._read_first(value, "candidates.json")
            return summary, candidates, manifest, "first_published"
        return self.get_summary(value), self.get_candidates(value), self.get_manifest(value), "replay"

    def get_first_details(self, value: str | date) -> dict[str, dict[str, Any]] | None:
        payload = self._read_first(value, "details.json")
        return payload if isinstance(payload, dict) else None

    def get_review_eligible(self, value: str | date) -> list[str] | None:
        if not self._read_first(value, "manifest.json"):
            return None
        payload = self._read_first(value, "eligible.json")
        return payload if isinstance(payload, list) and all(isinstance(item, str) for item in payload) else None

    def get_summary(self, value: str | date) -> dict[str, Any] | None:
        payload = self._read(value, "summary.json")
        return payload if isinstance(payload, dict) else None

    def get_candidates(self, value: str | date) -> list[dict[str, Any]] | None:
        payload = self._read(value, "candidates.json")
        return payload if isinstance(payload, list) else None

    def get_details(self, value: str | date) -> dict[str, dict[str, Any]] | None:
        payload = self._read(value, "details.json")
        return payload if isinstance(payload, dict) else None

    def get_manifest(self, value: str | date) -> dict[str, Any] | None:
        payload = self._read(value, "manifest.json")
        return payload if isinstance(payload, dict) else None
