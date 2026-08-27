"""Adapters from TickFlow's existing canonical stores to market facts."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl


def has_tickflow_market_partition(data_root: Path, trade_date: str) -> bool:
    """Return whether TickFlow already published local daily facts for the date."""
    iso_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    return any(
        any((Path(data_root) / table / f"date={iso_date}").glob("*.parquet"))
        for table in ("kline_daily_enriched", "kline_daily", "market_breadth_daily")
    )


def load_published_fact_evidence(data_root: Path, trade_date: str) -> dict[str, Any] | None:
    """Use an already published breadth fact as proof that the market opened."""
    iso_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    path = Path(data_root) / "market_breadth_daily" / f"date={iso_date}" / "part.parquet"
    if not path.is_file():
        return None
    frame = pl.read_parquet(path)
    if frame.is_empty():
        return None
    return {
        "trade_date": trade_date,
        "source": "tickflow_published_fact",
        "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "input_table": "market_breadth_daily",
    }


def load_tickflow_market_aggregate(data_root: Path, trade_date: str) -> dict[str, Any] | None:
    """Build daily breadth inputs from the already published TickFlow partition."""
    iso_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    for table in ("kline_daily_enriched", "kline_daily"):
        table_root = Path(data_root) / table
        paths = sorted((table_root / f"date={iso_date}").glob("*.parquet"))
        if not paths:
            continue
        frame = pl.read_parquet(paths)
        change_column = next(
            (name for name in ("change_pct", "pct_chg") if name in frame.columns),
            None,
        )
        amount_expr = (
            pl.col("amount_yi").cast(pl.Float64, strict=False)
            if "amount_yi" in frame.columns
            else (
                pl.col("amount").cast(pl.Float64, strict=False) / 100_000_000
                if "amount" in frame.columns
                else pl.lit(None, dtype=pl.Float64)
            )
        ).alias("amount_yi")
        previous_trade_date: str | None = None
        if change_column is not None:
            expressions = [
                pl.col(change_column).cast(pl.Float64, strict=False).alias("pct_chg"),
                amount_expr,
            ]
            if "symbol" in frame.columns:
                expressions.insert(0, pl.col("symbol").cast(pl.String))
            rows = frame.select(expressions)
        else:
            close_column = next(
                (name for name in ("raw_close", "close") if name in frame.columns),
                None,
            )
            if close_column is None or "symbol" not in frame.columns:
                continue
            previous_parts = sorted(
                (
                    path
                    for path in table_root.glob("date=*/part.parquet")
                    if path.parent.name.removeprefix("date=") < iso_date
                ),
                reverse=True,
            )
            if not previous_parts:
                continue
            previous = pl.read_parquet(previous_parts[0])
            previous_close_column = next(
                (name for name in ("raw_close", "close") if name in previous.columns),
                None,
            )
            if previous_close_column is None or "symbol" not in previous.columns:
                continue
            previous_trade_date = previous_parts[0].parent.name.removeprefix(
                "date="
            ).replace("-", "")
            rows = (
                frame.select(
                    pl.col("symbol").cast(pl.String),
                    pl.col(close_column)
                    .cast(pl.Float64, strict=False)
                    .alias("current_close"),
                    amount_expr,
                )
                .join(
                    previous.select(
                        pl.col("symbol").cast(pl.String),
                        pl.col(previous_close_column)
                        .cast(pl.Float64, strict=False)
                        .alias("previous_close"),
                    ),
                    on="symbol",
                    how="left",
                )
                .with_columns(
                    pl.when(pl.col("previous_close") > 0)
                    .then(
                        ((pl.col("current_close") / pl.col("previous_close")) - 1)
                        * 100
                    )
                    .otherwise(None)
                    .round(8)
                    .alias("pct_chg")
                )
                .select("symbol", "pct_chg", "amount_yi")
            )
        if rows.is_empty():
            continue
        payload = {
            "trade_date": trade_date,
            "source": "tickflow_enriched_aggregate",
            "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "daily": rows.to_dicts(),
            "input_table": table,
        }
        if previous_trade_date is not None:
            payload["previous_trade_date"] = previous_trade_date
        return payload
    return None
