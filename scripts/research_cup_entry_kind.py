"""Reconstruct causal cup entry kinds before choosing a new intervention."""
import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_cup_held_swing_low import load_baseline  # noqa: E402
from research_cup_upper_half import CUP_RUN  # noqa: E402

from app.backtest.matrix import load_market_data_matrix_from_parquet  # noqa: E402
from app.strategy.builtin._quants_legacy_patterns import LegacyPatternStrategy  # noqa: E402


def ordered_retest(high, low, close, rim, left_price, pivot):
    """An earlier dated breakout must precede the current-day support test."""
    return bool(rim + 1 < len(close) - 1
                and np.any(high[rim + 1:-1] >= pivot)
                and low[-1] <= left_price * 1.01 and close[-1] >= left_price)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ordered-retest", action="store_true")
    args = parser.parse_args()
    protocol = json.loads((ROOT / "docs/research/cup-handle/cup-ordered-retest-v1.json").read_text(encoding="utf-8")) if args.ordered_retest else None
    run = ROOT / "data/research/vcp/runs" / CUP_RUN
    relative = "backend/app/strategy/builtin/_quants_legacy_patterns.py"
    with ZipFile(run / "source.zip") as archive:
        if archive.read(relative) != (ROOT / relative).read_bytes():
            raise ValueError("Frozen detector differs")
    book = load_baseline()
    meta = json.loads((run / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = {p["id"]: p["default"] for p in meta["params"]}
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=sorted({r["symbol"] for r in book}), field_columns=set(),
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    assets = {s: i for i, s in enumerate(market.symbols)}
    strategy = LegacyPatternStrategy("cup")
    records, kept, removed = [], [], []
    for trade in book:
        result = strategy._detect(market, assets[trade["symbol"]], dates[trade["entry_signal_date"]], params)
        records.append({"symbol": trade["symbol"], "signal_date": trade["entry_signal_date"],
                        "entry_date": trade["entry_date"], "detection": result})
        if args.ordered_retest:
            if result.get("status") != "executable":
                raise ValueError("Original executable event no longer reproduces")
            a, t = assets[trade["symbol"]], dates[trade["entry_signal_date"]]
            indices = np.flatnonzero(np.isfinite(market.close[:t + 1, a]))
            maximum = {"short": 45, "medium": 120, "long": 260, "extended": 420}[result["scale"]]
            indices = indices[-maximum:]
            high, low, close = [getattr(market, f)[indices, a] for f in ("high", "low", "close")]
            li = int(np.nanargmax(high[:max(3, int(len(close) * .45))]))
            lp = float(high[li])
            bottom = li + 1 + int(np.nanargmin(low[li + 1:]))
            rim = next(i for i in range(bottom + 1, len(close)) if lp * .95 <= high[i] <= lp * 1.05)
            passed = ordered_retest(high, low, close, rim, lp, result["pivot"])
            records[-1]["ordered_retest"] = passed
            (kept if passed else removed).append(trade)
    report = {"source_run": CUP_RUN, "n": len(records),
              "status_counts": dict(Counter(r["detection"].get("status") for r in records)),
              "stage_counts": dict(Counter(r["detection"].get("stage") for r in records)),
              "scope": "Signal-day detector reconstruction; no outcome-based category or return comparison"}
    experiment = "cup-ordered-retest-v1" if args.ordered_retest else "cup-entry-kind-v1"
    if args.ordered_retest:
        baseline, variant = summarize(book), summarize(kept)
        passed = (len(kept) >= 100 and variant["avg_pnl"] > max(0, baseline["avg_pnl"])
                  and variant["signal_day_equal_weight_net"] >= baseline["signal_day_equal_weight_net"]
                  and sum(v["avg_pnl"] > 0 for v in variant["years"].values()) >= sum(v["avg_pnl"] > 0 for v in baseline["years"].values()))
        report.update(protocol=protocol, baseline=baseline, variant=variant, removed=summarize(removed),
                      rule="research_candidate" if passed else "drop")
    output = ROOT / "data/research/cup-handle" / experiment
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(records, ensure_ascii=False, indent=2,
                                                    default=lambda v: v.item()), encoding="utf-8")
    (ROOT / "docs/research/cup-handle" / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
