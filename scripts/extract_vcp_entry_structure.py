#!/usr/bin/env python3
"""Reconstruct causal VCP structure evidence at each executed entry signal."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.strategy.builtin._quants_vcp import detect, entry_allowed  # noqa: E402


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _frozen_source_check(run_dir: Path) -> str:
    relative = "backend/app/strategy/builtin/_quants_vcp.py"
    current = (ROOT / relative).read_bytes()
    with ZipFile(run_dir / "source.zip") as archive:
        frozen = archive.read(relative)
    if current != frozen:
        raise RuntimeError("current VCP detector differs from the run's frozen source")
    return _sha256(frozen)


def _defaults(run_dir: Path) -> dict:
    strategy = json.loads((run_dir / "strategy.json").read_text(encoding="utf-8"))
    return {
        str(item["id"]): item.get("default")
        for item in strategy["meta"]["params"]
        if "default" in item
    }


def reconstruct_entries(trades: list[dict], bars: pl.DataFrame, params: dict) -> list[dict]:
    grouped = {
        key[0] if isinstance(key, tuple) else key: frame.sort("date")
        for key, frame in bars.partition_by("symbol", as_dict=True).items()
    }
    detector_params = {**params, "legacy_semantics": True}
    evidence: list[dict] = []
    for trade in trades:
        symbol = str(trade["symbol"])
        signal_date = date.fromisoformat(str(trade["entry_signal_date"])[:10])
        history = grouped[symbol].filter(pl.col("date") <= signal_date).tail(260)
        if history.is_empty() or history["date"].max() != signal_date:
            raise RuntimeError(f"missing signal-date bar for {symbol} {signal_date}")
        # MarketDataMatrix stores price/volume fields as float32.  Reproduce
        # that exact input boundary before the detector promotes its window to
        # float64; direct parquet float64 values can change equality at a pivot.
        arrays = [
            history[column].to_numpy().astype(np.float32).astype(float)
            for column in ("high", "low", "close", "volume")
        ]
        dates = [value.isoformat() for value in history["date"].to_list()]
        structure = detect(*arrays, dates, detector_params)
        if structure is None:
            raise RuntimeError(f"detector returned no structure for {symbol} {signal_date}")
        primary = structure["primary"]
        signal_id = str(trade.get("entry_signal_id") or "")
        entry_params = detector_params
        if signal_id == "signal_quants_vcp_early_recovery":
            entry_params = {**detector_params, "prebreakout_pivot_closes_max": 0}
        elif signal_id == "signal_quants_vcp_broad_advance":
            entry_params = {**detector_params, "prebreakout_pivot_closes_max": 20}
        previous_close = arrays[2][-2] if len(arrays[2]) >= 2 else np.nan
        reconstructed_allowed = bool(
            primary.get("valid")
            and entry_allowed(primary, previous_close, entry_params, arrays[2])
        )
        depths = [float(leg["depth"]) for leg in primary.get("legs") or []]
        pretrigger_baseline = arrays[3][-51:-1]
        pretrigger_recent = arrays[3][-11:-1]
        pretrigger_dry_ratio = (
            float(np.mean(pretrigger_recent) / np.mean(pretrigger_baseline))
            if len(pretrigger_recent) == 10
            and len(pretrigger_baseline) >= 19
            and np.mean(pretrigger_baseline) > 0
            else None
        )
        evidence.append({
            "symbol": symbol,
            "entry_signal_date": signal_date.isoformat(),
            "entry_date": str(trade["entry_date"])[:10],
            "exit_date": str(trade["exit_date"])[:10],
            "entry_signal_id": signal_id,
            "pnl_pct": float(trade["pnl_pct"]),
            "exit_reason": trade["exit_reason"],
            "scale": primary.get("scale"),
            "setup": primary.get("setup"),
            "pivot": primary.get("pivot"),
            "planned_stop": primary.get("stop_price"),
            "distance_to_pivot": primary.get("distance"),
            "tightness": primary.get("tightness"),
            "volume_ratio": primary.get("volume_ratio"),
            "dry_volume_ratio": primary.get("dry_volume_ratio"),
            "pretrigger_dry_volume_ratio": pretrigger_dry_ratio,
            "close_location": primary.get("close_location"),
            "leg_count": len(depths),
            "leg_depths": depths,
            "contraction_strength": (
                1.0 - min(max(depths[-1] / depths[0], 0.0), 1.0)
                if depths and depths[0] > 0 else None
            ),
            "history_bars": history.height,
            "as_of": primary.get("as_of"),
            "reconstructed_entry_allowed": reconstructed_allowed,
        })
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    run_dir = args.data_root.resolve() / "research" / "vcp" / "runs" / args.run_id
    source_sha256 = _frozen_source_check(run_dir)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    trades = list(result.get("trades") or [])
    symbols = sorted({str(item["symbol"]) for item in trades})
    last_signal = max(str(item["entry_signal_date"])[:10] for item in trades)
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if path.parent.name <= f"date={last_signal}"
    ]
    bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").is_in(symbols))
        .select("symbol", "date", "high", "low", "close", "volume")
        .collect()
    )
    evidence = reconstruct_entries(trades, bars, _defaults(run_dir))
    output = run_dir / "entry-structure-evidence.json"
    report = {
        "schema_version": 1,
        "run_id": args.run_id,
        "scope": "executed_entries",
        "causal_cutoff": "entry_signal_date_completed_daily_bar",
        "detector_source_sha256": source_sha256,
        "reconstruction": {
            "matched_executable": sum(
                bool(item["reconstructed_entry_allowed"]) for item in evidence
            ),
            "mismatched_executable": sum(
                not bool(item["reconstructed_entry_allowed"]) for item in evidence
            ),
        },
        "records": evidence,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "records": len(evidence),
        "reconstruction": report["reconstruction"],
        "source_sha256": source_sha256,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
