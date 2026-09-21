#!/usr/bin/env python3
"""Keep VCP 321 fills whose causal primary has at least 3 contraction legs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.strategy.builtin._quants_vcp import detect  # noqa: E402
from research_vcp_breakeven import upper_half  # noqa: E402
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    apply_breakeven_after_gain_to_fill,
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
    verdict,
    _as_date,
    _round,
)

VCP_RUN = "20260909T030431101979Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/vcp-min-legs-3-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/vcp-min-legs-3-v1-analysis.json"
MIN_LEGS = 3
HISTORY_BARS = 260


def keep_min_legs(primary, min_legs: int = MIN_LEGS) -> bool:
    if not primary or not primary.get("valid"):
        return False
    return len(primary.get("legs") or []) >= int(min_legs)


def reconstruct_primary(trade, sessions, params):
    """Causal detect() at entry_signal_date. None if the signal bar or structure is missing."""
    signal_date = _as_date(trade["entry_signal_date"])
    rows = [
        row
        for row in sessions.get(str(trade["symbol"]), [])
        if _as_date(row["date"]) <= signal_date
    ]
    if not rows or _as_date(rows[-1]["date"]) != signal_date:
        return None
    window = rows[-HISTORY_BARS:]
    arrays = [
        np.asarray([float(row[column]) for row in window], dtype=np.float32).astype(float)
        for column in ("high", "low", "close", "volume")
    ]
    dates = [str(_as_date(row["date"])) for row in window]
    structure = detect(*arrays, dates, {**params, "legacy_semantics": True})
    if structure is None:
        return None
    primary = structure.get("primary") or {}
    if not primary.get("valid"):
        return None
    return primary


def filter_min_legs(trades, sessions, params, min_legs: int = MIN_LEGS):
    kept, short, missing = [], 0, 0
    for trade in trades:
        primary = reconstruct_primary(trade, sessions, params)
        if primary is None:
            missing += 1
            continue
        if keep_min_legs(primary, min_legs):
            kept.append(trade)
        else:
            short += 1
    return kept, short, missing


def attach_breakeven(trades, sessions, calendar, last_bar: date):
    attached = []
    for trade in trades:
        applied = apply_breakeven_after_gain_to_fill(
            entry_date=_as_date(trade["entry_date"]),
            exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]),
            baseline_pnl=float(trade["pnl_pct"]),
            sessions=sessions.get(str(trade["symbol"]), []),
            market_calendar=calendar,
            last_bar=last_bar,
        )
        row = dict(trade)
        row["pnl_pct"] = float(applied["pnl"])
        attached.append(row)
    return attached


def pack(trades):
    return independent_trade_stats([float(t["pnl_pct"]) for t in trades])


def decide_rule(variant, baseline):
    positive = (variant["avg_pnl"] or 0) > 0
    return "keep" if verdict(variant, baseline) == "keep" and positive else "drop"


def load_run_params(run_dir: Path) -> dict:
    strategy = json.loads((run_dir / "strategy.json").read_text(encoding="utf-8"))
    return {
        str(item["id"]): item.get("default")
        for item in strategy["meta"]["params"]
        if "default" in item
    }


def _delta(variant, baseline):
    return {
        "avg_pnl": _round((variant["avg_pnl"] or 0) - (baseline["avg_pnl"] or 0))
        if variant["avg_pnl"] is not None and baseline["avg_pnl"] is not None
        else None,
        "win_rate": _round((variant["win_rate"] or 0) - (baseline["win_rate"] or 0))
        if variant["win_rate"] is not None and baseline["win_rate"] is not None
        else None,
        "profit_factor": None
        if variant["profit_factor"] is None or baseline["profit_factor"] is None
        else round(variant["profit_factor"] - baseline["profit_factor"], 2),
    }


def contrast_book(trades, sessions, calendar, params, last_bar: date):
    attached = attach_breakeven(trades, sessions, calendar, last_bar)
    kept, short, missing = filter_min_legs(attached, sessions, params, MIN_LEGS)
    baseline = pack(attached)
    variant = pack(kept)
    return {
        "baseline": baseline,
        "variant": variant,
        "kept": len(kept),
        "dropped_short_legs": short,
        "missing_reconstruction": missing,
        "delta": _delta(variant, baseline),
        "rule": decide_rule(variant, baseline),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_dir = Path(args.runs_root) / VCP_RUN
    payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    params = load_run_params(run_dir)
    all_trades = payload.get("trades") or []
    train_all = training_trades(all_trades)
    val_all, val_open = slice_trades(
        all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31)
    )
    need = train_all + val_all
    if not need:
        raise SystemExit("VCP train/val set is empty")
    starts = [_as_date(t["entry_signal_date"]) for t in need] + [
        _as_date(t["entry_date"]) for t in need
    ]
    ends = [_as_date(t["exit_date"]) for t in need]
    print("loading sessions for VCP 321 reconstruction", flush=True)
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        min(starts) - timedelta(days=400),
        max(ends),
    )
    train_uh = upper_half(train_all, sessions, calendar)
    val_uh = upper_half(val_all, sessions, calendar)
    train_report = contrast_book(train_uh, sessions, calendar, params, date(2022, 12, 31))
    train_report["upper_half_n"] = len(train_uh)
    val_report = contrast_book(val_uh, sessions, calendar, params, date(2026, 12, 31))
    val_report["upper_half_n"] = len(val_uh)
    val_report["incomplete_excluded"] = len(val_open)
    report = {
        "experiment": "vcp-min-legs-3-v1",
        "baseline_run": VCP_RUN,
        "protocol": str(args.protocol),
        "training_2016_2022": train_report,
        "validation_2023_2026": val_report,
        "validation_note": "exposure, not clean OOS",
        "rule": train_report["rule"],
        "gaps": [],
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
                "rule": report["rule"],
                "training": train_report,
                "validation": val_report,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
