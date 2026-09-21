"""Audit original exit duties and causal MA20 state at cup entry."""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_held_swing_low import load_baseline  # noqa: E402

from app.backtest.matrix import (  # noqa: E402
    load_market_data_matrix_from_parquet,
    valid_rolling_mean,
)


def main():
    book = load_baseline()
    old = json.loads((ROOT / "data/research/cup-handle/cup-held-swing-low-exit-v1/exit-ledger.json").read_text(encoding="utf-8"))
    paths = {(t["symbol"], t["entry_date"]): t["original_path"] for t in old}
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=sorted({t["symbol"] for t in book}), field_columns=set(),
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    ma = valid_rolling_mean(market.close, np.isfinite(market.close), 20, bar_index=market.valid_bars)
    assets = {s: i for i, s in enumerate(market.symbols)}
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    records = []
    grouped = defaultdict(list)
    for trade in book:
        a, t = assets[trade["symbol"]], dates[trade["entry_signal_date"]]
        entry = dates[trade["entry_date"]]
        end = dates[trade["exit_date"]]
        entry_below = bool(market.close[t, a] < ma[t, a])
        held_above = bool((market.close[entry:end, a] >= ma[entry:end, a]).any())
        record = {**trade, "path": paths[(trade["symbol"], trade["entry_date"])],
                  "signal_close": float(market.close[t, a]), "signal_ma20": float(ma[t, a]),
                  "entry_signal_below_ma20": entry_below, "held_close_above_ma20": held_above}
        records.append(record)
        grouped[(record["path"], trade["exit_reason"], entry_below)].append(record)
    report = {"n": len(book), "entry_signal_below_ma20": sum(r["entry_signal_below_ma20"] for r in records),
              "scope": "Original completed fills and causal entry MA20 state; path labels retrospective, no new rule tested",
              "groups": [{"path": key[0], "exit_reason": key[1], "entry_signal_below_ma20": key[2],
                          "n": len(rows), "mean_net": float(np.mean([r["pnl_pct"] for r in rows])),
                          "median_duration": float(np.median([r["duration"] for r in rows])),
                          "held_close_above_ma20": sum(r["held_close_above_ma20"] for r in rows)}
                         for key, rows in grouped.items()]}
    output = ROOT / "data/research/cup-handle/cup-exit-duties-v1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "docs/research/cup-handle/cup-exit-duties-v1-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
