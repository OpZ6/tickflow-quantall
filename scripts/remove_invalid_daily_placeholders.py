#!/usr/bin/env python3
"""Remove evidenced null-OHLCV placeholders from production raw daily K.

Dry-run is the default.  ``--apply`` is allowed only when the supplied audit
matches the current raw inventory and its provider reconciliation passed.  The
script copies every touched partition to a recoverable backup before atomic
replacement and never fabricates price or volume values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(path: Path) -> dict[str, Any]:
    files = sorted(path.rglob("*.parquet"))
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
    }


def _missing_expr() -> pl.Expr:
    return pl.any_horizontal(
        pl.col(column).is_null()
        for column in ("open", "high", "low", "close", "volume")
    )


def _load_preconditions(
    audit_path: Path,
    bse_path: Path,
    raw_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audited_raw = audit["datasets"]["kline_daily"]
    current = _inventory(raw_root)
    if audited_raw.get("fingerprint") != current["fingerprint"]:
        raise RuntimeError("audit raw-daily fingerprint does not match production")
    missing_audit = audit["datasets"]["missing_ohlcv_audit"]
    if missing_audit.get("provider_reconciliation", {}).get("status") != "pass":
        raise RuntimeError("provider reconciliation did not pass")
    records = list(missing_audit.get("records") or [])
    if not records or len(records) != audited_raw.get("missing_ohlcv_rows"):
        raise RuntimeError("audit missing-row records are incomplete")

    bse = json.loads(bse_path.read_text(encoding="utf-8"))
    bse_absent = {
        item.get("symbol")
        for item in bse.get("records") or []
        if item.get("result") == "not_listed" and item.get("http_status") == 200
    }
    if bse.get("status") != "pass" or not {"920268.BJ", "920298.BJ"} <= bse_absent:
        raise RuntimeError("official BSE evidence does not cover unresolved symbols")
    return audit, records


def _target(raw_root: Path, trade_date: date) -> Path:
    target = (raw_root / f"date={trade_date.isoformat()}" / "part.parquet").resolve()
    if not target.is_relative_to(raw_root.resolve()):
        raise ValueError(f"partition target escaped {raw_root}: {target}")
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def _preflight(
    data_root: Path,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[Path, pl.DataFrame]]:
    raw_root = (data_root / "kline_daily").resolve()
    expected_keys = {
        (str(item["symbol"]), date.fromisoformat(str(item["date"])))
        for item in records
    }
    dates = sorted({item[1] for item in expected_keys})
    frames: dict[Path, pl.DataFrame] = {}
    observed_keys: set[tuple[str, date]] = set()
    removed_by_date: dict[str, int] = {}
    for trade_date in dates:
        target = _target(raw_root, trade_date)
        frame = pl.read_parquet(target)
        missing = frame.filter(_missing_expr())
        observed_keys.update(missing.select("symbol", "date").iter_rows())
        removed_by_date[trade_date.isoformat()] = missing.height
        frames[target] = frame.filter(~_missing_expr())
    if observed_keys != expected_keys:
        raise RuntimeError(
            f"audit keys differ from production missing keys: "
            f"missing={len(expected_keys - observed_keys)}, extra={len(observed_keys - expected_keys)}"
        )

    enriched_files = [
        str(data_root / "kline_daily_enriched" / f"date={value}" / "part.parquet")
        for value in removed_by_date
    ]
    expected_frame = pl.DataFrame(
        {
            "symbol": [item[0] for item in sorted(expected_keys)],
            "date": [item[1] for item in sorted(expected_keys)],
        }
    )
    enriched_keys = set(
        pl.scan_parquet(enriched_files)
        .select("symbol", "date")
        .join(expected_frame.lazy(), on=["symbol", "date"], how="inner")
        .collect()
        .iter_rows()
    )
    if enriched_keys:
        raise RuntimeError("placeholder keys unexpectedly exist in enriched daily data")
    return {
        "removed_rows": len(expected_keys),
        "affected_partitions": len(frames),
        "removed_by_date": removed_by_date,
        "enriched_matching_keys": 0,
    }, frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-manifest", type=Path, required=True)
    parser.add_argument("--bse-evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for path in (args.audit_manifest, args.bse_evidence):
        if not path.is_file():
            parser.error(f"evidence file does not exist: {path}")

    data_root = settings.data_dir.resolve()
    raw_root = (data_root / "kline_daily").resolve()
    audit, records = _load_preconditions(
        args.audit_manifest.resolve(), args.bse_evidence.resolve(), raw_root
    )
    plan, replacements = _preflight(data_root, records)
    plan.update({
        "dry_run": not args.apply,
        "source_data_version": audit.get("data_version"),
        "audit_manifest": args.audit_manifest.resolve().relative_to(ROOT).as_posix(),
        "audit_manifest_sha256": _sha256(args.audit_manifest),
        "bse_evidence": args.bse_evidence.resolve().relative_to(ROOT).as_posix(),
        "bse_evidence_sha256": _sha256(args.bse_evidence),
        "action": "remove rows with null OHLCV; do not impute values",
    })
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    run_id = f"raw-daily-placeholder-cleanup-{uuid4().hex[:8]}"
    backup_root = data_root / ".fact_backups" / run_id
    backup_root.mkdir(parents=True)
    backups: dict[Path, Path] = {}
    artifacts = []
    try:
        for target, replacement in replacements.items():
            backup = backup_root / target.relative_to(data_root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backups[target] = backup
            temporary = target.with_name(f".part.{run_id}.tmp")
            replacement.write_parquet(temporary)
            os.replace(temporary, target)
            artifacts.append({
                "path": target.relative_to(data_root).as_posix(),
                "backup_sha256": _sha256(backup),
                "published_sha256": _sha256(target),
                "rows": replacement.height,
            })
        remaining = (
            pl.scan_parquet(
                [str(path) for path in sorted(raw_root.rglob("*.parquet"))],
                missing_columns="insert",
                extra_columns="ignore",
            )
            .select(_missing_expr().sum())
            .collect()
            .item()
        )
        if remaining:
            raise RuntimeError(f"raw daily still contains {remaining} null-OHLCV rows")
    except Exception as exc:
        for target, backup in backups.items():
            shutil.copy2(backup, target)
        for target in replacements:
            target.with_name(f".part.{run_id}.tmp").unlink(missing_ok=True)
        (backup_root / "manifest.json").write_text(
            json.dumps(
                {
                    **plan,
                    "status": "failed_rolled_back",
                    "run_id": run_id,
                    "backup": backup_root.relative_to(data_root).as_posix(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "rollback_inventory": _inventory(raw_root),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise

    plan.update({
        "dry_run": False,
        "status": "complete",
        "run_id": run_id,
        "backup": backup_root.relative_to(data_root).as_posix(),
        "post_inventory": _inventory(raw_root),
        "artifacts": artifacts,
        "removed_records": records,
    })
    (backup_root / "manifest.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in plan.items() if key != "removed_records"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
