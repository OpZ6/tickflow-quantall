#!/usr/bin/env python3
"""Independently reconcile pre-snapshot adjustment events in an immutable repair run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import polars as pl
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _eastmoney_dividend_factors(
    local: pl.DataFrame,
    raw: pl.DataFrame,
) -> tuple[pl.DataFrame, list[dict]]:
    records: list[dict] = []
    factors: list[dict] = []
    for symbol in sorted(local["symbol"].unique().to_list()):
        code = symbol.split(".", 1)[0]
        response = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_SHAREBONUS_DET",
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageNumber": "1",
                "pageSize": "100",
                "sortColumns": "EX_DIVIDEND_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("result") or {}).get("data") or [])
        series = raw.filter(pl.col("symbol") == symbol)
        for event in local.filter(pl.col("symbol") == symbol).iter_rows(named=True):
            match = next(
                (
                    item for item in rows
                    if str(item.get("EX_DIVIDEND_DATE") or "")[:10]
                    == event["trade_date"].isoformat()
                ),
                None,
            )
            if match is None:
                continue
            positions = series.select(
                pl.arg_where(pl.col("date") == event["trade_date"])
            ).to_series()
            if positions.is_empty() or positions.item() == 0:
                continue
            previous_close = Decimal(str(series.row(positions.item() - 1, named=True)["close"]))
            cash_per_ten = Decimal(str(match.get("PRETAX_BONUS_RMB") or 0))
            bonus_per_ten = Decimal(str(match.get("BONUS_RATIO") or 0))
            transfer_per_ten = Decimal(str(match.get("IT_RATIO") or 0))
            theoretical = (
                (previous_close - cash_per_ten / Decimal(10))
                / (Decimal(1) + (bonus_per_ten + transfer_per_ten) / Decimal(10))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            expected_factor = float(previous_close / theoretical)
            factors.append({
                "symbol": symbol,
                "trade_date": event["trade_date"],
                "ex_factor": expected_factor,
            })
            records.append({
                "symbol": symbol,
                "trade_date": event["trade_date"].isoformat(),
                "equity_record_date": str(match.get("EQUITY_RECORD_DATE") or "")[:10],
                "implementation_plan": match.get("IMPL_PLAN_PROFILE"),
                "previous_close": float(previous_close),
                "theoretical_ex_price_rounded": float(theoretical),
                "derived_ex_factor": expected_factor,
            })
    return (
        pl.DataFrame(factors, schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "ex_factor": pl.Float64,
        }) if factors else pl.DataFrame(),
        records,
    )


def main() -> int:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="tushare")
    parser.add_argument("--snapshot-start", default="2016-09-05")
    parser.add_argument("--output-version", required=True)
    parser.add_argument("--factor-relative-tolerance", type=float, default=0.001)
    parser.add_argument("--adjusted-open-gap-limit", type=float, default=0.11)
    args = parser.parse_args()
    if Path(args.output_version).name != args.output_version or args.output_version in {"", ".", ".."}:
        parser.error("--output-version must be a single directory name")

    factor_path = settings.data_dir / "adj_factor" / "all.parquet"
    raw_files = sorted((settings.data_dir / "kline_daily").rglob("*.parquet"))
    raw_scan = pl.scan_parquet(
        [str(path) for path in raw_files], missing_columns="insert", extra_columns="ignore"
    )
    raw_start = raw_scan.select(pl.col("date").min()).collect().item()
    snapshot_start = datetime.fromisoformat(args.snapshot_start).date()
    local = (
        pl.read_parquet(factor_path)
        .filter(
            pl.col("trade_date").is_between(
                raw_start, snapshot_start, closed="left"
            )
        )
        .select("symbol", "trade_date", "ex_factor")
        .sort(["symbol", "trade_date"])
    )
    if local.is_empty():
        raise RuntimeError("no local pre-snapshot factor events overlap raw daily history")

    affected_symbols = sorted(local["symbol"].unique().to_list())
    raw = (
        raw_scan.filter(pl.col("symbol").is_in(affected_symbols))
        .select("symbol", "date", "open", "close")
        .sort(["symbol", "date"])
        .collect()
    )
    source_records: list[dict] = []
    if args.provider == "eastmoney_dividend":
        independent, source_records = _eastmoney_dividend_factors(local, raw)
    else:
        from app.data_providers import custom

        provider = custom.get_provider(args.provider)
        independent = provider.get_adj_factors(
            affected_symbols,
            datetime.combine(raw_start, datetime.min.time()),
            datetime.combine(snapshot_start, datetime.min.time()),
            "stock",
        )
    if independent.is_empty():
        raise RuntimeError(f"{args.provider} returned no overlapping factor events")
    independent = independent.filter(
        pl.col("trade_date").is_between(raw_start, snapshot_start, closed="left")
    ).select("symbol", "trade_date", "ex_factor").sort(["symbol", "trade_date"])
    if independent.is_empty():
        raise RuntimeError(f"{args.provider} returned no overlapping factor events")

    comparison = local.join(
        independent,
        on=["symbol", "trade_date"],
        how="full",
        suffix="_independent",
        coalesce=True,
    ).with_columns(
        (
            (pl.col("ex_factor") - pl.col("ex_factor_independent")).abs()
            / pl.col("ex_factor_independent").abs()
        ).alias("relative_difference")
    )
    missing_local = comparison["ex_factor"].null_count()
    missing_independent = comparison["ex_factor_independent"].null_count()
    max_relative_difference = comparison["relative_difference"].max()

    transitions = []
    for event in local.iter_rows(named=True):
        series = raw.filter(pl.col("symbol") == event["symbol"])
        positions = series.select(pl.arg_where(pl.col("date") == event["trade_date"])).to_series()
        if positions.is_empty() or positions.item() == 0:
            transitions.append({
                "symbol": event["symbol"],
                "trade_date": event["trade_date"].isoformat(),
                "status": "missing_raw_transition",
            })
            continue
        position = positions.item()
        previous = series.row(position - 1, named=True)
        current = series.row(position, named=True)
        adjusted_open_gap = (
            float(current["open"]) * float(event["ex_factor"]) / float(previous["close"]) - 1
        )
        adjusted_close_return = (
            float(current["close"]) * float(event["ex_factor"]) / float(previous["close"]) - 1
        )
        transitions.append({
            "symbol": event["symbol"],
            "trade_date": event["trade_date"].isoformat(),
            "previous_trade_date": previous["date"].isoformat(),
            "previous_close": previous["close"],
            "event_open": current["open"],
            "event_close": current["close"],
            "local_ex_factor": event["ex_factor"],
            "adjusted_open_gap": adjusted_open_gap,
            "adjusted_close_return": adjusted_close_return,
            "status": (
                "pass" if abs(adjusted_open_gap) <= args.adjusted_open_gap_limit else "fail"
            ),
        })

    status = "pass" if (
        missing_local == 0
        and missing_independent == 0
        and max_relative_difference is not None
        and max_relative_difference <= args.factor_relative_tolerance
        and all(item["status"] == "pass" for item in transitions)
    ) else "fail"
    report = {
        "schema_version": 1,
        "status": status,
        "provider": args.provider,
        "raw_history_start": raw_start.isoformat(),
        "snapshot_start_exclusive": snapshot_start.isoformat(),
        "local_factor_sha256": _sha256(factor_path),
        "local_events": local.height,
        "independent_events": independent.height,
        "missing_local_events": missing_local,
        "missing_independent_events": missing_independent,
        "factor_relative_tolerance": args.factor_relative_tolerance,
        "max_factor_relative_difference": max_relative_difference,
        "adjusted_open_gap_limit": args.adjusted_open_gap_limit,
        "source_records": source_records,
        "transitions": transitions,
    }

    output_parent = settings.data_dir / "repair"
    output = output_parent / args.output_version
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing reconciliation: {output}")
    output_parent.mkdir(parents=True, exist_ok=True)
    staging = output_parent / f".{args.output_version}.{os.getpid()}.tmp"
    staging.mkdir()
    try:
        comparison.write_parquet(staging / "factor-comparison.parquet")
        (staging / "reconciliation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        staging.replace(output)
    except BaseException:
        for child in staging.iterdir() if staging.exists() else ():
            child.unlink(missing_ok=True)
        if staging.exists():
            staging.rmdir()
        raise
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
