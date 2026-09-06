"""Prepare isolated point-in-time fundamentals for VCP discovery research.

The script uses TickFlow's configured ``local_financial`` Provider and its
full-market report-period endpoint.  It writes only under ``data/research``;
the application's production financial store is never modified.

Run from ``backend``::

    uv run --no-sync python ../scripts/prepare_vcp_fundamentals.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _quarters(start: date, end: date) -> list[date]:
    values: list[date] = []
    for year in range(start.year, end.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = date(year, month, day)
            if start <= value <= end:
                values.append(value)
    return values


def _merge(existing: pl.DataFrame, fresh: pl.DataFrame) -> pl.DataFrame:
    frames = [frame for frame in (existing, fresh) if not frame.is_empty()]
    if not frames:
        return pl.DataFrame()
    merged = pl.concat(frames, how="diagonal_relaxed")
    return (
        merged.filter(
            pl.col("symbol").is_not_null()
            & pl.col("period_end").is_not_null()
            & pl.col("announce_date").is_not_null()
        )
        .sort(["symbol", "period_end", "announce_date"])
        .unique(["symbol", "period_end"], keep="last")
        .sort(["symbol", "announce_date", "period_end"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2020, 3, 31))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2023, 9, 30))
    parser.add_argument("--output-version", default="market-core-v1")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start must not be later than --end")

    from app.config import settings
    from app.data_providers import custom as custom_sources

    output_dir = settings.data_dir / "research/vcp/fundamentals" / args.output_version
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "metrics.parquet"
    manifest_path = output_dir / "manifest.json"
    existing = pl.read_parquet(output_path) if output_path.exists() else pl.DataFrame()
    instruments_path = settings.data_dir / "instruments" / "instruments.parquet"
    if not instruments_path.exists():
        raise RuntimeError(f"missing stock universe: {instruments_path}")
    universe = pl.read_parquet(instruments_path, columns=["symbol"]).unique("symbol")
    universe_symbols = set(universe["symbol"].drop_nulls().to_list())
    provider = custom_sources.get_provider("local_financial")
    periods = _quarters(args.start, args.end)
    completed = (
        set(existing["period_end"].drop_nulls().to_list())
        if not existing.is_empty() and "period_end" in existing.columns
        else set()
    )

    frame = existing
    fetched: list[str] = []
    for index, period in enumerate(periods, 1):
        if period in completed and not args.refresh:
            print(json.dumps({"step": index, "period": str(period), "status": "cached"}), flush=True)
            continue
        fresh = provider.get_financial_market_table("metrics", period)
        if fresh.is_empty():
            raise RuntimeError(f"empty full-market metrics for {period}")
        fresh = fresh.filter(pl.col("symbol").is_in(universe_symbols))
        if fresh.is_empty():
            raise RuntimeError(f"no stock-universe metrics for {period}")
        frame = _merge(
            frame.filter(pl.col("period_end") != period) if not frame.is_empty() else frame,
            fresh,
        )
        temp = output_dir / ".metrics.parquet.tmp"
        frame.write_parquet(temp)
        temp.replace(output_path)
        fetched.append(str(period))
        print(
            json.dumps(
                {
                    "step": index,
                    "period": str(period),
                    "status": "fetched",
                    "period_rows": fresh.height,
                    "total_rows": frame.height,
                }
            ),
            flush=True,
        )

    # Older script versions may have cached non-stock Eastmoney securities.
    # Apply the authoritative TickFlow stock universe again before publication.
    frame = frame.filter(pl.col("symbol").is_in(universe_symbols))
    temp = output_dir / ".metrics.parquet.tmp"
    frame.write_parquet(temp)
    temp.replace(output_path)
    invalid_announcement_order = (
        frame.filter(pl.col("announce_date") < pl.col("period_end")).height
        if not frame.is_empty()
        else 0
    )
    manifest = {
        "dataset": "vcp-point-in-time-market-core-fundamentals",
        "version": args.output_version,
        "provider": "local_financial",
        "upstream_source": "akshare_eastmoney",
        "table": "metrics",
        "period_range": [str(args.start), str(args.end)],
        "periods": [str(value) for value in periods],
        "fetched_periods_this_run": fetched,
        "rows": frame.height,
        "symbols": frame["symbol"].n_unique() if not frame.is_empty() else 0,
        "universe_symbols": len(universe_symbols),
        "announcement_range": [
            str(frame["announce_date"].min()),
            str(frame["announce_date"].max()),
        ]
        if not frame.is_empty()
        else None,
        "invalid_announcement_order_rows": invalid_announcement_order,
        "point_in_time_rule": "usable only on trading dates strictly after announce_date",
        "revision_note": (
            "The upstream period snapshot may expose a later restatement instead of the originally "
            "published row. Its later announce_date delays availability and cannot introduce lookahead."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
