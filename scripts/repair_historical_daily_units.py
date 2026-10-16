#!/usr/bin/env python3
"""Repair 2015+ daily bars written with the legacy volume/amount units.

The evidenced legacy interval ends on 2025-08-22.  In that interval the local
parquet files store volume in shares and amount in thousand yuan.  The current
daily contract stores volume in lots and amount in yuan.  Dry-run is the
default; apply mode backs up every touched partition before atomic replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ("kline_daily", "kline_daily_enriched")
DEFAULT_START = date(2016, 1, 1)
EARLIEST_START = date(2015, 1, 1)
DEFAULT_END = date(2025, 8, 22)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _partition_date(path: Path) -> date:
    return date.fromisoformat(path.parent.name.removeprefix("date="))


def _targets(data_root: Path, start: date, end: date) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for dataset in DATASETS:
        root = (data_root / dataset).resolve()
        paths = [
            path.resolve()
            for path in sorted(root.glob("date=*/part.parquet"))
            if start <= _partition_date(path) <= end
        ]
        if not paths:
            raise RuntimeError(f"no {dataset} partitions in {start}..{end}")
        if any(not path.is_relative_to(root) for path in paths):
            raise RuntimeError(f"partition escaped dataset root: {dataset}")
        result[dataset] = paths
    raw_dates = {_partition_date(path) for path in result["kline_daily"]}
    enriched_dates = {_partition_date(path) for path in result["kline_daily_enriched"]}
    if raw_dates != enriched_dates:
        raise RuntimeError(
            "raw/enriched date coverage differs: "
            f"raw_only={len(raw_dates - enriched_dates)}, "
            f"enriched_only={len(enriched_dates - raw_dates)}"
        )
    return result


def _positive_ratio(frame: pl.DataFrame) -> pl.Series:
    price = "raw_close" if "raw_close" in frame.columns else "close"
    return (
        frame.filter(
            (pl.col("volume") > 0) & (pl.col("amount") > 0) & (pl.col(price) > 0)
        )
        .select((pl.col("amount") / (pl.col("volume") * pl.col(price))).alias("ratio"))
        .get_column("ratio")
    )


def _transform_partition(frame: pl.DataFrame, expected_date: date) -> pl.DataFrame:
    required = {"symbol", "date", "close", "volume", "amount"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"partition lacks required columns: {sorted(missing)}")
    dates = set(frame.get_column("date").drop_nulls().unique().to_list())
    if dates != {expected_date} or frame.get_column("date").null_count():
        raise RuntimeError(f"partition date mismatch for {expected_date}: {dates}")
    ratios = _positive_ratio(frame)
    if ratios.is_empty() or ratios.max() >= 1.0:
        raise RuntimeError(
            f"{expected_date} is not uniformly legacy-unit data; max ratio={ratios.max()}"
        )
    transformed = frame.with_columns(
        (pl.col("volume") / 100.0).alias("volume"),
        (pl.col("amount") * 1_000.0).alias("amount"),
    )
    post = _positive_ratio(transformed)
    if post.min() < 0.1 or post.max() >= 10_000.0:
        # A 0.01-yuan close can coexist with intraday trades above 10 yuan in
        # old negotiated NEEQ bars. Check the actual price range in those cases.
        price = "raw_close" if "raw_close" in frame.columns else "close"
        low = "raw_low" if "raw_low" in frame.columns else "low"
        high = "raw_high" if "raw_high" in frame.columns else "high"
        ratio = pl.col("amount") / (pl.col("volume") * pl.col(price))
        exceptional = transformed.filter(
            (pl.col("volume") > 0) & (pl.col("amount") > 0) & (pl.col(price) > 0)
            & ((ratio < 0.1) | (ratio >= 10_000.0))
        )
        average_price = pl.col("amount") / (pl.col("volume") * 100.0)
        if {low, high} - set(transformed.columns) or exceptional.filter(
            ~average_price.is_between(pl.col(low) * 0.99, pl.col(high) * 1.01)
            .fill_null(False)
        ).height:
            raise RuntimeError(
                f"{expected_date} post-repair ratio outside evidenced bounds: "
                f"min={post.min()}, max={post.max()}"
            )
    return transformed


def _preflight(
    data_root: Path,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
) -> tuple[dict, dict[str, list[Path]]]:
    targets = _targets(data_root, start, end)
    rows: dict[str, int] = {}
    bytes_by_dataset: dict[str, int] = {}
    ratio_bounds: dict[str, dict[str, float]] = {}
    for dataset, paths in targets.items():
        row_count = 0
        byte_count = 0
        minimum = float("inf")
        maximum = float("-inf")
        for path in paths:
            frame = pl.read_parquet(path)
            transformed = _transform_partition(frame, _partition_date(path))
            ratios = _positive_ratio(transformed)
            row_count += frame.height
            byte_count += path.stat().st_size
            minimum = min(minimum, float(ratios.min()))
            maximum = max(maximum, float(ratios.max()))
        rows[dataset] = row_count
        bytes_by_dataset[dataset] = byte_count
        ratio_bounds[dataset] = {"min": minimum, "max": maximum}
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "conversion": {"volume": "shares / 100 -> lots", "amount": "thousand yuan * 1000 -> yuan"},
        "partitions": {key: len(value) for key, value in targets.items()},
        "rows": rows,
        "source_bytes": bytes_by_dataset,
        "post_ratio_bounds": ratio_bounds,
    }, targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    if args.start < EARLIEST_START or args.end > DEFAULT_END or args.start > args.end:
        parser.error(
            f"repair range must stay within {EARLIEST_START}..{DEFAULT_END}"
        )

    plan, targets = _preflight(data_root, args.start, args.end)
    plan["dry_run"] = not args.apply
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    run_id = f"daily-unit-repair-{uuid4().hex[:8]}"
    backup_root = data_root / ".fact_backups" / run_id
    backup_root.mkdir(parents=True)
    backups: dict[Path, Path] = {}
    artifacts: list[dict] = []
    sys.path.insert(0, str(ROOT / "backend"))
    from app.enriched_generation import EnrichedPublication

    publication = EnrichedPublication(data_root, "stock")
    publication.begin()
    changed = False
    try:
        for dataset in DATASETS:
            for target in targets[dataset]:
                backup = backup_root / target.relative_to(data_root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                backups[target] = backup
                replacement = _transform_partition(
                    pl.read_parquet(target), _partition_date(target)
                )
                temporary = target.with_name(f".part.{run_id}.tmp")
                replacement.write_parquet(temporary)
                publication.mark_changed()
                changed = True
                os.replace(temporary, target)
                artifacts.append({
                    "path": target.relative_to(data_root).as_posix(),
                    "rows": replacement.height,
                    "backup_sha256": _sha256(backup),
                    "published_sha256": _sha256(target),
                })
        generation = publication.commit()
    except BaseException as exc:
        for target, backup in backups.items():
            shutil.copy2(backup, target)
        for paths in targets.values():
            for target in paths:
                target.with_name(f".part.{run_id}.tmp").unlink(missing_ok=True)
        if changed:
            publication.commit()
        else:
            publication.abandon()
        (backup_root / "manifest.json").write_text(
            json.dumps({**plan, "status": "failed_rolled_back", "error": repr(exc)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise

    plan.update({
        "dry_run": False,
        "status": "complete",
        "run_id": run_id,
        "enriched_generation": generation,
        "backup": backup_root.relative_to(data_root).as_posix(),
        "artifacts": artifacts,
    })
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in plan.items() if key != "artifacts"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
