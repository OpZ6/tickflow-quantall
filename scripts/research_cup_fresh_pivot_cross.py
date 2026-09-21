"""One causal cup buy-kind contrast against the frozen independent thin book."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from research_cup_loss_path_kind import autopsy_book, build_cup_thin_book  # noqa: E402
from research_cup_upper_half import CUP_RUN, pack  # noqa: E402
from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    dual_regime_gate,
    load_training_market,
    rs_universe_mask,
)
from research_vcp_two_bar_no_demand import (  # noqa: E402
    _as_date,
    load_symbol_sessions,
    training_trades,
)

EXPERIMENT = "cup-fresh-pivot-cross-v1"


def crosses_pivot(previous_close, signal_close, pivot):
    if any(v is None or not np.isfinite(v) or v <= 0
           for v in (previous_close, signal_close, pivot)):
        return None
    return bool(previous_close <= pivot < signal_close)


def key(trade):
    return (trade["symbol"], str(trade["entry_signal_date"])[:10],
            str(trade["entry_date"])[:10])


def summarize(trades):
    days = defaultdict(list)
    years = defaultdict(list)
    for trade in trades:
        days[str(trade["entry_signal_date"])[:10]].append(float(trade["pnl_pct"]))
        years[str(trade["entry_signal_date"])[:4]].append(trade)
    return {**pack(trades), "signal_days": len(days),
            "signal_day_equal_weight_net": float(np.mean([np.mean(v) for v in days.values()]))
            if days else None, "years": {y: pack(ts) for y, ts in sorted(years.items())}}


def main():
    folder = ROOT / "docs/research/cup-handle"
    protocol = json.loads((folder / f"{EXPERIMENT}.json").read_text(encoding="utf-8"))
    run = ROOT / "data/research/vcp/runs" / CUP_RUN
    payload = json.loads((run / "result.json").read_text(encoding="utf-8"))
    trades = training_trades(payload["trades"])
    evidence = json.loads((run / "entry-structure-evidence.json").read_text(encoding="utf-8"))
    pivots = {key(r): r["pivot"] for r in evidence["records"]}
    print("Loading training-only market and frozen thin book", flush=True)
    market, _, _ = load_training_market(ROOT / "data", DATA_START, date(2022, 12, 31))
    gate, _ = dual_regime_gate(market)
    _, ranks = rs_universe_mask(market, 85.0)
    dates = [_as_date(d) for d in market.timestamp_labels]
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in trades}),
        date(2015, 12, 1), date(2022, 12, 31))
    book, _, missing_upper, _ = build_cup_thin_book(
        trades, sessions, calendar, dates, list(market.symbols), gate, ranks)
    if len(book) != 2034:
        raise ValueError(f"Baseline drift: expected 2034, got {len(book)}")
    previous = dict(zip(calendar[1:], calendar[:-1], strict=True))
    bars = {s: {_as_date(b["date"]): b for b in bs} for s, bs in sessions.items()}
    kept, removed, missing, ledger = [], [], [], []
    for trade in book:
        signal = _as_date(trade["entry_signal_date"])
        symbol_bars = bars[trade["symbol"]]
        before = symbol_bars.get(previous.get(signal), {}).get("close")
        close = symbol_bars.get(signal, {}).get("close")
        pivot = pivots.get(key(trade))
        flag = crosses_pivot(before, close, pivot)
        (missing if flag is None else kept if flag else removed).append(trade)
        ledger.append({**trade, "previous_close": before, "signal_close": close,
                       "signal_pivot": pivot, "crosses": flag})
    baseline, variant = summarize(book), summarize(kept)
    passed = (not missing and len(kept) >= 100 and variant["avg_pnl"] > max(0, baseline["avg_pnl"])
              and variant["signal_day_equal_weight_net"] >= baseline["signal_day_equal_weight_net"])
    report = {"experiment": EXPERIMENT, "protocol": protocol, "baseline": baseline,
              "variant": variant, "removed": summarize(removed), "missing": len(missing),
              "baseline_upper_missing": missing_upper,
              "paths": {name: autopsy_book(ts, sessions, calendar)[0]
                        for name, ts in (("baseline", book), ("variant", kept), ("removed", removed))},
              "rule": "research_candidate" if passed else "drop",
              "validation": "No validation fills in frozen run; not clean OOS"}
    out = ROOT / "data/research/cup-handle" / EXPERIMENT
    out.mkdir(parents=True, exist_ok=True)
    (out / "selection-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{EXPERIMENT}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"paths", "protocol"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
