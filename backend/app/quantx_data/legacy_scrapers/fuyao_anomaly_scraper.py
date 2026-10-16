"""同花顺个股异动原因 (Fuyao 特色数据) — 当日快照采集。

该接口只返回当日快照，历史日期必须通过
``scripts/import_fuyao_anomaly_snapshot.py`` 显式导入已冻结的原始响应。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.plugins.fuyao.client import FuyaoClient, FuyaoError
from app.plugins.fuyao.provider import get_api_key

SHANGHAI = ZoneInfo("Asia/Shanghai")


def run(trade_date: str, output_dir: str) -> dict[str, Any]:
    observed_at = datetime.now(UTC).isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "trade_date": trade_date,
        "source": "fuyao_anomaly",
        "scraped_at": observed_at,
        "status": "unavailable",
        "timestamp": None,
        "records": [],
    }
    today = datetime.now(SHANGHAI).strftime("%Y%m%d")
    if trade_date != today:
        payload["error"] = (
            "anomaly analysis only returns the current-day snapshot; "
            "historical dates require an explicit frozen import"
        )
    elif not get_api_key():
        payload["status"] = "error"
        payload["error"] = "missing fuyao API key"
    else:
        client = FuyaoClient(api_key=get_api_key(), timeout=30.0)
        try:
            data = client.anomaly_analysis_list()
            records = data.get("item") if isinstance(data, dict) else None
            payload["timestamp"] = data.get("timestamp") if isinstance(data, dict) else None
            payload["records"] = [row for row in (records or []) if isinstance(row, dict)]
            payload["status"] = "ok" if payload["records"] else "empty"
        except FuyaoError as exc:
            payload["status"] = "error"
            payload["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            client.close()

    path = Path(output_dir) / "fuyao_anomaly.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
