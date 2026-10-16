#!/usr/bin/env python3
"""Backfill bounded, signal-linked minute execution samples from TDX.

Dry-run is the default.  The caller must name both the close-of-day signal date
and its later execution date.  ``--apply`` keeps a recoverable copy of the
target partition and records the fetched source frame plus signal provenance.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.plugins.tdx.provider import TdxProvider  # noqa: E402
from app.services.kline_sync import (  # noqa: E402
    _enforce_minute_beijing_wallclock,
    _write_minute_partition,
)

DEFAULT_STRATEGY = "quants_vcp_legacy_v1"
MIN_COMPLETE_SESSION_ROWS = 200


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _partition(data_root: Path, execution_date: date) -> Path:
    root = (data_root / "kline_minute").resolve()
    target = (root / f"date={execution_date.isoformat()}" / "part.parquet").resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"partition target escaped {root}: {target}")
    return target


def _select_signals(
    data_root: Path,
    signal_date: date,
    strategy_ids: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    paths = sorted((data_root / "strategy_signal_events").glob("date=*/part.parquet"))
    if not paths:
        raise RuntimeError("strategy_signal_events has no parquet files")
    frame = (
        pl.scan_parquet([str(path) for path in paths])
        .filter(
            (pl.col("event_date") == signal_date)
            & pl.col("strategy_id").is_in(strategy_ids)
            & pl.col("event_type").is_in(["candidate", "entry"])
        )
        .select(
            "strategy_id",
            "symbol",
            "event_date",
            "event_type",
            "source_run_id",
            "score",
        )
        .collect()
    )
    if frame.is_empty():
        raise RuntimeError(
            f"no candidate/entry signals for {signal_date} and {strategy_ids}"
        )
    records = sorted(
        frame.to_dicts(),
        key=lambda row: (
            row.get("score") is not None,
            float(row.get("score") or 0.0),
        ),
        reverse=True,
    )
    ordered_symbols = list(dict.fromkeys(str(row["symbol"]) for row in records))[:limit]
    selected: dict[str, dict[str, Any]] = {}
    for row in records:
        symbol = str(row["symbol"])
        if symbol not in ordered_symbols:
            continue
        item = selected.setdefault(
            symbol,
            {
                "symbol": symbol,
                "score": row.get("score"),
                "strategy_ids": [],
                "event_types": [],
                "source_run_ids": [],
            },
        )
        for source, key in (
            (row["strategy_id"], "strategy_ids"),
            (row["event_type"], "event_types"),
            (row["source_run_id"], "source_run_ids"),
        ):
            if source not in item[key]:
                item[key].append(source)
    return [selected[symbol] for symbol in ordered_symbols]


def _fetch(symbols: list[str], execution_date: date) -> pl.DataFrame:
    provider = TdxProvider()
    try:
        frame = provider.get_minute(
            symbols,
            datetime.combine(execution_date, time(9, 25)),
            datetime.combine(execution_date, time(15, 5)),
        )
    finally:
        provider.close()
    if frame.is_empty():
        return frame
    return (
        _enforce_minute_beijing_wallclock(frame, source="tdx")
        .filter(pl.col("datetime").dt.date() == execution_date)
        .unique(["symbol", "datetime"], keep="last")
        .sort(["symbol", "datetime"])
    )


def _plan(
    signals: list[dict[str, Any]],
    frame: pl.DataFrame,
    signal_date: date,
    execution_date: date,
    strategy_ids: list[str],
) -> dict[str, Any]:
    requested = [item["symbol"] for item in signals]
    per_symbol = []
    for item in signals:
        symbol = item["symbol"]
        rows = frame.filter(pl.col("symbol") == symbol)
        per_symbol.append({
            **item,
            "minute_rows": rows.height,
            "first_minute": str(rows["datetime"].min()) if rows.height else None,
            "last_minute": str(rows["datetime"].max()) if rows.height else None,
            "complete_session_candidate": rows.height >= MIN_COMPLETE_SESSION_ROWS,
        })
    duplicate_keys = (
        frame.height - frame.select("symbol", "datetime").unique().height
        if not frame.is_empty()
        else 0
    )
    null_ohlc = (
        int(
            frame.select(
                pl.any_horizontal(
                    pl.col(column).is_null()
                    for column in ("open", "high", "low", "close")
                ).sum()
            ).item()
        )
        if not frame.is_empty()
        else 0
    )
    returned = set(frame["symbol"].unique().to_list()) if not frame.is_empty() else set()
    return {
        "source": "tdx",
        "purpose": "signal_linked_minute_execution_sample",
        "signal_date": signal_date.isoformat(),
        "execution_date": execution_date.isoformat(),
        "strategy_ids": strategy_ids,
        "requested_symbols": len(requested),
        "returned_symbols": len(returned),
        "missing_symbols": sorted(set(requested) - returned),
        "complete_session_candidates": sum(
            bool(item["complete_session_candidate"]) for item in per_symbol
        ),
        "rows": frame.height,
        "duplicate_keys": duplicate_keys,
        "null_ohlc_rows": null_ohlc,
        "selection": per_symbol,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-date", type=_parse_date, required=True)
    parser.add_argument("--execution-date", type=_parse_date, required=True)
    parser.add_argument("--strategy-id", action="append", dest="strategy_ids")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.execution_date <= args.signal_date:
        parser.error("--execution-date must be after --signal-date")
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")

    strategy_ids = list(dict.fromkeys(args.strategy_ids or [DEFAULT_STRATEGY]))
    data_root = settings.data_dir.resolve()
    signals = _select_signals(data_root, args.signal_date, strategy_ids, args.limit)
    frame = _fetch([item["symbol"] for item in signals], args.execution_date)
    plan = _plan(signals, frame, args.signal_date, args.execution_date, strategy_ids)
    plan["dry_run"] = not args.apply
    if plan["duplicate_keys"] or plan["null_ohlc_rows"]:
        raise RuntimeError(f"minute sample preflight failed: {plan}")
    if plan["complete_session_candidates"] == 0:
        raise RuntimeError(f"no complete minute session candidates: {plan}")
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    run_id = (
        f"minute-sample-{args.signal_date.strftime('%Y%m%d')}-"
        f"{args.execution_date.strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    )
    backup_root = data_root / ".fact_backups" / run_id
    backup_root.mkdir(parents=True)
    source_frame = backup_root / "tdx-minute-source.parquet"
    frame.write_parquet(source_frame)
    target = _partition(data_root, args.execution_date)
    backup = None
    if target.is_file():
        backup = backup_root / target.relative_to(data_root)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    try:
        _write_minute_partition(frame, data_root / "kline_minute")
        stored = pl.read_parquet(target).filter(
            pl.col("symbol").is_in([item["symbol"] for item in signals])
        )
        expected = frame.select("symbol", "datetime").unique().height
        observed = stored.select("symbol", "datetime").unique().height
        if observed < expected:
            raise RuntimeError(f"stored minute keys {observed} < fetched keys {expected}")
    except Exception:
        if backup is not None:
            shutil.copy2(backup, target)
        elif target.is_file():
            target.unlink()
        raise

    plan.update({
        "dry_run": False,
        "run_id": run_id,
        "backup": backup_root.relative_to(data_root).as_posix(),
        "replaced_partition": backup is not None,
        "source_frame": source_frame.name,
    })
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
