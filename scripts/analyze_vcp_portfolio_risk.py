"""Audit portfolio-level risk concentration in a frozen VCP research run.

The audit is descriptive.  It does not choose a slot count, exposure target,
loss-streak rule, or any other portfolio parameter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "data/research/vcp/runs/20260907T123519390606Z"


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _max_loss_streak(trades: pl.DataFrame) -> int:
    longest = 0
    current = 0
    for is_loss in trades.sort(["exit_date", "entry_date"])["is_loss"]:
        current = current + 1 if is_loss else 0
        longest = max(longest, current)
    return longest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="?", default=DEFAULT_RUN)
    args = parser.parse_args()
    result_path = args.run / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    trades = pl.DataFrame(result["trades"]).with_columns(
        pl.col("entry_date").str.to_date(),
        pl.col("exit_date").str.to_date(),
        (pl.col("pnl_pct") <= 0).alias("is_loss"),
    )
    equity = (
        pl.DataFrame(result["equity_curve"])
        .with_columns(pl.col("date").str.to_date())
        .with_columns(pl.col("value").cum_max().alias("running_peak"))
        .with_columns((pl.col("value") / pl.col("running_peak") - 1).alias("drawdown"))
    )
    trough = equity.sort("drawdown").row(0, named=True)
    peak = (
        equity.filter(pl.col("date") <= trough["date"])
        .sort(["value", "date"], descending=[True, False])
        .row(0, named=True)
    )
    recovery_rows = equity.filter(
        (pl.col("date") > trough["date"]) & (pl.col("value") >= peak["value"])
    )
    recovery_date = recovery_rows["date"].min() if recovery_rows.height else None
    drawdown_trades = trades.filter(
        (pl.col("entry_date") <= trough["date"]) & (pl.col("exit_date") >= peak["date"])
    )

    cohorts = (
        trades.group_by("entry_date")
        .agg(
            pl.len().alias("trades"),
            pl.col("pnl_amount").sum().alias("pnl_amount"),
            pl.col("entry_value").sum().alias("entry_value"),
            pl.col("pnl_pct").mean().alias("mean_trade_return"),
            (~pl.col("is_loss")).sum().alias("wins"),
        )
        .with_columns((pl.col("pnl_amount") / pl.col("entry_value")).alias("capital_return"))
        .sort("entry_date")
    )
    negative = cohorts.filter(pl.col("pnl_amount") < 0)
    negative_amount = abs(float(negative["pnl_amount"].sum()))
    multi_negative_amount = abs(
        float(negative.filter(pl.col("trades") > 1)["pnl_amount"].sum())
    )

    positive_trades = trades.filter(pl.col("pnl_amount") > 0).sort(
        "pnl_amount", descending=True
    )
    negative_trades = trades.filter(pl.col("pnl_amount") < 0).sort("pnl_amount")
    gross_profit = float(positive_trades["pnl_amount"].sum())
    gross_loss = abs(float(negative_trades["pnl_amount"].sum()))

    yearly = (
        trades.group_by(pl.col("entry_date").dt.year().alias("year"))
        .agg(
            pl.len().alias("trades"),
            pl.col("pnl_amount").sum().alias("pnl_amount"),
            pl.col("pnl_pct").mean().alias("mean_trade_return"),
            (~pl.col("is_loss")).mean().alias("win_rate"),
        )
        .sort("year")
        .to_dicts()
    )
    worst_cohorts = cohorts.sort("pnl_amount").head(10).to_dicts()

    report = {
        "study": "frozen-vcp-portfolio-risk-audit-v1",
        "run_id": args.run.name,
        "method": (
            "Descriptive drawdown, entry-cohort, loss-streak, and contribution analysis; "
            "no portfolio parameter is selected."
        ),
        "trades": trades.height,
        "max_drawdown": {
            "peak_date": str(peak["date"]),
            "trough_date": str(trough["date"]),
            "recovery_date": str(recovery_date) if recovery_date else None,
            "drawdown": float(trough["drawdown"]),
            "overlapping_trades": drawdown_trades.height,
            "overlapping_winners": int((~drawdown_trades["is_loss"]).sum()),
            "overlapping_pnl_amount": float(drawdown_trades["pnl_amount"].sum()),
        },
        "entry_cohorts": {
            "cohorts": cohorts.height,
            "multi_trade_cohorts": cohorts.filter(pl.col("trades") > 1).height,
            "trades_in_multi_trade_cohorts": int(
                cohorts.filter(pl.col("trades") > 1)["trades"].sum()
            ),
            "max_same_day_entries": int(cohorts["trades"].max()),
            "negative_pnl_from_multi_trade_cohorts_share": (
                multi_negative_amount / negative_amount if negative_amount else None
            ),
            "worst_cohorts": worst_cohorts,
        },
        "path_concentration": {
            "max_consecutive_nonwinning_exits": _max_loss_streak(trades),
            "top_5_winner_gross_profit_share": (
                float(positive_trades.head(5)["pnl_amount"].sum()) / gross_profit
                if gross_profit
                else None
            ),
            "worst_5_trade_gross_loss_share": (
                abs(float(negative_trades.head(5)["pnl_amount"].sum())) / gross_loss
                if gross_loss
                else None
            ),
        },
        "by_entry_year": yearly,
        "stats_reference": {
            "annual_return": _as_float(result["stats"].get("annual_return")),
            "max_drawdown": _as_float(result["stats"].get("max_drawdown")),
            "average_exposure": _as_float(result["stats"].get("avg_exposure")),
        },
    }
    output = args.run / "portfolio-risk-analysis.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
