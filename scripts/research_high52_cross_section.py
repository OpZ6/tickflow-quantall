"""Frozen monthly cross-sectional high-anchor experiment using the existing matcher."""

import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backtest.engine import BacktestEngine, MatcherConfig, SimulationOptions  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    _limit_lock_matrices,
    build_market_data_matrix,
    build_market_matrix_from_signals,
    make_signal_matrix,
    slice_market_data_matrix,
    valid_shift,
)


def scores(close, high, t, lookback=252, skip=21):
    """All feature inputs end on the decision date, on the market calendar."""
    if t < lookback:
        raise ValueError("Insufficient market history")
    past = close[t - lookback + 1:t + 1]
    highs = high[t - lookback + 1:t + 1]
    count = (np.isfinite(past) & (past > 0)).sum(axis=0)
    maximum = np.max(np.where(np.isfinite(highs) & (highs > 0), highs, -np.inf), axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return close[t] / maximum, close[t - skip] / close[t - lookback] - 1, count


def deciles(values):
    ranks = pl.Series(values).rank("average").to_numpy()
    return np.ceil(ranks / len(values) * 10).clip(1, 10).astype(int)


def rank_ic(x, y):
    a = pl.Series(x).rank("average").to_numpy()
    b = pl.Series(y).rank("average").to_numpy()
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def replay_cohort(market, universe, config):
    """One frozen allocation per symbol; unfilled cash never changes ranks."""
    entry = np.zeros(market.shape, dtype=bool)
    exits = np.zeros_like(entry)
    entry[0] = universe
    exits[-2] = universe
    matrix = build_market_matrix_from_signals(
        market, make_signal_matrix(market.shape, entry=entry, exit=exits),
        entry_delay_bars=1, exit_delay_bars=1,
    )
    result = BacktestEngine(repo=None).simulate_independent_market_matrix(
        matrix, int(universe.sum()), config,
        options=SimulationOptions(include_monte_carlo=False, include_curves=False,
                                  include_per_symbol_stats=False, include_return_distribution=False),
    )
    trades = {trade.symbol: trade for trade in result.trades}
    assert len(trades) == len(result.trades)
    prices = np.array([market.open[1], market.high[1], market.low[1], market.close[1]])
    flat = np.all(np.isfinite(prices) & (prices > 0), axis=0) & (
        np.max(prices, axis=0) - np.min(prices, axis=0)
        <= np.maximum(np.abs(market.close[1]) * 1e-4, .01)
    )
    bought = (matrix.entry[1].astype(bool) & market.tradable[1].astype(bool)
              & np.isfinite(market.open[1]) & (market.open[1] > 0)
              & ~(flat & market.limit_up_locked[1].astype(bool)))
    rejected = sum(v for k, v in result.stats["execution"].items() if k.startswith("buy_"))
    assert int(universe.sum() - bought.sum()) == rejected
    rows = []
    for aid in np.flatnonzero(universe):
        symbol = market.symbols[aid]
        trade = trades.get(symbol)
        row = {"symbol": symbol, "status": "unfilled", "net_return": 0.,
               "gross_return": 0., "stale_mark": False, "exit_date": None,
               "entry_date": None, "mark_date": None}
        if bought[aid]:
            entry_price = float(market.open[1, aid])
            row["entry_date"] = market.timestamp_labels[1][:10]
            if trade is not None and trade.exit_reason == "signal":
                assert trade.entry_date == row["entry_date"]
                assert trade.exit_date == market.timestamp_labels[-1][:10]
                gross = float(market.open[-1, aid]) / entry_price
                net = gross * (1 - config.sell_cost_pct(trade.exit_date)) / (1 + config.buy_cost_pct())
                assert abs(net - 1 - trade.pnl_pct) <= 1e-6
                row.update(status="sold", exit_date=trade.exit_date)
            else:
                valid = np.flatnonzero(np.isfinite(market.close[:, aid]) & (market.close[:, aid] > 0))
                last = int(valid[-1])
                gross = float(market.close[last, aid]) / entry_price
                net = gross / (1 + config.buy_cost_pct())
                row.update(status="censored", stale_mark=last < market.shape[0] - 1,
                           mark_date=market.timestamp_labels[last][:10])
            row.update(net_return=net - 1, gross_return=gross - 1)
        else:
            assert trade is None
        rows.append(row)
    return rows, result.stats["execution"]


def interval(values, settings):
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(settings["seed"])
    block = settings["bootstrap_block_months"]
    samples = []
    for _ in range(settings["replicates"]):
        starts = rng.integers(len(values), size=int(np.ceil(len(values) / block)))
        ids = ((starts[:, None] + np.arange(block)) % len(values)).ravel()[:len(values)]
        samples.append(float(values[ids].mean()))
    lower, upper = np.quantile(samples, [.025, .975])
    p = (1 + np.sum(np.abs(np.array(samples) - values.mean()) >= abs(values.mean()))) / (len(samples) + 1)
    return {"mean": float(values.mean()), "ci95": [float(lower), float(upper)], "p": float(p)}


def cohort_metrics(rows, values, groups, broad_return, matched_return, previous_set=None):
    net = np.array([r["net_return"] for r in rows])
    means = [float(net[groups == g].mean()) for g in range(1, 11)]
    if not np.isfinite(means).all():
        raise ValueError("Empty signal-date group")
    selected = [r for i, r in enumerate(rows) if groups[i] == 10]
    selected_set = {r["symbol"] for r in selected}
    conservative = float(np.mean([-1. if r["status"] == "censored" else r["net_return"] for r in selected]))
    return {
        "group_net_returns": means,
        "group_gross_returns": [float(np.mean([r["gross_return"] for i, r in enumerate(rows)
                                               if groups[i] == g])) for g in range(1, 11)],
        "top_net_return": means[-1], "top_candidates": len(selected),
        "top_broad_excess": (1 + means[-1]) / (1 + broad_return) - 1,
        "top_matched_excess": (1 + means[-1]) / (1 + matched_return) - 1,
        "top_bottom_spread": means[-1] - means[0], "rank_ic": rank_ic(values, net),
        "top_status": {s: sum(r["status"] == s for r in selected) for s in ("sold", "unfilled", "censored")},
        "top_stale_marks": sum(r["stale_mark"] for r in selected),
        "top_zero_recovery_excess": (1 + conservative) / (1 + broad_return) - 1,
        "selected_set_replacement": (1 - len(selected_set & previous_set) / len(selected_set))
        if previous_set is not None else None,
    }, selected_set


def summarize(months, protocol, variant="high52"):
    report = {"experiment": protocol["experiment"], "months": len(months), "arms": {}}
    for arm in (variant, "momentum"):
        items = [m[arm] for m in months]
        annual = {}
        for year in sorted({m["signal_date"][:4] for m in months}):
            subset = [m[arm] for m in months if m["signal_date"].startswith(year)]
            annual[year] = {field: float(np.mean([r[field] for r in subset])) for field in (
                "top_broad_excess", "top_matched_excess", "rank_ic", "top_net_return",
            )}
        report["arms"][arm] = {
            "top_broad_excess": interval([m["top_broad_excess"] for m in items], protocol["statistics"]),
            "top_matched_excess": interval([m["top_matched_excess"] for m in items], protocol["statistics"]),
            "mean_rank_ic": float(np.mean([m["rank_ic"] for m in items])),
            "top_bottom_spread": float(np.mean([m["top_bottom_spread"] for m in items])),
            "group_net_returns": [float(np.mean([m["group_net_returns"][i] for m in items])) for i in range(10)],
            "top_candidates": sum(m["top_candidates"] for m in items),
            "top_status": {status: sum(m["top_status"][status] for m in items)
                           for status in ("sold", "unfilled", "censored")},
            "top_stale_marks": sum(m["top_stale_marks"] for m in items),
            "top_zero_recovery_excess": float(np.mean([m["top_zero_recovery_excess"] for m in items])),
            "mean_selected_set_replacement": float(np.mean([m["selected_set_replacement"] for m in items[1:]])),
            "annual": annual,
        }
    report["paired_improvement"] = interval(
        [m[variant]["top_broad_excess"] - m["momentum"]["top_broad_excess"] for m in months],
        protocol["statistics"],
    )
    g, arm = protocol["training_gates"], report["arms"][variant]
    report["checks"] = {
        "months": len(months) >= g["minimum_months"],
        "top_candidates": arm["top_candidates"] >= g["minimum_top_candidates"],
        "broad_excess": arm["top_broad_excess"]["mean"] > g["minimum_top_broad_excess"],
        "matched_excess": arm["top_matched_excess"]["mean"] > g["minimum_top_matched_excess"],
        "positive_years": sum(a["top_broad_excess"] > 0 for a in arm["annual"].values()) >= g["minimum_positive_years"],
        "top_bottom_spread": arm["top_bottom_spread"] >= g["minimum_top_bottom_spread"],
        "rank_ic": arm["mean_rank_ic"] > g["minimum_mean_rank_ic"],
        "paired_improvement": report["paired_improvement"]["mean"] > g["minimum_paired_improvement"],
        "broad_ci_positive": arm["top_broad_excess"]["ci95"][0] > 0,
        "paired_ci_positive": report["paired_improvement"]["ci95"][0] > 0,
    }
    report.update(training_supported=all(report["checks"].values()), live_qualified=False,
                  temporal_test_inspected=False, account_curve_available=False,
                  execution_scope="historical daily proxy; ST/issuer lifecycle incomplete")
    return report


def main():
    protocol_path = ROOT / "docs/research/momentum/high52-cross-section-train-v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    output = ROOT / "data/research/momentum" / protocol["experiment"]
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "research.py").write_bytes(Path(__file__).read_bytes())
    refpath = ROOT / "data/research/vcp/runs" / protocol["baseline_data_reference_run"] / "data-references.json"
    refs = [r for r in json.loads(refpath.read_text(encoding="utf-8"))["files"]
            if Path(r["path"]).parts[0] == "kline_daily_enriched"
            and protocol["data_start"] <= Path(r["path"]).parent.name.removeprefix("date=") <= protocol["data_end"]]
    for ref in refs:
        stat = (ROOT / "data" / ref["path"]).stat()
        if (stat.st_size, stat.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
            raise ValueError(f"Changed input: {ref['path']}")
    (output / "data-references.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")
    bars = pl.scan_parquet([str(ROOT / "data" / r["path"]) for r in refs]).select(
        "symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "amount",
    ).filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")).collect()
    market = build_market_data_matrix(bars, field_columns={"raw_close", "amount"})
    del bars
    dates = [d[:10] for d in market.timestamp_labels]
    valid = np.isfinite(market.close) & (market.close > 0)
    up, down = _limit_lock_matrices(market.close, market.fields["raw_close"], valid,
                                   [date.fromisoformat(d) for d in dates], list(market.symbols),
                                   [""] * len(market.symbols), {}, apply_latest_limits=False)
    # Unknown historical ST status: conservatively block one-price directional moves too.
    previous = valid_shift(market.close, 1, valid, bar_index=market.valid_bars)
    with np.errstate(divide="ignore", invalid="ignore"):
        daily_return = market.close / previous - 1
    market = replace(market, limit_up_locked=up | (daily_return >= .045),
                     limit_down_locked=down | (daily_return <= -.045))
    del previous, daily_return
    config = MatcherConfig(matching="open_t+1", **protocol["costs"])
    calendar = [i for i in range(protocol["lookback"], len(dates) - protocol["horizon"] - 1)
                if dates[i] >= protocol["signal_start"] and dates[i][:7] != dates[i + 1][:7]]
    all_rows, months = [], []
    previous_sets = {}
    for number, t in enumerate(calendar, 1):
        anchor, momentum, count = scores(market.close, market.high, t, protocol["lookback"], protocol["skip"])
        broad = valid[t] & market.tradable[t].astype(bool) & (market.volume[t] > 0)
        raw = market.fields["raw_close"][t]
        eligible = (broad & (raw >= 3) & (raw <= 300) & (market.fields["amount"][t] >= 20_000_000)
                    & np.isfinite(anchor) & (anchor > 0) & np.isfinite(momentum)
                    & valid[t - protocol["lookback"]] & valid[t - protocol["skip"]]
                    & (count >= protocol["minimum_observations"]))
        ids = np.flatnonzero(eligible)
        assert len(ids) >= 100, f"Insufficient cross-section {dates[t]}"
        group_ids = {"high52": deciles(anchor[ids]), "momentum": deciles(momentum[ids])}
        # Signal eligibility and both group assignments are now fixed, before replay.
        end = t + 1 + protocol["horizon"]
        sliced = slice_market_data_matrix(market, t, end + 1)
        rows, execution = replay_cohort(sliced, broad, config)
        by_symbol = {row["symbol"]: row for row in rows}
        eligible_rows = [by_symbol[market.symbols[i]] for i in ids]
        net = np.array([r["net_return"] for r in eligible_rows])
        broad_return = float(np.mean([r["gross_return"] for r in rows]))
        matched_return = float(net.mean())
        month = {"signal_date": dates[t], "entry_date": dates[t + 1], "endpoint": dates[end],
                 "broad_count": len(rows), "eligible_count": len(ids),
                 "broad_gross_return": broad_return, "matched_net_return": matched_return,
                 "execution": execution}
        for arm, values in (("high52", anchor[ids]), ("momentum", momentum[ids])):
            month[arm], previous_sets[arm] = cohort_metrics(
                eligible_rows, values, group_ids[arm], broad_return, matched_return,
                previous_sets.get(arm),
            )
        for i, row in enumerate(eligible_rows):
            row.update(eligible=True, high52=float(anchor[ids[i]]), momentum=float(momentum[ids[i]]),
                       high52_group=int(group_ids["high52"][i]), momentum_group=int(group_ids["momentum"][i]),
                       signal_raw_close=float(raw[ids[i]]),
                       signal_amount=float(market.fields["amount"][t, ids[i]]))
        for row in rows:
            row.setdefault("eligible", False)
            row.update(signal_date=dates[t], endpoint=dates[end])
        all_rows.extend(rows)
        months.append(month)
        print(f"cohort={number}/{len(calendar)} signal={dates[t]} eligible={len(ids)}", flush=True)
    pl.DataFrame(all_rows, infer_schema_length=None).write_parquet(output / "opportunity-ledger.parquet")
    (output / "months.json").write_text(json.dumps(months, indent=2, allow_nan=False), encoding="utf-8")
    report = summarize(months, protocol)
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
