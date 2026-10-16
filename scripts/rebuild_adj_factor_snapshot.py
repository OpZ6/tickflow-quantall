"""Build an isolated adjustment-factor snapshot from the configured provider.

The production ``data/adj_factor`` file is never modified.  The command is
intended for the P0 parity repair: it uses the current instrument/history
universe, fetches event-shaped factors, and writes an atomic parquet plus a
machine-readable quality report under ``data/repair``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    from app.config import settings
    from app.data_providers import custom
    from app.parquet import scan_daily_parquet
    from app.tickflow.repository import DataStore, KlineRepository

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="fuyao")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=datetime.now().date().isoformat())
    parser.add_argument("--output-version", default="adj-factor-20260906-v1")
    args = parser.parse_args()

    if Path(args.output_version).name != args.output_version or args.output_version in {"", ".", ".."}:
        parser.error("--output-version must be a single directory name")
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start > end:
        parser.error("--start must not be after --end")

    output_parent = settings.data_dir / "repair"
    output = output_parent / args.output_version
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing snapshot: {output}")
    output_parent.mkdir(parents=True, exist_ok=True)
    staging = output_parent / f".{args.output_version}.{os.getpid()}.tmp"
    staging.mkdir()
    store = DataStore(settings.data_dir)
    try:
        repo = KlineRepository(store)
        instruments = repo.get_instruments().select("symbol")
        local = scan_daily_parquet(str(settings.data_dir / "kline_daily/**/*.parquet"))
        symbols = sorted(
            set(instruments["symbol"].to_list())
            | set(local.select("symbol").unique().collect()["symbol"].to_list())
        )
        symbols = [s for s in symbols if s.endswith((".SH", ".SZ", ".BJ"))]
    finally:
        store.db.close()

    provider = custom.get_provider(args.provider)
    factors = provider.get_adj_factors(
        symbols,
        start,
        end,
    )
    factors = (
        factors.select("symbol", "trade_date", "ex_factor")
        .with_columns(
            pl.col("trade_date").cast(pl.Date),
            pl.col("ex_factor").cast(pl.Float64),
        )
        .filter(pl.col("ex_factor").is_finite() & (pl.col("ex_factor") > 0))
        .unique(subset=["symbol", "trade_date"])
        .sort(["symbol", "trade_date"])
    )
    if factors.is_empty():
        raise ValueError("provider returned no valid adjustment-factor events")
    factor_path = staging / "adj_factor.parquet"
    tmp = factor_path.with_suffix(".tmp.parquet")
    factors.write_parquet(tmp)
    tmp.replace(factor_path)
    report = {
        "provider": args.provider,
        "start": args.start,
        "end": args.end,
        "requested_symbols": len(symbols),
        "factor_rows": factors.height,
        "factor_symbols": factors["symbol"].n_unique() if factors.height else 0,
        "symbols_without_events": len(symbols)
        - (factors["symbol"].n_unique() if factors.height else 0),
        "production_untouched": True,
    }
    report_path = staging / "quality-summary.json"
    report_tmp = report_path.with_suffix(".tmp.json")
    report_tmp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_tmp.replace(report_path)
    staging.replace(output)
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
