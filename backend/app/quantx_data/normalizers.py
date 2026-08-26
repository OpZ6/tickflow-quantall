from __future__ import annotations

from copy import deepcopy
from typing import Any

from .io import json_default


def stock_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _normalize_rows(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_rows(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {str(key): _normalize_rows(item) for key, item in value.items()}
    for key in ("code", "ts_code", "股票代码", "证券代码"):
        if key in result and result[key] not in (None, ""):
            code = stock_code(result[key])
            if code:
                result["code"] = code
                if key != "code":
                    result["source_code"] = result[key]
                break
    return result


def normalize_source(name: str, trade_date: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize shared identity fields without changing source-specific facts."""
    normalized = _normalize_rows(deepcopy(payload))
    normalized["trade_date"] = str(normalized.get("trade_date") or normalized.get("as_of") or trade_date)
    normalized["source_name"] = name
    normalized["schema_version"] = max(int(normalized.get("schema_version") or 1), 1)
    normalized.setdefault("status", "ok")
    # Force JSON-safe scalars here so provider-specific pandas/numpy values do
    # not leak into persisted artifacts.
    return json_default(normalized) if not isinstance(normalized, dict) else normalized
