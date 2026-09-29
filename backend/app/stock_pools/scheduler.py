from __future__ import annotations

import logging
from datetime import date

from apscheduler.triggers.cron import CronTrigger

from app.stock_pools.publisher import publish_stock_pool
from app.stock_pools.repository import StockPoolRepository

logger = logging.getLogger(__name__)


def run_scheduled(repo, *, trade_date: date | None = None) -> dict | None:
    day = trade_date or repo.latest_enriched_date("stock")
    if day is None:
        return None
    if trade_date is None:
        snapshots = StockPoolRepository(repo.store.data_dir)
        if all(item is not None for item in (
            snapshots.get_manifest(day), snapshots.get_summary(day),
            snapshots.get_candidates(day), snapshots.get_details(day),
        )):
            return None
    try:
        return publish_stock_pool(repo, day)
    except Exception:
        logger.exception("scheduled stock-pool publication failed for %s", day)
        return None


def register(scheduler, repo, *, hour: int = 17, minute: int = 45) -> None:
    scheduler.add_job(
        lambda: run_scheduled(repo),
        trigger=CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone="Asia/Shanghai"),
        id="stock_pools_deadline_recovery", misfire_grace_time=86400, replace_existing=True,
    )
