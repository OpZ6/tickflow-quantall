"""Frozen matched-entry experiment: intact VCP pivot, pullback, then reclaim."""

import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from extract_vcp_entry_structure import _frozen_source_check  # noqa: E402
from research_high52_cross_section import replay_cohort  # noqa: E402

from app.backtest.engine import MatcherConfig  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    _limit_lock_matrices,
    build_market_data_matrix,
    slice_market_data_matrix,
)


def pullback_trigger(close, high, volume, tradable, pivot, watch=5):
    """Return the first completed confirmation bar, relative to breakout bar 0."""
    if not np.isfinite(pivot) or pivot <= 0 or close[0] < pivot:
        return None, "invalid_initial_pivot"
    pullback_high = None
    for i in range(1, min(watch + 1, len(close))):
        if not tradable[i] or not np.isfinite([close[i], high[i], volume[i]]).all():
            return None, "missing_observation"
        if close[i] < pivot:
            return None, "pivot_failed"
        if pullback_high is not None:
            if close[i] > pullback_high:
                return i, "confirmed"
        elif close[i] < close[i - 1] and volume[i] < volume[0]:
            pullback_high = high[i]
    return None, "no_reclaim" if pullback_high is not None else "no_pullback"


def replay_arm(market, signal, endpoint, config):
    if signal is None:
        return {"status": "no_trigger", "net_return": 0., "gross_return": 0.,
                "entry_date": None, "exit_date": None, "stale_mark": False,
                "mark_date": None, "exposure_sessions": 0}
    if endpoint - signal < 3:
        raise ValueError("Entry and exit must be separated by at least one full session")
    sliced = slice_market_data_matrix(market, signal, endpoint + 1)
    rows, _ = replay_cohort(sliced, np.ones(1, dtype=bool), config)
    row = rows[0]
    row["exposure_sessions"] = endpoint - signal - 1 if row["entry_date"] else 0
    return row


def benchmark_daily(bars):
    """Observed SH/SZ benchmark with no returns bridged over missing sessions."""
    dates = bars.select("date").unique().sort("date").with_row_index("session")
    frame = bars.join(dates, on="date").sort("symbol", "date").with_columns(
        pl.col("close").shift(1).over("symbol").alias("previous_close"),
        pl.col("session").shift(1).over("symbol").alias("previous_session"),
    ).with_columns(
        (pl.col("close") / pl.col("open") - 1).alias("oc"),
        pl.when(pl.col("session") == pl.col("previous_session") + 1)
        .then(pl.col("close") / pl.col("previous_close") - 1).alias("cc"),
        pl.when(pl.col("session") == pl.col("previous_session") + 1)
        .then(pl.col("open") / pl.col("previous_close") - 1).alias("co"),
    )
    return frame.group_by("date").agg(*[
        pl.col(c).filter(pl.col(c).is_finite() & pl.col(c).is_between(-.5, .5)).mean()
        for c in ("oc", "cc", "co")
    ]).sort("date")


def intervals(values, settings):
    """One row per market date, NaNs on no-event dates; same draws for all contrasts."""
    rng = np.random.default_rng(settings["seed"])
    block = settings["calendar_block_sessions"]
    samples = []
    for _ in range(settings["replicates"]):
        starts = rng.integers(len(values), size=int(np.ceil(len(values) / block)))
        ids = ((starts[:, None] + np.arange(block)) % len(values)).ravel()[:len(values)]
        samples.append(np.nanmean(values[ids], axis=0))
    samples = np.array(samples)
    means = np.nanmean(values, axis=0)
    alpha = .05 / settings["local_family_size"]
    return [{
        "mean": float(mean),
        "ci95": np.quantile(samples[:, i], [.025, .975]).tolist(),
        "local_adjusted_ci": np.quantile(samples[:, i], [alpha / 2, 1 - alpha / 2]).tolist(),
        "approx_p": float((1 + np.sum(np.abs(samples[:, i] - mean) >= abs(mean)))
                          / (len(samples) + 1)),
    } for i, mean in enumerate(means)]


