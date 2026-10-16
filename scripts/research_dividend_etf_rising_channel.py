"""Causal rising K-line channel versus simple dividend ETF alternatives."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_dividend_etf_backtest import (
    ROUND_TRIP_SIDE_COST, SYMBOLS, corporate_actions, load_etf_pair,
    metrics, public_payment_indices, signals, simulate, total_return_bars,
)


ROOT = Path("data/research/dividend_etf")


def rising_channel(frame: pd.DataFrame, window: int, width: float, trend_gate: bool) -> tuple[pd.Series, pd.Series]:
    """Fit log closes through yesterday; compare today's close to projected band."""
    y = np.log(frame.close.to_numpy())
    target = np.full(len(y), np.nan)
    position = np.full(len(y), np.nan)
    x = np.arange(window, dtype=float)
    centered = x - x.mean()
    denominator = float(centered @ centered)
    for i in range(window, len(y)):
        history = y[i - window:i]
        slope = float(centered @ history / denominator)
        fitted = history.mean() + slope * centered
        scatter = float(np.std(history - fitted, ddof=2))
        if scatter <= 0:
            continue
        projected = float(history.mean() + slope * (window - x.mean()))
        position[i] = (y[i] - projected) / (width * scatter)
        if trend_gate and slope <= 0:
            target[i] = .7
        elif position[i] <= -1:
            target[i] = 1.
        elif position[i] >= 1:
            target[i] = .7
        else:
            target[i] = .85
    return pd.Series(target), pd.Series(position)


def monthly_volatility_guard(frame: pd.DataFrame) -> pd.Series:
    """70% core; monthly cut risk after high trailing volatility."""
    vol = np.log(frame.close).diff().rolling(20).std() * np.sqrt(244)
    threshold = vol.shift(1).rolling(252, min_periods=252).quantile(.75)
    decision = (vol > threshold).astype(float)
    month_start = frame.date.dt.to_period("M").ne(frame.date.shift().dt.to_period("M"))
    weight = pd.Series(np.where(month_start, 1 - .3 * decision, np.nan)).ffill()
    weight.iloc[:272] = np.nan
    return weight


def main() -> None:
    report = {"status": "retrospective_channel_exploration", "causal_fit": "prior closes only", "symbols": {}}
    for symbol in SYMBOLS:
        raw, adjusted = load_etf_pair(ROOT, symbol)
        dividends, splits = corporate_actions(raw, adjusted, symbol)
        signal_frame = total_return_bars(raw, dividends) if symbol == "510880.SH" else adjusted
        fixed = signals(signal_frame)
        payment = public_payment_indices(raw, symbol, ROOT)
        first = 299
        candidates = {"hold": fixed.hold, "old_high_low_channel": fixed.channel, "macd": fixed.macd,
                      "core70_old_channel30": fixed.core70_channel30, "monthly_volatility_guard": monthly_volatility_guard(signal_frame)}
        positions = {}
        for window in (120, 180):
            for width in (1.5, 2.):
                for trend_gate in (False, True):
                    name = f"rising_channel_{window}_{width}_{'up_only' if trend_gate else 'any_slope'}"
                    candidates[name], positions[name] = rising_channel(signal_frame, window, width, trend_gate)
        results = {}
        for name, target in candidates.items():
            curve, changes, turnover = simulate(raw, target, first, ROUND_TRIP_SIDE_COST,
                                                 dividends=dividends, splits=splits, payment_indices=payment)
            results[name] = {**metrics(curve), "changes": changes, "turnover": turnover,
                             "mean_exposure": float(curve.asset_weight.mean()),
                             "returns_by_year": {str(year): float(group.equity.iloc[-1] / group.equity.iloc[0] - 1)
                                                 for year, group in curve.groupby(curve.date.dt.year) if len(group) > 20}}
        baseline = results["hold"]["cagr"]
        for value in results.values():
            value["cagr_minus_hold"] = value["cagr"] - baseline
        report["symbols"][symbol] = results
    (ROOT / "rising_channel_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for symbol, rows in report["symbols"].items():
        print(symbol, [(key, round(value["cagr"] * 100, 2), round(value["cagr_minus_hold"] * 100, 2), round(value["mdd"] * 100, 2))
                       for key, value in rows.items()])


if __name__ == "__main__":
    main()
