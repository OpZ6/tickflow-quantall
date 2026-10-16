#!/usr/bin/env python3
"""Backfill rolling sector-width history from a recorded Legulegu snapshot."""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.market_facts.builders import build_sector_breadth_history_batches  # noqa: E402
from app.market_facts.storage import FactPublication  # noqa: E402


def _metadata_path(data_root: Path, trade_date: str) -> Path:
    root = (
        data_root
        / "source_snapshots"
        / "legulegu"
        / "sector_breadth_daily"
        / f"trade_date={datetime.strptime(trade_date, '%Y%m%d').date().isoformat()}"
    )
    paths = sorted(root.glob("*.meta.json"), key=lambda path: path.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"no Legulegu sector snapshot for {trade_date}")
    return paths[-1]


def _load_snapshot(data_root: Path, metadata_path: Path) -> tuple[dict, dict]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    blob = data_root / str(metadata["blob_path"])
    payload = json.loads(gzip.decompress(blob.read_bytes()))
    return metadata, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trade_date", help="Snapshot date in YYYYMMDD format")
    parser.add_argument("--apply", action="store_true", help="Publish after preflight")
    args = parser.parse_args()

    data_root = REPO_ROOT / "data"
    metadata_path = _metadata_path(data_root, args.trade_date)
    metadata, payload = _load_snapshot(data_root, metadata_path)
    run_id = f"sector-history-{args.trade_date}-{uuid4().hex[:8]}"
    batches = build_sector_breadth_history_batches(
        args.trade_date, {"legulegu": payload}, run_id
    )
    if not batches:
        raise RuntimeError("snapshot contains no valid sector-width history")

    plan = {
        "dry_run": not args.apply,
        "snapshot": metadata_path.relative_to(REPO_ROOT).as_posix(),
        "blob_sha256": metadata.get("blob_sha256"),
        "dates": len(batches),
        "start": batches[0].trade_date.isoformat(),
        "end": batches[-1].trade_date.isoformat(),
        "rows": sum(batch.frame.height for batch in batches),
        "level1_rows": sum(
            batch.frame.filter(batch.frame["dimension"] == "sw_level1").height
            for batch in batches
        ),
        "level2_rows": sum(
            batch.frame.filter(batch.frame["dimension"] == "sw_level2").height
            for batch in batches
        ),
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    backup_root = data_root / ".fact_backups" / run_id
    for batch in batches:
        relative = (
            Path(batch.dataset_id.value)
            / f"date={batch.trade_date.isoformat()}"
            / "part.parquet"
        )
        source = data_root / relative
        if source.is_file():
            target = backup_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    publication = FactPublication(data_root, run_id)
    try:
        publication.stage(batches)
        artifacts = publication.manifest_artifacts()
        publication.commit()
        publication.finalize()
    except Exception:
        publication.rollback()
        publication.abandon()
        raise

    plan.update(
        {
            "dry_run": False,
            "run_id": run_id,
            "backup": backup_root.relative_to(REPO_ROOT).as_posix(),
            "artifacts": artifacts,
        }
    )
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
