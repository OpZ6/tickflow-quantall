"""Summarize a completed archived VCP run without rerunning or modifying it."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def summarize(result, phase="development"):
    trades = result["trades"]
    initial = float(result["config"]["initial_capital"])
    years = {}
    previous_equity = initial
    for point in result["equity_curve"]:
        year = str(point["date"])[:4]
        if year not in years:
            years[year] = {"start_equity": previous_equity, "first_date": point["date"]}
        years[year].update(last_date=point["date"], end_equity=point["value"])
        previous_equity = float(point["value"])
    for row in years.values():
        row["return"] = float(row["end_equity"]) / row["start_equity"] - 1
    exits = defaultdict(list)
    entries = defaultdict(list)
    for trade in trades:
        exits[trade["exit_reason"]].append(trade)
        entries[trade.get("entry_signal_id") or "unknown"].append(trade)

    def group_rows(groups):
        return {
            name: {
                "trades": len(rows),
                "wins": sum(float(row["pnl_pct"]) > 0 for row in rows),
                "net_pnl_amount": sum(float(row["pnl_amount"]) for row in rows),
                "mean_trade_return": sum(float(row["pnl_pct"]) for row in rows) / len(rows),
                "mean_holding_bars": sum(float(row["duration"]) for row in rows) / len(rows),
            }
            for name, rows in groups.items()
        }

    winners = sorted(
        [float(t["pnl_amount"]) for t in trades if float(t["pnl_amount"]) > 0], reverse=True
    )
    gross_profit = sum(winners)
    gross_loss = -sum(float(t["pnl_amount"]) for t in trades if float(t["pnl_amount"]) < 0)
    total_pnl = sum(float(t["pnl_amount"]) for t in trades)
    equity_change = float(result["stats"]["final_equity"]) - initial
    return {
        "run_id": result["run_id"],
        "phase": phase,
        "stats": result["stats"],
        "calendar_years": years,
        "exit_reasons": group_rows(exits),
        "entry_signals": group_rows(entries),
        "top_5_winners_share_of_gross_profit": sum(winners[:5]) / gross_profit
        if gross_profit
        else None,
        "realized_net_pnl": total_pnl,
        "gross_profit_amount": gross_profit,
        "gross_loss_amount": gross_loss,
        "monetary_profit_factor": gross_profit / gross_loss if gross_loss else None,
        "engine_profit_factor_semantics": "mean winning trade return / absolute mean losing trade return; this is a payoff ratio, not aggregate profit factor",
        "equity_change": equity_change,
        "equity_minus_realized_pnl": equity_change - total_pnl,
        "period_end_positions": result["equity_curve"][-1].get("positions")
        if result["equity_curve"]
        else None,
        "note": (
            f"{phase.capitalize()} descriptive analysis; calendar-year returns are mark-to-market, "
            "exit groups are realized PnL. Selection bias and fixed-cost assumptions remain."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    state = json.loads((args.run_dir / "status.json").read_text(encoding="utf-8"))
    if state["status"] != "completed":
        raise ValueError("Run has not completed successfully")
    result = json.loads((args.run_dir / "result.json").read_text(encoding="utf-8"))
    summary = summarize(result, state.get("phase", "development"))
    (args.run_dir / "analysis.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps({k: v for k, v in summary.items() if k != "stats"}, ensure_ascii=True, indent=2)
    )
    print(
        json.dumps(
            {
                k: result["stats"].get(k)
                for k in [
                    "total_return",
                    "annual_return",
                    "max_drawdown",
                    "sharpe",
                    "win_rate",
                    "profit_factor",
                    "n_trades",
                    "avg_exposure",
                    "final_equity",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
