"""Research low turnover on the frozen monthly opportunity/outcome ledger."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from research_high52_cross_section import cohort_metrics, deciles, interval, summarize  # noqa: E402


def turnover_scores(history, t, lookback=252, minimum_observations=200):
    """Negative mean percent turnover; missing sessions stay missing, never zero."""
    if not 1 <= minimum_observations <= lookback or not lookback - 1 <= t < len(history):
        raise ValueError("Invalid causal turnover window")
    window = np.asarray(history[t - lookback + 1:t + 1], dtype=np.float64)
    valid = np.isfinite(window) & (window >= 0)
    counts = valid.sum(axis=0)
    score = np.full(history.shape[1], np.nan)
    np.divide(-np.where(valid, window, 0).sum(axis=0), counts, out=score,
              where=counts >= minimum_observations)
    return score, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=ROOT / "docs/research/liquidity/low-turnover-cross-section-train-v1.json")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    base = ROOT / "data/research/momentum" / protocol["baseline_experiment"]
    output = ROOT / "data/research/liquidity" / protocol["experiment"]
    output.mkdir(parents=True, exist_ok=False)
    for name, path in (("protocol.json", args.protocol), ("research.py", Path(__file__)),
                       ("cohort_helpers.py", ROOT / "scripts/research_high52_cross_section.py"),
                       ("data-references.json", base / "data-references.json")):
        (output / name).write_bytes(path.read_bytes())
    refs = json.loads((base / "data-references.json").read_text(encoding="utf-8"))
    for ref in refs:
        stat = (ROOT / "data" / ref["path"]).stat()
        assert (stat.st_size, stat.st_mtime_ns) == (ref["size"], ref["mtime_ns"])
    dates = sorted({Path(r["path"]).parent.name.removeprefix("date=") for r in refs})
    ledger = pl.read_parquet(base / "opportunity-ledger.parquet")
    old_months = json.loads((base / "months.json").read_text(encoding="utf-8"))
    old_summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    low_vol_path = ROOT / protocol["frozen_low_volatility_reference"]
    low_vol_months = json.loads(low_vol_path.read_text(encoding="utf-8"))
    assert ledger.height == 284837 and ledger.filter(pl.col("eligible")).height == 191688
    assert len(old_months) == len(low_vol_months) == 82
    last_signal = old_months[-1]["signal_date"]
    calendar = pl.DataFrame({"date": [date.fromisoformat(d) for d in dates if d <= last_signal]})
    # This is an isolated research snapshot, not a production data-source route.
    with duckdb.connect(str(args.source), read_only=True) as connection:
        daily = connection.execute("""
            SELECT ts_code AS symbol, trade_date AS date, turnover_rate AS turnover_pct,
                   source_name, updated_at
            FROM dwd_daily_basic
            WHERE trade_date BETWEEN ? AND ?
              AND (ends_with(ts_code, '.SH') OR ends_with(ts_code, '.SZ'))
            ORDER BY trade_date, ts_code
        """, [dates[0], last_signal]).pl().join(calendar, on="date", how="semi")
    assert daily.select(pl.struct("symbol", "date").n_unique()).item() == daily.height
    assert daily["source_name"].unique().to_list() == [protocol["source_name"]]
    daily.write_parquet(output / "turnover-input.parquet")
    sources = [args.source, base / "opportunity-ledger.parquet", base / "months.json",
               base / "summary.json", low_vol_path]
    provenance = {"sources": [{"path": str(p), "size": p.stat().st_size,
                               "mtime_ns": p.stat().st_mtime_ns} for p in sources],
                  "snapshot_rows": daily.height, "minimum_date": str(daily["date"].min()),
                  "maximum_date": str(daily["date"].max()),
                  "updated_at_min": str(daily["updated_at"].min()),
                  "updated_at_max": str(daily["updated_at"].max()),
                  "unit": "percent points", "quality_level": "reconstructed"}
    (output / "source-manifest.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    symbols = sorted(daily["symbol"].unique().to_list())
    time_ids = {d: i for i, d in enumerate(dates)}
    asset_ids = {s: i for i, s in enumerate(symbols)}
    matrix = np.full((len(dates), len(symbols)), np.nan)
    positioned = daily.with_columns(
        pl.col("date").cast(pl.String).replace_strict(time_ids).alias("t"),
        pl.col("symbol").replace_strict(asset_ids).alias("i"),
    )
    matrix[positioned["t"].to_numpy(), positioned["i"].to_numpy()] = positioned["turnover_pct"].to_numpy()
    months, score_rows, missing, previous = [], [], [], {}
    for old, low_vol in zip(old_months, low_vol_months, strict=True):
        day = old["signal_date"]
        assert low_vol["signal_date"] == day
        pool = ledger.filter((pl.col("signal_date") == day) & pl.col("eligible"))
        ids = np.array([asset_ids[s] for s in pool["symbol"]])
        scores, counts = turnover_scores(matrix, time_ids[day], protocol["lookback"], protocol["minimum_observations"])
        if not np.isfinite(scores[ids]).all():
            missing.extend({"symbol": symbols[i], "signal_date": day, "observations": int(counts[i])}
                           for i in ids if not np.isfinite(scores[i]))
            continue
        groups = deciles(scores[ids])
        month = {k: v for k, v in old.items() if k not in ("high52", "momentum")}
        for arm, values, bands in (("low_turnover", scores[ids], groups),
                                   ("momentum", pool["momentum"].to_numpy(), pool["momentum_group"].to_numpy())):
            month[arm], previous[arm] = cohort_metrics(
                pool.to_dicts(), values, bands, old["broad_gross_return"], old["matched_net_return"], previous.get(arm),
            )
        assert month["momentum"] == old["momentum"], "Baseline changed"
        month["frozen_low_idiosyncratic"] = low_vol["low_idiosyncratic"]
        month["top_overlap_with_momentum"] = float(np.mean(pool["momentum_group"].to_numpy()[groups == 10] == 10))
        months.append(month)
        score_rows.extend({"symbol": symbols[i], "signal_date": day, "low_turnover": float(scores[i]),
                           "turnover_observations": int(counts[i]), "low_turnover_group": int(groups[j])}
                          for j, i in enumerate(ids))
    if missing:
        (output / "unavailable-scores.json").write_text(json.dumps(missing, indent=2), encoding="utf-8")
        raise ValueError(f"{len(missing)} unavailable scores; no partial universe accepted")
    assert len(months) == 82 and len(score_rows) == 191688
    scored = ledger.join(pl.DataFrame(score_rows), on=["symbol", "signal_date"], how="left", validate="1:1")
    assert scored.select(ledger.columns).sort("signal_date", "symbol").equals(ledger.sort("signal_date", "symbol"))
    scored.write_parquet(output / "scored-opportunity-ledger.parquet")
    (output / "months.json").write_text(json.dumps(months, indent=2, allow_nan=False), encoding="utf-8")
    report = summarize(months, protocol, variant="low_turnover")
    assert report["arms"]["momentum"] == old_summary["arms"]["momentum"]
    report["paired_improvement_over_frozen_low_idiosyncratic"] = interval(
        [m["low_turnover"]["top_broad_excess"] - m["frozen_low_idiosyncratic"]["top_broad_excess"] for m in months],
        protocol["statistics"],
    )
    report["verification"] = {"full_opportunities": ledger.height, "eligible_scores": len(score_rows),
                              "minimum_turnover_observations": min(r["turnover_observations"] for r in score_rows),
                              "baseline_metrics_unchanged": True, "outcome_columns_unchanged": True,
                              "matching_reexecuted": False, "maximum_endpoint": ledger["endpoint"].max()}
    report["mean_top_overlap_with_momentum"] = float(np.mean([m["top_overlap_with_momentum"] for m in months]))
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
