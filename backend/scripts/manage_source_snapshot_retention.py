"""Preview or quarantine expired raw source snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.market_facts.snapshots import SnapshotRetentionPolicy, SourceSnapshotStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--retention-days", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        help="Required with --apply; must equal QUARANTINE_EXPIRED_SNAPSHOTS",
    )
    args = parser.parse_args()
    policy = (
        SnapshotRetentionPolicy(args.retention_days)
        if args.retention_days is not None
        else SnapshotRetentionPolicy.from_environment()
    )
    store = SourceSnapshotStore(args.data_root.resolve())
    plan = store.plan_retention(policy)
    if not args.apply:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        return
    if args.confirm != "QUARANTINE_EXPIRED_SNAPSHOTS":
        parser.error("--apply requires --confirm QUARANTINE_EXPIRED_SNAPSHOTS")
    print(
        json.dumps(
            store.apply_retention(plan, confirmed=True),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
