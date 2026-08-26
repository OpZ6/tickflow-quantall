from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger

from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _trade_date_today() -> str | None:
    now = date.today()
    if now.weekday() >= 5:
        return None
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        try:
            import tushare as ts

            pro = ts.pro_api(token, timeout=15)
            frame = pro.trade_cal(exchange="SSE", start_date=now.strftime("%Y%m%d"), end_date=now.strftime("%Y%m%d"))
            if frame is not None and not frame.empty and int(frame.iloc[0].get("is_open", 0)) != 1:
                return None
        except Exception as exc:  # calendar outage must not disable weekday fallback
            logger.warning("trade calendar check failed; using weekday fallback: %s", exc)
    return now.strftime("%Y%m%d")


def run_scheduled(data_root: Path) -> dict | None:
    trade_date = _trade_date_today()
    if not trade_date:
        return None
    try:
        return run_pipeline(data_root, trade_date)
    except Exception:  # scheduler must remain alive after a source outage
        logger.exception("scheduled QuantX data run failed for %s", trade_date)
        return None


def register(scheduler, data_root: Path, *, hour: int = 16, minute: int = 0) -> None:
    """Register an independent post-close data refresh on TickFlow's scheduler."""
    scheduler.add_job(
        lambda: run_scheduled(data_root),
        trigger=CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone="Asia/Shanghai"),
        id="quantx_data_daily",
        misfire_grace_time=7200,
        replace_existing=True,
    )
