"""Adapters from TickFlow's existing canonical stores to market facts."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl


def load_tickflow_market_aggregate(data_root: Path, trade_date: str) -> dict[str, Any] | None:
    """Build daily breadth inputs from the already published TickFlow partition."""
    iso_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    for table in ("kline_daily_enriched", "kline_daily"):
        paths = sorted((Path(data_root) / table / f"date={iso_date}").glob("*.parquet"))
        if not paths:
            continue
        frame = pl.read_parquet(paths)
        change_column = next(
            (name for name in ("change_pct", "pct_chg") if name in frame.columns),
            None,
        )
        if change_column is None:
            continue
        amount_column = "amount" if "amount" in frame.columns else None
        rows = frame.select(
            pl.col(change_column).cast(pl.Float64, strict=False).alias("pct_chg"),
            (
                (pl.col(amount_column).cast(pl.Float64, strict=False) / 100_000_000)
                if amount_column
                else pl.lit(None, dtype=pl.Float64)
            ).alias("amount_yi"),
        ).drop_nulls("pct_chg")
        if rows.is_empty():
            continue
        return {
            "trade_date": trade_date,
            "source": "tickflow_enriched_aggregate",
            "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "daily": rows.to_dicts(),
            "input_table": table,
        }
    return None
