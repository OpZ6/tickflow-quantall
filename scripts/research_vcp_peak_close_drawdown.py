"""Frozen 8% close-peak exit on the currently requested composite VCP baseline."""
import argparse
import json
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
import polars as pl
from research_vcp_two_bar_no_demand import (
    COST_CONFIG,
    ROOT,
    _as_date,
    apply_two_bar_no_demand_to_fill,
    independent_trade_stats,
    load_symbol_sessions,
    net_round_trip,
    one_price_limit_down,
    prebreakout_volume_contracted,
    training_trades,
)


def peak_close_exit(trade, sessions, calendar):
    entry, end = _as_date(trade["entry_date"]), _as_date(trade["exit_date"])
    by_date = {_as_date(r["date"]): r for r in sessions}
    peak = None
    unchanged = {"pnl": trade["pnl_pct"], "shortened": False, "reason": "no_drawdown"}
    days = sorted(set(calendar))
    for day, next_day in pairwise(days):
        if day < entry or next_day >= end:
            continue
        bar = by_date.get(day)
        close = float(bar.get("close") or 0) if bar else 0.0
        if not np.isfinite(close) or close <= 0:
            return {**unchanged, "reason": "missing_close"}
        peak = max(peak, close) if peak is not None else close
        if close > peak * 0.92:
            continue
        fill = by_date.get(next_day)
        prices = np.array([fill.get(k) for k in ("open", "high", "low", "close")], dtype=float) if fill else np.zeros(4)
        volume = float(fill.get("volume") or 0) if fill else 0.0
        if (not (np.isfinite(prices) & (prices > 0)).all() or not np.isfinite(volume)
                or volume <= 0 or one_price_limit_down(*prices)):
            return {**unchanged, "reason": "blocked_exit", "signal_date": day.isoformat()}
        pnl = net_round_trip(prices[0] / trade["entry_price"] - 1,
                             COST_CONFIG.buy_cost_pct(), COST_CONFIG.sell_cost_pct(next_day))
        return {"pnl": pnl, "shortened": True, "reason": "peak_close_drawdown",
                "signal_date": day.isoformat(), "exit_date": next_day.isoformat()}
    return unchanged


def evaluate(run_id, scope, output, *, remove_no_demand=False):
    source = json.loads((ROOT / "data/research/vcp/runs" / run_id / "result.json").read_text(encoding="utf-8"))
    if scope == "full":
        assert source["stats"]["full_kind"] == "candidate_execution"
    trades = training_trades(source["trades"])
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in trades}),
        min(_as_date(t["entry_signal_date"]) for t in trades) - timedelta(days=80),
        max(_as_date(t["exit_date"]) for t in trades))
    rows, missing, rejected = [], 0, 0
    for t in trades:
        bars = sessions[t["symbol"]]
        flag = prebreakout_volume_contracted(signal_date=_as_date(t["entry_signal_date"]),
                                             sessions=bars, market_calendar=calendar)
        if not flag.get("expanding"):
            if flag["contracted"]:
                rejected += 1
            else:
                missing += 1
            continue
        base = {"pnl": t["pnl_pct"]} if remove_no_demand else apply_two_bar_no_demand_to_fill(
            entry_date=_as_date(t["entry_date"]), exit_date=_as_date(t["exit_date"]),
            entry_price=t["entry_price"], baseline_pnl=t["pnl_pct"], sessions=bars, market_calendar=calendar)
        current = {**t, "pnl_pct": base["pnl"], "exit_date": base.get("early_exit_date", t["exit_date"])}
        changed = peak_close_exit(current, bars, calendar)
        rows.append({"symbol": t["symbol"], "entry_date": t["entry_date"],
                     "baseline_exit": current["exit_date"], "baseline_pnl": base["pnl"], **changed})
    def stats(group, field):
        return independent_trade_stats([r[field] for r in group])
    baseline, variant = stats(rows, "baseline_pnl"), stats(rows, "pnl")
    if scope == "matched" and not remove_no_demand:
        expected = json.loads((ROOT / "docs/research/vcp/prebreakout-volume-expansion-v1-analysis.json")
                              .read_text(encoding="utf-8"))["variant"]
        assert baseline == expected, (baseline, expected)
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(output / f"{scope}-ledger.parquet")
    return {"source_run": run_id, "source_completed_training_fills": len(trades),
            "missing_selection_history": missing, "rejected_by_selection": rejected,
            "baseline": baseline, "variant": variant, "shortened": sum(r["shortened"] for r in rows),
            "blocked": sum(r["reason"] in {"blocked_exit", "missing_close"} for r in rows),
            "yearly": {str(y): {k: stats([r for r in rows if r["entry_date"].startswith(str(y))], k)
                                  for k in ("baseline_pnl", "pnl")} for y in range(2016, 2023)},
            "keep": variant["avg_pnl"] >= baseline["avg_pnl"] and variant["avg_pnl"] > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="docs/research/vcp/peak-close-drawdown-exit-v1.json")
    args = parser.parse_args()
    protocol_path = ROOT / args.protocol
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    output = ROOT / protocol["output"]
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    (output / "baseline-helper.py").write_bytes((ROOT / "scripts/research_vcp_two_bar_no_demand.py").read_bytes())
    remove_no_demand = protocol.get("remove_no_demand", False)
    report = {s: evaluate(protocol[f"{s}_run"], s, output, remove_no_demand=remove_no_demand)
              for s in ("matched", "full")}
    if remove_no_demand:
        comparison = ROOT / protocol["comparison_output"]
        prior = json.loads((comparison / "summary.json").read_text(encoding="utf-8"))
        for scope in ("matched", "full"):
            before = pl.read_parquet(comparison / f"{scope}-ledger.parquet")
            after = pl.read_parquet(output / f"{scope}-ledger.parquet")
            assert before.select("symbol", "entry_date").equals(after.select("symbol", "entry_date"))
            report[scope]["comparison_baseline"] = prior[scope]["variant"]
            report[scope]["keep"] = report[scope]["variant"]["avg_pnl"] >= prior[scope]["variant"]["avg_pnl"]
        report["rule"] = "keep" if report["full"]["keep"] and report["full"]["variant"]["avg_pnl"] > 0 else "drop"
    else:
        report["rule"] = "keep" if all(report[s]["keep"] for s in ("matched", "full")) else "drop"
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
