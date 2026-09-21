"""Trace original launch-support expiry/replacement on frozen held paths."""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_pullback_reclaim import PULLBACK_RUN  # noqa: E402
from research_vcp_loss_path_kind import label_book  # noqa: E402
from research_vcp_two_bar_no_demand import _as_date, load_symbol_sessions  # noqa: E402

from app.backtest.matrix import load_market_data_matrix_from_parquet  # noqa: E402
from app.strategy.builtin._price_structure import (  # noqa: E402
    _latest_prior_launch,
    _previous,
    _prior_mean,
    _ratio,
)


def main():
    book = json.loads((ROOT / "data/research/pullback/launch-pullback-reclaim-v1/baseline-trades.json").read_text(encoding="utf-8"))
    meta = json.loads((ROOT / "data/research/vcp/runs" / PULLBACK_RUN / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = {p["id"]: p["default"] for p in meta["params"]}
    symbols = sorted({t["symbol"] for t in book})
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=symbols, field_columns={"raw_close"},
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    previous = _previous(market.close, market)
    launch = ((_ratio(market.close - previous, previous) >= params["launch_gain_min"])
              & (market.volume >= _prior_mean(market.volume, market, 20) * params["launch_volume_ratio_min"]))
    support = _latest_prior_launch(market, launch, (market.open + market.close) / 2, params["launch_lookback"])
    sessions, calendar = load_symbol_sessions(ROOT / "data", symbols,
        min(_as_date(t["entry_date"]) for t in book), max(_as_date(t["exit_date"]) for t in book))
    labels, incomplete = label_book(book, sessions, calendar)
    paths = {(r["symbol"], r["entry_date"]): r["path"] for r in labels}
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    assets = {s: i for i, s in enumerate(market.symbols)}
    records, groups = [], defaultdict(list)
    for trade in book:
        a = assets[trade["symbol"]]
        signal, entry, end = (dates[trade[k][:10]] for k in ("entry_signal_date", "entry_date", "exit_date"))
        initial = float(support[signal, a])
        current = support[entry:end, a]
        closes = market.close[entry:end, a]
        valid = np.isfinite(current)
        fixed_break = closes < initial * (1 - params["failure_buffer"])
        dynamic_break = closes < current * (1 - params["failure_buffer"])
        different = np.flatnonzero(fixed_break != dynamic_break)
        record = {"symbol": trade["symbol"], "entry_date": trade["entry_date"],
                  "path": paths.get((trade["symbol"], trade["entry_date"]), "incomplete"),
                  "pnl": trade["pnl_pct"], "initial_support": initial,
                  "expired_during_hold": bool((~valid).any()),
                  "higher_support": bool((current > initial).any()),
                  "lower_support": bool((current < initial).any()),
                  "fixed_only_break": bool((fixed_break & ~dynamic_break).any()),
                  "dynamic_only_break": bool((dynamic_break & ~fixed_break).any()),
                  "first_difference": market.timestamp_labels[entry + different[0]][:10] if len(different) else None}
        records.append(record)
        groups[record["path"]].append(record)
    fields = ["expired_during_hold", "higher_support", "lower_support", "fixed_only_break", "dynamic_only_break"]
    report = {"source_run": PULLBACK_RUN, "n": len(book), "incomplete_paths": incomplete,
              "scope": "Descriptive held-path signal comparison, not an exit intervention or executable return estimate",
              "groups": {p: {"n": len(rows), **{f: sum(r[f] for r in rows) for f in fields}}
                         for p, rows in groups.items()}}
    output = ROOT / "data/research/pullback/launch-support-path-v1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "docs/research/pullback/launch-support-path-v1-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
