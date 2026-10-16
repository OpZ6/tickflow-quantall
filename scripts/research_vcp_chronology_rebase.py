"""Reconstruct the frozen VCP books and replay their exits without retuning."""
import argparse
import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_pullback_reclaim import replay  # noqa: E402
from research_vcp_min_legs import (  # noqa: E402
    VCP_RUN,
    attach_breakeven,
    filter_min_legs,
    load_run_params,
    upper_half,
)
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import load_symbol_sessions, training_trades  # noqa: E402

from app.backtest.engine import MatcherConfig  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    load_market_data_matrix_from_parquet,
    slice_market_data_matrix,
    valid_rolling_mean,
    valid_shift,
)


def breakeven_close_exits(close, entry_price):
    """Row zero predates entry; only a held close reaching +5% arms protection."""
    reached = close >= entry_price * 1.05
    reached[0] = False
    exits = np.maximum.accumulate(reached, axis=0) & (close < entry_price)
    exits[0] = False
    return exits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-midpoints", action="store_true")
    args = parser.parse_args()
    run = ROOT / "data/research/vcp/runs" / VCP_RUN
    source = json.loads((run / "result.json").read_text(encoding="utf-8"))["trades"]
    meta = json.loads((run / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = load_run_params(run)
    train = training_trades(source)
    validation, incomplete = slice_trades(source, date(2023, 1, 1), date(2026, 6, 30), date(2026, 6, 30))
    if incomplete:
        raise ValueError("Frozen validation coverage changed")
    needed = train + validation
    raw_upper = {}
    if args.raw_midpoints:
        keys = pl.DataFrame([{"symbol": t["symbol"], "date": date.fromisoformat(t["entry_signal_date"])} for t in needed])
        files = [ROOT / "data/kline_daily_enriched" / f"date={d}" / "part.parquet"
                 for d in sorted({t["entry_signal_date"] for t in needed})]
        raw = (pl.scan_parquet(files).select("symbol", "date", "raw_high", "raw_low", "raw_close")
               .join(keys.lazy(), on=["symbol", "date"], how="semi").collect())
        for row in raw.iter_rows(named=True):
            values = [row[f] for f in ("raw_high", "raw_low", "raw_close")]
            if any(v is None or not np.isfinite(v) or v <= 0 for v in values):
                raise ValueError("Missing raw quote for midpoint audit")
            high, low, close = [round(v * 100) for v in values]
            raw_upper[(row["symbol"], str(row["date"]))] = high > low and 2 * close >= high + low
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in needed}),
        min(date.fromisoformat(t["entry_signal_date"]) for t in needed) - timedelta(days=400),
        date(2026, 6, 30))
    books, overlays = {}, {}
    for name, rows, end, expected_n, expected_mean in (
        ("training", train, date(2022, 12, 31), 179, .019889),
        ("exposed_validation", validation, date(2026, 6, 30), 149, .015638),
    ):
        upper = ([t for t in rows if raw_upper[(t["symbol"], t["entry_signal_date"])]]
                 if args.raw_midpoints else upper_half(rows, sessions, calendar))
        kept, _short, missing = filter_min_legs(upper, sessions, params)
        if missing or (not args.raw_midpoints and len(kept) != expected_n):
            raise ValueError(f"Frozen membership drift: {name}, {len(kept)}, missing={missing}")
        overlay = attach_breakeven(kept, sessions, calendar, end)
        if not args.raw_midpoints and summarize(overlay)["avg_pnl"] != expected_mean:
            raise ValueError(f"Frozen overlay mean drift: {name}")
        books[name], overlays[name] = kept, overlay
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2026, 6, 30),
        symbols=sorted({t["symbol"] for rows in books.values() for t in rows}), field_columns={"raw_close"},
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    valid = np.isfinite(market.close)
    ma = valid_rolling_mean(market.close, valid, params["exit_ma_days"], bar_index=market.valid_bars)
    exits = ((market.close < ma) & (valid_shift(market.close, 1, valid, bar_index=market.valid_bars)
                                  >= valid_shift(ma, 1, valid, bar_index=market.valid_bars)))
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    assets = {s: i for i, s in enumerate(market.symbols)}
    config = MatcherConfig(matching="open_t+1", commission_pct=.0003, slippage_bps=10,
                           stamp_tax_policy="a_share_historical", stop_loss_pct=-.05,
                           max_hold_days=40, profit_lock_steps=meta["profit_lock_steps"])
    ledger, report = [], {"scope": "Frozen membership and rules; execution correction, no new hypothesis or clean OOS"}
    for name, book in books.items():
        cap = sum(d[:10] <= "2022-12-31" for d in market.timestamp_labels) if name == "training" else market.shape[0]
        grouped = {k: [] for k in ("old_source_replay", "old_full_breakeven", "corrected_source", "corrected_full_breakeven")}
        for i, trade in enumerate(book):
            a, start = assets[trade["symbol"]], dates[trade["entry_signal_date"]]
            sliced = slice_market_data_matrix(market, start, cap)
            arrays = {k: getattr(sliced, k)[:, a:a + 1] for k in
                      ("open", "high", "low", "close", "volume", "tradable", "limit_up_locked", "limit_down_locked")}
            single = replace(sliced, symbols=(trade["symbol"],), names=(market.names[a],),
                             fields={k: v[:, a:a + 1] for k, v in sliced.fields.items()}, _valid_bars=None, **arrays)
            entry = np.zeros(single.shape, dtype=bool)
            entry[0, 0] = True
            base_exit = exits[start:cap, a:a + 1].copy()
            base_exit[0] = False
            combined_exit = base_exit | breakeven_close_exits(single.close, float(single.open[1, 0]))
            outcomes = {}
            for label, signals in (("source", base_exit), ("full_breakeven", combined_exit)):
                with patch("app.backtest.engine._scheduled_open_exit", return_value=False):
                    old, _stats = replay(single, entry, signals, config=config)
                new, _stats = replay(single, entry, signals, config=config)
                if len(old) != 1 or len(new) != 1:
                    raise ValueError(f"Incomplete replay {name} {trade['symbol']} {trade['entry_date']}")
                outcomes["old_" + ("source_replay" if label == "source" else label)] = old[0]
                outcomes["corrected_" + label] = new[0]
            original = outcomes["old_source_replay"]
            if original["exit_date"] != trade["exit_date"] or abs(original["pnl_pct"] - trade["pnl_pct"]) > .000002:
                raise ValueError(f"Source matcher mismatch: {trade['symbol']} {trade['entry_date']} {original}")
            if any(t["entry_date"] != trade["entry_date"] or t["entry_price"] != original["entry_price"] for t in outcomes.values()):
                raise ValueError("Replayed entry changed")
            for label, fill in outcomes.items():
                grouped[label].append(fill)
            ledger.append({"period": name, "archived": trade, "archived_overlay": overlays[name][i], **outcomes})
            if i % 50 == 0:
                print(f"Replayed {name} {i + 1}/{len(book)}", flush=True)
        report[name] = {"archived_overlay": summarize(overlays[name]), **{k: summarize(v) for k, v in grouped.items()}}
    experiment = "vcp-frozen-chronology-rebase-v1" + ("-raw-midpoints" if args.raw_midpoints else "")
    if args.raw_midpoints:
        report["scope"] = "Same rules with exact raw-cent upper-half comparison; overlay columns are reconstructed legacy formulas on corrected membership"
    output = ROOT / "data/research/vcp" / experiment
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "docs/research/vcp" / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {a: {m: n for m, n in b.items() if m != "years"} for a, b in v.items()}
                      for k, v in report.items() if k != "scope"}), flush=True)


if __name__ == "__main__":
    main()
