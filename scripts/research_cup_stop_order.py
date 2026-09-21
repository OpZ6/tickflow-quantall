"""Full cup opportunity replay before comparing next-session buy stops."""
import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from research_cup_fresh_pivot_cross import summarize  # noqa: E402
from research_leader_universe_market_gate import dual_regime_gate, rs_universe_mask  # noqa: E402
from research_next_day_stop_entry import next_day_stop_entry  # noqa: E402

from app.backtest.engine import BacktestEngine, MatcherConfig, SimulationOptions  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    build_basic_filter_mask, build_market_matrix_from_signals,
    load_market_data_matrix_from_parquet, make_signal_matrix,
)
from app.strategy.builtin._quants_legacy_patterns import LegacyPatternStrategy  # noqa: E402
from app.strategy.builtin._price_structure import launch_pullback_support  # noqa: E402
from app.strategy.engine import DEFAULT_BASIC_FILTER  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialect", choices=["cup", "pullback"], default="cup")
    args = parser.parse_args()
    cup = args.dialect == "cup"
    source = ROOT / "data/research/vcp/runs" / ("20260909T133226351846Z" if cup else "20260909T053715693165Z")
    meta = read(source / "strategy.json")["meta"]
    params = {p["id"]: p["default"] for p in meta["params"]}
    source_config = read(source / "config.json")
    symbols = source_config["symbols"]
    out = ROOT / "data/research" / ("cup-handle" if cup else "pullback") / f"{args.dialect}-next-day-stop-order-v1"
    out.mkdir(parents=True, exist_ok=True)
    print("Loading full source universe and training market", flush=True)
    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2015, 1, 5), date(2022, 12, 31),
        symbols=symbols, instruments=pl.read_parquet(ROOT / "data/instruments/instruments.parquet"),
        field_columns={"raw_close", "raw_high", "raw_low", "amount", "total_shares"})
    gate, _ = dual_regime_gate(market)
    _, ranks = rs_universe_mask(market, 85.)
    print(f"Computing complete {args.dialect} event stream", flush=True)
    if cup:
        signals = LegacyPatternStrategy("cup", "signal_quants_cup_handle_entry", "signal_quants_cup_handle_exit").compute_signals(market, params)
        # Reproduce the archived float64 upper-half predicate, including zero-range rejection.
        files = [p for p in (ROOT / "data/kline_daily_enriched").glob("date=*/part.parquet")
                 if f'date={source_config["start"]}' <= p.parent.name <= f'date={source_config["end"]}']
        upper_rows = (pl.scan_parquet(files).filter((pl.col("high") > pl.col("low"))
                      & (((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low"))) >= .5))
                      .select("symbol", "date").collect())
        upper = np.zeros(market.shape, dtype=bool)
        date_ids = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
        asset_ids = {s: i for i, s in enumerate(market.symbols)}
        for symbol, day in upper_rows.iter_rows():
            if symbol in asset_ids:
                upper[date_ids[str(day)], asset_ids[symbol]] = True
    else:
        entry, exits = launch_pullback_support(market, params)
        signals = make_signal_matrix(market.shape, entry=entry, exit=exits)
        upper = True
    allowed = (build_basic_filter_mask(market, {**DEFAULT_BASIC_FILTER, **meta.get("basic_filter", {})})
               & gate[:, None] & (ranks >= 85) & upper
               & np.array([source_config["start"] <= d[:10] <= source_config["end"] for d in market.timestamp_labels])[:, None])
    entries = (signals.entry != 0) & allowed
    matrix = build_market_matrix_from_signals(market, make_signal_matrix(market.shape, entry=entries, exit=signals.exit),
                                             entry_delay_bars=1, exit_delay_bars=1)
    config = MatcherConfig(matching="open_t+1", commission_pct=.0003, slippage_bps=10,
                           stamp_tax_policy="a_share_historical", stop_loss_pct=-.07 if cup else -.06,
                           max_hold_days=30 if cup else 20)

    def simulate(value):
        result = BacktestEngine(repo=None).simulate_independent_market_matrix(
            value, int(entries.sum()), config, options=SimulationOptions(include_monte_carlo=False, include_curves=False))
        all_trades = [asdict(t) for t in result.trades]
        return [t for t in all_trades if t["exit_reason"] != "end"], all_trades, result.stats.get("execution")

    baseline, all_base, execution = simulate(matrix)
    reference = ("cup-handle/cup-armed-ma20-exit-v1-chronology-rebase" if cup
                 else "pullback/launch-fixed-support-exit-v1-chronology-rebase")
    archived = [r["baseline"] for r in read(ROOT / "data/research" / reference / "ledger.json")]
    old = {(t["symbol"], t["entry_signal_date"]): t for t in archived}
    new = {(t["symbol"], t["entry_signal_date"]): t for t in baseline}
    mismatch = [k for k in old.keys() & new.keys() if old[k]["exit_date"] != new[k]["exit_date"]
                or abs(old[k]["pnl_pct"] - new[k]["pnl_pct"]) > .000002]
    report = {"candidates": int(entries.sum()), "baseline": summarize(baseline),
              "missing": sorted(old.keys() - new.keys()), "extra": sorted(new.keys() - old.keys()),
              "mismatches": mismatch, "baseline_execution": execution}
    (out / "baseline-trades.json").write_text(json.dumps(all_base, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "baseline-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    if report["missing"] or report["extra"] or mismatch:
        raise ValueError("Full opportunity baseline differs; stop before variant")
    changed, orders = next_day_stop_entry(matrix)
    variant, all_variant, execution = simulate(changed)
    report.update(orders=orders, variant=summarize(variant), variant_execution=execution,
                  unfinished_variant=len(all_variant) - len(variant))
    (out / "variant-trades.json").write_text(json.dumps(all_variant, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
