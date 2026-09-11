"""Save one resumable security-history source page; never publish production facts."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.quantx_data.security_snapshots import collect_step


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", choices=("namechange", "stock_basic"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch-one", action="store_true", help="Permit one next-page source request")
    parser.add_argument("--inspect-names", action="store_true", help="Offline interval validation of saved name pages")
    parser.add_argument("--inspect-listings", action="store_true", help="Offline validation of saved listing status pages")
    parser.add_argument("--inspect-facts", action="store_true", help="Build and validate a fact batch in memory only")
    args = parser.parse_args()
    if args.inspect_names and (args.fetch_one or args.endpoint != "namechange"):
        parser.error("--inspect-names requires namechange and cannot fetch")
    if args.inspect_listings and (args.fetch_one or args.endpoint != "stock_basic"):
        parser.error("--inspect-listings requires stock_basic and cannot fetch")
    if args.inspect_facts and args.fetch_one:
        parser.error("--inspect-facts cannot fetch")
    state = collect_step(args.output, args.endpoint, allow_network=args.fetch_one)
    if args.inspect_names:
        from app.quantx_data.security_name_history import (
            inspect_name_pages,
        )

        pages = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.output.glob("page-*.json"))]
        state["name_history"] = inspect_name_pages(pages)
    if args.inspect_listings:
        from app.quantx_data.security_listing_history import summarize_listing_history

        pages = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.output.glob("page-*.json"))]
        state["listing_history"] = summarize_listing_history(pages)
    if args.inspect_facts:
        from app.market_facts.security_history import build_security_history_batch

        pages = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.output.glob("page-*.json"))]
        if pages:
            snapshot_date = max(datetime.fromisoformat(page["scraped_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date() for page in pages)
            try:
                batch = build_security_history_batch(
                    args.endpoint,
                    pages,
                    snapshot_date=snapshot_date,
                    run_id="offline-inspection",
                )
            except ValueError as exc:
                state["fact_batch"] = {
                    "status": "rejected",
                    "error": str(exc),
                    "production_published": False,
                }
            else:
                state["fact_batch"] = {
                    "dataset_id": batch.dataset_id.value,
                    "rows": batch.frame.height,
                    "snapshot_date": snapshot_date.isoformat(),
                    "production_published": False,
                }
        else:
            state["fact_batch"] = {"status": "missing", "production_published": False}
    print(json.dumps(state, ensure_ascii=False, indent=2))
    inspection_rejected = any(
        state.get(key, {}).get("status", "").startswith("rejected")
        for key in ("name_history", "listing_history", "fact_batch")
    )
    return 1 if state.get("error_kind") or inspection_rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
