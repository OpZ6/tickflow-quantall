"""Migrate legacy QuantX snapshots to canonical market facts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import settings
from app.market_facts.registry import DatasetId
from app.quantx_data.migration import migrate_quantx_history


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=settings.data_dir)
    parser.add_argument("--apply", action="store_true", help="publish facts; default is preflight only")
    parser.add_argument("--force", action="store_true", help="replace already migrated partitions")
    parser.add_argument(
        "--dataset",
        action="append",
        choices=[item.value for item in DatasetId],
        help="rebuild only this dataset when its migration version is stale; repeatable",
    )
    args = parser.parse_args()
    result = migrate_quantx_history(
        args.data_root,
        apply=args.apply,
        force=args.force,
        datasets=tuple(args.dataset) if args.dataset else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
