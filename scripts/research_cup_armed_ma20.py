"""Paired independent cup replay: MA20 protection starts after price reaches it."""
import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_cup_held_swing_low import load_baseline, paired_diagnostics  # noqa: E402
from research_pullback_reclaim import replay  # noqa: E402

from app.backtest.engine import MatcherConfig  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    load_market_data_matrix_from_parquet,
    slice_market_data_matrix,
    valid_rolling_mean,
)

EXPERIMENT = "cup-armed-ma20-exit-v1"


def armed_ma20_exit(close, ma):
    """Row zero is the entry signal close; cumulative state uses no future bars."""
    armed = np.maximum.accumulate(np.isfinite(close) & np.isfinite(ma) & (close >= ma), axis=0)
    exits = armed & (close < ma)
    exits[0] = False
    return exits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chronology-rebase", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "docs/research/cup-handle"
    protocol = json.loads((folder / f"{EXPERIMENT}.json").read_text(encoding="utf-8"))
    book = load_baseline()
    print("Loading training market for 2034 original entries", flush=True)
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=sorted({t["symbol"] for t in book}), field_columns={"raw_close"},
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    ma = valid_rolling_mean(market.close, np.isfinite(market.close), 20, bar_index=market.valid_bars)
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    assets = {s: i for i, s in enumerate(market.symbols)}
    config = MatcherConfig(matching="open_t+1", commission_pct=0.0003,
                           stamp_tax_policy="a_share_historical", slippage_bps=10,
                           stop_loss_pct=-0.07, max_hold_days=30)
    ledger, original, variant = [], [], []
    for i, trade in enumerate(book):
        a, start = assets[trade["symbol"]], dates[trade["entry_signal_date"]]
        sliced = slice_market_data_matrix(market, start, market.shape[0])
        arrays = {k: getattr(sliced, k)[:, a:a + 1] for k in
                  ("open", "high", "low", "close", "volume", "tradable", "limit_up_locked", "limit_down_locked")}
        single = replace(sliced, symbols=(trade["symbol"],), names=(market.names[a],),
                         fields={k: v[:, a:a + 1] for k, v in sliced.fields.items()},
                         _valid_bars=None, **arrays)
        entry = np.zeros(single.shape, dtype=bool)
        entry[0, 0] = True
        baseline_exit = single.close < ma[start:, a:a + 1]
        baseline_exit[0] = False
        new_exit = armed_ma20_exit(single.close, ma[start:, a:a + 1])
        outcomes = {}
        for arm, exits in (("baseline", baseline_exit), ("variant", new_exit)):
            fills, _stats = replay(single, entry, exits, config=config)
            if len(fills) > 1:
                raise ValueError("More than one fill per original entry")
            outcomes[arm] = fills[0] if fills else None
        old, new = outcomes["baseline"], outcomes["variant"]
        if old is None or (not args.chronology_rebase and
                (old["exit_date"] != trade["exit_date"] or abs(old["pnl_pct"] - trade["pnl_pct"]) > 0.000002)):
            raise ValueError(f"Baseline mismatch {trade['symbol']} {trade['entry_date']}: {old}")
        if old["entry_date"] != trade["entry_date"] or (new is not None and
                (new["entry_date"] != old["entry_date"] or new["entry_price"] != old["entry_price"])):
            raise ValueError("Exit replacement changed entry execution")
        original.append(old)
        if new:
            variant.append(new)
        ledger.append({"archived": trade, "signal_below_ma20": bool(market.close[start, a] < ma[start, a]), **outcomes})
        if i % 300 == 0:
            print(f"Replayed {i + 1}/{len(book)} entries", flush=True)
    old, new = summarize(original), summarize(variant)
    changed = sum(r["variant"] is not None and r["baseline"] != r["variant"] for r in ledger)
    passed = (len(variant) == len(book) and changed >= 100 and new["avg_pnl"] > max(0, old["avg_pnl"])
              and new["signal_day_equal_weight_net"] >= old["signal_day_equal_weight_net"]
              and sum(y["avg_pnl"] > 0 for y in new["years"].values()) >= sum(y["avg_pnl"] > 0 for y in old["years"].values()))
    report = {"protocol": protocol, "baseline": old, "variant": new, "changed": changed,
              "uncompleted": len(book) - len(variant),
              "earlier": sum(r["variant"] is not None and r["variant"]["exit_date"] < r["baseline"]["exit_date"] for r in ledger),
              "later": sum(r["variant"] is not None and r["variant"]["exit_date"] > r["baseline"]["exit_date"] for r in ledger),
              "rule": "research_candidate" if passed else "drop"}
    experiment = EXPERIMENT
    if args.chronology_rebase:
        experiment += "-chronology-rebase"
        report["scope"] = "Technical replay after scheduled open exit chronology correction; same frozen rules, not a new hypothesis"
        report["archived_baseline"] = summarize(book)
        report["baseline_changed_exits"] = sum(
            r["archived"]["exit_date"] != r["baseline"]["exit_date"] or
            abs(r["archived"]["pnl_pct"] - r["baseline"]["pnl_pct"]) > 0.000002 for r in ledger)
    if passed:
        paired = [{**r["baseline"], "overlay": {"pnl": r["variant"]["pnl_pct"],
                   "shortened": r["baseline"] != r["variant"]}} for r in ledger]
        report["robustness"] = paired_diagnostics(paired, market.timestamp_labels)
    output = ROOT / "data/research/cup-handle" / experiment
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "protocol"}), flush=True)


if __name__ == "__main__":
    main()
