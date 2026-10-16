"""Import an explicit dated popularity snapshot through the canonical fact contract."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.market_facts.builders import _build_security_popularity
from app.market_facts.registry import DatasetId
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
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    payload_date = str(payload.get("trade_date") or payload.get("date") or "").replace("-", "")
    if payload_date != trade_date:
        raise ValueError(f"snapshot date {payload_date!r} does not match {trade_date}")
    payload["source_schema_version"] = payload.get("schema_version")
    payload["schema_version"] = 1
    normalized = normalize_source("security_popularity", trade_date, payload)
    run_id = f"popularity-import-{trade_date}-{uuid.uuid4().hex[:8]}"
    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    SourceSnapshotStore(args.data_dir).record(
        source_id="security_popularity",
        dataset_ids=(DatasetId.SECURITY_POPULARITY_DAILY,),
        trade_date=trade_date,
        run_id=run_id,
        payload=payload,
    )
    # Persist the frozen snapshot where the offline recompute path looks for it,
    # so a later --recompute reuses it instead of publishing an empty partition.
    date_dir = args.data_dir / "quantx" / trade_date
    for folder, content in (("normalized", normalized), ("raw", payload)):
        target_file = date_dir / folder / "security_popularity.json"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    batch = _build_security_popularity(
        trade_date, {"security_popularity": normalized}, run_id, ingested_at,
    )
    publication = FactPublication(args.data_dir, run_id)
    try:
        publication.stage([batch])
        publication.commit()
        publication.finalize()
    except Exception:
        publication.abandon()
        raise
    print(json.dumps({"dataset": batch.dataset_id.value, "date": trade_date, "rows": batch.frame.height}, ensure_ascii=False))


if __name__ == "__main__":
    main()
