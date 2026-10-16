"""One profitable-position distribution exit against frozen independent fills."""
import json
from pathlib import Path

import numpy as np
import polars as pl
from research_vcp_two_bar_no_demand import (
    COST_CONFIG,
    ROOT,
    _as_date,
    independent_trade_stats,
    load_symbol_sessions,
    net_round_trip,
    one_price_limit_down,
    training_trades,
)


def distribution_exit(trade, sessions, calendar):
    entry, exit_day = _as_date(trade["entry_date"]), _as_date(trade["exit_date"])
    entry_price = float(trade["entry_price"])
    unchanged = {"pnl": trade["pnl_pct"], "shortened": False, "reason": "no_event"}
    by_date = {_as_date(r["date"]): r for r in sessions}
    days = sorted(set(calendar))
    for previous_day, day, next_day in zip(days, days[1:], days[2:], strict=False):
        if previous_day < entry or next_day >= exit_day:
            continue
        previous, current = by_date.get(previous_day), by_date.get(day)
        if previous is None or current is None:
            continue
        values = np.array([current["close"], previous["low"], current["volume"], previous["volume"]], dtype=float)
        if not (np.isfinite(values) & (values > 0)).all():
            continue
        if not (entry_price < values[0] < values[1] and values[2] > values[3]):
            continue
        fill = by_date.get(next_day)
        if fill is None:
            return {**unchanged, "reason": "blocked_exit", "signal_date": day.isoformat()}
        prices = np.array([fill[k] for k in ("open", "high", "low", "close")], dtype=float)
        volume = float(fill.get("volume") or 0)
        if (not (np.isfinite(prices) & (prices > 0)).all() or not np.isfinite(volume)
                or volume <= 0 or one_price_limit_down(*prices)):
            return {**unchanged, "reason": "blocked_exit", "signal_date": day.isoformat()}
        pnl = net_round_trip(prices[0] / entry_price - 1, COST_CONFIG.buy_cost_pct(),
                             COST_CONFIG.sell_cost_pct(next_day))
        return {"pnl": pnl, "shortened": True, "reason": "profitable_distribution",
                "signal_date": day.isoformat(), "exit_date": next_day.isoformat()}
    return unchanged


def main():
    protocol_path = ROOT / "docs/research/vcp/profitable-distribution-exit-v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    output = ROOT / protocol["output"]
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    source = json.loads((ROOT / "data/research/vcp/runs" / protocol["baseline_run"] / "result.json")
                        .read_text(encoding="utf-8"))
    assert source["stats"]["full_kind"] == "candidate_execution"
    trades = training_trades(source["trades"])
    assert len(trades) == 474
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in trades}),
        min(_as_date(t["entry_date"]) for t in trades), max(_as_date(t["exit_date"]) for t in trades))
    rows = [{"symbol": t["symbol"], "entry_date": t["entry_date"], "baseline_pnl": t["pnl_pct"],
             **distribution_exit(t, sessions[t["symbol"]], calendar)} for t in trades]
    def stats(group, field):
        return independent_trade_stats([r[field] for r in group])
    baseline, variant = stats(rows, "baseline_pnl"), stats(rows, "pnl")
    assert baseline["avg_pnl"] == 0.009139
    report = {"baseline": baseline, "variant": variant,
              "shortened": sum(r["shortened"] for r in rows),
              "blocked": sum(r["reason"] == "blocked_exit" for r in rows),
              "yearly": {str(y): {k: stats([r for r in rows if r["entry_date"].startswith(str(y))], k)
                                    for k in ("baseline_pnl", "pnl")} for y in range(2016, 2023)},
              "rule": "keep" if variant["avg_pnl"] >= baseline["avg_pnl"] and variant["avg_pnl"] > 0 else "drop",
              "live_qualified": False}
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(output / "ledger.parquet")
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
