"""Collect current A-share popularity rankings from independent public endpoints."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def _code(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else ""


def _lists(value: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []
    if isinstance(value, list):
        rows = [item for item in value if isinstance(item, dict)]
        if rows and any(any(key in row for key in ("code", "symbol", "secu_code", "stock_code")) for row in rows):
            found.append(rows)
        for item in value:
            found.extend(_lists(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_lists(item))
    return found


def _rows(payload: Any, source: str, observed_at: str) -> list[dict[str, Any]]:
    choices = _lists(payload)
    raw_rows = max(choices, key=len) if choices else []
    result = []
    for fallback_rank, item in enumerate(raw_rows, 1):
        code = _code(item.get("code") or item.get("symbol") or item.get("secu_code") or item.get("stock_code"))
        if not code:
            continue
        tag_data = item.get("tag")
        concept_tags = tag_data.get("concept_tag") if isinstance(tag_data, dict) else None
        result.append({
            "source_root": source, "code": code,
            "name": item.get("name") or item.get("stock_name") or item.get("secu_name") or "",
            "rank": item.get("rank") or item.get("rank_num") or item.get("order") or fallback_rank,
            "rank_change": item.get("rank_change") or item.get("rank_diff") or item.get("increment"),
            "heat_value": item.get("heat_value") or item.get("heat") or item.get("value"),
            "reason": item.get("reason") or item.get("analyse") or item.get("up_reason") or "",
            "concept_tags": ";".join(concept_tags) if isinstance(concept_tags, list) else "",
            "list_type": item.get("list_type") or "normal", "observed_at": observed_at,
            "source_updated_at": item.get("update_time") or "",
        })
    return result


def _json(session: requests.Session, method: str, url: str, **kwargs) -> Any:
    response = session.request(method, url, headers={"User-Agent": UA, "Referer": url}, timeout=18, **kwargs)
    response.raise_for_status()
    try:
        return response.json()
    except json.JSONDecodeError:
        text = response.text.strip()
        start, end = text.find("("), text.rfind(")")
        if start >= 0 and end > start:
            return json.loads(text[start + 1:end])
        raise


def run(trade_date: str, output_dir: str) -> dict[str, Any]:
    observed_at = datetime.now(UTC).isoformat(timespec="seconds")
    if trade_date != datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"):
        payload = {
            "schema_version": 1, "trade_date": trade_date,
            "source": "security_popularity", "scraped_at": observed_at,
            "status": "unavailable", "source_status": {
                "historical": {
                    "status": "unavailable",
                    "reason": "live popularity endpoints cannot reconstruct a historical snapshot",
                    "observed_at": observed_at,
                },
            }, "records": [],
        }
        path = Path(output_dir) / "security_popularity.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    session = requests.Session()
    session.trust_env = False
    records: list[dict[str, Any]] = []
    status: dict[str, dict[str, Any]] = {}
    endpoints = {
        "ths": ("GET", "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock", {"params": {"stock_type": "a", "type": "day", "list_type": "normal"}}),
        "xueqiu": ("GET", "https://stock.xueqiu.com/v5/stock/hot_stock/list.json", {"params": {"type": 12, "size": 100}}),
        "eastmoney": ("POST", "https://emappdata.eastmoney.com/stockrank/getAllCurrentList", {"json": {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "marketType": "", "pageNo": 1, "pageSize": 100}}),
    }
    for source, (method, url, options) in endpoints.items():
        try:
            if source == "xueqiu":
                session.get("https://xueqiu.com/hot/stock", headers={"User-Agent": UA}, timeout=18)
            parsed = _rows(_json(session, method, url, **options), source, observed_at)
            records.extend(parsed[:100])
            status[source] = {"status": "ok" if parsed else "empty", "count": len(parsed[:100]), "observed_at": observed_at}
        except Exception as exc:  # each optional source degrades independently
            status[source] = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "observed_at": observed_at}
    try:
        from curl_cffi import requests as curl_requests
        response = curl_requests.get(
            "https://finance.pae.baidu.com/vapi/v1/hotrank",
            params={"market": "ab", "type": "hour", "pn": 0, "rn": 100},
            headers={"User-Agent": UA}, impersonate="chrome124", timeout=18,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("Result") if isinstance(payload, dict) else None
        body = result.get("body") if isinstance(result, dict) else None
        converted = []
        for rank, row in enumerate(body or [], 1):
            if isinstance(row, list) and len(row) >= 5:
                converted.append({"code": row[4], "name": row[0], "rank": rank, "heat_value": row[2] if len(row) > 2 else None})
        parsed = _rows(converted, "baidu", observed_at)
        records.extend(parsed[:100])
        status["baidu"] = {"status": "ok" if parsed else "empty", "count": len(parsed[:100]), "observed_at": observed_at}
    except Exception as exc:
        status["baidu"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "observed_at": observed_at}
    payload = {
        "schema_version": 1, "trade_date": trade_date, "source": "security_popularity",
        "scraped_at": observed_at, "status": "ok" if records else "empty",
        "source_status": status, "records": records,
    }
    path = Path(output_dir) / "security_popularity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
