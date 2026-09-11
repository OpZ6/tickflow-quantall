"""Freeze a read-only P0 audit manifest for the current production research data.

Run from the repository root:

    backend/.venv/Scripts/python.exe scripts/audit_production_research_data.py \
        --output-version production-research-20260907-v1

The command never copies or modifies production datasets.  It records their
coverage and an inventory fingerprint in a new, immutable audit directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CORE_PRICE_BENCHMARKS = {
    "000001.SH": "上证指数",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "399006.SZ": "创业板指",
}
P0_STRATEGY_SCOPE = {
    "strategy_ids": [
        "quants_vcp_legacy_v1",
        "vcp_leader_breakout",
        "launch_pullback_support",
    ],
    "industry_membership_required": False,
    "industry_feature_policy": (
        "disabled until point-in-time membership history is available"
    ),
}


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.parquet")) if path.exists() else []


def _scan(path: Path) -> tuple[pl.LazyFrame | None, list[Path]]:
    files = _files(path)
    if not files:
        return None, []
    return pl.scan_parquet(
        [str(item) for item in files],
        missing_columns="insert",
        extra_columns="ignore",
    ), files


def _inventory(path: Path) -> dict[str, Any]:
    files = _files(path)
    rows = [
        {
            "path": item.relative_to(ROOT).as_posix(),
            "size": item.stat().st_size,
            "mtime_ns": item.stat().st_mtime_ns,
        }
        for item in files
    ]
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return {
        "file_count": len(rows),
        "bytes": sum(item["size"] for item in rows),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
        "fingerprint_scope": "relative_path_size_mtime_ns",
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _daily_summary(path: Path, *, enriched: bool = False) -> dict[str, Any]:
    scan, _ = _scan(path)
    if scan is None:
        return {**_inventory(path), "available": False}
    schema = set(scan.collect_schema().names())
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    if not required.issubset(schema):
        return {
            **_inventory(path),
            "available": False,
            "missing_columns": sorted(required - schema),
        }
    missing_ohlcv = pl.any_horizontal(
        pl.col(column).is_null() for column in ("open", "high", "low", "close", "volume")
    )
    malformed_ohlcv = (
        (pl.col("low") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (pl.col("open") < pl.col("low"))
        | (pl.col("open") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("volume") < 0)
        | pl.any_horizontal(
            (~pl.col(column).is_finite()).fill_null(False)
            for column in ("open", "high", "low", "close", "volume")
        )
    ).fill_null(False)
    summary = scan.select(
        pl.len().alias("rows"),
        pl.struct("symbol", "date").n_unique().alias("unique_keys"),
        pl.col("symbol").n_unique().alias("symbols"),
        pl.col("date").n_unique().alias("trade_dates"),
        pl.col("date").min().alias("first_date"),
        pl.col("date").max().alias("last_date"),
        missing_ohlcv.sum().alias("missing_ohlcv_rows"),
        pl.col("symbol").filter(missing_ohlcv).n_unique().alias("missing_ohlcv_symbols"),
        pl.col("date").filter(missing_ohlcv).n_unique().alias("missing_ohlcv_dates"),
        pl.col("date").filter(missing_ohlcv).min().alias("first_missing_ohlcv_date"),
        pl.col("date").filter(missing_ohlcv).max().alias("last_missing_ohlcv_date"),
        malformed_ohlcv.sum().alias("malformed_ohlcv_rows"),
    ).collect().row(0, named=True)
    summary["duplicate_keys"] = summary["rows"] - summary.pop("unique_keys")
    if enriched:
        summary["price_basis"] = "qfq"
    return {**_inventory(path), "available": True, **summary}


def _missing_ohlcv_audit(raw_path: Path, instruments_path: Path) -> tuple[dict[str, Any], pl.DataFrame]:
    scan, _ = _scan(raw_path)
    if scan is None:
        return {"available": False, "rows": 0, "classifications": {}}, pl.DataFrame()
    schema = set(scan.collect_schema().names())
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    if not required.issubset(schema):
        return {
            "available": False,
            "rows": 0,
            "missing_columns": sorted(required - schema),
            "classifications": {},
        }, pl.DataFrame()
    missing = pl.any_horizontal(
        pl.col(column).is_null() for column in ("open", "high", "low", "close", "volume")
    )
    columns = [
        name for name in (
            "symbol", "date", "open", "high", "low", "close", "volume", "amount", "quote_ts"
        ) if name in schema
    ]
    rows = scan.filter(missing).select(columns).collect().sort(["symbol", "date"])
    if rows.is_empty():
        return {"available": True, "rows": 0, "classifications": {}, "records": []}, rows

    instruments = pl.DataFrame()
    if instruments_path.exists():
        source = pl.read_parquet(instruments_path)
        keep = [name for name in ("symbol", "name", "listing_date") if name in source.columns]
        if "symbol" in keep:
            instruments = source.select(keep).unique("symbol", keep="last")
            if "listing_date" in instruments.columns:
                instruments = instruments.with_columns(
                    pl.coalesce(
                        pl.col("listing_date").cast(pl.Utf8).str.to_date("%Y-%m-%d", strict=False),
                        pl.col("listing_date").cast(pl.Utf8).str.to_date("%Y%m%d", strict=False),
                    ).alias("listing_date")
                )
    if not instruments.is_empty():
        rows = rows.join(instruments, on="symbol", how="left")
    for name in ("name", "listing_date"):
        if name not in rows.columns:
            rows = rows.with_columns(pl.lit(None).alias(name))

    sane_listing = pl.col("listing_date") >= date(1990, 1, 1)
    rows = rows.with_columns(
        pl.when(sane_listing & (pl.col("listing_date") > pl.col("date")))
        .then(pl.lit("pre_listing_supported"))
        .when(sane_listing & (pl.col("listing_date") <= pl.col("date")))
        .then(pl.lit("known_instrument_nontrading_candidate"))
        .otherwise(pl.lit("unresolved_security_master"))
        .alias("classification")
    )
    counts = {
        item["classification"]: item["len"]
        for item in rows.group_by("classification").len().sort("classification").iter_rows(named=True)
    }
    records = []
    for record in rows.iter_rows(named=True):
        records.append({
            key: (value.isoformat() if isinstance(value, date) else value)
            for key, value in record.items()
        })
    return {
        "available": True,
        "rows": rows.height,
        "symbols": rows["symbol"].n_unique(),
        "dates": rows["date"].n_unique(),
        "classifications": counts,
        "classification_semantics": {
            "pre_listing_supported": "current security master has a sane listing date after the row date",
            "known_instrument_nontrading_candidate": "listed instrument with no valid OHLCV; suspension or another no-trade state still needs historical master evidence",
            "unresolved_security_master": "instrument is absent or has an unusable listing date in the current security master",
        },
        "records": records,
    }, rows


def _reconcile_missing_ohlcv(rows: pl.DataFrame, providers: list[str]) -> dict[str, Any]:
    if rows.is_empty() or not providers:
        return {"status": "not_run", "providers": {}}
    from app.data_providers import custom as custom_sources

    symbols = sorted(rows["symbol"].unique().to_list())
    missing_keys = set(rows.select("symbol", "date").iter_rows())
    first_date = rows["date"].min() - timedelta(days=3)
    last_date = rows["date"].max() + timedelta(days=3)
    observations: dict[str, Any] = {}
    observed_key_sets: list[set[tuple[str, date]]] = []
    for provider_name in providers:
        try:
            provider = custom_sources.get_provider(provider_name)
            frame = provider.get_daily(
                symbols,
                start_time=datetime.combine(first_date, datetime.min.time()),
                end_time=datetime.combine(last_date, datetime.min.time()),
                asset_type="stock",
            )
            if frame.is_empty():
                keys: set[tuple[str, date]] = set()
                null_dates = 0
            else:
                null_dates = frame["date"].null_count() if "date" in frame.columns else frame.height
                keys = set(frame.drop_nulls(["symbol", "date"]).select("symbol", "date").iter_rows())
            observed_key_sets.append(keys)
            encoded = json.dumps(
                sorted((symbol, trade_date.isoformat()) for symbol, trade_date in keys),
                separators=(",", ":"),
            ).encode()
            overlap = sorted(missing_keys & keys)
            observations[provider_name] = {
                "status": "pass" if null_dates == 0 and not overlap else "fail",
                "rows": frame.height,
                "symbols": len({symbol for symbol, _ in keys}),
                "dates": len({trade_date for _, trade_date in keys}),
                "null_dates": null_dates,
                "observed_key_fingerprint": hashlib.sha256(encoded).hexdigest(),
                "missing_keys_returned": [
                    {"symbol": symbol, "date": trade_date.isoformat()}
                    for symbol, trade_date in overlap
                ],
            }
        except Exception as exc:
            observations[provider_name] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    successful = [item for item in observations.values() if item["status"] == "pass"]
    agreement = len(observed_key_sets) == len(providers) and all(
        keys == observed_key_sets[0] for keys in observed_key_sets[1:]
    )
    return {
        "status": "pass" if len(successful) == len(providers) and agreement else "incomplete",
        "window": {"start": first_date.isoformat(), "end": last_date.isoformat()},
        "requested_symbols": len(symbols),
        "providers_agree_on_observed_keys": agreement,
        "providers": observations,
        "interpretation": "provider absence supports a no-trade placeholder finding but does not distinguish suspension, pre-listing, delisting, or symbol-master defects",
    }


def _adj_factor_summary(path: Path) -> dict[str, Any]:
    scan, _ = _scan(path)
    if scan is None:
        return {**_inventory(path), "available": False}
    summary = scan.select(
        pl.len().alias("rows"),
        pl.struct("symbol", "trade_date").n_unique().alias("unique_keys"),
        pl.col("symbol").n_unique().alias("symbols"),
        pl.col("trade_date").min().alias("first_date"),
        pl.col("trade_date").max().alias("last_date"),
        ((pl.col("ex_factor") <= 0) | pl.col("ex_factor").is_null() | ~pl.col("ex_factor").is_finite())
        .sum()
        .alias("invalid_rows"),
        (pl.col("trade_date") < date(2016, 9, 5)).sum().alias("events_before_research_snapshot"),
    ).collect().row(0, named=True)
    summary["duplicate_keys"] = summary["rows"] - summary.pop("unique_keys")
    return {**_inventory(path), "available": True, **summary}


def _dated_summary(path: Path, date_column: str, symbol_column: str | None = None) -> dict[str, Any]:
    scan, _ = _scan(path)
    if scan is None:
        return {**_inventory(path), "available": False}
    expressions = [
        pl.len().alias("rows"),
        pl.col(date_column).n_unique().alias("dates"),
        pl.col(date_column).min().alias("first_date"),
        pl.col(date_column).max().alias("last_date"),
    ]
    if symbol_column:
        expressions.append(pl.col(symbol_column).n_unique().alias("symbols"))
    return {
        **_inventory(path),
        "available": True,
        **scan.select(*expressions).collect().row(0, named=True),
    }


def _core_benchmark_summary(path: Path, stock_dates: set[date]) -> dict[str, Any]:
    scan, _ = _scan(path)
    if scan is None:
        return {"available": False, "complete_symbols": 0, "symbols": []}
    frame = (
        scan.filter(pl.col("symbol").is_in(CORE_PRICE_BENCHMARKS))
        .select([name for name in ("symbol", "date", "data_source") if name in scan.collect_schema().names()])
        .collect()
        .unique(["symbol", "date"], keep="last")
    )
    rows = []
    for symbol, display_name in CORE_PRICE_BENCHMARKS.items():
        series = frame.filter(pl.col("symbol") == symbol)
        dates = set(series["date"].to_list()) if not series.is_empty() else set()
        rows.append({
            "symbol": symbol,
            "name": display_name,
            "rows": len(dates),
            "first_date": min(dates).isoformat() if dates else None,
            "last_date": max(dates).isoformat() if dates else None,
            "stock_trade_dates_missing": len(stock_dates - dates),
            "data_sources": (
                sorted(series["data_source"].drop_nulls().unique().to_list())
                if "data_source" in series.columns else []
            ),
            "price_basis": "unadjusted_price_index",
        })
    complete = sum(item["stock_trade_dates_missing"] == 0 for item in rows)
    return {
        "available": True,
        "required_symbols": len(CORE_PRICE_BENCHMARKS),
        "complete_symbols": complete,
        "stock_trade_dates": len(stock_dates),
        "symbols": rows,
    }


def _minute_execution_summary(data_dir: Path) -> dict[str, Any]:
    """Validate bounded signal-linked minute samples and their production keys."""
    manifests = sorted(
        (data_dir / ".fact_backups").glob("minute-sample-*/manifest.json")
    )
    runs: list[dict[str, Any]] = []
    complete_sessions = 0
    for manifest_path in manifests:
        errors: list[str] = []
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_path = manifest_path.parent / str(manifest.get("source_frame") or "")
            if not source_path.is_file():
                errors.append("missing_source_frame")
                frame = pl.DataFrame()
            else:
                frame = pl.read_parquet(source_path)
            required = {"symbol", "datetime", "open", "high", "low", "close"}
            missing_columns = sorted(required - set(frame.columns))
            if missing_columns:
                errors.append(f"missing_columns:{','.join(missing_columns)}")
            duplicate_keys = (
                frame.height - frame.select("symbol", "datetime").unique().height
                if not missing_columns else None
            )
            null_ohlc = (
                int(frame.select(pl.any_horizontal(
                    pl.col(column).is_null()
                    for column in ("open", "high", "low", "close")
                ).sum()).item())
                if not missing_columns else None
            )
            execution_date = date.fromisoformat(str(manifest["execution_date"]))
            wrong_dates = (
                int(frame.filter(pl.col("datetime").dt.date() != execution_date).height)
                if not missing_columns else None
            )
            if frame.height != manifest.get("rows"):
                errors.append("manifest_row_mismatch")
            if duplicate_keys:
                errors.append("duplicate_keys")
            if null_ohlc:
                errors.append("null_ohlc")
            if wrong_dates:
                errors.append("wrong_execution_date")

            target = data_dir / "kline_minute" / f"date={execution_date}" / "part.parquet"
            production_keys_present = False
            if target.is_file() and not missing_columns:
                stored = pl.read_parquet(target).select("symbol", "datetime").unique()
                source_keys = frame.select("symbol", "datetime").unique()
                production_keys_present = (
                    source_keys.join(stored, on=["symbol", "datetime"], how="anti").height == 0
                )
            if not production_keys_present:
                errors.append("source_keys_missing_from_production")

            observed_complete = 0
            if not missing_columns:
                observed_complete = (
                    frame.group_by("symbol").len().filter(pl.col("len") >= 200).height
                )
            declared_complete = int(manifest.get("complete_session_candidates") or 0)
            if observed_complete != declared_complete:
                errors.append("complete_session_count_mismatch")
            selection = manifest.get("selection") or []
            if not selection or any(not item.get("source_run_ids") for item in selection):
                errors.append("missing_signal_provenance")
            valid = (
                manifest.get("source") == "tdx"
                and manifest.get("purpose") == "signal_linked_minute_execution_sample"
                and manifest.get("dry_run") is False
                and not errors
            )
            if valid:
                complete_sessions += observed_complete
            runs.append({
                "run_id": manifest.get("run_id"),
                "signal_date": manifest.get("signal_date"),
                "execution_date": manifest.get("execution_date"),
                "requested_symbols": manifest.get("requested_symbols"),
                "returned_symbols": manifest.get("returned_symbols"),
                "missing_symbols": manifest.get("missing_symbols"),
                "complete_sessions": observed_complete,
                "rows": frame.height,
                "source_frame_sha256": _file_sha256(source_path) if source_path.is_file() else None,
                "manifest_sha256": _file_sha256(manifest_path),
                "production_keys_present": production_keys_present,
                "status": "pass" if valid else "fail",
                "errors": errors,
            })
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, pl.exceptions.PolarsError) as exc:
            runs.append({
                "run_id": manifest_path.parent.name,
                "status": "fail",
                "errors": [f"{type(exc).__name__}: {exc}"],
                "manifest_sha256": _file_sha256(manifest_path),
            })
    valid_runs = sum(item["status"] == "pass" for item in runs)
    acceptance = {
        "minimum_valid_runs": 2,
        "minimum_complete_signal_sessions": 30,
        "scope": "execution samples only; not broad minute-backtest coverage",
    }
    return {
        "status": (
            "pass"
            if valid_runs >= acceptance["minimum_valid_runs"]
            and complete_sessions >= acceptance["minimum_complete_signal_sessions"]
            else ("incomplete" if runs else "fail")
        ),
        "valid_runs": valid_runs,
        "complete_signal_sessions": complete_sessions,
        "acceptance": acceptance,
        "runs": runs,
    }


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    status = run("status", "--porcelain=v1")
    return {"commit": run("rev-parse", "HEAD"), "worktree_clean": not status, "status": status.splitlines()}


def build_manifest(
    data_dir: Path,
    version: str,
    *,
    reconciliation_providers: list[str] | None = None,
    reconciliation_manifest: Path | None = None,
    early_adjustment_reconciliation: Path | None = None,
) -> dict[str, Any]:
    raw_path = data_dir / "kline_daily"
    calendar_path = data_dir / "trading_calendar"
    raw = _daily_summary(raw_path)
    enriched = _daily_summary(data_dir / "kline_daily_enriched", enriched=True)
    factors = _adj_factor_summary(data_dir / "adj_factor" / "all.parquet")
    early_adjustment = {
        "status": "incomplete",
        "reason": "2015 to 2016-09-04 has no validated independent-provider reconciliation",
    }
    if early_adjustment_reconciliation is not None:
        evidence = json.loads(early_adjustment_reconciliation.read_text(encoding="utf-8"))
        current_factor_sha256 = _file_sha256(data_dir / "adj_factor" / "all.parquet")
        independent_provider = evidence.get("provider") in {"tushare", "eastmoney_dividend"}
        matches_current = evidence.get("local_factor_sha256") == current_factor_sha256
        evidence_passed = evidence.get("status") == "pass"
        early_adjustment = {
            "status": (
                "pass" if independent_provider and matches_current and evidence_passed else "fail"
            ),
            "provider": evidence.get("provider"),
            "evidence_path": early_adjustment_reconciliation.resolve().relative_to(ROOT).as_posix(),
            "matches_current_factor_file": matches_current,
            "local_events": evidence.get("local_events"),
            "independent_events": evidence.get("independent_events"),
            "max_factor_relative_difference": evidence.get("max_factor_relative_difference"),
        }
    calendar = _dated_summary(calendar_path, "trade_date")
    indices = _dated_summary(data_dir / "kline_index_daily", "date", "symbol")
    instruments = _dated_summary(data_dir / "instruments" / "instruments.parquet", "as_of", "symbol")
    financials = _dated_summary(data_dir / "financials" / "overview" / "part.parquet", "period_end", "symbol")
    missing_ohlcv_audit, missing_ohlcv_rows = _missing_ohlcv_audit(
        raw_path, data_dir / "instruments" / "instruments.parquet"
    )
    if reconciliation_manifest is not None:
        prior = json.loads(reconciliation_manifest.read_text(encoding="utf-8"))
        prior_raw = prior["datasets"]["kline_daily"]
        if prior_raw.get("fingerprint") != raw.get("fingerprint"):
            raise ValueError("reconciliation manifest belongs to a different raw daily inventory")
        reconciliation = dict(
            prior["datasets"]["missing_ohlcv_audit"]["provider_reconciliation"]
        )
        reconciliation["reused_from_data_version"] = prior.get("data_version")
    else:
        reconciliation = _reconcile_missing_ohlcv(
            missing_ohlcv_rows, reconciliation_providers or []
        )
    missing_ohlcv_audit["provider_reconciliation"] = reconciliation

    raw_scan, _ = _scan(raw_path)
    calendar_scan, _ = _scan(calendar_path)
    raw_dates = set(raw_scan.select("date").unique().collect()["date"].to_list()) if raw_scan is not None else set()
    open_dates = set(
        calendar_scan.filter(pl.col("is_open")).select("trade_date").unique().collect()["trade_date"].to_list()
    ) if calendar_scan is not None else set()
    missing_calendar_dates = sorted(raw_dates - open_dates)
    core_benchmarks = _core_benchmark_summary(
        data_dir / "kline_index_daily", raw_dates
    )

    ext_industry_config = data_dir / "ext_data" / "ext_hy_ths" / "config.json"
    ext_industry = json.loads(ext_industry_config.read_text(encoding="utf-8")) if ext_industry_config.exists() else {}
    minute_inventory = _inventory(data_dir / "kline_minute")
    minute_execution = _minute_execution_summary(data_dir)
    raw_integrity_status = "pass"
    if raw.get("duplicate_keys") or raw.get("malformed_ohlcv_rows"):
        raw_integrity_status = "fail"
    elif raw.get("missing_ohlcv_rows"):
        raw_integrity_status = "incomplete"
    enriched_integrity_status = "pass"
    if enriched.get("duplicate_keys") or enriched.get("malformed_ohlcv_rows"):
        enriched_integrity_status = "fail"
    elif enriched.get("missing_ohlcv_rows"):
        enriched_integrity_status = "incomplete"
    gates = {
        "raw_daily_integrity": {
            "status": raw_integrity_status,
            "duplicate_keys": raw.get("duplicate_keys"),
            "missing_ohlcv_rows": raw.get("missing_ohlcv_rows"),
            "malformed_ohlcv_rows": raw.get("malformed_ohlcv_rows"),
            "classification_counts": missing_ohlcv_audit.get("classifications"),
            "provider_reconciliation_status": missing_ohlcv_audit["provider_reconciliation"]["status"],
        },
        "enriched_daily_integrity": {
            "status": enriched_integrity_status,
            "duplicate_keys": enriched.get("duplicate_keys"),
            "missing_ohlcv_rows": enriched.get("missing_ohlcv_rows"),
            "malformed_ohlcv_rows": enriched.get("malformed_ohlcv_rows"),
        },
        "adjustment_factor_integrity": {
            "status": "pass" if factors.get("duplicate_keys") == 0 and factors.get("invalid_rows") == 0 else "fail",
            "duplicate_keys": factors.get("duplicate_keys"),
            "invalid_rows": factors.get("invalid_rows"),
        },
        "early_adjustment_independent_reconciliation": early_adjustment,
        "authoritative_trading_calendar": {
            "status": "pass" if not missing_calendar_dates else "fail",
            "raw_trade_dates_missing_from_calendar": len(missing_calendar_dates),
            "first_missing": str(missing_calendar_dates[0]) if missing_calendar_dates else None,
            "last_missing": str(missing_calendar_dates[-1]) if missing_calendar_dates else None,
        },
        "historical_security_master": {
            "status": "incomplete",
            "available": ["current symbol", "current name", "listing_date"],
            "missing": ["delisting history", "name/code changes", "historical ST state", "suspension intervals", "daily tradable universe"],
        },
        "long_horizon_benchmarks": {
            "status": (
                "pass"
                if core_benchmarks["complete_symbols"] == core_benchmarks.get("required_symbols")
                else "fail"
            ),
            "benchmark_first_date": indices.get("first_date"),
            "stock_first_date": raw.get("first_date"),
            "complete_core_price_indices": core_benchmarks["complete_symbols"],
            "required_core_price_indices": core_benchmarks.get("required_symbols"),
            "return_basis_available": False,
        },
        "historical_industry_membership": {
            "status": "pass",
            "data_status": (
                "unavailable_historically"
                if ext_industry.get("mode") == "snapshot"
                else "unverified"
            ),
            "requirement": "not_required_for_current_p0_strategy_scope",
            "observed_mode": ext_industry.get("mode"),
            "feature_policy": P0_STRATEGY_SCOPE["industry_feature_policy"],
        },
        "minute_execution_evidence": {
            **minute_execution,
            "file_count": minute_inventory["file_count"],
        },
    }
    return {
        "schema_version": 1,
        "data_version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_dir": str(data_dir.resolve()),
        "source_kind": "live_production_inventory",
        "immutable_data_copy": False,
        "p0_strategy_scope": P0_STRATEGY_SCOPE,
        "git": _git_state(),
        "datasets": {
            "kline_daily": raw,
            "kline_daily_enriched": enriched,
            "adj_factor": factors,
            "instruments": instruments,
            "trading_calendar": calendar,
            "kline_index_daily": indices,
            "core_price_benchmarks": core_benchmarks,
            "financial_overview": financials,
            "kline_minute": minute_inventory,
            "industry_membership": {
                "mode": ext_industry.get("mode"),
                "updated_at": ext_industry.get("updated_at"),
                "last_rows": (ext_industry.get("pull") or {}).get("last_rows"),
            },
            "missing_ohlcv_audit": missing_ohlcv_audit,
        },
        "gates": gates,
        "p0_status": "pass" if all(item["status"] == "pass" for item in gates.values()) else "incomplete",
        "safe_use": "diagnostic_only_until_all_p0_gates_pass",
    }


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-version", default="production-research-20260907-v1")
    parser.add_argument(
        "--reconcile-provider",
        action="append",
        default=[],
        help="read-only daily provider to cross-check missing OHLCV keys; repeat for multiple providers",
    )
    parser.add_argument(
        "--reconciliation-manifest",
        type=Path,
        help="reuse provider evidence only when its raw-daily inventory fingerprint still matches",
    )
    parser.add_argument(
        "--early-adjustment-reconciliation",
        type=Path,
        help="validated independent reconciliation.json for the current production factor file",
    )
    args = parser.parse_args()
    if Path(args.output_version).name != args.output_version or args.output_version in {"", ".", ".."}:
        parser.error("--output-version must be a single directory name")
    if args.reconcile_provider and args.reconciliation_manifest:
        parser.error("use either --reconcile-provider or --reconciliation-manifest")
    if args.reconciliation_manifest and not args.reconciliation_manifest.is_file():
        parser.error("--reconciliation-manifest must be an existing file")
    if args.early_adjustment_reconciliation and not args.early_adjustment_reconciliation.is_file():
        parser.error("--early-adjustment-reconciliation must be an existing file")

    output_parent = settings.data_dir / "research" / "data-versions"
    output = output_parent / args.output_version
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing audit: {output}")
    output_parent.mkdir(parents=True, exist_ok=True)
    staging = output_parent / f".{args.output_version}.{os.getpid()}.tmp"
    staging.mkdir()
    try:
        manifest = build_manifest(
            settings.data_dir,
            args.output_version,
            reconciliation_providers=args.reconcile_provider,
            reconciliation_manifest=args.reconciliation_manifest,
            early_adjustment_reconciliation=args.early_adjustment_reconciliation,
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        staging.replace(output)
    except BaseException:
        if staging.exists():
            (staging / "manifest.json").unlink(missing_ok=True)
            staging.rmdir()
        raise
    print(json.dumps({"output": str(output), "p0_status": manifest["p0_status"], "gates": manifest["gates"]}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
