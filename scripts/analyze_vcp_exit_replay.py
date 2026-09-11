"""Summarize preregistered matched exit replays; no strategy tuning."""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment")
    folder = ROOT / "data/research/vcp" / parser.parse_args().experiment
    protocol = json.loads((folder / "protocol.json").read_text(encoding="utf-8"))
    rows = json.loads((folder / "records.json").read_text(encoding="utf-8"))
    baseline, variant = protocol["arms"]
    a = np.array([r["arms"][baseline]["excess"] for r in rows])
    b = np.array([r["arms"][variant]["excess"] for r in rows])
    delta = b - a
    run = ROOT / "data/research/vcp/runs" / protocol["baseline_run"]
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    refs = json.loads((run / "data-references.json").read_text(encoding="utf-8"))["files"]
    calendar = sorted({Path(r["path"]).parent.name.removeprefix("date=") for r in refs
                       if Path(r["path"]).parts[0] == "kline_daily_enriched"
                       and config["start"] <= Path(r["path"]).parent.name.removeprefix("date=") <= config["end"]})
    index = {d: i for i, d in enumerate(calendar)}
    sums, counts = np.zeros(len(calendar)), np.zeros(len(calendar))
    for row, value in zip(rows, delta, strict=True):
        sums[index[row["signal_date"]]] += value
        counts[index[row["signal_date"]]] += 1
    rng = np.random.default_rng(20260910)
    bootstrap = []
    for _ in range(2000):
        starts = rng.integers(len(calendar), size=int(np.ceil(len(calendar) / 60)))
        ids = ((starts[:, None] + np.arange(60)) % len(calendar)).ravel()[:len(calendar)]
        bootstrap.append(sums[ids].sum() / counts[ids].sum())
    ci = np.quantile(bootstrap, [.025, .975])
    annual = {year: float(np.mean([delta[i] for i, r in enumerate(rows)
                                  if r["entry_date"][:4] == year]))
              for year in sorted({r["entry_date"][:4] for r in rows})}
    retained = float(np.mean(b[a > 0] > 0))
    mean_loss_a = float(-a[a < 0].mean()) if (a < 0).any() else 0.0
    mean_loss_b = float(-b[b < 0].mean()) if (b < 0).any() else 0.0
    keys = [(r["symbol"], r["signal_date"], r["entry_date"]) for r in rows]
    original = json.loads((run / "result.json").read_text(encoding="utf-8"))["trades"]
    expected = {(r["symbol"], r["entry_signal_date"], r["entry_date"]) for r in original}
    checks = {
        "all_entries_matched": len(keys) == len(set(keys)) == 4396 and set(keys) == expected,
        "positive_mean_paired_improvement": bool(delta.mean() > 0),
        "four_positive_improvement_years": sum(v > 0 for v in annual.values()) >= 4,
        "nonnegative_variant_excess": bool(b.mean() >= 0),
        "positive_outcome_retention_90pct": retained >= .9,
        "mean_negative_outcome_deterioration_at_most_0_005": mean_loss_b - mean_loss_a <= .005,
        "paired_ci_lower_positive": bool(ci[0] > 0),
    }
    report = {
        "experiment": protocol["experiment"], "n": len(rows),
        "mean_excess": {baseline: float(a.mean()), variant: float(b.mean())},
        "paired_improvement": float(delta.mean()), "paired_ci95": ci.tolist(),
        "centered_two_sided_p": float((1 + np.sum(np.abs(np.array(bootstrap) - delta.mean())
                                                   >= abs(delta.mean()))) / 2001),
        "statistics": {"replicates": 2000, "block_trading_days": 60, "seed": 20260910},
        "annual_improvements": annual, "positive_baseline_retention": retained,
        "mean_negative_excess_magnitude": {baseline: mean_loss_a, variant: mean_loss_b},
        "censored": {arm: sum(r["arms"][arm]["censored"] for r in rows) for arm in protocol["arms"]},
        "horizon_mfe50": {"n": sum(r["horizon_mfe"] >= .5 for r in rows),
                          "mean_excess": {arm: float(np.mean([r["arms"][arm]["excess"] for r in rows
                                                              if r["horizon_mfe"] >= .5]))
                                          for arm in protocol["arms"]}},
        "checks": checks, "research_supported": all(checks.values()),
        "selection_supported": False, "live_qualified": False,
    }
    (folder / "gate-analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
