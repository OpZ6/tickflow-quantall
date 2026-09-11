"""Matched volume-filter experiment on the goal.md frozen baseline."""
import argparse
import json
from datetime import timedelta
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl
from research_vcp_two_bar_no_demand import (
    BASELINE_RUN,
    ROOT,
    _as_date,
    apply_two_bar_no_demand_to_fill,
    independent_trade_stats,
    load_symbol_sessions,
    training_trades,
)


def signal_volume_ratio(sessions, calendar, signal_day):
    """Use 20 prior market sessions; never bridge a missing observation."""
    days = sorted(set(calendar))
    if signal_day not in days or days.index(signal_day) < 20:
        raise ValueError("insufficient signal history")
    end = days.index(signal_day)
    by_date = {_as_date(r["date"]): r for r in sessions}
    window = days[end - 20:end + 1]
    if any(d not in by_date for d in window):
        raise ValueError("missing volume session")
    volumes = np.array([by_date[d]["volume"] for d in window], dtype=float)
    if not (np.isfinite(volumes) & (volumes > 0)).all():
        raise ValueError("invalid volume")
    return float(volumes[-1] / volumes[:-1].mean())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    protocol_path = ROOT / "docs/research/vcp/breakout-volume-filter-v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    output = ROOT / (args.output or protocol["output"])
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol_path.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    source = ROOT / "data/research/vcp/runs" / BASELINE_RUN / "result.json"
    trades = training_trades(json.loads(source.read_text(encoding="utf-8"))["trades"])
    assert len(trades) == 171
    sessions, calendar = load_symbol_sessions(
        ROOT / "data", sorted({t["symbol"] for t in trades}),
        min(_as_date(t["entry_signal_date"]) for t in trades) - timedelta(days=90),
        max(_as_date(t["exit_date"]) for t in trades),
    )
    rows = []
    for t in trades:
        bars = sessions[t["symbol"]]
        signal = _as_date(t["entry_signal_date"])
        assert signal < _as_date(t["entry_date"])
        try:
            ratio = signal_volume_ratio(bars, calendar, signal)
        except ValueError:
            ratio = None
        applied = apply_two_bar_no_demand_to_fill(
            entry_date=_as_date(t["entry_date"]), exit_date=_as_date(t["exit_date"]),
            entry_price=t["entry_price"], baseline_pnl=t["pnl_pct"],
            sessions=bars, market_calendar=calendar,
        )
        rows.append({"symbol": t["symbol"], "signal_date": signal.isoformat(),
                     "entry_date": t["entry_date"], "signal_id": t["entry_signal_id"],
                     "original_pnl": t["pnl_pct"], "pnl": applied["pnl"],
                     "exit_date": applied.get("early_exit_date", t["exit_date"]),
                     "exit_rule": applied["reason"], "volume_ratio": ratio,
                     "selected": ratio >= 1.0 if ratio is not None else None})
    def stats(subset):
        return independent_trade_stats([r["pnl"] for r in subset])
    baseline = stats(rows)
    expected = json.loads((ROOT / "docs/research/vcp/two-bar-no-demand-exit-v1-analysis.json")
                          .read_text(encoding="utf-8"))["variant"]
    assert baseline == expected, (baseline, expected)
    selected = stats([r for r in rows if r["selected"]])
    rejected = stats([r for r in rows if r["selected"] is False])
    unknown = [r for r in rows if r["selected"] is None]
    known_selected = [r for r in rows if r["selected"]]
    # Bound the effect of missing classifications; this does not choose a trading rule.
    possibilities = [stats(known_selected + list(subset))["avg_pnl"]
                     for n in range(len(unknown) + 1) for subset in combinations(unknown, n)]
    report = {"baseline": baseline, "selected": selected, "rejected": rejected,
              "baseline_reproduced": True, "missing_features": len(unknown),
              "unclassified": unknown, "selection_mean_bounds": [min(possibilities), max(possibilities)],
              "yearly": {str(y): {"all": stats([r for r in rows if r["entry_date"].startswith(str(y))]),
                                    "selected": stats([r for r in rows if r["entry_date"].startswith(str(y)) and r["selected"]])}
                         for y in range(2016, 2023)},
              "decision": "drop" if max(possibilities) < baseline["avg_pnl"]
              else "incomplete_features" if unknown else "provisional_keep",
              "live_qualified": False, "scope": protocol["scope"]}
    pl.DataFrame(rows).write_parquet(output / "ledger.parquet")
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
