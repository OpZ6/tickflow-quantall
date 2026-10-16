#!/usr/bin/env python
"""Run TickFlow's independent deterministic QuantX data pipeline.

Examples:
    uv run python scripts/run_quantx_data.py --date 20260825
    uv run python scripts/run_quantx_data.py --date 20260825 --recompute
    uv run python scripts/run_quantx_data.py --date 20260825 --source pywencai --force
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.quantx_data.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TickFlow independent QuantX data update")
    parser.add_argument("--date", required=True, help="trade date YYYYMMDD")
    parser.add_argument("--data-dir", help="TickFlow data directory (defaults to the prototype data directory)")
    parser.add_argument("--source", action="append", dest="sources", help="source to run; repeatable")
    parser.add_argument("--force", action="store_true", help="ignore the target date source snapshot")
    parser.add_argument("--recompute", action="store_true", help="reuse source snapshots and recompute tables")
    args = parser.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).resolve().parents[1] / "data"
    result = run_pipeline(data_dir, args.date, selected_sources=args.sources, force=args.force, recompute=args.recompute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] in {"complete", "degraded"} else 2)


if __name__ == "__main__":
    main()
