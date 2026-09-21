#!/usr/bin/env python3
"""Keep VCP 179 fills whose causal primary.volume_ratio is at least 1.50."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_vcp_breakeven import upper_half  # noqa: E402
from research_vcp_min_legs import (  # noqa: E402
    MIN_LEGS,
    VCP_RUN,
    attach_breakeven,
    decide_rule,
    filter_min_legs,
    load_run_params,
    pack,
    reconstruct_primary,
    _delta,
)
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    apply_breakeven_after_gain_to_fill,
    load_symbol_sessions,
    training_trades,
    _as_date,
)

DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/vcp-volume-ratio-150-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/vcp-volume-ratio-150-v1-analysis.json"
MIN_VOLUME_RATIO = 1.50


def keep_volume_ratio(primary, min_ratio: float = MIN_VOLUME_RATIO) -> bool:
    if not primary or not primary.get("valid"):
        return False
    value = primary.get("volume_ratio")
    if value is None:
        return False
    return float(value) >= float(min_ratio)


def filter_volume_ratio(trades, sessions, params, min_ratio: float = MIN_VOLUME_RATIO):
    kept, thin, missing = [], 0, 0
    for trade in trades:
        primary = reconstruct_primary(trade, sessions, params)
        if primary is None or primary.get("volume_ratio") is None:
            missing += 1
            continue
        if keep_volume_ratio(primary, min_ratio):
            kept.append(trade)
        else:
            thin += 1
    return kept, thin, missing


def contrast_book(trades, sessions, calendar, params, last_bar: date):
    attached = attach_breakeven(trades, sessions, calendar, last_bar)
    legs, short, miss_legs = filter_min_legs(attached, sessions, params, MIN_LEGS)
    kept, thin, miss_vol = filter_volume_ratio(legs, sessions, params, MIN_VOLUME_RATIO)
    baseline = pack(legs)
    variant = pack(kept)
    return {
        "baseline": baseline,
        "variant": variant,
        "kept": len(kept),
        "legs_n": len(legs),
        "dropped_short_legs": short,
        "dropped_thin_volume": thin,
        "missing_reconstruction": miss_legs + miss_vol,
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
    print("loading sessions for VCP 179 volume_ratio overlay", flush=True)
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
        "experiment": "vcp-volume-ratio-150-v1",
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