def summarize(records, dates, protocol):
    arms = protocol["arms"]
    by_date = {}
    for row in records:
        by_date.setdefault(row["signal_date"], []).append(row)
    daily = []
    for day, rows in sorted(by_date.items()):
        item = {"date": day, "events": len(rows), "benchmark": rows[0]["benchmark"]}
        for arm in arms:
            item[arm] = float(np.mean([r["arms"][arm]["net_return"] for r in rows]))
        daily.append(item)
    calendar = [d for d in dates if daily[0]["date"] <= d <= daily[-1]["date"]]
    values = np.full((len(calendar), 3), np.nan)
    lookup = {d: i for i, d in enumerate(calendar)}
    for row in daily:
        values[lookup[row["date"]]] = [row["intact_pullback"] - row[x]
                                      for x in ("immediate", "wait_five", "benchmark")]
    inference = dict(zip(("vs_immediate", "vs_wait_five", "vs_broad"),
                         intervals(values, protocol["statistics"]), strict=True))
    summaries = {}
    yearly = {}
    for year in range(2016, 2023):
        group = [r for r in daily if r["date"].startswith(str(year))]
        yearly[str(year)] = {
            "signal_dates": len(group),
            **{arm: float(np.mean([r[arm] - r["benchmark"] for r in group])) for arm in arms},
            "paired_improvement": float(np.mean([
                r["intact_pullback"] - r["immediate"] for r in group
            ])),
        }
    for arm in arms:
        outcomes = [r["arms"][arm] for r in records]
        filled = [r for r in outcomes if r["entry_date"]]
        summaries[arm] = {
            "status": dict(Counter(r["status"] for r in outcomes)),
            "event_mean_net": float(np.mean([r["net_return"] for r in outcomes])),
            "date_mean_net": float(np.mean([r[arm] for r in daily])),
            "date_mean_broad_excess": float(np.mean([r[arm] - r["benchmark"] for r in daily])),
            "filled_mean_net": float(np.mean([r["net_return"] for r in filled])) if filled else None,
            "mean_exposure_sessions_per_opportunity": float(np.mean([
                r["exposure_sessions"] for r in outcomes
            ])),
            "stale_marks": sum(r["stale_mark"] for r in outcomes),
        }
    filled_dates = {r["signal_date"] for r in records if r["arms"]["intact_pullback"]["entry_date"]}
    filled = sum(bool(r["arms"]["intact_pullback"]["entry_date"]) for r in records)
    gates = protocol["gates"]
    checks = {
        "minimum_delayed_fills": filled >= gates["minimum_delayed_fills"],
        "minimum_delayed_fill_signal_dates": len(filled_dates) >= gates["minimum_delayed_fill_signal_dates"],
        "minimum_mean_paired_improvement": inference["vs_immediate"]["mean"] >= gates["minimum_mean_paired_improvement"],
        "minimum_positive_broad_years": sum(r["intact_pullback"] > 0 for r in yearly.values()) >= gates["minimum_positive_broad_years"],
        **{f"{key}_adjusted_ci_positive": r["local_adjusted_ci"][0] > 0 for key, r in inference.items()},
    }
    baseline_winners = [r for r in records if r["arms"]["immediate"]["net_return"] >= .10]
    zero_recovery = []
    for day in daily:
        rows = by_date[day["date"]]
        zero_recovery.append(np.mean([
            -1. if r["arms"]["intact_pullback"]["status"] == "censored"
            else r["arms"]["intact_pullback"]["net_return"] for r in rows
        ]) - day["benchmark"])
    return {
        "events": len(records), "signal_dates": len(daily), "calendar_sessions": len(calendar),
        "symbols": len({r["symbol"] for r in records}),
        "confirmation_reasons": dict(Counter(r["confirmation_reason"] for r in records)),
        "delayed_filled_signal_dates": len(filled_dates), "arms": summaries,
        "inference": inference, "yearly_broad_excess": yearly, "gates": checks,
        "baseline_10pct_winners": len(baseline_winners),
        "baseline_10pct_winners_missed": sum(not r["arms"]["intact_pullback"]["entry_date"]
                                            for r in baseline_winners),
        "delayed_zero_recovery_date_mean_broad_excess": float(np.mean(zero_recovery)),
        "entry_research_supported": all(checks.values()), "live_qualified": False,
        "decision": "retain_for_full_candidate_replay" if all(checks.values()) else "stop_representation_and_neighbors",
    }, daily


