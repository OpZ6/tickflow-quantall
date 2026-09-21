from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.stock_pools.repository import StockPoolRepository
from app.stock_pools.rules import RULE_VERSION
from app.stock_pools.service import StockPoolService
from app.tickflow.repository import KlineRepository

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(day: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(day, threading.Lock())


def _encoded(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def publish_stock_pool(repo: KlineRepository, trade_date: date) -> dict[str, Any]:
    day = trade_date.isoformat()
    lock = _lock_for(day)
    if not lock.acquire(blocking=False):
        raise RuntimeError(f"stock-pool publication already active for {day}")
    root = Path(repo.store.data_dir).resolve() / "stock_pools"
    run_id = f"{trade_date:%Y%m%d}-{uuid.uuid4().hex[:12]}"
    staging = root / ".runs" / run_id
    target = StockPoolRepository(repo.store.data_dir).date_dir(trade_date)
    backup = root / f".backup-{trade_date:%Y%m%d}-{run_id}"
    try:
        from app.research_materials.builder import refresh_if_configured

        refresh_if_configured(Path(repo.store.data_dir))
        payload = StockPoolService(repo).build(trade_date)
        staging.mkdir(parents=True, exist_ok=False)
        artifacts = []
        for filename, key in (("summary.json", "summary"), ("candidates.json", "candidates"), ("details.json", "details")):
            content = _encoded(payload[key])
            (staging / filename).write_bytes(content)
            artifacts.append({"path": filename, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        manifest = {
            "schema_version": 1, "trade_date": day, "run_id": run_id,
            "status": payload["summary"]["status"], "rule_version": RULE_VERSION,
            "input_generation": payload["summary"]["input_generation"],
            "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "artifacts": artifacts,
        }
        (staging / "manifest.json").write_bytes(_encoded(manifest))
        root.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(staging, target)
        except Exception:
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return {**manifest, "candidate_count": payload["summary"]["candidate_count"]}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        lock.release()
