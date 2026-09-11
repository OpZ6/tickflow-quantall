#!/usr/bin/env python3
"""Backfill a point-in-time Tushare trading calendar through Market Facts.

Dry-run is the default.  ``--apply`` records a content-addressed source
snapshot, publishes one as-of partition atomically, and keeps a recoverable
backup manifest when a prior partition existed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.market_facts.builders import build_trading_calendar_history_batch  # noqa: E402
from app.market_facts.registry import DatasetId  # noqa: E402
from app.market_facts.snapshots import SourceSnapshotStore  # noqa: E402
from app.market_facts.storage import FactPublication  # noqa: E402
from app.plugins.tushare.client import build_tushare_client  # noqa: E402
from app.quantx_data.schemas import SourceSpec  # noqa: E402
from app.quantx_data.source_manager import SourceManager  # noqa: E402


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _collector(start: date, end: date):
    def collect(_trade_date: str, _output_dir: Path) -> dict[str, Any]:
        raw = build_tushare_client(timeout=30.0).trade_cal(
            exchange="SSE",
            start_date=_yyyymmdd(start),
            end_date=_yyyymmdd(end),
        )
        records = [] if raw is None else raw.to_dict("records")
        return {
            "status": "ok" if records else "empty",
            "source": "tushare",
            "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "trade_calendar": {"records": records},
        }

    return collect


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def calendar_preflight(frame, start: date, end: date) -> dict[str, Any]:
    """Validate this SSE request exactly, not just the number of dates returned."""
    expected = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    actual = set(frame["trade_date"].to_list())
    report = {
        "exchange": "SSE",
        "rows": frame.height,
        "open_days": frame.filter(frame["is_open"])["trade_date"].n_unique(),
        "duplicate_keys": frame.height - frame.select("exchange", "trade_date").unique().height,
        "missing_natural_dates": len(expected - actual),
        "unexpected_dates": len(actual - expected),
        "unexpected_exchange_rows": sum(value != "SSE" for value in frame["exchange"]),
        "unknown_open_status": frame["is_open"].null_count(),
    }
    if end < start or any(report[key] for key in (
        "duplicate_keys", "missing_natural_dates", "unexpected_dates",
        "unexpected_exchange_rows", "unknown_open_status",
    )):
        raise ValueError(f"calendar preflight failed: {report}")
    return report


def calendar_payload(start: date, end: date, source_file: Path | None = None):
    request = {"exchange": "SSE", "start_date": start.isoformat(), "end_date": end.isoformat()}
    if source_file is not None and source_file.exists():
        saved = json.loads(source_file.read_text(encoding="utf-8"))
        if saved.get("request") != request or saved.get("payload", {}).get("status") != "ok":
            raise ValueError("saved calendar request/status mismatch")
        return saved["payload"]
    manager = SourceManager()
    spec = SourceSpec(
        name="tushare_calendar_history",
        required=True,
        collector="builtin:tushare_calendar_history",
        role="market",
        min_records=1,
        display_name="Tushare trading calendar history",
        dependency_modules=("tushare",),
        timeout_seconds=30,
        max_retries=0,
    )
    manager.register(spec, _collector(start, end))
    with tempfile.TemporaryDirectory(prefix="tickflow-calendar-") as temp_dir:
        result = manager.collect(
            spec.name,
            _yyyymmdd(end),
            Path(temp_dir),
            force=True,
        )
    if not result.ok:
        raise RuntimeError(result.error or f"calendar source status: {result.status}")
    if source_file is not None:
        source_file.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create: never overwrite prior source evidence. A partial
        # file fails JSON parsing on resume instead of triggering another call.
        with source_file.open("x", encoding="utf-8") as stream:
            json.dump({"request": request, "payload": result.payload}, stream, ensure_ascii=False, default=str)
    return result.payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=_parse_date, default=date(2015, 1, 1))
    parser.add_argument("--end-date", type=_parse_date, default=date.today())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source-file", type=Path, help="Save successful response; reuse existing file without network")
    args = parser.parse_args()
    if args.end_date < args.start_date:
        parser.error("--end-date must not be before --start-date")
    payload = calendar_payload(args.start_date, args.end_date, args.source_file)

    run_id = f"calendar-history-{_yyyymmdd(args.end_date)}-{uuid4().hex[:8]}"
    batch = build_trading_calendar_history_batch(
        _yyyymmdd(args.end_date), payload, run_id
    )
    frame = batch.frame
    coverage = calendar_preflight(frame, args.start_date, args.end_date)
    plan: dict[str, Any] = {
        "dry_run": not args.apply,
        "source": "tushare",
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        **coverage,
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    data_root = settings.data_dir.resolve()
    snapshot = SourceSnapshotStore(data_root).record(
        source_id="tushare",
        dataset_ids=(DatasetId.TRADING_CALENDAR,),
        trade_date=_yyyymmdd(args.end_date),
        run_id=run_id,
        payload=payload,
    )
    relative = (
        Path(DatasetId.TRADING_CALENDAR.value)
        / f"date={args.end_date.isoformat()}"
        / "part.parquet"
    )
    existing = data_root / relative
    backup_root = data_root / ".fact_backups" / run_id
    if existing.is_file():
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(existing, backup)

    publication = FactPublication(data_root, run_id)
    try:
        publication.stage([batch])
        artifacts = publication.manifest_artifacts()
        publication.commit()
        publication.finalize()
    except Exception:
        publication.rollback()
        publication.abandon()
        raise

    plan.update({
        "dry_run": False,
        "run_id": run_id,
        "snapshot_sha256": snapshot.sha256,
        "snapshot_metadata": [
            path.relative_to(data_root).as_posix() for path in snapshot.metadata_paths
        ],
        "backup": backup_root.relative_to(data_root).as_posix(),
        "artifacts": artifacts,
    })
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
