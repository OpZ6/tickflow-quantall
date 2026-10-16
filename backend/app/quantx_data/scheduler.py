from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger

from app.market_facts.adapters import has_tickflow_market_partition
from app.market_facts.repository import MarketFactRepository

from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _trade_date_today(data_root: Path, *, today: date | None = None) -> str | None:
    now = today or date.today()
    calendar_state = MarketFactRepository(data_root).is_trading_day(now)
    if calendar_state is False:
        return None
    trade_date = now.strftime("%Y%m%d")
    if calendar_state is True or has_tickflow_market_partition(data_root, trade_date):
        return trade_date
    logger.warning(
        "QuantX schedule skipped for %s: calendar unknown and no local TickFlow partition",
        trade_date,
    )
    return None


def run_scheduled(data_root: Path, *, trade_date: str | None = None) -> dict | None:
    """Publish an explicit local snapshot, or today's scheduled snapshot.

    The main data pipeline passes its newest persisted session explicitly. This
    prevents a manual refresh just after midnight from publishing an empty
    snapshot for the new trading day.
    """
    trade_date = trade_date or _trade_date_today(data_root)
    if not trade_date:
        return None
    if not has_tickflow_market_partition(data_root, trade_date):
        logger.warning(
            "QuantX schedule skipped for %s: no local TickFlow partition",
            trade_date,
        )
        return None
    try:
        return run_pipeline(data_root, trade_date)
    except Exception:  # scheduler must remain alive after a source outage
        logger.exception("scheduled QuantX data run failed for %s", trade_date)
        return None


def register(
    scheduler, data_root: Path, *, hour: int = 17, minute: int = 30,
    after_run: Callable[[date], object] | None = None,
) -> None:
    """Register recovery runs after the normal pipeline window.

    The normal QuantX run is dependency-triggered by TickFlow's successful
    post-close pipeline. Recovery retries once at 20:30 when another data task
    occupied the first slot; a complete stock-pool snapshot skips the retry.
    """
    def recover() -> None:
        trade_date = _trade_date_today(data_root)
        if trade_date is None:
            return
        day = datetime.strptime(trade_date, "%Y%m%d").date()
        if after_run:
            from app.stock_pools.repository import StockPoolRepository

            summary = StockPoolRepository(data_root).get_summary(day)
            if summary and summary.get("status") == "complete":
                return
        from app.services.pipeline_jobs import job_store, release_run_slot, try_acquire_run_slot

        owner = f"quantx-recovery-{trade_date}"
        if job_store.active_id() or not try_acquire_run_slot(owner):
            logger.info("QuantX recovery deferred for %s: data task is active", trade_date)
            return
        try:
            result = run_scheduled(data_root, trade_date=trade_date)
            if result and result.get("status") in {"complete", "degraded"} and after_run:
                after_run(day)
        finally:
            release_run_slot(owner)

    scheduler.add_job(
        recover,
        trigger=CronTrigger(day_of_week="mon-fri", hour=f"{hour},20" if hour != 20 else "20",
                            minute=minute, timezone="Asia/Shanghai"),
        id="quantx_data_deadline_recovery",
        misfire_grace_time=86400,
        replace_existing=True,
    )
