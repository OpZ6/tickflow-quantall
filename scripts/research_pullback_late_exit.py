"""Describe late exits without using future recovery as an entry/exit condition."""
import argparse
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

from app.backtest.matrix import load_market_data_matrix_from_parquet  # noqa: E402
from app.strategy.builtin._price_structure import (  # noqa: E402
    _latest_prior_launch,
    _previous,
    _prior_mean,
    _ratio,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--supply", action="store_true")
    args = parser.parse_args()
    ledger = json.loads((ROOT / "data/research/pullback/launch-fixed-support-exit-v1/ledger.json").read_text(encoding="utf-8"))
    late = [r for r in ledger if r["variant"] and r["variant"]["exit_date"] > r["baseline"]["exit_date"]]
    meta = json.loads((ROOT / "data/research/vcp/runs" / PULLBACK_RUN / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = {p["id"]: p["default"] for p in meta["params"]}
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=sorted({r["baseline"]["symbol"] for r in late}), field_columns={"raw_close"},
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    prev = _previous(market.close, market)
    launch = ((_ratio(market.close - prev, prev) >= params["launch_gain_min"])
              & (market.volume >= _prior_mean(market.volume, market, 20) * params["launch_volume_ratio_min"]))
    support = _latest_prior_launch(market, launch, (market.open + market.close) / 2, params["launch_lookback"])
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    assets = {s: i for i, s in enumerate(market.symbols)}
    records = []
    for r in late:
        old, new = r["baseline"], r["variant"]
        a = assets[old["symbol"]]
        signal, start, end = (dates[old["exit_signal_date"]], dates[old["exit_date"]], dates[new["exit_date"]])
        level = float(support[signal, a])
        threshold = level * (1 - params["failure_buffer"])
        # End open already sold: exclude that day's later high/close.
        closes = market.close[start:end, a]
        complete = bool(np.isfinite(closes).all())
        recovered = bool((closes >= threshold).any()) if complete else None
        records.append({"symbol": old["symbol"], "entry_date": old["entry_date"], "path": r["path"],
                        "old_exit_signal_date": old["exit_signal_date"], "old_exit_date": old["exit_date"],
                        "new_exit_date": new["exit_date"], "initial_support": r["support"],
                        "exit_support": level, "support_raised": level > r["support"],
                        "recovered_old_exit_line": recovered, "complete_interval": complete,
                        "extra_market_days": end-start, "old_pnl": old["pnl_pct"],
                        "new_pnl": new["pnl_pct"], "delta": new["pnl_pct"]-old["pnl_pct"],
                        "new_exit_reason": new["exit_reason"]})
        if args.supply:
            anchors = np.flatnonzero(launch[:signal, a])
            anchor = int(anchors[-1])
            prior = np.flatnonzero(np.isfinite(market.close[:signal, a]))[-1]
            records[-1].update({
                "anchor_date": market.timestamp_labels[anchor][:10],
                "signal_volume_to_launch": float(market.volume[signal, a] / market.volume[anchor, a]),
                "signal_volume_to_prior": float(market.volume[signal, a] / market.volume[prior, a]),
                "signal_return": float(market.close[signal, a] / market.close[prior, a] - 1),
                "signal_close_location": float((market.close[signal, a] - market.low[signal, a]) /
                                               (market.high[signal, a] - market.low[signal, a]))
                if market.high[signal, a] > market.low[signal, a] else None,
                "signal_bar": {f: float(getattr(market, f)[signal, a])
                               for f in ("open", "high", "low", "close", "volume")}})
    groups = defaultdict(list)
    for r in records:
        groups[str(r["recovered_old_exit_line"])].append(r)
    report = {"n": len(records), "all_original_exits_signal": all(r["baseline"]["exit_reason"] == "signal" for r in late),
              "raised_support": sum(r["support_raised"] for r in records),
              "mean_delta": float(np.mean([r["delta"] for r in records])),
              "recovery_groups": {k: {"n": len(rows), "improved": sum(r["delta"] > 0 for r in rows),
                                       "mean_delta": float(np.mean([r["delta"] for r in rows]))}
                                  for k, rows in groups.items()},
              "scope": "Post-exit recovery is retrospective, not signal-day information; no actionable gate or threshold proposed"}
    experiment = "launch-late-exit-supply-v1" if args.supply else "launch-late-exit-path-v1"
    if args.supply:
        fields = ("signal_volume_to_launch", "signal_volume_to_prior", "signal_return", "signal_close_location")
        report["signal_day_distributions"] = {
            k: {f: {"n": sum(r[f] is not None for r in rows),
                     "q25_median_q75": np.quantile([r[f] for r in rows if r[f] is not None], [.25, .5, .75]).tolist()}
                for f in fields} for k, rows in groups.items()}
        report["scope"] = "Exploratory signal-day distributions against exposed future labels; no threshold search or trading rule"
    out = ROOT / "data/research/pullback" / experiment
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "docs/research/pullback" / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
