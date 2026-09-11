#!/usr/bin/env python3
"""Repair enriched turnover rates left 100x high by the daily-unit migration.

The legacy interval through 2025-08-22 originally stored volume in shares.
``repair_historical_daily_units.py`` converted that volume to lots, but the
already-materialized ``turnover_rate`` column retained the value calculated
from share-volume.  The enriched contract stores percentage points, so those
historical values must be divided by 100.  Dry-run is the default; apply mode
backs up every touched partition before atomic replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START = date(2016, 1, 1)
DEFAULT_END = date(2025, 8, 22)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _partition_date(path: Path) -> date:
    return date.fromisoformat(path.parent.name.removeprefix("date="))


def _targets(data_root: Path, start: date, end: date) -> list[Path]:
    dataset_root = (data_root / "kline_daily_enriched").resolve()
    paths = [
        path.resolve()
        for path in sorted(dataset_root.glob("date=*/part.parquet"))
        if start <= _partition_date(path) <= end
    ]
    if not paths:
        raise RuntimeError(f"no enriched partitions in {start}..{end}")
    if any(not path.is_relative_to(dataset_root) for path in paths):
        raise RuntimeError("partition escaped kline_daily_enriched root")
    return paths


def _transform_partition(frame: pl.DataFrame, expected_date: date) -> pl.DataFrame:
    required = {"symbol", "date", "turnover_rate"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"partition lacks required columns: {sorted(missing)}")
    dates = set(frame.get_column("date").drop_nulls().unique().to_list())
    if dates != {expected_date} or frame.get_column("date").null_count():
        raise RuntimeError(f"partition date mismatch for {expected_date}: {dates}")

    positive = frame.get_column("turnover_rate").drop_nulls().filter(
        frame.get_column("turnover_rate").drop_nulls() > 0
    )
    if positive.is_empty() or positive.median() < 10.0:
        raise RuntimeError(
            f"{expected_date} is not evidenced 100x turnover data; "
            f"positive median={positive.median()}"
        )
    repaired = frame.with_columns(
        (pl.col("turnover_rate") / 100.0).alias("turnover_rate")
    )
    repaired_positive = repaired.get_column("turnover_rate").drop_nulls().filter(
        repaired.get_column("turnover_rate").drop_nulls() > 0
    )
    if repaired_positive.median() >= 10.0 or repaired_positive.max() > 100.0:
        raise RuntimeError(
            f"{expected_date} post-repair turnover outside evidenced bounds: "
            f"median={repaired_positive.median()}, max={repaired_positive.max()}"
        )
    return repaired


def _preflight(
    data_root: Path,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
) -> tuple[dict, list[Path]]:
    paths = _targets(data_root, start, end)
    row_count = 0
    source_bytes = 0
    pre_medians: list[float] = []
    post_medians: list[float] = []
    post_maximum = 0.0
    for path in paths:
        frame = pl.read_parquet(path)
        repaired = _transform_partition(frame, _partition_date(path))
        before = frame.get_column("turnover_rate").drop_nulls().filter(
            frame.get_column("turnover_rate").drop_nulls() > 0
        )
        after = repaired.get_column("turnover_rate").drop_nulls().filter(
            repaired.get_column("turnover_rate").drop_nulls() > 0
        )
        row_count += frame.height
        source_bytes += path.stat().st_size
        pre_medians.append(float(before.median()))
        post_medians.append(float(after.median()))
        post_maximum = max(post_maximum, float(after.max()))
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "conversion": {"turnover_rate": "legacy percentage points / 100"},
        "partitions": len(paths),
        "rows": row_count,
        "source_bytes": source_bytes,
        "daily_median_before": {
            "min": min(pre_medians),
            "max": max(pre_medians),
        },
        "daily_median_after": {
            "min": min(post_medians),
            "max": max(post_medians),
        },
        "post_maximum": post_maximum,
    }, paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.start < DEFAULT_START or args.end > DEFAULT_END or args.start > args.end:
        parser.error(f"repair range must stay within {DEFAULT_START}..{DEFAULT_END}")

    data_root = args.data_root.resolve()
    plan, targets = _preflight(data_root, args.start, args.end)
    plan["dry_run"] = not args.apply
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    run_id = f"turnover-rate-repair-{uuid4().hex[:8]}"
    backup_root = data_root / ".fact_backups" / run_id
    backup_root.mkdir(parents=True)
    backups: dict[Path, Path] = {}
    artifacts: list[dict] = []
    try:
        for target in targets:
            backup = backup_root / target.relative_to(data_root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backups[target] = backup
            replacement = _transform_partition(
                pl.read_parquet(target), _partition_date(target)
            )
            temporary = target.with_name(f".part.{run_id}.tmp")
            replacement.write_parquet(temporary)
            os.replace(temporary, target)
            artifacts.append({
                "path": target.relative_to(data_root).as_posix(),
                "rows": replacement.height,
                "backup_sha256": _sha256(backup),
                "published_sha256": _sha256(target),
            })
    except BaseException as exc:
        for target, backup in backups.items():
            shutil.copy2(backup, target)
        for target in targets:
            target.with_name(f".part.{run_id}.tmp").unlink(missing_ok=True)
        (backup_root / "manifest.json").write_text(
            json.dumps(
                {**plan, "status": "failed_rolled_back", "error": repr(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise

    plan.update({
        "dry_run": False,
        "status": "complete",
        "run_id": run_id,
        "backup": backup_root.relative_to(data_root).as_posix(),
        "artifacts": artifacts,
    })
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(
        {key: value for key, value in plan.items() if key != "artifacts"},
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
