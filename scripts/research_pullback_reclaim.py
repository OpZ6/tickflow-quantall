"""Replay full launch opportunities before changing the pullback entry event."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_launch_pullback_leader_day import PULLBACK_RUN, filter_gate, filter_rs  # noqa: E402
from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    dual_regime_gate,
    rs_universe_mask,
)
from research_vcp_loss_path_kind import label_book, summarize_loss_paths  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    _as_date,
    load_symbol_sessions,
    training_trades,
)

from app.backtest.engine import BacktestEngine, MatcherConfig, SimulationOptions  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    build_basic_filter_mask,
    build_market_matrix_from_signals,
    load_market_data_matrix_from_parquet,
    make_signal_matrix,
)
from app.strategy.builtin._price_structure import (  # noqa: E402
    _latest_prior_launch,
    _previous,
    _prior_mean,
    _ratio,
    launch_pullback_support,
)
from app.strategy.engine import DEFAULT_BASIC_FILTER  # noqa: E402

EXPERIMENT = "launch-pullback-reclaim-v1"


def reclaim_after_touch(close, first_touch, launch, support, failure_buffer):
    """A later close reclaims the frozen support; existing invalidation cancels waiting."""
    entries = np.zeros_like(first_touch, dtype=bool)
    pending = np.full(close.shape[1], np.nan)
    for t in range(close.shape[0]):
        cancel = (launch[t] | ~np.isfinite(close[t]) | ~np.isfinite(support[t])
                  | (close[t] < pending * (1 - failure_buffer)))
        pending[cancel] = np.nan
        if t:
            take = (np.isfinite(pending) & np.isfinite(close[t - 1])
                    & (close[t - 1] <= pending) & (close[t] > pending))
            entries[t] = take
            pending[take] = np.nan
        start = first_touch[t] & ~launch[t] & np.isfinite(close[t]) & np.isfinite(support[t])
        pending[start] = support[t, start]
    return entries


def replay(market, entries, exits, config=None):
    signals = make_signal_matrix(market.shape, entry=entries, exit=exits)
    matrix = build_market_matrix_from_signals(market, signals, entry_delay_bars=1, exit_delay_bars=1)
    config = config or MatcherConfig(matching="open_t+1", commission_pct=0.0003,
                           stamp_tax_policy="a_share_historical", slippage_bps=10,
                           stop_loss_pct=-0.06, max_hold_days=20)
    result = BacktestEngine(repo=None).simulate_independent_market_matrix(
        matrix, int(entries.sum()), config,
        options=SimulationOptions(include_monte_carlo=False, include_curves=False,
                                  include_per_symbol_stats=False, include_return_distribution=False))
    trades = [asdict(t) for t in result.trades]
    return [t for t in trades if t["exit_reason"] != "end"], result.stats


def trade_key(t):
    return t["symbol"], str(t["entry_signal_date"])[:10]


def main():
    protocol_path = ROOT / "docs/research/pullback" / f"{EXPERIMENT}.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    run = ROOT / "data/research/vcp/runs" / PULLBACK_RUN
    source = json.loads((run / "result.json").read_text(encoding="utf-8"))
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    meta = json.loads((run / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = {p["id"]: p["default"] for p in meta["params"]}
    print("Loading full training market, then reproducing original thin book", flush=True)
    root = ROOT / "data/kline_daily_enriched"
    files = [p for p in root.glob("date=*/part.parquet")
             if "date=2015-01-05" <= p.parent.name <= "date=2022-12-31"]
    full_symbols = (pl.scan_parquet(files).select("symbol").unique()
                    .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
                    .collect()["symbol"].to_list())
    market = load_market_data_matrix_from_parquet(
        root, DATA_START, date(2022, 12, 31), symbols=full_symbols,
        instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"),
        field_columns={"raw_close", "amount", "total_shares"})
    dates = [_as_date(d) for d in market.timestamp_labels]
    symbols = list(market.symbols)
    gate, _ = dual_regime_gate(market)
    _, ranks = rs_universe_mask(market, 85.0)
    baseline, _ = filter_gate(training_trades(source["trades"]), dates, gate)
    baseline, _ = filter_rs(baseline, symbols, dates, ranks, 85.0)
    if len(baseline) != 1421:
        raise ValueError(f"Archived thin-book drift: {len(baseline)}")
    first_touch, exits = launch_pullback_support(market, params)
    source_symbols = set(config["symbols"])
    universe = np.array([s in source_symbols for s in symbols])
    allowed = (build_basic_filter_mask(market, {**DEFAULT_BASIC_FILTER, **meta.get("basic_filter", {})})
               & universe[None, :] & gate[:, None] & (ranks >= 85)
               & np.array([date(2016, 1, 4) <= d <= date(2022, 12, 30) for d in dates])[:, None])
    entries = first_touch & allowed
    print(f"Replaying {int(entries.sum())} original entry candidates", flush=True)
    replayed, stats = replay(market, entries, exits)
    archived = {trade_key(t): t for t in baseline}
    rebuilt = {trade_key(t): t for t in replayed}
    mismatches = []
    for key in archived.keys() & rebuilt.keys():
        old, new = archived[key], rebuilt[key]
        if (str(old["exit_date"])[:10] != str(new["exit_date"])[:10]
                or round(abs(old["pnl_pct"] - new["pnl_pct"]), 6) > 1e-6):
            mismatches.append({"key": key, "old": old, "new": new})
    report = {"experiment": EXPERIMENT, "archived": summarize(baseline),
              "replayed": summarize(replayed), "missing": sorted(archived.keys() - rebuilt.keys()),
              "extra": sorted(rebuilt.keys() - archived.keys()), "mismatches": mismatches,
              "execution": stats.get("execution"), "source_run": PULLBACK_RUN,
              "rounding_tolerance": 0.000001,
              "max_net_difference": max((abs(archived[k]["pnl_pct"] - rebuilt[k]["pnl_pct"])
                                         for k in archived.keys() & rebuilt.keys()), default=None),
              "price_scale_changes": sum(archived[k]["entry_price"] != rebuilt[k]["entry_price"]
                                         for k in archived.keys() & rebuilt.keys())}
    output = ROOT / "data/research/pullback" / EXPERIMENT
    output.mkdir(parents=True, exist_ok=True)
    (output / "baseline-replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output / "baseline-trades.json").write_text(json.dumps(replayed, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"archived": report["archived"], "replayed": report["replayed"],
                      "missing": len(report["missing"]), "extra": len(report["extra"]),
                      "mismatches": len(mismatches)}, ensure_ascii=False), flush=True)
    if report["missing"] or report["extra"] or mismatches:
        raise ValueError("Replay differs from original; resolve execution before testing new entry")
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in replayed}),
        min(_as_date(t["entry_date"]) for t in replayed),
        max(_as_date(t["exit_date"]) for t in replayed))
    labels, incomplete = label_book(replayed, sessions, calendar)
    autopsy = summarize_loss_paths(labels)
    autopsy["incomplete"] = incomplete
    print("Baseline paths: " + json.dumps(autopsy, ensure_ascii=False), flush=True)
    previous = _previous(market.close, market)
    launch = ((_ratio(market.close - previous, previous) >= params["launch_gain_min"])
              & (market.volume >= _prior_mean(market.volume, market, 20) * params["launch_volume_ratio_min"]))
    support = _latest_prior_launch(market, launch, (market.open + market.close) / 2,
                                   params["launch_lookback"])
    variant_entries = reclaim_after_touch(market.close, first_touch, launch, support,
                                          params["failure_buffer"]) & allowed
    print(f"Replaying {int(variant_entries.sum())} reclaim entry candidates", flush=True)
    variant, variant_stats = replay(market, variant_entries, exits)
    launch_indices = [np.flatnonzero(launch[:, a]) for a in range(market.shape[1])]
    date_index = {str(d): i for i, d in enumerate(dates)}
    symbol_index = {s: i for i, s in enumerate(symbols)}

    def opportunity(symbol, signal_date):
        t, a = date_index[str(signal_date)[:10]], symbol_index[symbol]
        anchors = launch_indices[a]
        position = np.searchsorted(anchors, t, side="left") - 1
        if position < 0:
            raise ValueError("Entry without prior launch")
        return symbol + ":" + str(dates[anchors[position]])

    by_opportunity = [{opportunity(t["symbol"], t["entry_signal_date"]): t for t in trades}
                      for trades in (replayed, variant)]
    old, new = by_opportunity
    for arm, candidates, trades in (("baseline", entries, replayed), ("variant", variant_entries, variant)):
        completed = {trade_key(t) for t in trades}
        candidate_rows = [{"symbol": symbols[a], "signal_date": str(dates[t]),
                           "opportunity": opportunity(symbols[a], dates[t]),
                           "completed": (symbols[a], str(dates[t])) in completed}
                          for t, a in zip(*np.nonzero(candidates), strict=True)]
        (output / f"{arm}-candidates.json").write_text(json.dumps(candidate_rows, indent=2), encoding="utf-8")
    baseline_summary, variant_summary = summarize(replayed), summarize(variant)
    enough = len(variant) >= 100
    better = (enough and variant_summary["avg_pnl"] > max(0, baseline_summary["avg_pnl"])
              and variant_summary["signal_day_equal_weight_net"] >= baseline_summary["signal_day_equal_weight_net"]
              and sum(y["avg_pnl"] > 0 for y in variant_summary["years"].values())
              >= sum(y["avg_pnl"] > 0 for y in baseline_summary["years"].values()))
    result = {"experiment": EXPERIMENT, "protocol": protocol, "baseline": baseline_summary,
              "variant": variant_summary, "baseline_paths": autopsy,
              "variant_execution": variant_stats.get("execution"),
              "candidate_counts": {"baseline": int(entries.sum()), "variant": int(variant_entries.sum())},
              "opportunities": {"retained": len(old.keys() & new.keys()),
                                "lost": len(old.keys() - new.keys()), "new": len(new.keys() - old.keys()),
                                "lost_stats": summarize([old[k] for k in old.keys() - new.keys()]),
                                "new_stats": summarize([new[k] for k in new.keys() - old.keys()]),
                                "old_winners": sum(t["pnl_pct"] > 0 for t in old.values()),
                                "old_winners_retained": sum(old[k]["pnl_pct"] > 0 for k in old.keys() & new.keys())},
              "rule": "research_candidate" if better else "drop"}
    (output / "variant-trades.json").write_text(json.dumps(variant, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (protocol_path.with_name(f"{EXPERIMENT}-analysis.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"protocol", "baseline_paths"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
