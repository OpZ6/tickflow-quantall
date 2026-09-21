"""Describe entry gaps and T+1 exposure in original cup hard-stop paths."""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_cup_held_swing_low import load_baseline  # noqa: E402

from app.backtest.matrix import (  # noqa: E402
    load_market_data_matrix_from_parquet,
    valid_rolling_mean,
)


def main():
    book = load_baseline()
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=sorted({t["symbol"] for t in book}), field_columns=set(),
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    ma = valid_rolling_mean(market.close, np.isfinite(market.close), 20, bar_index=market.valid_bars)
    assets = {s: i for i, s in enumerate(market.symbols)}
    records, groups = [], defaultdict(list)
    for trade in book:
        a = assets[trade["symbol"]]
        signal, entry, end = [dates[trade[k]] for k in ("entry_signal_date", "entry_date", "exit_date")]
        low, high, close = [float(getattr(market, k)[signal, a]) for k in ("low", "high", "close")]
        opening, entry_low, exit_open = [float(arr[t, a]) for arr, t in
                                       ((market.open, entry), (market.low, entry), (market.open, end))]
        if not np.isfinite([low, high, close, opening, entry_low, exit_open]).all():
            raise ValueError(f"Missing required bar: {trade['symbol']} {trade['entry_date']}")
        location = "below_signal_low" if opening < low else "above_signal_high" if opening > high else "inside_signal_range"
        stop = opening * .93
        row = {**trade, "entry_location": location, "signal_low": low, "signal_high": high,
               "signal_close": close, "entry_open": opening, "entry_low": entry_low,
               "exit_open": exit_open, "entry_day_touched_stop": entry_low <= stop,
               "exit_open_below_stop": exit_open <= stop, "market_days_held": end - entry,
               "prior_close_ma20_exit": bool(market.close[end - 1, a] < ma[end - 1, a]),
               "blocked_exit_days": trade.get("blocked_exit_days", 0),
               "missing_held_bars": int((~np.isfinite(market.close[entry:end + 1, a])).sum())}
        records.append(row)
        groups[(location, trade["exit_reason"])].append(row)
    stops = [r for r in records if r["exit_reason"] == "stop_loss"]
    report = {"scope": "Retrospective path diagnosis on all original entries, no entry filtering or new rule tested",
              "n": len(records), "hard_stops": len(stops),
              "hard_stop_entry_day_touches": sum(r["entry_day_touched_stop"] for r in stops),
              "hard_stop_exit_open_below_stop": sum(r["exit_open_below_stop"] for r in stops),
              "hard_stop_first_sellable_day": sum(r["market_days_held"] == 1 for r in stops),
              "hard_stop_paths_with_missing_bars": sum(r["missing_held_bars"] > 0 for r in stops),
              "intraday_stop_with_prior_close_exit_and_no_block": sum(
                  r["prior_close_ma20_exit"] and not r["exit_open_below_stop"] and not r["blocked_exit_days"] for r in stops),
              "groups": [{"entry_location": k[0], "exit_reason": k[1], **summarize(rows),
                          "entry_day_touched_stop": sum(r["entry_day_touched_stop"] for r in rows),
                          "median_market_days_held": float(np.median([r["market_days_held"] for r in rows]))}
                         for k, rows in groups.items()]}
    experiment = "cup-stop-entry-path-v1"
    output = ROOT / "data/research/cup-handle" / experiment
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "docs/research/cup-handle" / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "groups"}), flush=True)
    for group in report["groups"]:
        print(json.dumps({k: v for k, v in group.items() if k != "years"}), flush=True)


if __name__ == "__main__":
    main()
