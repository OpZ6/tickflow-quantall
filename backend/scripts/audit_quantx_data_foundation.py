"""Reconcile published QuantX dates against canonical market-fact partitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import settings
from app.market_facts.audit import audit_quantx_data_foundation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=settings.data_dir)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-artifacts", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when any partition is missing or invalid",
    )
    args = parser.parse_args()
    result = audit_quantx_data_foundation(
        args.data_root,
        include_artifacts=args.include_artifacts,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return int(args.strict and result["summary"]["gap_partition_count"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
