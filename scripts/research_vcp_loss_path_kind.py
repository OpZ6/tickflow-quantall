#!/usr/bin/env python3
"""Autopsy VCP 179 losers into 给回 / 失败突破 / 磨掉, then one buy/sell kind overlay.

Path labels are a pure function of already-held bars and fill PnL. The kind overlay
is applied on top of the frozen 179 book (upper-half ∩ 5% 守成本 ∩ ≥3 legs).
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
from research_vcp_min_legs import (  # noqa: E402
    MIN_LEGS,
    VCP_RUN,
    decide_rule,
    filter_min_legs,
    load_run_params,
    pack,
    _delta,
)
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    COST_CONFIG,
    apply_breakeven_after_gain_to_fill,
    independent_trade_stats,
    load_symbol_sessions,
    net_round_trip,
    one_price_limit_down,
    training_trades,
    _as_date,
    _round,
)

from app.backtest.engine import MatcherConfig  # noqa: E402

DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/vcp-loss-path-kind-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/vcp-loss-path-kind-v1-analysis.json"

PATH_WIN = "赢家"
PATH_GIVEBACK = "给回"
PATH_FAILED = "失败突破"
PATH_GRIND = "磨掉"
GIVEBACK_MFE = 0.05
FAILED_MFE = 0.03


def label_held_loss_path(*, pnl: float, mfe: float) -> str:
    """Partition one fill from held-path MFE and realized PnL.

    给回: high printed ≥ +5% vs entry, still finished ≤ 0. Demand existed; the hold gave it back.
    失败突破: high never printed +3%, finished ≤ 0. Breakout never followed through.
    磨掉: loser with 3% ≤ MFE < 5%. Some follow-through, then chopped without a 5% give-back.
    赢家: pnl > 0.
    """
    if float(pnl) > 0:
        return PATH_WIN
    if float(mfe) >= GIVEBACK_MFE:
        return PATH_GIVEBACK
    if float(mfe) < FAILED_MFE:
        return PATH_FAILED
    return PATH_GRIND


def held_excursions(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    sessions: list[dict],
    market_calendar: list[date],
) -> dict:
    """MFE/MAE from highs/lows on market sessions from entry through exit. Holes do not roll."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if entry_date not in calendar:
        return {"complete": False, "reason": "missing_entry_bar"}
    if not np.isfinite(entry_price) or entry_price <= 0:
        return {"complete": False, "reason": "missing_entry_price"}
    start = calendar.index(entry_date)
    highs: list[float] = []
    lows: list[float] = []
    for i in range(start, len(calendar)):
        day = calendar[i]
        if day > exit_date:
            break
        bar = by_date.get(day)
        if bar is None:
            return {"complete": False, "reason": "missing_bar"}
        high = float(bar.get("high") or 0.0)
        low = float(bar.get("low") or 0.0)
        if not np.isfinite(high) or high <= 0 or not np.isfinite(low) or low <= 0:
            return {"complete": False, "reason": "missing_price"}
        highs.append(high)
        lows.append(low)
        if day == exit_date:
            return {
                "complete": True,
                "mfe": max(highs) / float(entry_price) - 1.0,
                "mae": min(lows) / float(entry_price) - 1.0,
                "holding_bars": len(highs),
            }
    return {"complete": False, "reason": "missing_exit_bar"}


