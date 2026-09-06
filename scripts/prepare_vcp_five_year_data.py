"""Build an isolated five-year VCP dataset using an installed market-data provider.

Run from backend: uv run --no-sync python ../scripts/prepare_vcp_five_year_data.py
Existing completed stages are reused; production market data is not overwritten.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import traceback
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    import polars as pl

    from app.config import settings
    from app.data_providers import custom
    from app.indicators.pipeline import run_pipeline
    from app.parquet import scan_daily_parquet
    from app.tickflow.repository import DataStore, KlineRepository

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-version", default="five-year-20260904-v1")
    parser.add_argument("--data-start", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument(
        "--evaluation-start", type=date.fromisoformat, default=date(2021, 9, 6)
    )
    parser.add_argument(
        "--adjustment-start",
        type=date.fromisoformat,
        help="Optional factor-event start; use only with an evaluation warmup that excludes the omitted boundary.",
    )
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 4))
    args = parser.parse_args()
    adjustment_start = args.adjustment_start or args.data_start
    if not args.data_start <= adjustment_start < args.evaluation_start <= args.end:
        parser.error("require data-start < evaluation-start <= end")

    output = settings.data_dir / "research/vcp/datasets" / args.output_version
    output.mkdir(parents=True, exist_ok=True)
    previous = (
        json.loads((output / "build-status.json").read_text(encoding="utf-8"))
        if (output / "build-status.json").exists()
        else {}
    )
    logging.basicConfig(filename=output / "build.log", encoding="utf-8", level=logging.INFO)
    state = {
        "status": "running",
        "provider": "fuyao",
        "data_start": str(args.data_start),
        "evaluation_start": str(args.evaluation_start),
        "adjustment_start": str(adjustment_start),
        "end": str(args.end),
        "universe_basis": "current_instruments_union_local_history; historical_delisted_coverage_unverified",
        "started_at": datetime.now(UTC).isoformat(),
    }

    def save(name, value):
        (output / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    def progress(stage, **values):
        state.update(stage=stage, **values)
        save("build-status.json", state)
        print(json.dumps({"stage": stage, **values}, ensure_ascii=True, default=str), flush=True)

    production = staged = None
    try:
        production = DataStore(settings.data_dir)
        repo = KlineRepository(production)
        instruments = repo.get_instruments()
        local = (
            scan_daily_parquet(str(settings.data_dir / "kline_daily/**/*.parquet"))
            .select("symbol")
            .unique()
            .collect()
        )
        symbols = sorted(set(instruments["symbol"].to_list()) | set(local["symbol"].to_list()))
        symbols = [s for s in symbols if s.endswith((".SH", ".SZ", ".BJ"))]
        save("universe.json", {"symbols": symbols, "basis": state["universe_basis"]})
        staged = DataStore(output)
        target_repo = KlineRepository(staged)
        instruments.write_parquet(output / "instruments/instruments.parquet")
        provider = custom.get_provider("fuyao")
        start = datetime.combine(args.data_start, datetime.min.time())
        end = datetime.combine(args.end, datetime.max.time())

        daily_file = output / "download-daily.parquet"
        if not daily_file.exists():
            progress("fetch_daily", symbols=len(symbols))
            daily = provider.get_daily(symbols, start_time=start, end_time=end)
            if daily.is_empty():
                raise ValueError("Provider returned no daily data")
            if daily.select(pl.struct("symbol", "date").n_unique()).item() != daily.height:
                raise ValueError("Duplicate symbol/date in provider daily data")
            daily.write_parquet(daily_file.with_suffix(".tmp"))
            daily_file.with_suffix(".tmp").replace(daily_file)
        daily = pl.read_parquet(daily_file)
        progress(
            "daily_downloaded", daily_rows=daily.height, daily_symbols=daily["symbol"].n_unique()
        )

        adj_file = output / "adj_factor/all.parquet"
        if not adj_file.exists():
            progress("fetch_adjustments")

            def adj_progress(current, total):
                if current == total or current % 500 == 0:
                    progress("fetch_adjustments", done=current, total=total)

            factors = provider.get_adj_factors(
                symbols,
                start_time=datetime.combine(adjustment_start, datetime.min.time()),
                end_time=end,
                on_chunk_done=adj_progress,
            )
            if factors.is_empty() or factors.filter(pl.col("ex_factor") <= 0).height:
                raise ValueError("Missing or invalid adjustment events")
            factors.write_parquet(adj_file.with_suffix(".tmp"))
            adj_file.with_suffix(".tmp").replace(adj_file)
        factors = pl.read_parquet(adj_file)
        progress(
            "adjustments_downloaded",
            factor_events=factors.height,
            factor_symbols=factors["symbol"].n_unique(),
        )

        if not (output / "daily-published.json").exists():
            target_repo.append_daily(daily)
            save("daily-published.json", {"rows": daily.height})
        # Reuse existing benchmark history as a separately labelled input.
        for path in (settings.data_dir / "kline_index_daily").rglob("*.parquet"):
            target = output / path.relative_to(settings.data_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
        del daily
        progress("build_enriched")
        rows = (
            previous.get("enriched_rows")
            if previous.get("status") == "completed_with_limitations"
            else None
        )
        if rows is None:
            rows = run_pipeline(
                data_dir=output,
                on_batch_done=lambda current, total: progress(
                    "build_enriched", done=current, total=total
                ),
            )
        progress("audit_coverage", enriched_rows=rows)
        raw = pl.scan_parquet(str(output / "kline_daily/**/*.parquet"))
        coverage = (
            raw.group_by("symbol")
            .agg(
                pl.col("date").min().alias("first"),
                pl.col("date").max().alias("last"),
                (pl.col("date") < args.evaluation_start).sum().alias("warmup_bars"),
                (pl.col("date") >= args.evaluation_start).sum().alias("evaluation_bars"),
            )
            .collect()
            .sort("symbol")
        )
        save("coverage.json", coverage.to_dicts())
        dates = (
            raw.group_by("date")
            .agg(pl.col("symbol").n_unique().alias("symbols"))
            .collect()
            .sort("date")
        )
        save("daily-coverage.json", dates.to_dicts())
        missing = sorted(set(symbols) - set(coverage["symbol"].to_list()))
        log_text = (output / "build.log").read_text(encoding="utf-8")
        rejected = sorted(set(re.findall(r"除权因子自检剔除 (\d{6}\.[A-Z]+)", log_text)))
        invalid = (
            raw.filter(
                (pl.col("low") <= 0)
                | (pl.col("high") < pl.col("low"))
                | (pl.col("open") < pl.col("low"))
                | (pl.col("open") > pl.col("high"))
                | (pl.col("close") < pl.col("low"))
                | (pl.col("close") > pl.col("high"))
                | pl.any_horizontal(
                    pl.col(c).is_null() | ~pl.col(c).is_finite()
                    for c in ["open", "high", "low", "close", "volume"]
                )
                | (pl.col("volume") < 0)
            )
            .select("symbol")
            .collect()
        )
        invalid_symbols = sorted(set(invalid["symbol"].to_list()))
        save(
            "quality-summary.json",
            {
                "requested_symbols": len(symbols),
                "received_symbols": coverage.height,
                "missing_symbols": missing,
                "symbols_with_253_warmup_bars": coverage.filter(
                    pl.col("warmup_bars") >= 253
                ).height,
                "factor_event_symbols": factors["symbol"].n_unique(),
                "rejected_adjustment_symbols": rejected,
                "invalid_ohlcv_rows": invalid.height,
                "invalid_ohlcv_symbols": invalid_symbols,
                "excluded_symbols": sorted(set(missing + rejected + invalid_symbols)),
                "factor_absence_is_not_proof_of_no_corporate_actions": True,
                "survivorship_bias_not_resolved": True,
                "provider_event_rejections": "See build.log; provider rejects implausible adjustment events",
                "ready_for_unqualified_performance_claims": False,
            },
        )
        state["status"] = "completed_with_limitations"
        progress("completed", missing_symbols=len(missing), covered_symbols=coverage.height)
    except BaseException as exc:
        state["status"] = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        state["error"] = str(exc)
        (output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        state["finished_at"] = datetime.now(UTC).isoformat()
        save("build-status.json", state)
        if staged is not None:
            staged.db.close()
        if production is not None:
            production.db.close()


if __name__ == "__main__":
    main()
