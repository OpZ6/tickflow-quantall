#!/usr/bin/env python3
"""Backfill long-horizon core A-share price indices from Tencent.

Dry-run is the default. ``--apply`` stores the fetched source frame and a
recoverable copy of every replaced partition, writes through KlineRepository,
and rolls back all touched files if publication or verification fails.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.data_providers.tencent_index import fetch_index_daily  # noqa: E402
from app.indicators.pipeline import compute_enriched  # noqa: E402
from app.tickflow.repository import DataStore, KlineRepository  # noqa: E402

CORE_PRICE_INDICES = {
    "000001.SH": "上证指数",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "399006.SZ": "创业板指",
}


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _target(data_root: Path, table: str, trade_date: date) -> Path:
    root = (data_root / table).resolve()
    target = (root / f"date={trade_date.isoformat()}" / "part.parquet").resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"partition target escaped {root}: {target}")
    return target


def _fetch(start: date, end: date) -> pl.DataFrame:
    frames = [
        fetch_index_daily(symbol, start, end)
        for symbol in CORE_PRICE_INDICES
    ]
    if any(frame.is_empty() for frame in frames):
        missing = [
            symbol
            for symbol, frame in zip(CORE_PRICE_INDICES, frames, strict=True)
            if frame.is_empty()
        ]
        raise RuntimeError(f"empty Tencent index series: {', '.join(missing)}")
    return (
        pl.concat(frames, how="diagonal_relaxed")
        .unique(["symbol", "date"], keep="last")
        .sort(["symbol", "date"])
    )


def _plan(frame: pl.DataFrame, start: date, end: date, data_root: Path) -> dict[str, Any]:
    raw_dates = set(
        pl.scan_parquet(
            [str(path) for path in sorted((data_root / "kline_daily").rglob("*.parquet"))],
            missing_columns="insert",
            extra_columns="ignore",
        )
        .filter(pl.col("date").is_between(start, end, closed="both"))
        .select("date")
        .unique()
        .collect()["date"]
        .to_list()
    )
    per_symbol = []
    for symbol, name in CORE_PRICE_INDICES.items():
        series = frame.filter(pl.col("symbol") == symbol)
        dates = set(series["date"].to_list())
        per_symbol.append({
            "symbol": symbol,
            "name": name,
            "rows": series.height,
            "first_date": series["date"].min().isoformat(),
            "last_date": series["date"].max().isoformat(),
            "stock_trade_dates_missing": len(raw_dates - dates),
        })
    return {
        "source": "tencent_index",
        "price_basis": "unadjusted_price_index",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "rows": frame.height,
        "symbols": len(CORE_PRICE_INDICES),
        "duplicate_keys": frame.height - frame.select("symbol", "date").unique().height,
        "missing_ohlc_rows": frame.select(
            pl.any_horizontal(
                pl.col(column).is_null() for column in ("open", "high", "low", "close")
            ).sum()
        ).item(),
        "per_symbol": per_symbol,
    }


def _backup_targets(
    data_root: Path,
    backup_root: Path,
    dates: list[date],
) -> dict[Path, Path | None]:
    backups: dict[Path, Path | None] = {}
    for table in ("kline_index_daily", "kline_index_enriched"):
        for trade_date in dates:
            target = _target(data_root, table, trade_date)
            if target.is_file():
                backup = backup_root / target.relative_to(data_root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None
    return backups


def _rollback(backups: dict[Path, Path | None]) -> None:
    for target, backup in backups.items():
        if backup is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.is_file():
            target.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=_parse_date, default=date(2015, 1, 1))
    parser.add_argument("--end-date", type=_parse_date, default=date.today())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.end_date < args.start_date:
        parser.error("--end-date must not be before --start-date")

    data_root = settings.data_dir.resolve()
    frame = _fetch(args.start_date, args.end_date)
    plan = _plan(frame, args.start_date, args.end_date, data_root)
    plan["dry_run"] = not args.apply
    if (
        plan["duplicate_keys"]
        or plan["missing_ohlc_rows"]
        or any(item["stock_trade_dates_missing"] for item in plan["per_symbol"])
    ):
        raise RuntimeError(f"benchmark preflight failed: {plan}")
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    run_id = f"core-index-{args.end_date.strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    backup_root = data_root / ".fact_backups" / run_id
    backup_root.mkdir(parents=True)
    frame.write_parquet(backup_root / "tencent-index-source.parquet")
    dates = sorted(frame["date"].unique().to_list())
    backups = _backup_targets(data_root, backup_root, dates)
    repo = KlineRepository(DataStore(data_root))
    try:
        repo.append_index_daily(frame)
        enriched = compute_enriched(frame, factors=None, instruments=None)
        repo.append_index_enriched(enriched)
        repo.refresh_index_views()
        for item in plan["per_symbol"]:
            stored = repo.get_index_daily(
                item["symbol"], args.start_date, args.end_date,
                columns=["symbol", "date", "open", "high", "low", "close"],
            )
            if stored.height != item["rows"]:
                raise RuntimeError(
                    f"stored row mismatch for {item['symbol']}: {stored.height} != {item['rows']}"
                )
    except Exception:
        _rollback(backups)
        raise
    finally:
        repo.db.close()

    plan.update({
        "dry_run": False,
        "run_id": run_id,
        "backup": backup_root.relative_to(data_root).as_posix(),
        "replaced_partitions": sum(backup is not None for backup in backups.values()),
        "created_partitions": sum(backup is None for backup in backups.values()),
        "source_frame": "tencent-index-source.parquet",
    })
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
