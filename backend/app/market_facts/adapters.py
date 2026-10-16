"""Adapters from TickFlow's existing canonical stores to market facts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

_NEW_HIGH_LOOKBACK_SESSIONS = 100
_NEW_HIGH_MINIMUM_HISTORY_SESSIONS = 21


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


def _derive_new_high_100d(
    data_root: Path,
    table_root: Path,
    iso_date: str,
    current: pl.DataFrame,
    daily_rows: pl.DataFrame,
) -> dict[str, Any] | None:
    close_column = next(
        (name for name in ("raw_close", "close") if name in current.columns),
        None,
    )
    if close_column is None or "symbol" not in current.columns:
        return None

    previous_partitions = sorted(
        (
            path
            for path in table_root.glob("date=*")
            if path.is_dir() and path.name.removeprefix("date=") < iso_date
        ),
        reverse=True,
    )[:_NEW_HIGH_LOOKBACK_SESSIONS]
    history_frames: list[pl.DataFrame] = []
    for partition in previous_partitions:
        paths = sorted(partition.glob("*.parquet"))
        if not paths:
            continue
        history = pl.read_parquet(paths)
        history_close_column = next(
            (name for name in ("raw_close", "close") if name in history.columns),
            None,
        )
        if history_close_column is None or "symbol" not in history.columns:
            continue
        history_frames.append(
            history.select(
                pl.col("symbol").cast(pl.String),
                pl.col(history_close_column)
                .cast(pl.Float64, strict=False)
                .alias("history_close"),
            ).drop_nulls(["symbol", "history_close"])
        )
    if not history_frames:
        return None

    history_stats = pl.concat(history_frames).group_by("symbol").agg(
        pl.len().alias("history_sessions"),
        pl.col("history_close").max().alias("previous_high_close"),
    )
    candidates = (
        current.select(
            pl.col("symbol").cast(pl.String),
            pl.col(close_column)
            .cast(pl.Float64, strict=False)
            .alias("current_close"),
        )
        .join(history_stats, on="symbol", how="left")
        .join(daily_rows.select("symbol", "pct_chg"), on="symbol", how="left")
        .filter(
            (pl.col("history_sessions") >= _NEW_HIGH_MINIMUM_HISTORY_SESSIONS)
            & (pl.col("current_close") >= pl.col("previous_high_close"))
        )
    )

    instruments_path = Path(data_root) / "instruments" / "instruments.parquet"
    if instruments_path.is_file():
        instruments = pl.read_parquet(instruments_path)
        if {"symbol", "name"}.issubset(instruments.columns):
            candidates = candidates.join(
                instruments.select(
                    pl.col("symbol").cast(pl.String),
                    pl.col("name").cast(pl.String),
                ).unique("symbol"),
                on="symbol",
                how="left",
            )
    if "name" not in candidates.columns:
        candidates = candidates.with_columns(pl.lit("").alias("name"))

    stocks = (
        candidates.select(
            pl.col("symbol").alias("code"),
            pl.col("name").fill_null(""),
            pl.col("pct_chg").round(8),
        )
        .sort("code")
        .to_dicts()
    )
    return {
        "status": "ok",
        "source": "tickflow_local_kline",
        "count": len(stocks),
        "lookback_sessions": _NEW_HIGH_LOOKBACK_SESSIONS,
        "minimum_history_sessions": _NEW_HIGH_MINIMUM_HISTORY_SESSIONS,
        "stocks": stocks,
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
        new_high_100d = _derive_new_high_100d(
            Path(data_root), table_root, iso_date, frame, rows
        )
        if new_high_100d is not None:
            payload["new_high_100d"] = new_high_100d
        if previous_trade_date is not None:
            payload["previous_trade_date"] = previous_trade_date
        return payload
    return None
