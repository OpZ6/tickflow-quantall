"""Actual same-day VCP selector from the retained pre-breakout volume hypothesis."""
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

from extract_vcp_entry_structure import _defaults, _frozen_source_check  # noqa: E402
from research_high52_cross_section import rank_ic, replay_cohort  # noqa: E402
from research_vcp_intact_pullback import intervals  # noqa: E402

from app.backtest.engine import MatcherConfig  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    _limit_lock_matrices,
    build_market_data_matrix,
    slice_market_data_matrix,
)
from app.strategy.builtin._quants_vcp import QuantsLegacyVcpStrategy  # noqa: E402


def volume_ratio(prior_volume):
    """Caller supplies only bars strictly preceding the completed signal."""
    v = np.asarray(prior_volume[-40:], dtype=float)
    if len(v) != 40 or not (np.isfinite(v) & (v > 0)).all():
        return np.nan
    return float(v[-10:].mean() / v[:30].mean())


def select_dry_half(ratios):
    ratios = np.asarray(ratios, dtype=float)
    valid = np.isfinite(ratios) & (ratios > 0)
    selected = np.zeros(len(ratios), dtype=bool)
    if valid.any():
        selected[valid] = ratios[valid] <= np.median(ratios[valid])
    return valid, selected


def main():
    protocol_path = ROOT / "docs/research/vcp/prebreakout-volume-selection-train-v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    output = ROOT / "data/research/vcp" / protocol["experiment"]
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    source = ROOT / "data/research/vcp/runs" / protocol["baseline_run"]
    _frozen_source_check(source)
    config_source = json.loads((source / "config.json").read_text(encoding="utf-8"))
    symbols = set(config_source["symbols"])
    params = _defaults(source)
    frames = []
    with ZipFile(ROOT / protocol["data_archive"]) as z:
        for n in z.namelist():
            if (n.startswith("data/kline_daily_enriched/date=") and n.endswith("/part.parquet")
                    and n.split("date=")[1][:10] <= protocol["training_data_end"]):
                frames.append(pl.read_parquet(BytesIO(z.read(n)), columns=[
                    "symbol", "date", "open", "high", "low", "close", "volume", "raw_close"
                ]).filter(pl.col("symbol").is_in(symbols)))
    market = build_market_data_matrix(pl.concat(frames), field_columns={"raw_close"})
    del frames
    dates = [d[:10] for d in market.timestamp_labels]
    source_trades = json.loads((source / "result.json").read_text(encoding="utf-8"))["trades"]
    known_names = {r["symbol"]: r["name"] for r in source_trades}
    names = tuple(known_names.get(s, "") for s in market.symbols)
    up, down = _limit_lock_matrices(market.close, market.fields["raw_close"], np.isfinite(market.close),
                                   [date.fromisoformat(d) for d in dates], list(market.symbols),
                                   list(names), {}, apply_latest_limits=False)
    market = replace(market, names=names, limit_up_locked=up, limit_down_locked=down)
    last = dates.index(protocol["signal_period"][1])
    print(f"reconstructing_complete_signals shape={market.shape}", flush=True)
    signals = QuantsLegacyVcpStrategy().compute_signals(slice_market_data_matrix(market, 0, last + 1), params)
    print(f"signals_computed raw_entries={int(signals.entry.sum())}", flush=True)
    observations = [np.flatnonzero(np.isfinite(market.close[:, a])) for a in range(market.shape[1])]
    candidates = []
    for t, a in np.argwhere(signals.entry.astype(bool) & (signals.entry_signal_code == 0)):
        if not protocol["signal_period"][0] <= dates[t] <= protocol["signal_period"][1]:
            continue
        ids = observations[a]
        preceding = ids[ids < t]
        candidates.append({"symbol": market.symbols[a], "signal_date": dates[t], "t": int(t),
                           "asset": int(a), "volume_dry_ratio": volume_ratio(market.volume[preceding, a])})
    del signals, observations
    by_date = {}
    for row in candidates:
        by_date.setdefault(row["signal_date"], []).append(row)
    for rows in by_date.values():
        valid, selected = select_dry_half([r["volume_dry_ratio"] for r in rows])
        for r, v, s in zip(rows, valid, selected, strict=True):
            r.update(feature_valid=bool(v), selected=bool(s))
    pl.DataFrame(candidates).write_parquet(output / "frozen-candidates.parquet")
    print(f"frozen_candidates={len(candidates)} dates={len(by_date)}", flush=True)
    evaluate_selection(market, candidates, protocol, output)


