"""Retrospective sensitivity and expanding-year walk-forward diagnostics.

The years in this file have already been examined during exploratory research.
Walk-forward here checks algorithm chronology; it is not a clean holdout.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_dividend_etf_backtest import (
    ROUND_TRIP_SIDE_COST,
    SYMBOLS,
    corporate_actions,
    load_etf_pair,
    metrics,
    period_metrics,
    signals,
    simulate,
    total_return_bars,
)


INPUT = Path("data/research/dividend_etf")
OUTPUT = INPUT / "robustness_results.json"


def channel_target(frame: pd.DataFrame, lookback: int, band: float) -> pd.Series:
    high = frame.high.shift(1).rolling(lookback, min_periods=lookback).max()
    low = frame.low.shift(1).rolling(lookback, min_periods=lookback).min()
    position = ((frame.close - low) / (high - low)).clip(0, 1)
    target = pd.Series(np.select([position <= band, position >= 1 - band], [1., .5], default=.75), index=frame.index)
    target[position.isna()] = np.nan
    return target


def macd_target(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    line = frame.close.ewm(span=fast, adjust=False).mean() - frame.close.ewm(span=slow, adjust=False).mean()
    return (line > line.ewm(span=9, adjust=False).mean()).astype(float)


def year_metrics(curve: pd.DataFrame) -> dict:
    return {str(year): period_metrics(curve, f"{year}-01-01", f"{year}-12-31") for year in sorted(curve.date.dt.year.unique())}


def one_fold(frame: pd.DataFrame, target: pd.Series, year: int, dividends: pd.Series, splits: pd.Series) -> dict:
    year_indices = frame.index[frame.date.dt.year == year]
    if len(year_indices) < 30:
        return {"status": "insufficient"}
    first = int(year_indices.min()) - 1
    subset = frame.iloc[: int(year_indices.max()) + 1]
    curve, changes, _ = simulate(subset, target.iloc[: len(subset)], first, ROUND_TRIP_SIDE_COST, dividends=dividends.iloc[: len(subset)], splits=splits.iloc[: len(subset)])
    return {"strategy_return": metrics(curve)["total_return"], "trades": changes, "bars": len(curve)}


def expanding_walkforward(frame: pd.DataFrame, candidate_targets: dict[str, pd.Series], dividends: pd.Series, splits: pd.Series) -> dict:
    """Choose trailing three-year CAGR winner at each year-end, trade next year."""
    folds = []
    years = sorted(frame.date.dt.year.unique())
    for year in years:
        if year < 2023 or year == years[0]:
            continue
        train_first = frame.index[frame.date >= pd.Timestamp(f"{year - 3}-01-01")]
        train_last = frame.index[frame.date < pd.Timestamp(f"{year}-01-01")]
        if len(train_first) == 0 or len(train_last) == 0:
            continue
        first = max(199, int(train_first.min()))
        last = int(train_last.max())
        if last - first < 400:
            continue
        train_frame = frame.iloc[: last + 1]
        training_scores = {}
        for name, target in candidate_targets.items():
            curve, _, _ = simulate(train_frame, target.iloc[: len(train_frame)], first, ROUND_TRIP_SIDE_COST, dividends=dividends.iloc[: len(train_frame)], splits=splits.iloc[: len(train_frame)])
            training_scores[name] = metrics(curve)["cagr"]
        selected = max(training_scores, key=training_scores.get)
        test = one_fold(frame, candidate_targets[selected], year, dividends, splits)
        benchmark = one_fold(frame, candidate_targets["hold"], year, dividends, splits)
        if test.get("status") == "insufficient" or benchmark.get("status") == "insufficient":
            continue
        folds.append({"year": int(year), "selected": selected, "train_cagr": training_scores[selected], "test_return": test["strategy_return"], "hold_return": benchmark["strategy_return"], "excess": test["strategy_return"] - benchmark["strategy_return"]})
    if not folds:
        return {"status": "insufficient", "folds": []}
    wealth = float(np.prod([1 + fold["test_return"] for fold in folds]))
    hold_wealth = float(np.prod([1 + fold["hold_return"] for fold in folds]))
    return {"folds": folds, "compound_return": wealth - 1, "hold_compound_return": hold_wealth - 1, "positive_excess_years": sum(fold["excess"] > 0 for fold in folds)}


def cross_sectional_ic(panel: list[pd.DataFrame]) -> dict:
    """Monthly five-ETF rank correlation; diagnostic due tiny, related universe."""
    common = pd.concat(panel, ignore_index=True)
    counts = common.groupby("date").symbol.nunique()
    common = common[common.date.isin(counts[counts == len(SYMBOLS)].index)]
    month_ends = common.groupby(common.date.dt.to_period("M")).date.max()
    common = common[common.date.isin(month_ends)]
    out = {}
    for feature in ("channel_position", "mom60", "macd_histogram_pct"):
        values = []
        for _, group in common.groupby("date"):
            if group[feature].notna().sum() != len(SYMBOLS) or group.forward20.notna().sum() != len(SYMBOLS):
                continue
            value = group[feature].corr(group.forward20, method="spearman")
            if np.isfinite(value):
                values.append(float(value))
        out[feature] = {"months": len(values), "mean_rank_ic": float(np.mean(values)) if values else None, "positive_months": sum(value > 0 for value in values)}
    return out


def main() -> None:
    report = {"status": "retrospective_sensitivity_not_clean_oos", "symbols": {}}
    panel = []
    for symbol in SYMBOLS:
        frame, adjusted = load_etf_pair(INPUT, symbol)
        dividends, splits = corporate_actions(frame, adjusted, symbol)
        signal_frame = total_return_bars(frame, dividends) if symbol == "510880.SH" else adjusted
        fixed = signals(signal_frame)
        return_frame = signal_frame if symbol == "512890.SH" else total_return_bars(frame, dividends)
        panel.append(pd.DataFrame({
            "symbol": symbol, "date": frame.date,
            "channel_position": fixed.channel_position,
            "mom60": fixed.mom60,
            "macd_histogram_pct": fixed.macd_histogram / signal_frame.close,
            "forward20": return_frame.close.shift(-20) / return_frame.close - 1,
        }))
        first = 249
        hold_curve, _, _ = simulate(frame, fixed.hold, first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
        baseline = metrics(hold_curve)["cagr"]
        grid = []
        for lookback in (40, 60, 120):
            for band in (.2, .25, .3):
                target = channel_target(signal_frame, lookback, band)
                curve, changes, _ = simulate(frame, target, first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
                grid.append({"family": "channel", "lookback": lookback, "band": band, "cagr": metrics(curve)["cagr"], "mdd": metrics(curve)["mdd"], "excess_vs_hold": metrics(curve)["cagr"] - baseline, "changes": changes})
        for fast in (8, 12, 16):
            for slow in (17, 26, 35):
                if fast >= slow:
                    continue
                target = macd_target(signal_frame, fast, slow)
                curve, changes, _ = simulate(frame, target, first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
                grid.append({"family": "macd", "fast": fast, "slow": slow, "signal": 9, "cagr": metrics(curve)["cagr"], "mdd": metrics(curve)["mdd"], "excess_vs_hold": metrics(curve)["cagr"] - baseline, "changes": changes})
        for window in (120, 200, 250):
            target = (signal_frame.close > signal_frame.close.rolling(window, min_periods=window).mean()).astype(float)
            curve, changes, _ = simulate(frame, target, first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
            grid.append({"family": "ma", "window": window, "cagr": metrics(curve)["cagr"], "mdd": metrics(curve)["mdd"], "excess_vs_hold": metrics(curve)["cagr"] - baseline, "changes": changes})
        annual = {}
        for name in ("hold", "ma200", "macd", "channel", "ma200_channel"):
            curve, _, _ = simulate(frame, fixed[name], 199, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
            annual[name] = year_metrics(curve)
        candidate_targets = {name: fixed[name] for name in ("hold", "ma200", "macd", "channel")}
        by_family = {}
        for family in ("channel", "macd", "ma"):
            rows = [row for row in grid if row["family"] == family]
            by_family[family] = {"tested": len(rows), "positive_vs_hold": sum(row["excess_vs_hold"] > 0 for row in rows), "median_excess": float(np.median([row["excess_vs_hold"] for row in rows])), "min_excess": min(row["excess_vs_hold"] for row in rows), "max_excess": max(row["excess_vs_hold"] for row in rows)}
        report["symbols"][symbol] = {"grid": grid, "grid_summary": by_family, "yearly": annual, "retrospective_walkforward": expanding_walkforward(frame, candidate_targets, dividends, splits)}
    report["cross_sectional_ic"] = cross_sectional_ic(panel)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({symbol: value["grid_summary"] for symbol, value in report["symbols"].items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
