"""Create, verify, or restore a non-destructive QuantX data-foundation backup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.market_facts.backup import create_backup, restore_backup, verify_backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("data_root", type=Path)
    create.add_argument("backup_dir", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("backup_dir", type=Path)

    restore = subparsers.add_parser("restore")
    restore.add_argument("backup_dir", type=Path)
    restore.add_argument("restore_data_root", type=Path)

    args = parser.parse_args()
    if args.command == "create":
        result = create_backup(args.data_root, args.backup_dir)
        result = {
            key: result[key]
            for key in (
                "schema_version",
                "scope_version",
                "created_at",
                "source_data_root",
                "roots",
                "file_count",
                "bytes",
                "sha256",
            )
        }
    elif args.command == "verify":
        result = verify_backup(args.backup_dir)
    else:
        result = restore_backup(args.backup_dir, args.restore_data_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
