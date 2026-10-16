"""Import an explicit frozen current-day anomaly-analysis snapshot as a dated fact.

The Fuyao anomaly endpoint only returns the current-day snapshot, so historical
dates must be frozen at collection time and imported through the canonical fact
contract, exactly like the popularity snapshot import.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.market_facts.builders import FactBatch, _build_stock_logic_evidence
from app.market_facts.registry import DatasetId, get_dataset
from app.market_facts.snapshots import SourceSnapshotStore
from app.market_facts.storage import FactPublication
from app.quantx_data.normalizers import normalize_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    trade_date = args.date.replace("-", "")
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    items = raw.get("item") if isinstance(raw.get("item"), list) else raw.get("records")
    timestamp = raw.get("timestamp")
    if timestamp is None:
        raise ValueError("snapshot must carry the upstream millisecond timestamp")
    observed = datetime.fromtimestamp(int(timestamp) / 1000, ZoneInfo("Asia/Shanghai"))
    if observed.strftime("%Y%m%d") != trade_date:
        raise ValueError(f"snapshot timestamp date {observed:%Y%m%d} does not match {trade_date}")
    records = [row for row in (items or []) if isinstance(row, dict)]
    payload = {
        "schema_version": 1,
        "trade_date": trade_date,
        "source": "fuyao_anomaly",
        "scraped_at": observed.isoformat(timespec="seconds"),
        "status": "ok" if records else "empty",
        "timestamp": int(timestamp),
        "records": records,
    }
    normalized = normalize_source("fuyao_anomaly", trade_date, payload)
    run_id = f"anomaly-import-{trade_date}-{uuid.uuid4().hex[:8]}"
    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    SourceSnapshotStore(args.data_dir).record(
        source_id="fuyao_anomaly",
        dataset_ids=(DatasetId.STOCK_LOGIC_EVIDENCE_DAILY,),
        trade_date=trade_date,
        run_id=run_id,
        payload=payload,
    )
    # Persist the frozen snapshot where the offline recompute path looks for it,
    # so a later --recompute reuses it instead of publishing an empty partition.
    date_dir = args.data_dir / "quantx" / trade_date
    for folder, content in (("normalized", normalized), ("raw", payload)):
        target_file = date_dir / folder / "fuyao_anomaly.json"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    empty_ladder = pl.DataFrame(schema=get_dataset(DatasetId.LIMIT_LADDER_DAILY).storage_schema)
    batch = _build_stock_logic_evidence(
        trade_date, {"fuyao_anomaly": normalized}, empty_ladder, run_id, ingested_at,
    )
    frame = batch.frame
    target = (
        args.data_dir
        / DatasetId.STOCK_LOGIC_EVIDENCE_DAILY.value
        / f"date={batch.trade_date.isoformat()}"
        / "part.parquet"
    )
    if target.is_file() and not frame.is_empty():
        existing = pl.read_parquet(target)
        frame = pl.concat([existing, frame], how="diagonal_relaxed").unique(
            subset=["trade_date", "evidence_source", "symbol", "evidence_kind"],
            keep="last",
            maintain_order=True,
        )
    batch = FactBatch(DatasetId.STOCK_LOGIC_EVIDENCE_DAILY, batch.trade_date, frame)
    publication = FactPublication(args.data_dir, run_id)
    try:
        publication.stage([batch])
        publication.commit()
        publication.finalize()
    except Exception:
        publication.abandon()
        raise
    print(json.dumps({
        "dataset": batch.dataset_id.value, "date": trade_date,
        "rows": batch.frame.height, "imported": len(records),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
