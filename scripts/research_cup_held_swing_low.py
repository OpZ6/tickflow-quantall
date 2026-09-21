"""One causal, post-entry swing-support exit on every frozen cup thin-book fill."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from research_cup_fresh_pivot_cross import key, summarize  # noqa: E402
from research_cup_upper_half import CUP_RUN  # noqa: E402
from research_vcp_loss_path_kind import label_book  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    COST_CONFIG,
    _as_date,
    load_symbol_sessions,
    net_round_trip,
    one_price_limit_down,
    training_trades,
)

EXPERIMENT = "cup-held-swing-low-exit-v1"


def apply_swing_exit(*, entry_date, exit_date, entry_price, baseline_pnl,
                     sessions, market_calendar, config=COST_CONFIG, failed_rally=False):
    unchanged = {"pnl": baseline_pnl, "shortened": False, "reason": "no_break"}
    bars = {_as_date(r["date"]): r for r in sessions}
    calendar = sorted({_as_date(d) for d in market_calendar})
    if entry_date not in calendar or not np.isfinite(entry_price) or entry_price <= 0:
        return {**unchanged, "reason": "missing_entry"}
    held = [d for d in calendar if entry_date <= d < exit_date]
    low_history = []
    high_history = []
    support = confirmed_date = None
    prior_high = latest_low = armed_high = None
    for day in held:
        bar = bars.get(day)
        if bar is None:
            return {**unchanged, "reason": "missing_bar"}
        low, close = bar.get("low"), bar.get("close")
        if any(v is None or not np.isfinite(v) or v <= 0 for v in (low, close)):
            return {**unchanged, "reason": "missing_price"}
        low_history.append(low)
        new_low = (len(low_history) >= 3 and low_history[-2] < low_history[-3]
                   and low_history[-2] < low_history[-1])
        if failed_rally:
            high = bar.get("high")
            if high is None or not np.isfinite(high) or high <= 0:
                return {**unchanged, "reason": "missing_price"}
            high_history.append(high)
            center = len(high_history) - 2
            if new_low:
                latest_low = (center, low_history[-2])
            if armed_high is not None and high > armed_high:
                support = armed_high = None
            if (len(high_history) >= 3 and high_history[-2] > high_history[-3]
                    and high_history[-2] > high_history[-1]):
                peak = high_history[-2]
                if (prior_high is not None and latest_low is not None
                        and prior_high[0] < latest_low[0] < center and peak < prior_high[1]):
                    support, confirmed_date, armed_high = latest_low[1], day, peak
                else:
                    support = armed_high = None
                prior_high = (center, peak)
        elif new_low and (support is None or low_history[-2] > support):
            support, confirmed_date = low_history[-2], day
        # All pivots above are known at this close; execution is next open.
        if support is not None and close < support:
            position = calendar.index(day)
            if position + 1 >= len(calendar):
                return {**unchanged, "reason": "missing_exit_bar"}
            fill_day = calendar[position + 1]
            if fill_day >= exit_date:
                return {**unchanged, "reason": "original_exit_first"}
            fill = bars.get(fill_day)
            if fill is None:
                return {**unchanged, "reason": "missing_exit_bar"}
            prices = [fill.get(f) for f in ("open", "high", "low", "close")]
            if any(v is None or not np.isfinite(v) or v <= 0 for v in prices):
                return {**unchanged, "reason": "missing_exit_price"}
            volume = fill.get("volume")
            if (volume is None or not np.isfinite(volume) or volume <= 0
                    or one_price_limit_down(*prices)):
                return {**unchanged, "reason": "early_exit_blocked"}
            return {
                "pnl": net_round_trip(prices[0] / entry_price - 1,
                                      config.buy_cost_pct(), config.sell_cost_pct(fill_day)),
                "shortened": True,
                "reason": "failed_rally_support_broken" if failed_rally else "confirmed_swing_low_broken",
                "support": support, "confirmed_date": confirmed_date.isoformat(),
                "signal_date": day.isoformat(), "early_exit_date": fill_day.isoformat(),
                "early_exit_price": prices[0],
            }
    return unchanged


def load_baseline():
    path = ROOT / "data/research/cup-handle/cup-fresh-pivot-cross-v1/selection-ledger.json"
    membership = json.loads(path.read_text(encoding="utf-8"))
    run = ROOT / "data/research/vcp/runs" / CUP_RUN
    source = json.loads((run / "result.json").read_text(encoding="utf-8"))
    original = {key(t): t for t in training_trades(source["trades"])}
    book = []
    for row in membership:
        trade = original[key(row)]
        for field in ("entry_price", "exit_date", "exit_price", "pnl_pct"):
            if trade[field] != row[field]:
                raise ValueError(f"Frozen fill mismatch: {key(row)} {field}")
        book.append(trade)
    if len(book) != 2034 or len({key(t) for t in book}) != 2034:
        raise ValueError("Thin-book membership mismatch")
    if summarize(book)["avg_pnl"] != 0.005438:
        raise ValueError("Thin-book mean mismatch")
    return book


def paired_diagnostics(ledger, market_calendar):
    """Fixed 30-market-day moving blocks; paired actual-return deltas, no retuning."""
    days = sorted({_as_date(d) for d in market_calendar}
                  | {_as_date(r["entry_signal_date"]) for r in ledger})
    first = min(_as_date(r["entry_signal_date"]) for r in ledger)
    last = max(_as_date(r["entry_signal_date"]) for r in ledger)
    days = [d for d in days if first <= d <= last]
    index = {d: i for i, d in enumerate(days)}
    sums, counts = np.zeros(len(days)), np.zeros(len(days))
    deltas, changed_dates, by_year = [], set(), defaultdict(list)
    for row in ledger:
        signal = _as_date(row["entry_signal_date"])
        delta = row["overlay"]["pnl"] - row["pnl_pct"]
        sums[index[signal]] += delta
        counts[index[signal]] += 1
        deltas.append(delta)
        by_year[signal.year].append(delta)
        if row["overlay"]["shortened"]:
            changed_dates.add(signal)
    nonempty = counts > 0
    daily = np.divide(sums, counts, out=np.zeros_like(sums), where=nonempty)
    block = 30
    rng = np.random.default_rng(20260912)
    starts = rng.integers(0, len(days) - block + 1, size=(2000, int(np.ceil(len(days) / block))))
    sampled = (starts[:, :, None] + np.arange(block)).reshape(2000, -1)[:, :len(days)]
    event_draws = sums[sampled].sum(axis=1) / counts[sampled].sum(axis=1)
    day_draws = daily[sampled].sum(axis=1) / nonempty[sampled].sum(axis=1)

    def interval(draws, point):
        return {"delta": point, "ci95": np.quantile(draws, [0.025, 0.975]).tolist(),
                "centered_bootstrap_two_sided_p": float(np.mean(np.abs(draws - point) >= abs(point)))}

    ordered = sorted(deltas, reverse=True)
    return {
        "scope": "post-initial-gate robustness, exposed training; actual net returns, not Alpha",
        "block_market_days": block, "draws": 2000, "seed": 20260912,
        "signal_days": int(nonempty.sum()), "changed_signal_days": len(changed_dates),
        "event_mean": interval(event_draws, float(np.mean(deltas))),
        "signal_day_mean": interval(day_draws, float(daily[nonempty].mean())),
        "event_mean_delta_without_largest_improvement": float(np.mean(ordered[1:])),
        "event_mean_delta_without_top_five_improvements": float(np.mean(ordered[5:])),
        "yearly_paired_delta": {str(y): float(np.mean(v)) for y, v in sorted(by_year.items())},
        "leave_one_year_out_delta": {
            str(y): float(np.mean([d for year, values in by_year.items() if year != y for d in values]))
            if len(by_year) > 1 else None
            for y in sorted(by_year)},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed-rally", action="store_true")
    args = parser.parse_args()
    experiment = "cup-failed-rally-exit-v1" if args.failed_rally else EXPERIMENT
    folder = ROOT / "docs/research/cup-handle"
    protocol = json.loads((folder / f"{experiment}.json").read_text(encoding="utf-8"))
    book = load_baseline()
    print("Loading training-only held bars for 2034 verified original fills", flush=True)
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in book}),
        min(_as_date(t["entry_date"]) for t in book),
        max(_as_date(t["exit_date"]) for t in book))
    labeled, incomplete = label_book(book, sessions, calendar)
    labels = {(r["symbol"], r["entry_date"], r["exit_date"]): r["path"] for r in labeled}
    ledger, variant = [], []
    grouped = defaultdict(lambda: {"baseline": [], "variant": [], "shortened": 0})
    for trade in book:
        applied = apply_swing_exit(
            entry_date=_as_date(trade["entry_date"]), exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]), baseline_pnl=float(trade["pnl_pct"]),
            sessions=sessions.get(trade["symbol"], []), market_calendar=calendar,
            failed_rally=args.failed_rally)
        changed = {**trade, "pnl_pct": applied["pnl"]}
        variant.append(changed)
        path = labels.get((trade["symbol"], trade["entry_date"], trade["exit_date"]), "incomplete")
        grouped[path]["baseline"].append(trade)
        grouped[path]["variant"].append(changed)
        grouped[path]["shortened"] += int(applied["shortened"])
        ledger.append({**trade, "original_path": path, "overlay": applied})
    baseline, altered = summarize(book), summarize(variant)
    reasons = Counter(row["overlay"]["reason"] for row in ledger)
    def positive_years(summary):
        return sum(r["avg_pnl"] > 0 for r in summary["years"].values())
    changed_count = sum(row["overlay"]["shortened"] for row in ledger)
    passed = (changed_count >= 100
              and altered["avg_pnl"] > max(0, baseline["avg_pnl"])
              and altered["signal_day_equal_weight_net"] >= baseline["signal_day_equal_weight_net"]
              and positive_years(altered) >= positive_years(baseline))
    report = {
        "experiment": experiment, "protocol": protocol, "baseline": baseline, "variant": altered,
        "reasons": dict(reasons), "incomplete_path_labels": incomplete,
        "paths": {p: {"baseline": summarize(g["baseline"]), "variant": summarize(g["variant"]),
                      "shortened": g["shortened"]} for p, g in grouped.items()},
        "rule": "research_candidate" if passed else "drop",
    }
    if passed:
        robustness = paired_diagnostics(ledger, calendar)
        (folder / f"{experiment}-robustness.json").write_text(
            json.dumps(robustness, ensure_ascii=False, indent=2), encoding="utf-8")
        report["initial_gate_passed"] = True
        if (robustness["event_mean"]["ci95"][0] <= 0
                or robustness["signal_day_mean"]["ci95"][0] <= 0):
            report["rule"] = "not_adopted_evidence_insufficient"
    output = ROOT / "data/research/cup-handle" / experiment
    output.mkdir(parents=True, exist_ok=True)
    (output / "exit-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{experiment}-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"paths", "protocol"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
