#!/usr/bin/env python3
"""Import causal daily share-capital changes from the read-only Quants warehouse.

The source ``daily_basic`` contract stores share counts in 10,000-share units.
TickFlow stores absolute shares. Dry-run is the default; ``--apply`` backs up
the previous table and atomically publishes the validated replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_changes(connection: duckdb.DuckDBPyConnection, start: date, end: date) -> pl.DataFrame:
    query = """
        WITH cleaned AS (
            SELECT
                ts_code AS symbol,
                trade_date AS effective_date,
                close,
                turnover_rate,
                CASE WHEN total_share > 0 THEN total_share * 10000.0 END AS total_shares,
                CASE WHEN float_share > 0 THEN float_share * 10000.0 END AS float_shares,
                circ_mv,
                total_mv,
                pe,
                pb,
                source_name,
                updated_at
            FROM dwd_daily_basic
            WHERE trade_date BETWEEN ? AND ?
        ), marked AS (
            SELECT *,
                lag(total_shares) OVER (
                    PARTITION BY symbol ORDER BY effective_date
                ) AS previous_total_shares,
                lag(float_shares) OVER (
                    PARTITION BY symbol ORDER BY effective_date
                ) AS previous_float_shares
            FROM cleaned
        )
        SELECT
            symbol,
            effective_date AS period_end,
            close,
            turnover_rate,
            float_shares,
            total_shares,
            circ_mv,
            total_mv,
            pe,
            pb,
            effective_date,
            'quants:' || coalesce(source_name, 'unknown') AS source,
            cast(updated_at AS DATE) AS observed_at,
            'reconstructed' AS quality_level
        FROM marked
        WHERE previous_total_shares IS NULL
           OR total_shares IS DISTINCT FROM previous_total_shares
           OR float_shares IS DISTINCT FROM previous_float_shares
        ORDER BY symbol, effective_date
    """
    return connection.execute(query, [start, end]).pl()


def _validate(frame: pl.DataFrame, start: date, end: date) -> dict[str, object]:
    required = {"symbol", "effective_date", "total_shares", "float_shares", "source"}
    if frame.is_empty() or not required <= set(frame.columns):
        raise ValueError("share history is empty or missing required columns")
    duplicate_keys = frame.height - frame.select("symbol", "effective_date").unique().height
    invalid_total = frame.filter(
        pl.col("total_shares").is_null() | (pl.col("total_shares") <= 0)
    ).height
    invalid_float = frame.filter(
        pl.col("float_shares").is_null() | (pl.col("float_shares") <= 0)
    ).height
    outside_range = frame.filter(
        ~pl.col("effective_date").is_between(start, end, closed="both")
    ).height
    if duplicate_keys or invalid_total or outside_range:
        raise ValueError(
            "share history preflight failed: "
            f"duplicate_keys={duplicate_keys}, invalid_total={invalid_total}, "
            f"outside_range={outside_range}"
        )
    return {
        "rows": frame.height,
        "symbols": frame["symbol"].n_unique(),
        "first_effective_date": frame["effective_date"].min(),
        "last_effective_date": frame["effective_date"].max(),
        "duplicate_keys": duplicate_keys,
        "invalid_total_shares": invalid_total,
        "invalid_float_shares": invalid_float,
        "source_counts": frame.group_by("source").len().sort("source").to_dicts(),
    }


def _merge_predecessors(frame: pl.DataFrame, existing_path: Path, start: date) -> pl.DataFrame:
    if not existing_path.exists():
        return frame
    existing = pl.read_parquet(existing_path)
    if not {"symbol", "effective_date"} <= set(existing.columns):
        return frame
    predecessors = existing.filter(pl.col("effective_date").cast(pl.Date) < start)
    if predecessors.is_empty():
        return frame
    return (
        pl.concat([predecessors, frame], how="diagonal_relaxed")
        .sort(["symbol", "effective_date", "observed_at"], nulls_last=True)
        .unique(["symbol", "effective_date"], keep="last")
        .sort(["symbol", "effective_date"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quants-db", type=Path, required=True)
    parser.add_argument("--tickflow-data", type=Path, default=ROOT / "data")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.end_date < args.start_date:
        parser.error("--end-date must not be before --start-date")
    source_db = args.quants_db.resolve()
    if not source_db.is_file():
        parser.error(f"Quants database does not exist: {source_db}")

    connection = duckdb.connect(str(source_db), read_only=True)
    try:
        frame = _load_changes(connection, args.start_date, args.end_date)
    finally:
        connection.close()
    report: dict[str, object] = {
        "dry_run": not args.apply,
        "source_database": str(source_db),
        "source_database_bytes": source_db.stat().st_size,
        "source_database_mtime_utc": datetime.fromtimestamp(
            source_db.stat().st_mtime, UTC
        ).isoformat(),
        "source_table": "dwd_daily_basic",
        "source_share_unit": "10000_shares",
        "target_share_unit": "shares",
        "unit_multiplier": 10000,
        "start_date": args.start_date,
        "end_date": args.end_date,
        **_validate(frame, args.start_date, args.end_date),
    }
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    data_dir = args.tickflow_data.resolve()
    target = data_dir / "financials" / "shares" / "part.parquet"
    frame = _merge_predecessors(frame, target, args.start_date)
    run_id = f"share-history-{args.end_date:%Y%m%d}-{os.urandom(4).hex()}"
    backup_root = data_dir / ".fact_backups" / run_id
    backup = backup_root / "financials" / "shares" / "part.parquet"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=".shares-", suffix=".parquet", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        frame.write_parquet(temporary, compression="zstd")
        published = pl.read_parquet(temporary)
        if published.height != frame.height:
            raise ValueError("published share history row count changed")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    report.update({
        "dry_run": False,
        "run_id": run_id,
        "published_rows": frame.height,
        "published_symbols": frame["symbol"].n_unique(),
        "target": target.relative_to(data_dir).as_posix(),
        "target_sha256": _sha256(target),
        "backup": backup_root.relative_to(data_dir).as_posix(),
    })
    (backup_root / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
