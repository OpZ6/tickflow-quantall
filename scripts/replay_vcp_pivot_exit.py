"""Matched VCP exit experiment using the existing independent matcher."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backtest.engine import BacktestEngine, MatcherConfig  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    _limit_lock_matrices,
    build_market_data_matrix,
    build_market_matrix_from_signals,
    make_signal_matrix,
    slice_market_data_matrix,
    valid_rolling_mean,
    valid_shift,
)


def pivot_ma20_exit(close, ma20, pivot):
    """Initial structure floor becomes a trend exit as MA20 rises above it."""
    return close < np.fmax(pivot, ma20)


def replay_event(market, signal_index, end_index, pivot, config, variant="original_entry_pivot_loss"):
    """One entry per matrix ensures overlapping entries never share a pivot."""
    valid = np.isfinite(market.close)
    ma = valid_rolling_mean(market.close, valid, 20, bar_index=market.valid_bars)
    previous = valid_shift(market.close, 1, valid, bar_index=market.valid_bars)
    previous_ma = valid_shift(ma, 1, valid, bar_index=market.valid_bars)
    cross = (market.close < ma) & (previous >= previous_ma)
    sliced = slice_market_data_matrix(market, signal_index, end_index + 1)
    entries = np.zeros(sliced.shape, dtype=bool)
    entries[0, 0] = True
    outcomes = {}
    for arm in ("ma20_cross", variant):
        if arm == "ma20_cross":
            exits = cross[signal_index:end_index + 1].copy()
        elif arm == "original_entry_pivot_loss":
            exits = sliced.close < pivot
        elif arm == "pivot_ma20_support":
            exits = pivot_ma20_exit(sliced.close, ma[signal_index:end_index + 1], pivot)
        else:
            raise ValueError(f"Unknown exit arm: {arm}")
        exits[0] = False  # Never use a pre-entry exit condition.
        signals = make_signal_matrix(sliced.shape, entry=entries, exit=exits)
        matrix = build_market_matrix_from_signals(
            sliced, signals, entry_delay_bars=1, exit_delay_bars=1
        )
        result = BacktestEngine(repo=None).simulate_independent_market_matrix(matrix, 1, config)
        if any(v for k, v in result.stats["execution"].items() if k.startswith("buy_")):
            raise ValueError("Archived executable entry no longer fills")
        if len(result.trades) > 1:
            raise ValueError("Expected one independent entry")
        trade = asdict(result.trades[0]) if result.trades else None
        censored = trade is None or trade["exit_reason"] == "end"
        entry_price = float(sliced.open[1, 0])
        if censored:
            wealth = float(sliced.close[-1, 0]) / (entry_price * (1 + config.buy_cost_pct()))
        else:
            wealth = float(trade["exit_price"]) * (
                1 - config.sell_cost_pct(trade["exit_date"])
            ) / (entry_price * (1 + config.buy_cost_pct()))
        outcomes[arm] = {
            "entry_date": sliced.timestamp_labels[1][:10], "entry_price": round(entry_price, 4),
            "censored": censored, "endpoint_wealth": wealth,
            "trade": trade, "execution": result.stats["execution"],
        }
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=(
        ROOT / "docs/research/vcp/entry-pivot-exit-replacement-v1.json"
    ))
    protocol_path = parser.parse_args().protocol
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    variant = protocol["arms"][1]
    output = ROOT / "data/research/vcp" / protocol["experiment"]
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    (output / "replay.py").write_bytes(Path(__file__).read_bytes())
    directory = ROOT / "data/research/vcp/runs" / protocol["baseline_run"]

    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    def key(r):
        return tuple(r.get(k) for k in ("symbol", "entry_signal_date", "entry_date", "entry_signal_id"))

    trades = read("result.json")["trades"]
    structures = {key(r): r for r in read("entry-structure-evidence.json")["records"]}
    labels = {key(r): r for r in read("trade-path-analysis.json")["trades"]}
    assert len(trades) == len(structures) == len(labels) == 4396
    refs = [r for r in read("data-references.json")["files"]
            if Path(r["path"]).parts[0] == "kline_daily_enriched"
            and Path(r["path"]).parent.name.removeprefix("date=") <= protocol["training_data_end"]]
    for ref in refs:
        stat = (ROOT / "data" / ref["path"]).stat()
        if (stat.st_size, stat.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
            raise ValueError(f"Changed input: {ref['path']}")
    bars = pl.scan_parquet([str(ROOT / "data" / r["path"]) for r in refs]).select(
        "symbol", "date", "open", "high", "low", "close", "volume",
        "raw_close"
    ).filter(pl.col("symbol").is_in({t["symbol"] for t in trades})).collect()
    by_symbol = {}
    for trade in trades:
        by_symbol.setdefault(trade["symbol"], []).append(trade)
    all_market = build_market_data_matrix(bars, field_columns={"raw_close"})
    names = tuple(by_symbol[s][0].get("name", "") for s in all_market.symbols)
    up, down = _limit_lock_matrices(
        all_market.close, all_market.fields["raw_close"], np.isfinite(all_market.close),
        [date.fromisoformat(d[:10]) for d in all_market.timestamp_labels],
        list(all_market.symbols), list(names), {}, apply_latest_limits=False,
    )
    all_market = replace(all_market, names=names, limit_up_locked=up, limit_down_locked=down)
    del bars
    config = MatcherConfig(
        matching="open_t+1", commission_pct=0.0003, slippage_bps=10,
        stamp_tax_pct=0.0005, stamp_tax_policy="a_share_historical",
    )
    records = []
    for symbol, events in by_symbol.items():
        asset = all_market.symbols.index(symbol)
        market = replace(
            all_market, symbols=(symbol,), names=(names[asset],), _valid_bars=None,
            fields={}, **{field: getattr(all_market, field)[:, asset:asset + 1] for field in (
                "open", "high", "low", "close", "volume", "tradable",
                "limit_up_locked", "limit_down_locked",
            )},
        )
        date_index = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
        for trade in events:
            label = labels[key(trade)]
            start = date_index[trade["entry_signal_date"]]
            end = date_index[label["evaluation_horizon_end_date"]]
            outcome = replay_event(market, start, end, structures[key(trade)]["pivot"], config, variant)
            for arm in outcome.values():
                assert arm["entry_date"] == trade["entry_date"]
                assert abs(arm["entry_price"] - trade["entry_price"]) < 0.00011
                arm["excess"] = arm["endpoint_wealth"] / (1 + label["market_return_horizon"]) - 1
            records.append({
                "symbol": symbol, "signal_date": trade["entry_signal_date"],
                "entry_date": trade["entry_date"], "horizon_end": label["evaluation_horizon_end_date"],
                "horizon_mfe": label["horizon_mfe"], "arms": outcome,
            })
        if len(records) % 100 < len(events):
            print(f"replayed={len(records)}/4396", flush=True)
    (output / "records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"COMPLETED {len(records)} paired events: {output}", flush=True)


if __name__ == "__main__":
    main()