def _median(values: list[float | int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def summarize_loss_paths(records: list[dict]) -> dict:
    buckets = {PATH_WIN: [], PATH_GIVEBACK: [], PATH_FAILED: [], PATH_GRIND: []}
    for row in records:
        buckets[str(row["path"])].append(row)
    losers = [row for row in records if row["path"] != PATH_WIN]
    paths = {}
    for name, rows in buckets.items():
        pnls = [float(row["pnl"]) for row in rows]
        mfes = [float(row["mfe"]) for row in rows]
        holds = [int(row["holding_bars"]) for row in rows]
        paths[name] = {
            "n": len(rows),
            "share_of_book": _round(len(rows) / len(records) if records else None),
            "share_of_losers": _round(len(rows) / len(losers) if losers and name != PATH_WIN else None),
            "avg_pnl": _round(float(np.mean(pnls)) if pnls else None),
            "avg_mfe": _round(float(np.mean(mfes)) if mfes else None),
            "median_holding_bars": _median(holds),
        }
    if PATH_WIN in paths:
        paths[PATH_WIN]["share_of_losers"] = None
    attacked = max(
        (PATH_GIVEBACK, PATH_FAILED, PATH_GRIND),
        key=lambda name: (paths[name]["n"], -ord(name[0])),
    )
    return {
        "book_n": len(records),
        "loser_n": len(losers),
        "incomplete": 0,
        "paths": paths,
        "attacked_path": attacked if losers else None,
    }


def apply_high_print_breakeven_to_fill(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    baseline_pnl: float,
    sessions: list[dict],
    market_calendar: list[date],
    config: MatcherConfig = COST_CONFIG,
    activate_pct: float = GIVEBACK_MFE,
    last_bar: date | None = None,
) -> dict:
    """After a held-bar high prints +activate_pct, sell next open if close is below entry.

    Same-bar high-print and close-below-entry fires. A stock hole or one-price
    limit-down does not roll; the original exit is kept.
    """
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    unchanged = {"pnl": float(baseline_pnl), "shortened": False, "reason": "no_breakeven"}
    if entry_date not in calendar or not np.isfinite(entry_price) or entry_price <= 0:
        return {**unchanged, "reason": "missing_entry_bar"}
    start = calendar.index(entry_date)
    armed = False
    threshold = float(entry_price) * (1.0 + float(activate_pct))
    for i in range(start, len(calendar)):
        day = calendar[i]
        if day >= exit_date:
            break
        bar = by_date.get(day)
        if bar is None:
            return {**unchanged, "reason": "missing_bar"}
        high = float(bar.get("high") or 0.0)
        close = float(bar.get("close") or 0.0)
        if not np.isfinite(high) or high <= 0 or not np.isfinite(close) or close <= 0:
            return {**unchanged, "reason": "missing_price"}
        if high >= threshold:
            armed = True
        if not armed or close >= float(entry_price):
            continue
        if i + 1 >= len(calendar):
            return {**unchanged, "reason": "missing_exit_bar"}
        next_day = calendar[i + 1]
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
            "reason": "high_print_breakeven",
            "signal_date": day.isoformat(),
            "early_exit_date": next_day.isoformat(),
            "early_exit_price": open_px,
        }
    return unchanged


def overlay_book(trades, sessions, calendar, last_bar: date) -> dict:
    baseline_pnls, variant_pnls = [], []
    shortened = blocked = 0
    grouped = sessions if isinstance(sessions, dict) else {}
    for trade in trades:
        applied = apply_high_print_breakeven_to_fill(
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
            "missing_price",
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


def materialize_breakeven(trade, sessions, calendar, last_bar: date) -> dict:
    applied = apply_breakeven_after_gain_to_fill(
        entry_date=_as_date(trade["entry_date"]),
        exit_date=_as_date(trade["exit_date"]),
        entry_price=float(trade["entry_price"]),
        baseline_pnl=float(trade["pnl_pct"]),
        sessions=sessions.get(str(trade["symbol"]), []) if isinstance(sessions, dict) else sessions,
        market_calendar=calendar,
        last_bar=last_bar,
    )
    row = dict(trade)
    row["original_exit_date"] = str(trade["exit_date"])
    row["original_pnl_pct"] = float(trade["pnl_pct"])
    row["pnl_pct"] = float(applied["pnl"])
    row["breakeven"] = applied
    if applied.get("shortened") and applied.get("early_exit_date"):
        row["exit_date"] = applied["early_exit_date"]
    return row


def build_main_book(trades, sessions, calendar, params, last_bar: date):
    attached = [materialize_breakeven(trade, sessions, calendar, last_bar) for trade in trades]
    kept, short, missing = filter_min_legs(attached, sessions, params, MIN_LEGS)
    return kept, short, missing


def label_book(trades, sessions, calendar) -> tuple[list[dict], int]:
    records = []
    incomplete = 0
    grouped = sessions if isinstance(sessions, dict) else {}
    for trade in trades:
        path = held_excursions(
            entry_date=_as_date(trade["entry_date"]),
            exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]),
            sessions=grouped.get(str(trade["symbol"]), []),
            market_calendar=calendar,
        )
        if not path.get("complete"):
            incomplete += 1
            continue
        records.append(
            {
                "symbol": str(trade["symbol"]),
                "entry_date": str(trade["entry_date"])[:10],
                "exit_date": str(trade["exit_date"])[:10],
                "pnl": float(trade["pnl_pct"]),
                "mfe": float(path["mfe"]),
                "mae": float(path["mae"]),
                "holding_bars": int(path["holding_bars"]),
                "path": label_held_loss_path(pnl=float(trade["pnl_pct"]), mfe=float(path["mfe"])),
            }
        )
    return records, incomplete


def autopsy_book(trades, sessions, calendar, params, last_bar: date) -> dict:
    kept, short, missing = build_main_book(trades, sessions, calendar, params, last_bar)
    records, incomplete = label_book(kept, sessions, calendar)
    summary = summarize_loss_paths(records)
    summary["incomplete"] = incomplete
    summary["dropped_short_legs"] = short
    summary["missing_reconstruction"] = missing
    summary["stats"] = pack(kept)
    return summary, kept


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--autopsy-only", action="store_true")
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
    print("loading sessions for VCP 179 loss-path autopsy", flush=True)
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        min(starts) - timedelta(days=400),
        max(ends),
    )
    train_uh = upper_half(train_all, sessions, calendar)
    val_uh = upper_half(val_all, sessions, calendar)
    train_summary, train_kept = autopsy_book(
        train_uh, sessions, calendar, params, date(2022, 12, 31)
    )
    val_summary, val_kept = autopsy_book(
        val_uh, sessions, calendar, params, date(2026, 12, 31)
    )
    val_summary["incomplete_excluded"] = len(val_open)
    train_overlay = None
    val_overlay = None
    rule = None
    if not args.autopsy_only:
        train_overlay = overlay_book(train_kept, sessions, calendar, date(2022, 12, 31))
        val_overlay = overlay_book(val_kept, sessions, calendar, date(2026, 12, 31))
        rule = train_overlay["rule"]
        val_avg = (val_overlay.get("variant") or {}).get("avg_pnl")
        if rule == "keep" and val_avg is not None and val_avg < 0:
            rule = "drop"
        train_overlay["rule"] = rule
        val_overlay["rule"] = rule
        train_summary["overlay"] = train_overlay
        val_summary["overlay"] = val_overlay
    report = {
        "experiment": "vcp-loss-path-kind-v1",
        "baseline_run": VCP_RUN,
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
                "rule": rule,
                "change": protocol.get("change"),
                "training_paths": {
                    "attacked_path": train_summary.get("attacked_path"),
                    "paths": {
                        name: {"n": row["n"], "avg_pnl": row["avg_pnl"]}
                        for name, row in (train_summary.get("paths") or {}).items()
                    },
                    "incomplete": train_summary.get("incomplete"),
                    "stats": train_summary.get("stats"),
                },
                "training_overlay": train_overlay,
                "validation_overlay": val_overlay,
                "validation_note": "exposure, not clean OOS",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
