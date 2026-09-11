"""Test market-adjusted strength on an unchanged frozen opportunity/outcome ledger."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from research_high52_cross_section import cohort_metrics, deciles, interval, summarize  # noqa: E402

from app.backtest.matrix import build_market_data_matrix  # noqa: E402


def adjacent_log_returns(close):
    close = np.asarray(close, dtype=np.float64)
    returns = np.full(close.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        simple = close[1:] / close[:-1] - 1
        good = ((close[1:] > 0) & (close[:-1] > 0) & np.isfinite(simple)
                & (np.abs(simple) <= .5))
        returns[1:] = np.where(good, np.log1p(simple), np.nan)
    return returns


def market_model_statistics(close, market_log, t, lookback=252, minimum_pairs=120):
    """OLS with intercept, using identical valid observations for all moments."""
    if t < lookback:
        raise ValueError("Invalid causal estimation window")
    history = np.asarray(close[t - lookback:t + 1], dtype=np.float64)
    y = adjacent_log_returns(history)[1:]
    x = np.asarray(market_log[t - lookback + 1:t + 1], dtype=np.float64)[:, None]
    good = np.isfinite(y) & np.isfinite(x)
    counts = good.sum(axis=0)
    safe_count = np.maximum(counts, 1)
    mean_x = np.where(good, x, 0).sum(axis=0) / safe_count
    mean_y = np.where(good, y, 0).sum(axis=0) / safe_count
    dx, dy = x - mean_x, y - mean_y
    variance = np.where(good, dx * dx, 0).sum(axis=0)
    covariance = np.where(good, dx * dy, 0).sum(axis=0)
    beta = np.full(close.shape[1], np.nan)
    np.divide(covariance, variance, out=beta, where=(counts >= minimum_pairs) & (variance > 1e-12))
    residual = dy - beta * dx
    total_sigma = np.sqrt(np.where(good, dy**2, 0).sum(axis=0) / np.maximum(counts - 1, 1))
    residual_sigma = np.sqrt(np.where(good, residual**2, 0).sum(axis=0) / np.maximum(counts - 2, 1))
    total_sigma[~np.isfinite(beta)] = np.nan
    residual_sigma[~np.isfinite(beta)] = np.nan
    return beta, counts, total_sigma, residual_sigma


def market_adjusted_scores(close, market_log, t, lookback=252, skip=21, minimum_pairs=120):
    """Market beta removal preserves intercept strength; all inputs end at t."""
    if not 0 < skip < lookback:
        raise ValueError("Invalid causal estimation window")
    beta, counts, _, _ = market_model_statistics(close, market_log, t, lookback, minimum_pairs)
    history = np.asarray(close[t - lookback:t + 1], dtype=np.float64)
    formation_market = market_log[t - lookback + 1:t - skip + 1]
    if not np.isfinite(formation_market).all():
        return np.full(close.shape[1], np.nan), beta, counts
    with np.errstate(divide="ignore", invalid="ignore"):
        log_momentum = np.log(history[-skip - 1] / history[0])
    score = log_momentum - beta * formation_market.sum()
    score[(history[0] <= 0) | (history[-skip - 1] <= 0)] = np.nan
    return score, beta, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "docs/research/momentum/market-adjusted-strength-train-v1.json")
    protocol_path = parser.parse_args().protocol
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    variant = protocol["variant"]
    if variant not in ("market_adjusted", "low_idiosyncratic"):
        raise ValueError(f"Unknown prespecified variant: {variant}")
    base = ROOT / "data/research/momentum" / protocol["baseline_experiment"]
    output = ROOT / "data/research" / protocol.get("output_family", "momentum") / protocol["experiment"]
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "research.py").write_bytes(Path(__file__).read_bytes())
    (output / "cohort_helpers.py").write_bytes((ROOT / "scripts/research_high52_cross_section.py").read_bytes())
    refs = json.loads((base / "data-references.json").read_text(encoding="utf-8"))
    for ref in refs:
        path = ROOT / "data" / ref["path"]
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
            raise ValueError(f"Changed frozen input: {path}")
        assert protocol["data_period"][0] <= path.parent.name.removeprefix("date=") <= protocol["data_period"][1]
    source_files = [base / name for name in ("opportunity-ledger.parquet", "months.json", "summary.json", "protocol.json")]
    manifest = [{"path": str(p.relative_to(ROOT)), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
                for p in source_files]
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "data-references.json").write_bytes((base / "data-references.json").read_bytes())
    (output / "baseline-summary.json").write_bytes((base / "summary.json").read_bytes())
    ledger = pl.read_parquet(base / "opportunity-ledger.parquet")
    old_months = json.loads((base / "months.json").read_text(encoding="utf-8"))
    old_summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    assert ledger.height == 284837 and ledger.filter(pl.col("eligible")).height == 191688
    assert ledger.select(pl.struct("symbol", "signal_date").n_unique()).item() == ledger.height
    bars = pl.scan_parquet([str(ROOT / "data" / r["path"]) for r in refs]).select(
        "symbol", "date", "open", "high", "low", "close",
    ).filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")).collect()
    market = build_market_data_matrix(bars)
    del bars
    daily_log = adjacent_log_returns(market.close)
    simple = np.expm1(daily_log)
    counts = np.isfinite(simple).sum(axis=1)
    market_log = np.log1p(np.nansum(simple, axis=1) / np.maximum(counts, 1))
    market_log[counts == 0] = np.nan
    del daily_log, simple
    time_ids = {d[:10]: i for i, d in enumerate(market.timestamp_labels)}
    asset_ids = {s: i for i, s in enumerate(market.symbols)}
    months, score_rows, missing = [], [], []
    previous = {}
    for old in old_months:
        day = old["signal_date"]
        pool = ledger.filter((pl.col("signal_date") == day) & pl.col("eligible"))
        rows = pool.to_dicts()
        ids = np.array([asset_ids[s] for s in pool["symbol"]])
        if variant == "market_adjusted":
            score, beta, observations = market_adjusted_scores(
                market.close, market_log, time_ids[day], protocol["lookback"], protocol["skip"],
                protocol["minimum_beta_observations"],
            )
        else:
            beta, observations, total_sigma, residual_sigma = market_model_statistics(
                market.close, market_log, time_ids[day], protocol["lookback"], protocol["minimum_beta_observations"],
            )
            score = -residual_sigma
        if not np.isfinite(score[ids]).all():
            missing.extend({"symbol": market.symbols[i], "signal_date": day,
                            "beta_observations": int(observations[i])}
                           for i in ids if not np.isfinite(score[i]))
            continue
        groups = deciles(score[ids])
        month = {k: v for k, v in old.items() if k not in ("high52", "momentum")}
        methods = [
            (variant, score[ids], groups),
            ("momentum", pool["momentum"].to_numpy(), pool["momentum_group"].to_numpy()),
        ]
        if variant == "low_idiosyncratic":
            total_groups = deciles(-total_sigma[ids])
            methods.append(("low_total", -total_sigma[ids], total_groups))
        for arm, values, bands in methods:
            month[arm], previous[arm] = cohort_metrics(
                rows, values, bands, old["broad_gross_return"], old["matched_net_return"], previous.get(arm),
            )
        assert month["momentum"] == old["momentum"], "Baseline cohort metrics changed"
        month["top_overlap_with_momentum"] = float(np.mean(pool["momentum_group"].to_numpy()[groups == 10] == 10))
        month["top_mean_beta"] = float(beta[ids][groups == 10].mean())
        month["momentum_top_mean_beta"] = float(beta[ids][pool["momentum_group"].to_numpy() == 10].mean())
        months.append(month)
        for j, i in enumerate(ids):
            row = {"symbol": market.symbols[i], "signal_date": day, variant: float(score[i]),
                   "beta": float(beta[i]), "beta_observations": int(observations[i]),
                   variant + "_group": int(groups[j])}
            if variant == "low_idiosyncratic":
                row.update(total_sigma=float(total_sigma[i]), residual_sigma=float(residual_sigma[i]),
                           low_total=float(-total_sigma[i]), low_total_group=int(total_groups[j]))
            score_rows.append(row)
    if missing:
        (output / "unavailable-scores.json").write_text(json.dumps(missing, indent=2), encoding="utf-8")
        raise ValueError(f"{len(missing)} scores unavailable; no partial-universe result accepted")
    assert len(months) == 82 and len(score_rows) == 191688
    scored = ledger.join(pl.DataFrame(score_rows), on=["symbol", "signal_date"], how="left", validate="1:1")
    assert scored.select(ledger.columns).sort("signal_date", "symbol").equals(ledger.sort("signal_date", "symbol"))
    scored.write_parquet(output / "scored-opportunity-ledger.parquet")
    (output / "months.json").write_text(json.dumps(months, indent=2, allow_nan=False), encoding="utf-8")
    report = summarize(months, protocol, variant=protocol["variant"])
    assert report["arms"]["momentum"] == old_summary["arms"]["momentum"]
    report["verification"] = {"full_opportunities": ledger.height, "eligible_scores": len(score_rows),
                              "baseline_metrics_unchanged": True, "outcome_columns_unchanged": True,
                              "matching_reexecuted": False, "maximum_endpoint": ledger["endpoint"].max()}
    report["mean_top_overlap_with_momentum"] = float(np.mean([m["top_overlap_with_momentum"] for m in months]))
    if variant == "low_idiosyncratic":
        control = summarize(months, protocol, variant="low_total")
        report["ordinary_low_volatility"] = control
        paired = interval([m[variant]["top_broad_excess"] - m["low_total"]["top_broad_excess"]
                           for m in months], protocol["statistics"])
        report["paired_improvement_over_ordinary_low_volatility"] = paired
        preferred = None
        if report["training_supported"] and (not control["training_supported"] or paired["ci95"][0] > 0):
            preferred = variant
        elif control["training_supported"]:
            preferred = "low_total"
        report["preferred_training_candidate"] = preferred
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
