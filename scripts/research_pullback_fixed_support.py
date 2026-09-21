"""Paired full-path independent replay of persistent initial launch support."""
import argparse
import json
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_cup_held_swing_low import paired_diagnostics  # noqa: E402
from research_pullback_reclaim import PULLBACK_RUN, replay  # noqa: E402

from app.backtest.matrix import (  # noqa: E402
    load_market_data_matrix_from_parquet,
    slice_market_data_matrix,
)
from app.strategy.builtin._price_structure import (  # noqa: E402
    _latest_prior_launch,
    _previous,
    _prior_mean,
    _ratio,
)

EXPERIMENT = "launch-fixed-support-exit-v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chronology-rebase", action="store_true")
    parser.add_argument("--robustness-only", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "docs/research/pullback"
    if args.robustness_only:
        experiment = EXPERIMENT + "-chronology-rebase"
        result = json.loads((folder / f"{experiment}-analysis.json").read_text(encoding="utf-8"))
        if result["rule"] != "research_candidate" or result["uncompleted"]:
            raise ValueError("Robustness requires completed paired initial gate")
        ledger = json.loads((ROOT / "data/research/pullback" / experiment / "ledger.json").read_text(encoding="utf-8"))
        paired = [{**r["baseline"], "overlay": {"pnl": r["variant"]["pnl_pct"],
                   "shortened": r["baseline"]["exit_date"] != r["variant"]["exit_date"] or
                   r["baseline"]["pnl_pct"] != r["variant"]["pnl_pct"]}} for r in ledger]
        calendar = [p.parent.name.removeprefix("date=") for p in (ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet")]
        robustness = paired_diagnostics(paired, calendar)
        (folder / f"{experiment}-robustness.json").write_text(json.dumps(robustness, indent=2), encoding="utf-8")
        print(json.dumps(robustness), flush=True)
        return
    protocol = json.loads((folder / f"{EXPERIMENT}.json").read_text(encoding="utf-8"))
    book = json.loads((ROOT / "data/research/pullback/launch-pullback-reclaim-v1/baseline-trades.json").read_text(encoding="utf-8"))
    paths = json.loads((ROOT / "data/research/pullback/launch-support-path-v1/ledger.json").read_text(encoding="utf-8"))
    path_map = {(r["symbol"], r["entry_date"]): r["path"] for r in paths}
    meta = json.loads((ROOT / "data/research/vcp/runs" / PULLBACK_RUN / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = {p["id"]: p["default"] for p in meta["params"]}
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=sorted({t["symbol"] for t in book}), field_columns={"raw_close"},
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"))
    previous = _previous(market.close, market)
    launch = ((_ratio(market.close - previous, previous) >= params["launch_gain_min"])
              & (market.volume >= _prior_mean(market.volume, market, 20) * params["launch_volume_ratio_min"]))
    support = _latest_prior_launch(market, launch, (market.open + market.close) / 2, params["launch_lookback"])
    dates = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    assets = {s: i for i, s in enumerate(market.symbols)}
    ledger, original, variant = [], [], []
    groups = defaultdict(lambda: {"baseline": [], "variant": []})
    for i, trade in enumerate(book):
        a, start = assets[trade["symbol"]], dates[trade["entry_signal_date"]]
        # Full training tail preserves delayed exits after the original exit.
        sliced = slice_market_data_matrix(market, start, market.shape[0])
        fields = {k: v[:, a:a + 1] for k, v in sliced.fields.items()}
        arrays = {k: getattr(sliced, k)[:, a:a + 1] for k in
                  ("open", "high", "low", "close", "volume", "tradable", "limit_up_locked", "limit_down_locked")}
        single = replace(sliced, symbols=(trade["symbol"],), names=(market.names[a],),
                         fields=fields, _valid_bars=None, **arrays)
        entry = np.zeros(single.shape, dtype=bool)
        entry[0, 0] = True
        level = float(support[start, a])
        if not np.isfinite(level):
            raise ValueError("Missing entry support")
        outcomes = {}
        for arm, exit_level in (("baseline", support[start:, a:a + 1]), ("variant", level)):
            exits = single.close < exit_level * (1 - params["failure_buffer"])
            exits[0] = False
            fills, _stats = replay(single, entry, exits)
            outcomes[arm] = fills[0] if fills else None
            if len(fills) > 1:
                raise ValueError("More than one fill per entry")
        old, new = outcomes["baseline"], outcomes["variant"]
        if old is not None and new is not None and (new["entry_date"] != trade["entry_date"]
                                or new["entry_price"] != old["entry_price"]):
            raise ValueError("Exit replacement changed entry execution")
        if old is None or (not args.chronology_rebase and
                (old["exit_date"] != trade["exit_date"] or abs(old["pnl_pct"] - trade["pnl_pct"]) > 0.000002)):
            raise ValueError(f"Baseline mismatch {trade['symbol']} {trade['entry_date']}")
        original.append(old)
        path = path_map[(trade["symbol"], trade["entry_date"])]
        if new:
            variant.append(new)
            groups[path]["baseline"].append(old)
            groups[path]["variant"].append(new)
        ledger.append({"archived": trade, "path": path, "support": level, **outcomes})
        if i % 300 == 0:
            print(f"Replayed {i + 1}/{len(book)} entries", flush=True)
    old, new = summarize(original), summarize(variant)
    changed = sum(r["variant"] is not None and (r["baseline"]["exit_date"], r["baseline"]["pnl_pct"]) !=
                  (r["variant"]["exit_date"], r["variant"]["pnl_pct"]) for r in ledger)
    passed = (len(variant) == len(book) and changed >= 100 and new["avg_pnl"] > max(0, old["avg_pnl"])
              and new["signal_day_equal_weight_net"] >= old["signal_day_equal_weight_net"]
              and sum(y["avg_pnl"] > 0 for y in new["years"].values()) >= sum(y["avg_pnl"] > 0 for y in old["years"].values()))
    report = {"protocol": protocol, "baseline": old, "variant": new, "changed": changed,
              "uncompleted": len(book) - len(variant),
              "earlier": sum(r["variant"] is not None and r["variant"]["exit_date"] < r["baseline"]["exit_date"] for r in ledger),
              "later": sum(r["variant"] is not None and r["variant"]["exit_date"] > r["baseline"]["exit_date"] for r in ledger),
              "paths": {p: {arm: summarize(rows) for arm, rows in g.items()} for p, g in groups.items()},
              "rule": "research_candidate" if passed else "drop"}
    experiment = EXPERIMENT
    if args.chronology_rebase:
        experiment += "-chronology-rebase"
        report["scope"] = "Same frozen rules, technical replay after open exit chronology correction"
        report["archived_baseline"] = summarize(book)
        report["baseline_changed_exits"] = sum(
            r["archived"]["exit_date"] != r["baseline"]["exit_date"] or
            abs(r["archived"]["pnl_pct"] - r["baseline"]["pnl_pct"]) > 0.000002 for r in ledger)
    output = ROOT / "data/research/pullback" / experiment
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"protocol", "paths"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
