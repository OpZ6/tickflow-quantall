"""财务同步的本地增强实现（全市场概览 / 历史回补 / 按标的补数）。

从 `app/services/financial_sync.py` 拆出来：上游那个文件是活跃开发区，
每次合并都要在那 273 行里逐块判定。这里的函数只依赖上游的通用 helper
（`_get_symbols` / `_write_table` / …），通过 `_base` 模块对象访问，
因此本模块不构成循环导入。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

import app.services.financial_sync as _base

logger = logging.getLogger(__name__)


def provider_info() -> dict[str, Any]:
    """Return the effective provider and its supported synchronization mode."""
    from app.services import preferences
    name = preferences.get_financial_provider()
    if name == "tickflow":
        return {"provider": name, "mode": "expert_bulk", "supports_overview": False}
    from app.data_providers import custom as custom_sources
    provider = custom_sources.get_provider(name)
    mode_fn = getattr(provider, "financial_mode", None)
    return {
        "provider": name,
        "mode": mode_fn() if callable(mode_fn) else "custom",
        "supports_overview": callable(getattr(provider, "get_financial_overview", None)),
    }


def sync_market_overview(data_dir: Path) -> int:
    from app.services import preferences
    from app.data_providers import custom as custom_sources
    provider = custom_sources.get_provider(preferences.get_financial_provider())
    fn = getattr(provider, "get_financial_overview", None)
    if not callable(fn):
        raise RuntimeError("当前财务数据源不支持全市场业绩概览")
    df = fn()
    symbols = set(_base._get_symbols(data_dir))
    if symbols and not df.is_empty():
        df = df.filter(pl.col("symbol").is_in(symbols))
    if df.is_empty():
        raise RuntimeError("上游返回空概览，已保留本地上一版数据")
    return _base._write_table(OVERVIEW_TABLE, df, data_dir)


def _report_periods(start_year: int, today: date | None = None) -> list[date]:
    current = today or date.today()
    periods = [
        date(year, month, day)
        for year in range(max(2012, start_year), current.year + 1)
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
        if date(year, month, day) < current
    ]
    return periods


def _merge_market_core(existing: pl.DataFrame, fresh: pl.DataFrame) -> pl.DataFrame:
    """Merge bulk core facts without replacing richer non-AkShare detail rows."""
    if fresh.is_empty():
        return existing
    if existing.is_empty():
        return _base._merge_report_history(fresh)
    keys = fresh.select(["symbol", "period_end"]).unique()
    marked = existing.join(keys.with_columns(pl.lit(True).alias("_incoming")),
                           on=["symbol", "period_end"], how="left")
    source = pl.col("source").fill_null("") if "source" in marked.columns else pl.lit("")
    keep_existing = marked.filter(
        pl.col("_incoming").is_null() | ~source.str.starts_with("akshare")
    ).drop("_incoming")
    protected = existing.filter(
        ~pl.col("source").fill_null("").str.starts_with("akshare")
    ) if "source" in existing.columns else existing.head(0)
    protected_keys = protected.select(["symbol", "period_end"]).unique()
    accepted_fresh = fresh.join(
        protected_keys.with_columns(pl.lit(True).alias("_protected")),
        on=["symbol", "period_end"], how="left",
    ).filter(pl.col("_protected").is_null()).drop("_protected")
    return _base._merge_report_history(keep_existing, accepted_fresh)


def sync_market_history(
    data_dir: Path,
    *,
    start_year: int = 2012,
    on_progress=None,
) -> dict[str, int]:
    """Backfill full-market core financial history by report period.

    Older periods above the historical completion threshold are skipped; the
    latest four periods are always refreshed for delayed filings and revisions.
    """
    from app.data_providers import custom as custom_sources
    from app.services import preferences

    provider = custom_sources.get_provider(preferences.get_financial_provider())
    fetch = getattr(provider, "get_financial_market_table", None)
    if not callable(fetch):
        raise RuntimeError("当前财务数据源不支持全市场历史核心报表")
    universe_symbols = set(_base._get_symbols(data_dir))
    # Historical listed-company counts are much lower than today's universe.
    # A completed old market period still has well over 1,000 rows, while the
    # pre-existing on-demand detail cache normally has only a handful.
    threshold = min(1000, max(100, int(len(universe_symbols) * 0.85)))
    periods = _report_periods(start_year)
    tables = ("metrics", "income", "balance_sheet", "cash_flow")
    total_steps = len(periods) * len(tables)
    step = 0
    result: dict[str, int] = {}

    for table in tables:
        existing = _base.get_financial_df(data_dir, table)
        dirty = 0
        for period in periods:
            step += 1
            period_rows = 0
            if not existing.is_empty() and "period_end" in existing.columns:
                period_rows = existing.filter(pl.col("period_end") == period)[
                    "symbol"
                ].n_unique()
            refresh_recent = period in periods[-4:]
            skipped = period_rows >= threshold and not refresh_recent
            if on_progress:
                on_progress({
                    "step": step,
                    "total": total_steps,
                    "table": table,
                    "period": period.isoformat(),
                    "skipped": skipped,
                })
            if skipped:
                continue
            try:
                fresh = fetch(table, period)
            except Exception as exc:  # noqa: BLE001
                logger.warning("market financial %s %s failed: %s", table, period, exc)
                if on_progress:
                    on_progress({
                        "step": step,
                        "total": total_steps,
                        "table": table,
                        "period": period.isoformat(),
                        "error": str(exc),
                    })
                continue
            if universe_symbols and not fresh.is_empty():
                fresh = fresh.filter(pl.col("symbol").is_in(universe_symbols))
            if fresh.is_empty():
                logger.warning("market financial %s %s returned empty", table, period)
                continue
            existing = _merge_market_core(existing, fresh)
            dirty += 1
            if dirty % 4 == 0:
                result[table] = _base._write_table(table, existing, data_dir)
        if dirty % 4:
            result[table] = _base._write_table(table, existing, data_dir)
        if not existing.is_empty():
            result.setdefault(table, existing.height)
    _base._refresh_financials_views(data_dir)
    return result


def sync_stock(symbol: str, data_dir: Path, capset: CapabilitySet) -> dict[str, int]:
    """Fetch all detailed tables for one stock and merge them into local history."""
    if not symbol:
        raise ValueError("symbol 不能为空")
    result: dict[str, int] = {}
    for table in FINANCIAL_TABLES:
        fresh = _base._fetch_table(table, [symbol], capset, latest_only=False)
        if fresh.is_empty():
            result[table] = 0
            continue
        existing = _base.get_financial_df(data_dir, table)
        if table == "shares" and not existing.is_empty() and "symbol" in existing.columns:
            existing = existing.filter(pl.col("symbol") != symbol)
        merged = _base._merge_report_history(existing, fresh)
        result[table] = _base._write_table(table, merged, data_dir)
    return result


# ================================================================
# 调度器
# ================================================================
