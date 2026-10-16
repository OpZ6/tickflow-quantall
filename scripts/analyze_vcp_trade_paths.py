#!/usr/bin/env python3
"""Analyze post-entry VCP trade paths without changing or tuning the strategy.

Future bars are used only as post-trade labels (MFE/MAE and threshold-touch
timing), never as signal inputs.  The output is a mechanism diagnostic for one
already completed research run.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, timedelta
from math import prod
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _median(values: list[float | int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def _first_touch(values: list[float], threshold: float, *, above: bool) -> int | None:
    for index, value in enumerate(values):
        if (value >= threshold) if above else (value <= threshold):
            return index
    return None


def build_equal_weight_market_returns(bars: pl.DataFrame) -> pl.DataFrame:
    """Build causal SH/SZ equal-weight returns for trade-relative evaluation."""
    return (
        bars.filter(
            pl.col("symbol").str.ends_with(".SH")
            | pl.col("symbol").str.ends_with(".SZ")
        )
        .sort(["symbol", "date"])
        .with_columns(
            (pl.col("close") / pl.col("open") - 1.0).alias("open_to_close"),
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1.0)
            .alias("close_to_close"),
        )
        .filter(
            pl.col("open_to_close").is_finite()
            & pl.col("open_to_close").is_between(-0.5, 0.5)
        )
        .group_by("date")
        .agg(
            pl.col("open_to_close").mean(),
            pl.col("close_to_close")
            .filter(
                pl.col("close_to_close").is_finite()
                & pl.col("close_to_close").is_between(-0.5, 0.5)
            )
            .mean(),
            pl.len().alias("market_constituents"),
        )
        .sort("date")
    )


def _market_return(
    dates: list[date], market_by_date: dict[date, dict[str, float | int | None]]
) -> float | None:
    if not dates:
        return None
    returns: list[float] = []
    for index, trade_date in enumerate(dates):
        row = market_by_date.get(trade_date)
        if row is None:
            return None
        field = "open_to_close" if index == 0 else "close_to_close"
        value = row.get(field)
        if value is None:
            return None
        returns.append(float(value))
    return prod(1.0 + value for value in returns) - 1.0


def _geometric_excess(stock_return: float, market_return: float | None) -> float | None:
    if market_return is None or market_return <= -1.0:
        return None
    return (1.0 + stock_return) / (1.0 + market_return) - 1.0


def _market_outcome_regime(market_return: float | None) -> str | None:
    if market_return is None:
        return None
    if market_return < -0.05:
        return "down"
    if market_return > 0.05:
        return "up"
    return "sideways"


def analyze_trade_paths(
    trades: list[dict],
    bars: pl.DataFrame,
    *,
    market_returns: pl.DataFrame | None = None,
    evaluation_horizon_bars: int | None = None,
    early_path_bars: tuple[int, ...] = (5, 10, 20),
) -> list[dict]:
    grouped = {}
    for key, frame in bars.partition_by("symbol", as_dict=True).items():
        symbol = key[0] if isinstance(key, tuple) else key
        frame = frame.sort("date")
        grouped[symbol] = (
            frame,
            {value: index for index, value in enumerate(frame["date"].to_list())},
        )
    market_by_date = (
        {row["date"]: row for row in market_returns.to_dicts()}
        if market_returns is not None
        else {}
    )
    records: list[dict] = []
    for trade in trades:
        symbol = str(trade["symbol"])
        entry_date = date.fromisoformat(str(trade["entry_date"])[:10])
        exit_date = date.fromisoformat(str(trade["exit_date"])[:10])
        grouped_symbol = grouped.get(symbol)
        if grouped_symbol is None:
            raise RuntimeError(f"no bars for trade symbol {symbol}")
        frame, date_indexes = grouped_symbol
        entry_index = date_indexes.get(entry_date)
        exit_index = date_indexes.get(exit_date)
        if entry_index is None or exit_index is None or exit_index < entry_index:
            raise RuntimeError(f"incomplete trade path for {symbol} {entry_date}..{exit_date}")
        held = frame.slice(entry_index, exit_index - entry_index + 1)
        if held.is_empty() or held["date"].min() != entry_date or held["date"].max() != exit_date:
            raise RuntimeError(f"incomplete trade path for {symbol} {entry_date}..{exit_date}")
        entry_price = float(trade["entry_price"])
        high_returns = (held["high"] / entry_price - 1.0).to_list()
        low_returns = (held["low"] / entry_price - 1.0).to_list()
        mfe = max(high_returns)
        mae = min(low_returns)
        held_dates = held["date"].to_list()
        held_market_return = (
            _market_return(held_dates, market_by_date) if market_by_date else None
        )
        record = {
            "symbol": symbol,
            "entry_signal_date": trade.get("entry_signal_date"),
            "entry_date": entry_date.isoformat(),
            "exit_date": exit_date.isoformat(),
            "entry_year": entry_date.year,
            "entry_signal_id": trade.get("entry_signal_id"),
            "exit_reason": trade.get("exit_reason"),
            "pnl_pct": float(trade["pnl_pct"]),
            "market_return_held": held_market_return,
            "excess_return_held": _geometric_excess(
                float(trade["pnl_pct"]), held_market_return
            ),
            "market_outcome_held": _market_outcome_regime(held_market_return),
            "pnl_amount": float(trade.get("pnl_amount") or 0.0),
            "holding_bars": held.height,
            "mfe": mfe,
            "mae": mae,
            "first_plus_5_bar": _first_touch(high_returns, 0.05, above=True),
            "first_plus_10_bar": _first_touch(high_returns, 0.10, above=True),
            "first_minus_3_bar": _first_touch(low_returns, -0.03, above=False),
            "first_minus_5_bar": _first_touch(low_returns, -0.05, above=False),
            "gave_back_5pct_move": mfe >= 0.05 and float(trade["pnl_pct"]) <= 0,
            "failed_without_3pct_mfe": float(trade["pnl_pct"]) <= 0 and mfe < 0.03,
        }
        if evaluation_horizon_bars is not None:
            horizon = max(int(evaluation_horizon_bars), 1)
            evaluated = frame.slice(entry_index, horizon + 1)
            horizon_high = (evaluated["high"] / entry_price - 1.0).to_list()
            horizon_low = (evaluated["low"] / entry_price - 1.0).to_list()
            horizon_mfe = max(horizon_high)
            horizon_mae = min(horizon_low)
            evaluated_dates = evaluated["date"].to_list()
            horizon_market_return = (
                _market_return(evaluated_dates, market_by_date) if market_by_date else None
            )
            horizon_close_return = float(evaluated["close"][-1]) / entry_price - 1.0
            record.update({
                "evaluation_horizon_bars": horizon,
                "evaluation_bars_available": max(evaluated.height - 1, 0),
                "evaluation_horizon_complete": evaluated.height >= horizon + 1,
                "evaluation_horizon_end_date": (
                    evaluated_dates[-1].isoformat() if evaluated_dates else None
                ),
                "horizon_mfe": horizon_mfe,
                "horizon_mae": horizon_mae,
                "horizon_close_return": horizon_close_return,
                "market_return_horizon": horizon_market_return,
                "excess_return_horizon": _geometric_excess(
                    horizon_close_return, horizon_market_return
                ),
                "market_outcome_horizon": _market_outcome_regime(horizon_market_return),
                "realized_capture_of_horizon_mfe": (
                    max(float(trade["pnl_pct"]), 0.0) / horizon_mfe
                    if horizon_mfe > 0 else None
                ),
                "early_close_returns": {
                    str(bar): (
                        float(evaluated["close"][bar]) / entry_price - 1.0
                        if evaluated.height > bar else None
                    )
                    for bar in early_path_bars
                },
                "early_excess_returns": {
                    str(bar): (
                        _geometric_excess(
                            float(evaluated["close"][bar]) / entry_price - 1.0,
                            _market_return(evaluated_dates[: bar + 1], market_by_date),
                        )
                        if evaluated.height > bar and market_by_date else None
                    )
                    for bar in early_path_bars
                },
            })
        records.append(record)
    return records


def summarize(
    records: list[dict],
    *,
    large_winner_thresholds: tuple[float, ...] = (0.2, 0.5, 1.0),
    early_path_bars: tuple[int, ...] = (5, 10, 20),
) -> dict:
    def group_summary(rows: list[dict]) -> dict:
        count = len(rows)
        exits = Counter(str(row["exit_reason"]) for row in rows)
        positive = [row for row in rows if row["pnl_pct"] > 0]
        negative = [row for row in rows if row["pnl_pct"] <= 0]
        excess = [
            float(row["excess_return_held"])
            for row in rows
            if row.get("excess_return_held") is not None
        ]
        return {
            "trades": count,
            "win_rate": _round(len(positive) / count if count else None),
            "average_pnl": _round(_mean([row["pnl_pct"] for row in rows])),
            "average_market_return_held": _round(_mean([
                float(row["market_return_held"])
                for row in rows
                if row.get("market_return_held") is not None
            ])),
            "average_excess_return_held": _round(_mean(excess)),
            "positive_excess_share": _round(
                sum(value > 0 for value in excess) / len(excess) if excess else None
            ),
            "average_win": _round(_mean([row["pnl_pct"] for row in positive])),
            "average_nonwin": _round(_mean([row["pnl_pct"] for row in negative])),
            "stop_loss_share": _round(exits.get("stop_loss", 0) / count if count else None),
            "average_mfe": _round(_mean([row["mfe"] for row in rows])),
            "average_mae": _round(_mean([row["mae"] for row in rows])),
            "failed_without_3pct_mfe_share": _round(
                sum(bool(row["failed_without_3pct_mfe"]) for row in rows) / count
                if count else None
            ),
            "gave_back_5pct_move_share": _round(
                sum(bool(row["gave_back_5pct_move"]) for row in rows) / count
                if count else None
            ),
            "failed_without_3pct_mfe_share_of_nonwins": _round(
                sum(bool(row["failed_without_3pct_mfe"]) for row in negative)
                / len(negative)
                if negative else None
            ),
            "gave_back_5pct_move_share_of_nonwins": _round(
                sum(bool(row["gave_back_5pct_move"]) for row in negative)
                / len(negative)
                if negative else None
            ),
            "exit_reasons": dict(sorted(exits.items())),
        }

    by_signal = {}
    for signal in sorted({str(row["entry_signal_id"]) for row in records}):
        by_signal[signal] = group_summary(
            [row for row in records if str(row["entry_signal_id"]) == signal]
        )
    by_year = {}
    for year in sorted({int(row["entry_year"]) for row in records}):
        by_year[str(year)] = group_summary(
            [row for row in records if int(row["entry_year"]) == year]
        )
    positive_pnl = sorted(
        (float(row["pnl_amount"]) for row in records if row["pnl_amount"] > 0),
        reverse=True,
    )
    stops = [row for row in records if row["exit_reason"] == "stop_loss"]
    winners = [row for row in records if row["pnl_pct"] > 0]
    summary = {
        "overall": group_summary(records),
        "by_entry_signal": by_signal,
        "by_entry_year": by_year,
        "path_timing_bars": {
            "stop_losses": {
                "median_first_minus_3": _median([
                    row["first_minus_3_bar"] for row in stops
                    if row["first_minus_3_bar"] is not None
                ]),
                "median_first_minus_5": _median([
                    row["first_minus_5_bar"] for row in stops
                    if row["first_minus_5_bar"] is not None
                ]),
                "median_holding": _median([row["holding_bars"] for row in stops]),
            },
            "winning_trades": {
                "median_first_plus_5": _median([
                    row["first_plus_5_bar"] for row in winners
                    if row["first_plus_5_bar"] is not None
                ]),
                "median_first_plus_10": _median([
                    row["first_plus_10_bar"] for row in winners
                    if row["first_plus_10_bar"] is not None
                ]),
                "median_holding": _median([row["holding_bars"] for row in winners]),
            },
        },
        "top_5_winner_share_of_positive_pnl": _round(
            sum(positive_pnl[:5]) / sum(positive_pnl) if positive_pnl else None
        ),
    }
    horizon_rows = [row for row in records if row.get("horizon_mfe") is not None]
    if horizon_rows:
        horizon_excess = [
            float(row["excess_return_horizon"])
            for row in horizon_rows
            if row.get("excess_return_horizon") is not None
        ]
        by_market_outcome = {}
        for regime in ("down", "sideways", "up"):
            regime_rows = [
                row for row in horizon_rows
                if row.get("market_outcome_horizon") == regime
            ]
            regime_summary = group_summary(regime_rows)
            regime_summary.update({
                "average_close_return_horizon": _round(_mean([
                    float(row["horizon_close_return"]) for row in regime_rows
                ])),
                "average_market_return_horizon": _round(_mean([
                    float(row["market_return_horizon"]) for row in regime_rows
                ])),
                "average_excess_return_horizon": _round(_mean([
                    float(row["excess_return_horizon"]) for row in regime_rows
                ])),
            })
            by_market_outcome[regime] = regime_summary
        summary["evaluation_horizon"] = {
            "trades": len(horizon_rows),
            "complete_paths": sum(bool(row["evaluation_horizon_complete"]) for row in horizon_rows),
            "average_excess_return": _round(_mean(horizon_excess)),
            "positive_excess_share": _round(
                sum(value > 0 for value in horizon_excess) / len(horizon_excess)
                if horizon_excess else None
            ),
            "by_entry_year": {
                str(year): {
                    "trades": len(year_rows),
                    "average_close_return_horizon": _round(_mean([
                        float(row["horizon_close_return"]) for row in year_rows
                    ])),
                    "average_excess_return_horizon": _round(_mean([
                        float(row["excess_return_horizon"])
                        for row in year_rows
                        if row.get("excess_return_horizon") is not None
                    ])),
                }
                for year in sorted({int(row["entry_year"]) for row in horizon_rows})
                if (
                    year_rows := [
                        row for row in horizon_rows if int(row["entry_year"]) == year
                    ]
                )
            },
            "by_market_outcome": by_market_outcome,
            "large_winner_paths": {
                f"mfe_at_least_{round(threshold * 100)}pct": {
                    "candidates": len(big),
                    "candidate_share": _round(len(big) / len(horizon_rows)),
                    "realized_at_least_threshold": sum(
                        float(row["pnl_pct"]) >= threshold for row in big
                    ),
                    "positive_exits": sum(float(row["pnl_pct"]) > 0 for row in big),
                    "average_exit_capture": _round(_mean([
                        float(row["realized_capture_of_horizon_mfe"])
                        for row in big
                        if row.get("realized_capture_of_horizon_mfe") is not None
                    ])),
                    "median_exit_capture": _round(_median([
                        float(row["realized_capture_of_horizon_mfe"])
                        for row in big
                        if row.get("realized_capture_of_horizon_mfe") is not None
                    ])),
                }
                for threshold in large_winner_thresholds
                for big in [[
                    row for row in horizon_rows
                    if float(row["horizon_mfe"]) >= threshold
                ]]
            },
            "early_close_returns": {
                str(bar): {
                    "available": len(values),
                    "average": _round(_mean(values)),
                    "median": _round(_median(values)),
                    "positive_share": _round(
                        sum(value > 0 for value in values) / len(values) if values else None
                    ),
                }
                for bar in early_path_bars
                for values in [[
                    float(row["early_close_returns"][str(bar)])
                    for row in horizon_rows
                    if row["early_close_returns"].get(str(bar)) is not None
                ]]
            },
            "early_excess_returns": {
                str(bar): {
                    "available": len(values),
                    "average": _round(_mean(values)),
                    "median": _round(_median(values)),
                    "positive_share": _round(
                        sum(value > 0 for value in values) / len(values) if values else None
                    ),
                }
                for bar in early_path_bars
                for values in [[
                    float(row["early_excess_returns"][str(bar)])
                    for row in horizon_rows
                    if row.get("early_excess_returns", {}).get(str(bar)) is not None
                ]]
            },
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--horizon-bars",
        type=int,
        help="Override the post-entry label horizon without changing the strategy run.",
    )
    args = parser.parse_args()
    run_dir = args.data_root.resolve() / "research" / "vcp" / "runs" / args.run_id
    result_path = run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    protocol = json.loads((run_dir / "protocol.json").read_text(encoding="utf-8"))
    analysis = protocol.get("analysis") or {}
    horizon = int(
        args.horizon_bars
        if args.horizon_bars is not None
        else analysis.get("evaluation_horizon_bars")
        or result.get("strategy_info", {}).get("max_hold_days")
        or 40
    )
    if horizon <= 0:
        raise ValueError("horizon-bars must be positive")
    early_path_bars = tuple(int(value) for value in analysis.get("early_path_bars", [5, 10, 20]))
    large_winner_thresholds = tuple(
        float(value) for value in analysis.get("large_winner_mfe_thresholds", [0.2, 0.5, 1.0])
    )
    trades = list(result.get("trades") or [])
    if not trades:
        raise RuntimeError(f"run has no materialized trades: {args.run_id}")
    symbols = sorted({str(item["symbol"]) for item in trades})
    start = min(str(item["entry_date"])[:10] for item in trades)
    end = (
        max(date.fromisoformat(str(item["entry_date"])[:10]) for item in trades)
        + timedelta(days=max(horizon * 2, 80))
    ).isoformat()
    cutoff = protocol.get("training_data_end")
    if "training_gate" in protocol and cutoff is None:
        raise ValueError("training_gate requires explicit training_data_end")
    if cutoff is not None:
        date.fromisoformat(cutoff)
        if any(str(t["entry_date"])[:10] > cutoff or str(t["exit_date"])[:10] > cutoff for t in trades):
            raise ValueError("Trade crosses training_data_end")
        end = min(end, cutoff)
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={start}" <= path.parent.name <= f"date={end}"
    ]
    bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").is_in(symbols))
        .select("symbol", "date", "high", "low", "close")
        .collect()
    )
    market_bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .select("symbol", "date", "open", "close")
        .collect()
    )
    market_returns = build_equal_weight_market_returns(market_bars)
    records = analyze_trade_paths(
        trades,
        bars,
        market_returns=market_returns,
        evaluation_horizon_bars=horizon,
        early_path_bars=early_path_bars,
    )
    if cutoff is not None and (
        len(records) != len(trades)
        or any(not r.get("evaluation_horizon_complete") for r in records)
    ):
        raise ValueError("Incomplete training labels before training_data_end; no report published")
    report = {
        "schema_version": 1,
        "run_id": args.run_id,
        "analysis_role": "post_trade_labels_only",
        "future_data_in_signal_generation": False,
        "bar_source": "kline_daily_enriched",
        "market_benchmark": (
            "daily rebalanced SH/SZ equal-weight adjusted return; entry day uses "
            "cross-sectional open-to-close and later days use close-to-close"
        ),
        "summary": summarize(
            records,
            large_winner_thresholds=large_winner_thresholds,
            early_path_bars=early_path_bars,
        ),
        "trades": records,
    }
    output = run_dir / "trade-path-analysis.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