def main():
    protocol_path = ROOT / "docs/research/vcp/intact-pivot-pullback-entry-train-v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    output = ROOT / "data/research/vcp" / protocol["experiment"] / protocol["execution_attempt"]
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    directory = ROOT / "data/research/vcp/runs" / protocol["baseline_run"]
    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    def key(row):
        return tuple(row[k] for k in ("symbol", "entry_signal_date", "entry_date", "entry_signal_id"))

    trades = [r for r in read("result.json")["trades"]
              if r["entry_signal_id"] == "signal_quants_vcp_breakout"]
    structures = {key(r): r for r in read("entry-structure-evidence.json")["records"]}
    assert len(trades) == 4240 and len({key(r) for r in trades}) == 4240
    frames = []
    with ZipFile(ROOT / protocol["data_archive"]) as archive:
        members = sorted(n for n in archive.namelist()
                         if n.startswith("data/kline_daily_enriched/date=")
                         and n.endswith("/part.parquet")
                         and n.split("date=")[1][:10] <= protocol["training_data_end"])
        for n in members:
            frames.append(pl.read_parquet(BytesIO(archive.read(n)), columns=[
                "symbol", "date", "open", "high", "low", "close", "volume", "raw_close"
            ]))
    bars = pl.concat(frames).filter(
        pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")
    )
    del frames
    print(f"archived_training_partitions={len(members)} rows={bars.height}", flush=True)
    _frozen_source_check(directory)
    comparison = json.loads((output.parent / "execution-r2/archive-structure-comparison.json")
                            .read_text(encoding="utf-8"))
    assert not comparison["failures"]
    assert comparison["metrics"]["max_normalized_pivot_error"] < .0002
    assert comparison["metrics"]["max_dry_volume_error"] == 0
    reconstructed = comparison["records"]
    assert len(reconstructed) == len(trades)
    archive_structures = {key(r): r for r in reconstructed}
    assert set(archive_structures) == {key(t) for t in trades}
    for row in reconstructed:
        old = structures[key(row)]
        for field in ("scale", "setup",
                      "reconstructed_entry_allowed", "pretrigger_dry_volume_ratio"):
            assert row[field] == old[field], (key(row), field, row[field], old[field])
    (output / "input-verification.json").write_text(json.dumps({
        "archive": protocol["data_archive"], "training_partitions": len(members),
        "first_date": str(bars["date"].min()), "last_date": str(bars["date"].max()),
        "reconstructed_original_structure_identities_equal": len(reconstructed),
        "price_basis_comparison": comparison["metrics"],
        "original_detector_source_equal": True,
    }, indent=2), encoding="utf-8")
    print("all_original_pivots_and_structure_inputs_verified", flush=True)
    benchmark = benchmark_daily(bars)
    benchmark.write_parquet(output / "benchmark.parquet")
    names_by_symbol = {t["symbol"]: t["name"] for t in trades}
    market = build_market_data_matrix(bars.filter(pl.col("symbol").is_in(names_by_symbol)),
                                      field_columns={"raw_close"})
    del bars
    dates = [d[:10] for d in market.timestamp_labels]
    assert dates == [d.isoformat() for d in benchmark["date"]]
    names = tuple(names_by_symbol[s] for s in market.symbols)
    up, down = _limit_lock_matrices(
        market.close, market.fields["raw_close"], np.isfinite(market.close),
        [date.fromisoformat(d) for d in dates], list(market.symbols), list(names), {},
        apply_latest_limits=False,
    )
    market = replace(market, names=names, limit_up_locked=up, limit_down_locked=down)
    config = MatcherConfig(matching="open_t+1", **protocol["cost"])
    date_index = {d: i for i, d in enumerate(dates)}
    oc, cc, co = (benchmark[c].to_numpy() for c in ("oc", "cc", "co"))
    by_symbol = {}
    for trade in trades:
        by_symbol.setdefault(trade["symbol"], []).append(trade)
    records = []
    for symbol, events in by_symbol.items():
        aid = market.symbols.index(symbol)
        single = replace(market, symbols=(symbol,), names=(names[aid],), _valid_bars=None,
                         fields={}, **{field: getattr(market, field)[:, aid:aid + 1] for field in (
                             "open", "high", "low", "close", "volume", "tradable",
                             "limit_up_locked", "limit_down_locked",
                         )})
        for trade in events:
            start = date_index[trade["entry_signal_date"]]
            end = start + protocol["endpoint_session_offset"]
            assert dates[end] <= protocol["training_data_end"]
            pivot = archive_structures[key(trade)]["pivot"]
            confirm, reason = pullback_trigger(
                single.close[start:, 0], single.high[start:, 0], single.volume[start:, 0],
                single.tradable[start:, 0], pivot, protocol["rule"]["watch_sessions"],
            )
            signals = {"immediate": start, "intact_pullback": start + confirm if confirm else None,
                       "wait_five": start + protocol["rule"]["watch_sessions"]}
            outcomes = {arm: replay_arm(single, signal, end, config) for arm, signal in signals.items()}
            assert outcomes["immediate"]["entry_date"] == trade["entry_date"]
            old_pivot = structures[key(trade)]["pivot"]
            price_scale = float(single.open[start + 1, 0]) / trade["entry_price"]
            assert abs(pivot / price_scale / old_pivot - 1) < .0002
            broad = (1 + oc[start + 1]) * np.prod(1 + cc[start + 2:end]) * (1 + co[end]) - 1
            assert np.isfinite(broad)
            records.append({"symbol": symbol, "signal_date": dates[start], "endpoint": dates[end],
                            "pivot": pivot, "confirmation_offset": confirm,
                            "confirmation_reason": reason, "benchmark": float(broad), "arms": outcomes})
        if len(records) % 250 < len(events):
            print(f"replayed={len(records)}/4240", flush=True)
    (output / "records.json").write_text(json.dumps(records, indent=2, allow_nan=False), encoding="utf-8")
    report, daily = summarize(records, dates, protocol)
    (output / "daily.json").write_text(json.dumps(daily, indent=2, allow_nan=False), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
