#!/usr/bin/env python3
"""Audit causal float turnover between the final VCP pivot and breakout."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from analyze_vcp_moneyflow_sponsorship import _feature_summary
from build_vcp_blind_casebook import _candidates

ROOT = Path(__file__).resolve().parents[1]

OUTPUT = ROOT / "data/research/vcp/analysis/overhead-supply-turnover-2017-2026-v1.json"
DETAIL = ROOT / "data/research/vcp/analysis/overhead-supply-turnover-2017-2026-v1.parquet"


def cumulative_float_turnover(volume_lots: np.ndarray, float_shares: np.ndarray) -> float | None:
    """Return the fraction of float traded, given A-share lots and shares."""
    volume_lots = np.asarray(volume_lots, dtype=float)
    float_shares = np.asarray(float_shares, dtype=float)
    if not len(volume_lots) or len(volume_lots) != len(float_shares):
        return None
    valid = np.isfinite(volume_lots) & (volume_lots >= 0) & np.isfinite(float_shares) & (float_shares > 0)
    if not np.all(valid):
        return None
    return float(np.sum(volume_lots * 100.0 / float_shares))


def main() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.backtest.matrix import load_market_data_matrix_from_parquet

    candidates = (
        _candidates()
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "signal_date", "scale", "pivot_date", "pivot", "true_breakout_10_7_20", "return_40d")
    )
    symbols = candidates.get_column("symbol").unique().sort().to_list()
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched",
        candidates.get_column("pivot_date").min() - timedelta(days=5),
        candidates.get_column("signal_date").max(),
        field_columns={"float_shares"},
        symbols=symbols,
    )
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}
    date_ids = {label[:10]: index for index, label in enumerate(market.timestamp_labels)}
    float_shares = market.field("float_shares")
    rows = []
    rejected = {"symbol_missing": 0, "date_missing": 0, "no_sessions": 0, "share_coverage": 0}
    for row in candidates.iter_rows(named=True):
        asset = symbol_ids.get(row["symbol"])
        pivot_t = date_ids.get(row["pivot_date"].isoformat())
        signal_t = date_ids.get(row["signal_date"].isoformat())
        if asset is None:
            rejected["symbol_missing"] += 1
            continue
        if pivot_t is None or signal_t is None:
            rejected["date_missing"] += 1
            continue
        sessions = np.arange(pivot_t, signal_t, dtype=int)
        sessions = sessions[np.isfinite(market.close[sessions, asset])]
        if not len(sessions):
            rejected["no_sessions"] += 1
            continue
        value = cumulative_float_turnover(market.volume[sessions, asset], float_shares[sessions, asset])
        if value is None:
            rejected["share_coverage"] += 1
            continue
        rows.append(
            {
                "symbol": row["symbol"],
                "signal_date": row["signal_date"],
                "pivot_date": row["pivot_date"],
                "scale": row["scale"],
                "base_sessions": len(sessions),
                "cumulative_float_turnover": value,
                "true_breakout_10_7_20": row["true_breakout_10_7_20"],
                "return_40d": row["return_40d"],
            }
        )
    detail = pd.DataFrame(rows)
    detail["year"] = pd.to_datetime(detail["signal_date"]).dt.year
    summary = _feature_summary(detail, "cumulative_float_turnover")
    result = {
        "experiment": "overhead-supply-turnover-audit-2017-2026-v1",
        "candidate_setups": int(candidates.height),
        "usable_setups": len(detail),
        "coverage": len(detail) / candidates.height if candidates.height else None,
        "rejected": rejected,
        "feature": summary,
        "decision": "advance_to_fixed_v3_ranking" if summary["all_gates_passed"] else "stop_without_variants",
        "interpretation_boundary": "This audit tests one continuous causal association. It does not select a turnover cutoff or establish an independently validated strategy.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    pl.from_pandas(detail).write_parquet(DETAIL)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
