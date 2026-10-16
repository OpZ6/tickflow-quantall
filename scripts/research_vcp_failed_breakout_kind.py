#!/usr/bin/env python3
"""VCP 179 book: 止损 if the entry-day close is strictly below the fill price.

Targets 失败突破 (held high never +3%, finished ≤ 0). Not two-bar no-demand,
not underwater two-bar, not a +3% print recut. Overlay sits on the frozen
179 fills (upper-half ∩ 5% 守成本 ∩ ≥3 legs).
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
    COST_CONFIG,
    independent_trade_stats,
    load_symbol_sessions,
    net_round_trip,
    one_price_limit_down,
    training_trades,
    _as_date,
)

from app.backtest.engine import MatcherConfig  # noqa: E402

DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/vcp-failed-breakout-entry-close-stop-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/vcp-failed-breakout-entry-close-stop-v1-analysis.json"


def apply_entry_day_close_stop_to_fill(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    baseline_pnl: float,
    sessions: list[dict],
    market_calendar: list[date],
    config: MatcherConfig = COST_CONFIG,
    last_bar: date | None = None,
) -> dict:
    """Sell next market open when the entry-day close is strictly below the fill.

    Equal close does not fire. A stock hole or one-price limit-down does not roll.
    """
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    unchanged = {"pnl": float(baseline_pnl), "shortened": False, "reason": "no_stop"}
    if entry_date not in calendar or not np.isfinite(entry_price) or entry_price <= 0:
        return {**unchanged, "reason": "missing_entry_bar"}
    idx = calendar.index(entry_date)
    if entry_date >= exit_date:
        return {**unchanged, "reason": "baseline_already_out"}
    bar = by_date.get(entry_date)
    if bar is None:
        return {**unchanged, "reason": "missing_bar"}
    close = float(bar.get("close") or 0.0)
    if not np.isfinite(close) or close <= 0:
        return {**unchanged, "reason": "missing_close"}
    if close >= float(entry_price):
        return unchanged
    if idx + 1 >= len(calendar):
        return {**unchanged, "reason": "missing_exit_bar"}
    next_day = calendar[idx + 1]
    if next_day >= exit_date:
        return {**unchanged, "reason": "baseline_already_out"}
    fill = by_date.get(next_day)
    if fill is None:
        return {**unchanged, "reason": "missing_exit_bar"}
    open_px = float(fill.get("open") or 0.0)
    volume = float(fill.get("volume") or 0.0)
    if (
        not np.isfinite(open_px)
        or open_px <= 0
        or volume <= 0
        or one_price_limit_down(
            open_px,
            float(fill.get("high") or 0.0),
            float(fill.get("low") or 0.0),
            float(fill.get("close") or 0.0),
        )
    ):
        return {**unchanged, "reason": "early_exit_blocked"}
    pnl = net_round_trip(
        open_px / float(entry_price) - 1.0,
        config.buy_cost_pct(),
        config.sell_cost_pct(next_day),
    )
    return {
        "pnl": float(pnl),
        "shortened": True,
        "reason": "entry_day_close_below_cost",
        "signal_date": entry_date.isoformat(),
        "early_exit_date": next_day.isoformat(),
        "early_exit_price": open_px,
    }


def overlay_book(trades, sessions, calendar, last_bar: date) -> dict:
    baseline_pnls, variant_pnls = [], []
    shortened = blocked = 0
    grouped = sessions if isinstance(sessions, dict) else {}
    for trade in trades:
        applied = apply_entry_day_close_stop_to_fill(
            entry_date=_as_date(trade["entry_date"]),
            exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]),
            baseline_pnl=float(trade["pnl_pct"]),
            sessions=grouped.get(str(trade["symbol"]), []),
            market_calendar=calendar,
            last_bar=last_bar,
        )
        baseline_pnls.append(float(trade["pnl_pct"]))
        variant_pnls.append(float(applied["pnl"]))
        if applied.get("shortened"):
            shortened += 1
        if applied.get("reason") in {
            "missing_bar",
            "missing_close",
            "missing_exit_bar",
            "early_exit_blocked",
            "missing_entry_bar",
        }:
            blocked += 1
    baseline = independent_trade_stats(baseline_pnls)
    variant = independent_trade_stats(variant_pnls)
    return {
        "baseline": baseline,
        "variant": variant,
        "shortened": shortened,
        "blocked_kept_baseline": blocked,
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
    print("loading sessions for VCP 179 failed-breakout stop overlay", flush=True)
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        min(starts) - timedelta(days=400),
        max(ends),
    )
    train_uh = upper_half(train_all, sessions, calendar)
    val_uh = upper_half(val_all, sessions, calendar)
    train_kept, train_short, train_missing = build_main_book(
        train_uh, sessions, calendar, params, date(2022, 12, 31)
    )
    val_kept, val_short, val_missing = build_main_book(
        val_uh, sessions, calendar, params, date(2026, 12, 31)
    )
    train_overlay = overlay_book(train_kept, sessions, calendar, date(2022, 12, 31))
    val_overlay = overlay_book(val_kept, sessions, calendar, date(2026, 12, 31))
    rule = train_overlay["rule"]
    val_avg = (val_overlay.get("variant") or {}).get("avg_pnl")
    if rule == "keep" and val_avg is not None and val_avg < 0:
        rule = "drop"
    train_overlay["rule"] = rule
    val_overlay["rule"] = rule
    val_overlay["incomplete_excluded"] = len(val_open)
    report = {
        "experiment": "vcp-failed-breakout-entry-close-stop-v1",
        "baseline_run": VCP_RUN,
        "protocol": str(args.protocol),
        "change": protocol.get("change"),
        "training_2016_2022": {
            **train_overlay,
            "dropped_short_legs": train_short,
            "missing_reconstruction": train_missing,
            "upper_half_n": len(train_uh),
            "kept": len(train_kept),
        },
        "validation_2023_2026": {
            **val_overlay,
            "dropped_short_legs": val_short,
            "missing_reconstruction": val_missing,
            "upper_half_n": len(val_uh),
            "kept": len(val_kept),
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
                    "shortened": train_overlay["shortened"],
                    "blocked_kept_baseline": train_overlay["blocked_kept_baseline"],
                    "delta": train_overlay["delta"],
                    "kept": len(train_kept),
                },
                "validation": {
                    "baseline": val_overlay["baseline"],
                    "variant": val_overlay["variant"],
                    "shortened": val_overlay["shortened"],
                    "blocked_kept_baseline": val_overlay["blocked_kept_baseline"],
                    "delta": val_overlay["delta"],
                    "kept": len(val_kept),
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
