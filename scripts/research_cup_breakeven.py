#!/usr/bin/env python3
"""+5% then back below entry → next-open exit, on 2034 cup leader-open∩upper-half fills."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

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
)
from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    dual_regime_gate,
    load_training_market,
    rs_universe_mask,
)
from research_vcp_breakeven import overlay_book  # noqa: E402
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    apply_breakeven_after_gain_to_fill,
    independent_trade_stats,
    load_symbol_sessions,
    net_round_trip,
    training_trades,
    _as_date,
)

DEFAULT_PROTOCOL = ROOT / "docs/research/cup-handle/cup-handle-breakeven-after-5pct-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/cup-handle/cup-handle-breakeven-after-5pct-v1-analysis.json"


def _hold_window(trades):
    starts = [
        min(_as_date(t["entry_signal_date"]), _as_date(t["entry_date"]))
        for t in trades
    ]
    ends = [_as_date(t["exit_date"]) for t in trades]
    return min(starts) - timedelta(days=5), max(ends)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = json.loads((Path(args.runs_root) / CUP_RUN / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train_all = training_trades(all_trades)
    val_all, val_open = slice_trades(
        all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31)
    )
    print("loading market for cup leader-open universe", flush=True)
    market, _listing, _names = load_training_market(Path(args.data_root), DATA_START, date(2026, 12, 31))
    gate, _ = dual_regime_gate(market)
    _mask, ranks = rs_universe_mask(market, 85.0)
    dates = [_as_date(label) for label in market.timestamp_labels]
    symbols = list(market.symbols)
    train_base, _ = filter_gate(train_all, dates, gate)
    train_base, _ = filter_rs(train_base, symbols, dates, ranks, 85.0)
    val_base, _ = filter_gate(val_all, dates, gate)
    val_base, _ = filter_rs(val_base, symbols, dates, ranks, 85.0)
    need = train_base + val_base
    if not need:
        raise SystemExit("leader-open cup train/val set is empty")
    start, end = _hold_window(need)
    sessions, calendar = load_symbol_sessions(
        Path(args.data_root),
        sorted({str(t["symbol"]) for t in need}),
        start,
        end,
    )
    train_kept, train_lower, train_miss = filter_upper(train_base, sessions, calendar)
    train_report = overlay_book(train_kept, sessions, calendar, date(2022, 12, 31))
    train_report["upper_half_n"] = len(train_kept)
    train_report["lower_half"] = train_lower
    train_report["missing_signal_bar"] = train_miss
    train_report["rule"] = decide_rule(train_report["variant"], train_report["baseline"])
    val_kept, val_lower, val_miss = filter_upper(val_base, sessions, calendar)
    val_report = overlay_book(val_kept, sessions, calendar, date(2026, 12, 31)) if val_kept else {
        "baseline": independent_trade_stats([]),
        "variant": independent_trade_stats([]),
        "shortened": 0,
        "blocked_kept_baseline": 0,
        "delta": _delta(independent_trade_stats([]), independent_trade_stats([])),
        "rule": "drop",
    }
    val_report["upper_half_n"] = len(val_kept)
    val_report["lower_half"] = val_lower
    val_report["missing_signal_bar"] = val_miss
    val_report["incomplete_excluded"] = len(val_open)
    report = {
        "experiment": "cup-handle-breakeven-after-5pct-v1",
        "baseline_run": CUP_RUN,
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
