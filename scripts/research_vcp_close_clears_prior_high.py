#!/usr/bin/env python3
"""VCP 179 book: keep breakouts whose signal-day close clears the prior high.

Targets 失败突破. Signal-day visible 突破买点. Not 阳线, not 守前日低点, not a
post-entry 止损. Overlay sits on the frozen 179 fills
(upper-half ∩ 5% 守成本 ∩ ≥3 legs).
"""
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

from research_vcp_breakeven import upper_half  # noqa: E402
from research_vcp_loss_path_kind import build_main_book  # noqa: E402
from research_vcp_min_legs import (  # noqa: E402
    VCP_RUN,
    decide_rule,
    load_run_params,
    _delta,
)
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
    _as_date,
)

DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/vcp-failed-breakout-close-clears-prior-high-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/vcp-failed-breakout-close-clears-prior-high-v1-analysis.json"


def breakout_close_clears_prior_high(
    *,
    signal_date: date,
    sessions: list[dict],
    market_calendar: list[date],
) -> dict:
    """True when the breakout close is strictly above the prior market session high.

    A hole on the prior market session does not roll to an earlier stock bar.
    """
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if signal_date not in calendar:
        return {"clears": False, "reason": "missing_breakout_bar"}
    idx = calendar.index(signal_date)
    if idx < 1:
        return {"clears": False, "reason": "missing_prior_bar"}
    prior_day, day = calendar[idx - 1], calendar[idx]
    prior = by_date.get(prior_day)
    cur = by_date.get(day)
    if prior is None:
        return {"clears": False, "reason": "missing_prior_bar"}
    if cur is None:
        return {"clears": False, "reason": "missing_breakout_bar"}
    prior_high = float(prior.get("high") or 0.0)
    close = float(cur.get("close") or 0.0)
    if not np.isfinite(prior_high) or prior_high <= 0 or not np.isfinite(close) or close <= 0:
        return {"clears": False, "reason": "missing_price"}
    clears = close > prior_high
    return {
        "clears": clears,
        "reason": "clears_prior_high" if clears else "fails_prior_high",
        "prior_high": prior_high,
        "breakout_close": close,
    }


def filter_close_clears_prior_high(trades, sessions, calendar):
    kept, failed, missing = [], 0, 0
    grouped = sessions if isinstance(sessions, dict) else {}
    for trade in trades:
        flag = breakout_close_clears_prior_high(
            signal_date=_as_date(trade["entry_signal_date"]),
            sessions=grouped.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if flag.get("clears"):
            kept.append(trade)
        elif flag.get("reason") == "fails_prior_high":
            failed += 1
        else:
            missing += 1
    return kept, failed, missing


def overlay_book(trades, sessions, calendar) -> dict:
    kept, failed, missing = filter_close_clears_prior_high(trades, sessions, calendar)
    baseline = independent_trade_stats([float(t["pnl_pct"]) for t in trades])
    variant = independent_trade_stats([float(t["pnl_pct"]) for t in kept])
    return {
        "baseline": baseline,
        "variant": variant,
        "kept": len(kept),
        "dropped_fails_prior_high": failed,
        "missing_bar": missing,
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
    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
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
    print("loading sessions for VCP 179 close-clears-prior-high overlay", flush=True)
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        min(starts) - timedelta(days=400),
        max(ends),
    )
    train_uh = upper_half(train_all, sessions, calendar)
    val_uh = upper_half(val_all, sessions, calendar)
    train_book, train_short, train_missing = build_main_book(
        train_uh, sessions, calendar, params, date(2022, 12, 31)
    )
    val_book, val_short, val_missing = build_main_book(
        val_uh, sessions, calendar, params, date(2026, 12, 31)
    )
    train_overlay = overlay_book(train_book, sessions, calendar)
    val_overlay = overlay_book(val_book, sessions, calendar)
    rule = train_overlay["rule"]
    val_avg = (val_overlay.get("variant") or {}).get("avg_pnl")
    if rule == "keep" and val_avg is not None and val_avg < 0:
        rule = "drop"
    train_overlay["rule"] = rule
    val_overlay["rule"] = rule
    report = {
        "experiment": "vcp-failed-breakout-close-clears-prior-high-v1",
        "baseline_run": VCP_RUN,
        "protocol": str(args.protocol),
        "change": protocol.get("change"),
        "training_2016_2022": {
            **train_overlay,
            "dropped_short_legs": train_short,
            "missing_reconstruction": train_missing,
            "upper_half_n": len(train_uh),
            "book_n": len(train_book),
        },
        "validation_2023_2026": {
            **val_overlay,
            "dropped_short_legs": val_short,
            "missing_reconstruction": val_missing,
            "upper_half_n": len(val_uh),
            "book_n": len(val_book),
            "incomplete_excluded": len(val_open),
        },
        "validation_note": "exposure, not clean OOS",
        "rule": rule,
        "gaps": [],
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
                "rule": rule,
                "change": protocol.get("change"),
                "training": {
                    "baseline": train_overlay["baseline"],
                    "variant": train_overlay["variant"],
                    "kept": train_overlay["kept"],
                    "dropped_fails_prior_high": train_overlay["dropped_fails_prior_high"],
                    "missing_bar": train_overlay["missing_bar"],
                    "delta": train_overlay["delta"],
                    "book_n": len(train_book),
                },
                "validation": {
                    "baseline": val_overlay["baseline"],
                    "variant": val_overlay["variant"],
                    "kept": val_overlay["kept"],
                    "dropped_fails_prior_high": val_overlay["dropped_fails_prior_high"],
                    "missing_bar": val_overlay["missing_bar"],
                    "delta": val_overlay["delta"],
                    "book_n": len(val_book),
                    "incomplete_excluded": len(val_open),
                },
                "validation_note": "exposure, not clean OOS",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