def evaluate_selection(market, candidates, protocol, output,
                       score_field="volume_dry_ratio", score_direction=-1):
    """Shared fixed-cost replay and date-level comparison for the two selectors."""
    dates = [d[:10] for d in market.timestamp_labels]
    by_date = {}
    for row in candidates:
        by_date.setdefault(row["signal_date"], []).append(row)
    benchmark = pl.read_parquet(ROOT / "data/research/vcp/intact-pivot-pullback-entry-train-v1/execution-r3/benchmark.parquet")
    assert dates == [d.isoformat() for d in benchmark["date"]]
    oc, cc, co = (benchmark[c].to_numpy() for c in ("oc", "cc", "co"))
    config = MatcherConfig(matching="open_t+1", commission_pct=.0003, slippage_bps=10,
                           stamp_tax_policy="a_share_historical")
    ledger, daily = [], []
    previous = None
    for number, (day, rows) in enumerate(sorted(by_date.items()), 1):
        t = rows[0]["t"]
        mask = np.zeros(market.shape[1], dtype=bool)
        mask[[r["asset"] for r in rows]] = True
        outcomes, _ = replay_cohort(slice_market_data_matrix(market, t, t + 12), mask, config)
        lookup = {r["symbol"]: r for r in outcomes}
        for r in rows:
            r.update(lookup[r["symbol"]], endpoint=dates[t + 11])
            ledger.append(r)
        valid = [r for r in rows if r["feature_valid"]]
        selected = [r for r in valid if r["selected"]]
        rejected = [r for r in valid if not r["selected"]]
        if not valid:
            continue
        broad = float((1 + oc[t + 1]) * np.prod(1 + cc[t + 2:t + 11]) * (1 + co[t + 11]) - 1)
        scores, returns = (np.array([score_direction * r[score_field] for r in valid]),
                           np.array([r["net_return"] for r in valid]))
        current = {r["symbol"] for r in selected}
        daily.append({"date": day, "candidates": len(valid), "selected_count": len(selected),
                      "selected": float(np.mean([r["net_return"] for r in selected])),
                      "all": float(returns.mean()), "broad": broad,
                      "rejected": float(np.mean([r["net_return"] for r in rejected])) if rejected else None,
                      "ic": rank_ic(scores, returns) if np.std(scores) > 0 and np.std(returns) > 0 else None,
                      "replacement": 1 - len(current & previous) / len(previous) if previous else None,
                      "zero_recovery_selected": float(np.mean([
                          -1. if r["status"] == "censored" else r["net_return"] for r in selected]))})
        previous = current
        if number % 200 == 0:
            print(f"replayed_dates={number}/{len(by_date)}", flush=True)
    pl.DataFrame(ledger, infer_schema_length=None).write_parquet(output / "ledger.parquet")
    (output / "daily.json").write_text(json.dumps(daily, indent=2), encoding="utf-8")
    calendar = [d for d in dates if daily[0]["date"] <= d <= daily[-1]["date"]]
    values = np.full((len(calendar), 2), np.nan)
    index = {d: i for i, d in enumerate(calendar)}
    for r in daily:
        values[index[r["date"]]] = [r["selected"] - r["all"], r["selected"] - r["broad"]]
    inference = dict(zip(("vs_all", "vs_broad"), intervals(values, protocol["statistics"]), strict=True))
    yearly = {}
    for year in range(2016, 2023):
        group = [r for r in daily if r["date"].startswith(str(year))]
        yearly[str(year)] = {"dates": len(group), "paired": float(np.mean([r["selected"] - r["all"] for r in group])),
                             "broad_excess": float(np.mean([r["selected"] - r["broad"] for r in group]))}
    selected = [r for r in ledger if r["selected"]]
    informative = sum(r["rejected"] is not None for r in daily)
    mean_ic = float(np.mean([r["ic"] for r in daily if r["ic"] is not None]))
    g = protocol["gates"]
    checks = {"selected_sample": len(selected) >= g["minimum_selected"],
              "informative_dates": informative >= g["minimum_informative_dates"],
              "paired_improvement": inference["vs_all"]["mean"] >= g["minimum_paired_improvement"],
              "positive_broad_years": sum(r["broad_excess"] > 0 for r in yearly.values()) >= g["minimum_positive_broad_years"],
              "positive_paired_years": sum(r["paired"] > 0 for r in yearly.values()) >= g["minimum_positive_paired_years"],
              "mean_ic_positive": mean_ic > 0,
              **{f"{k}_adjusted_ci_positive": r["local_adjusted_ci"][0] > 0 for k, r in inference.items()}}
    report = {"candidates": len(ledger), "missing_features": sum(not r["feature_valid"] for r in ledger),
              "selected": len(selected), "signal_dates": len(daily), "informative_dates": informative,
              "mean_daily_ic": mean_ic, "ic_dates": sum(r["ic"] is not None for r in daily),
              "selected_status": dict(Counter(r["status"] for r in selected)),
              "all_status": dict(Counter(r["status"] for r in ledger)),
              "date_mean_net": {k: float(np.mean([r[k] for r in daily])) for k in ("selected", "all", "broad")},
              "inference": inference, "yearly": yearly, "gates": checks,
              "mean_set_replacement": float(np.mean([r["replacement"] for r in daily if r["replacement"] is not None])),
              "zero_recovery_broad_excess": float(np.mean([r["zero_recovery_selected"] - r["broad"] for r in daily])),
              "training_supported": all(checks.values()), "live_qualified": False}
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
