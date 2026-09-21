#!/usr/bin/env python3
"""Autopsy cup 2,034 losers, then one buy/sell kind overlay.

Does not overlay VCP 179. Book is dual-regime ∩ RS≥85 ∩ upper-half on
frozen cup run 20260909T133226351846Z.
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

from research_cup_upper_half import (  # noqa: E402
    CUP_RUN,
    _delta,
    decide_rule,
    filter_gate,
    filter_rs,
    filter_upper,
    pack,
)
from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    dual_regime_gate,
    load_training_market,
    rs_universe_mask,
)
from research_vcp_loss_path_kind import (  # noqa: E402
    held_excursions,
    label_book,
    label_held_loss_path,
    summarize_loss_paths,
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

DEFAULT_PROTOCOL = ROOT / "docs/research/cup-handle/cup-loss-path-kind-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/cup-handle/cup-loss-path-kind-v1-analysis.json"
VCP_MAIN_RUN = "20260909T030431101979Z"


def build_cup_thin_book(trades, sessions, calendar, dates, symbols, gate, ranks):
    gated, _ = filter_gate(trades, dates, gate)
    ranked, _ = filter_rs(gated, symbols, dates, ranks, 85.0)
    kept, lower, missing = filter_upper(ranked, sessions, calendar)
    return kept, lower, missing, len(ranked)


def _hold_window(trades):
    starts = [
        min(_as_date(t["entry_signal_date"]), _as_date(t["entry_date"]))
        for t in trades
    ]
    ends = [_as_date(t["exit_date"]) for t in trades]
    return min(starts) - timedelta(days=5), max(ends)


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


def autopsy_book(trades, sessions, calendar) -> dict:
    records, incomplete = label_book(trades, sessions, calendar)
    summary = summarize_loss_paths(records)
    summary["incomplete"] = incomplete
    summary["stats"] = pack(trades)
    return summary, records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--autopsy-only", action="store_true")
    args = parser.parse_args()
    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    run_dir = Path(args.runs_root) / CUP_RUN
    payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train_all = training_trades(all_trades)
    val_all, val_open = slice_trades(
        all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31)
    )
    print("loading market for cup 2034 thin book", flush=True)
    market, _listing, _names = load_training_market(
        Path(args.data_root), DATA_START, date(2026, 12, 31)
    )
    gate, _ = dual_regime_gate(market)
    _mask, ranks = rs_universe_mask(market, 85.0)
    dates = [_as_date(label) for label in market.timestamp_labels]
    symbols = list(market.symbols)
    train_gated, _ = filter_gate(train_all, dates, gate)
    train_gated, _ = filter_rs(train_gated, symbols, dates, ranks, 85.0)
    val_gated, _ = filter_gate(val_all, dates, gate)
    val_gated, _ = filter_rs(val_gated, symbols, dates, ranks, 85.0)
    need = train_gated + val_gated
    if not need:
        raise SystemExit("cup train/val set is empty")
    start, end = _hold_window(need)
    print("loading sessions for cup 2034 path autopsy", flush=True)
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        start,
        end,
    )
    train_kept, train_lower, train_miss, train_leader_n = build_cup_thin_book(
        train_all, sessions, calendar, dates, symbols, gate, ranks
    )
    val_kept, val_lower, val_miss, val_leader_n = build_cup_thin_book(
        val_all, sessions, calendar, dates, symbols, gate, ranks
    )
    train_summary, _ = autopsy_book(train_kept, sessions, calendar)
    if val_kept:
        val_summary, _ = autopsy_book(val_kept, sessions, calendar)
    else:
        val_summary = {
            "book_n": 0,
            "loser_n": 0,
            "incomplete": 0,
            "paths": {},
            "attacked_path": None,
            "stats": independent_trade_stats([]),
        }
    train_summary["lower_half"] = train_lower
    train_summary["missing_signal_bar"] = train_miss
    train_summary["leader_open_n"] = train_leader_n
    val_summary["lower_half"] = val_lower
    val_summary["missing_signal_bar"] = val_miss
    val_summary["leader_open_n"] = val_leader_n
    val_summary["incomplete_excluded"] = len(val_open)
    train_overlay = None
    val_overlay = None
    rule = None
    if not args.autopsy_only:
        train_overlay = overlay_book(train_kept, sessions, calendar, date(2022, 12, 31))
        val_overlay = (
            overlay_book(val_kept, sessions, calendar, date(2026, 12, 31))
            if val_kept
            else {
                "baseline": independent_trade_stats([]),
                "variant": independent_trade_stats([]),
                "shortened": 0,
                "blocked_kept_baseline": 0,
                "delta": _delta(independent_trade_stats([]), independent_trade_stats([])),
                "rule": "drop",
            }
        )
        rule = train_overlay["rule"]
        train_overlay["rule"] = rule
        val_overlay["rule"] = rule
        train_summary["overlay"] = train_overlay
        val_summary["overlay"] = val_overlay
    report = {
        "experiment": "cup-loss-path-kind-v1",
        "baseline_run": CUP_RUN,
        "not_vcp_run": VCP_MAIN_RUN,
        "protocol": str(args.protocol),
        "change": protocol.get("change"),
        "training_2016_2022": train_summary,
        "validation_2023_2026": val_summary,
        "validation_note": "exposure, not clean OOS",
        "autopsy_only": bool(args.autopsy_only),
        "rule": rule,
        "gaps": [],
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": args.output,
                "baseline_run": CUP_RUN,
                "attacked_path": train_summary.get("attacked_path"),
                "training_stats": train_summary.get("stats"),
                "training_paths": {
                    name: {"n": row.get("n"), "avg_pnl": row.get("avg_pnl")}
                    for name, row in (train_summary.get("paths") or {}).items()
                },
                "incomplete": train_summary.get("incomplete"),
                "rule": rule,
                "training_overlay": train_overlay,
                "validation_overlay": val_overlay,
                "validation_n": val_summary.get("book_n"),
                "validation_note": "exposure, not clean OOS",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
