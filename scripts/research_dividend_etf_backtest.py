"""Exploratory dividend ETF timing comparisons using a cash action ledger.

Signals use the completed close. Trades occur at the next available open.
Dividend amounts are inferred from the raw/qfq price difference and credited
on ex-date; full announcement verification and payment timing remain pending.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm


SYMBOLS = ("510880.SH", "512890.SH", "513630.SH", "515080.SH", "159331.SZ")
ROUND_TRIP_SIDE_COST = 0.0005


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    if frame.date.duplicated().any() or frame[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError(f"invalid ETF bars: {path}")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"nonpositive ETF price: {path}")
    return frame


def load_etf_pair(root: Path, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = load(root / f"{symbol}_raw.csv")
    adjusted = pd.read_csv(root / f"{symbol}_qfq.csv", parse_dates=["date"])
    if symbol == "510880.SH":
        bad = pd.Timestamp("2008-01-02")
        copied = pd.Timestamp("2008-12-31")
        bad_row = raw.loc[raw.date == bad]
        copied_row = raw.loc[raw.date == copied]
        fields = ["open", "high", "low", "close", "volume"]
        adjusted_bad = adjusted.loc[adjusted.date == bad]
        adjusted_copied = adjusted.loc[adjusted.date == copied]
        if (len(bad_row) != 1 or len(copied_row) != 1
                or not bad_row[fields].reset_index(drop=True).equals(copied_row[fields].reset_index(drop=True))
                or len(adjusted_bad) != 1 or len(adjusted_copied) != 1
                or not adjusted_bad[fields].reset_index(drop=True).equals(adjusted_copied[fields].reset_index(drop=True))):
            raise ValueError("510880 known bad row changed; recheck upstream")
        raw = raw.loc[raw.date != bad].reset_index(drop=True)
        adjusted = adjusted.loc[adjusted.date != bad].reset_index(drop=True)
    if not raw.date.equals(adjusted.date):
        raise ValueError(f"raw/qfq dates differ: {symbol}")
    return raw, adjusted


def corporate_actions(raw: pd.DataFrame, adjusted: pd.DataFrame, symbol: str) -> tuple[pd.Series, pd.Series]:
    """Infer cash distributions from qfq offsets; handle 512890's verified split."""
    if not raw.date.equals(adjusted.date):
        raise ValueError(f"raw/qfq dates differ: {symbol}")
    dividends = pd.Series(0., index=raw.index)
    splits = pd.Series(1., index=raw.index)
    if symbol == "512890.SH":
        matches = raw.index[raw.date == pd.Timestamp("2021-10-25")]
        if len(matches) != 1:
            raise ValueError("missing 512890 post-split trading date")
        before = raw.date < pd.Timestamp("2021-10-25")
        if not np.allclose(adjusted.close[before], raw.close[before] / 2, atol=.00051) or not np.allclose(adjusted.close[~before], raw.close[~before], atol=.00051):
            raise ValueError("512890 adjustment contains more than the verified 1:2 split")
        splits.iloc[int(matches[0])] = 2.
        return dividends, splits
    if symbol == "159331.SZ":
        snapshot = Path("data/research/dividend_etf/public_payouts.json")
        if not snapshot.exists():
            raise ValueError("159331 requires exact public payout snapshot; run research_dividend_etf_payouts.py")
        payouts = json.loads(snapshot.read_text(encoding="utf-8"))["symbols"][symbol]
        for day, payout in payouts.items():
            match = raw.index[raw.date == pd.Timestamp(day)]
            if len(match) == 1:
                dividends.iloc[int(match[0])] = float(payout["amount"])
        return dividends, splits
    offset = (raw.close - adjusted.close).round(3)
    change = (offset.shift(1) - offset).fillna(0).round(3)
    if (change < -.0005).any():
        raise ValueError(f"negative inferred payout or unhandled action: {symbol}")
    return change.clip(lower=0), splits


def total_return_bars(raw: pd.DataFrame, dividends: pd.Series) -> pd.DataFrame:
    """Positive synthetic total-return path for signals and return labels."""
    frame = raw.copy()
    factor = np.ones(len(frame))
    for i in range(1, len(frame)):
        factor[i] = factor[i - 1] * (1 + float(dividends.iloc[i]) / float(frame.close.iloc[i]))
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].to_numpy() * factor
    return frame


def signals(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame.close
    ma200 = close.rolling(200, min_periods=200).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    high60 = frame.high.shift(1).rolling(60, min_periods=60).max()
    low60 = frame.low.shift(1).rolling(60, min_periods=60).min()
    position = ((close - low60) / (high60 - low60)).clip(0, 1)
    channel = pd.Series(np.select([position <= .25, position >= .75], [1., .25], default=.6), index=frame.index)
    channel[position.isna()] = np.nan
    out = pd.DataFrame({
        "hold": 1.,
        "ma200": (close > ma200).astype(float),
        "macd": (macd > macd_signal).astype(float),
        "channel": channel,
        "ma200_channel": channel * (close > ma200).astype(float),
        "channel_position": position,
        "macd_histogram": macd - macd_signal,
        "mom60": close.pct_change(60),
    })
    out["core70_macd30"] = .7 + .3 * out["macd"]
    out["core70_channel30"] = .7 + .3 * out["channel"]
    return out


def simulate(
    frame: pd.DataFrame,
    target: pd.Series,
    first_index: int,
    cost: float,
    dividends: pd.Series | None = None,
    splits: pd.Series | None = None,
    reinvest_dividends: bool = False,
    dividend_lag_bars: int = 0,
    payment_indices: pd.Series | None = None,
) -> tuple[pd.DataFrame, int, float]:
    if dividend_lag_bars < 0:
        raise ValueError("dividend lag must be nonnegative")
    cash, units, changes, turnover = 1., 0., 0, 0.
    receivable = 0.
    pending: dict[int, float] = {}
    previous_target = 0.
    records = []
    for i in range(first_index + 1, len(frame)):
        settled = pending.pop(i, 0.)
        cash += settled
        receivable -= settled
        if splits is not None:
            units *= float(splits.iloc[i])
        if dividends is not None:
            claim = units * float(dividends.iloc[i])
            due = int(payment_indices.iloc[i]) if payment_indices is not None else i + dividend_lag_bars
            if due > i:
                pending[due] = pending.get(due, 0.) + claim
                receivable += claim
            else:
                cash += claim
        price = float(frame.open.iloc[i])
        desired = float(target.iloc[i - 1])
        if not np.isfinite(desired) or not 0 <= desired <= 1:
            raise ValueError("invalid target allocation")
        before = cash + units * price + receivable
        if desired != previous_target or (reinvest_dividends and (settled > 0 or (dividends is not None and dividends.iloc[i] > 0 and dividend_lag_bars == 0))):
            current_value = units * price
            if desired * before >= current_value:
                target_value = desired * (before + cost * current_value) / (1 + desired * cost)
            else:
                target_value = desired * (before - cost * current_value) / (1 - desired * cost)
            desired_units = target_value / price
            delta = desired_units - units
            if delta > 0:
                delta = min(delta, max(0., cash) / (price * (1 + cost)))
                desired_units = units + delta
            fee = abs(delta) * price * cost
            cash -= delta * price + fee
            units = desired_units
            changes += 1
            turnover += abs(delta) * price / before
            previous_target = desired
        close = float(frame.close.iloc[i])
        equity = cash + units * close + receivable
        records.append({"date": frame.date.iloc[i], "equity": equity, "asset_weight": units * close / equity})
    result = pd.DataFrame(records)
    return result, changes, turnover


def public_payment_indices(frame: pd.DataFrame, symbol: str, root: Path) -> pd.Series:
    """First tradable open on or after each published cash payment date."""
    payouts = json.loads((root / "public_payouts.json").read_text(encoding="utf-8"))["symbols"][symbol]
    due = pd.Series(0, index=frame.index)
    for ex_date, payout in payouts.items():
        ex = frame.index[frame.date == pd.Timestamp(ex_date)]
        if len(ex) != 1:
            raise ValueError(f"missing payout ex-date: {symbol} {ex_date}")
        due.iloc[int(ex[0])] = max(int(ex[0]) + 1, int(frame.date.searchsorted(pd.Timestamp(payout["payment_date"]))))
    return due


def metrics(curve: pd.DataFrame) -> dict:
    if len(curve) < 2:
        return {"status": "insufficient"}
    nav = curve.equity.to_numpy()
    days = (curve.date.iloc[-1] - curve.date.iloc[0]).days
    annual = float(nav[-1] ** (365.25 / days) - 1)
    drawdown = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"days": len(curve), "total_return": float(nav[-1] - 1), "cagr": annual, "mdd": drawdown}


def period_metrics(curve: pd.DataFrame, start: str, end: str) -> dict:
    sub = curve[(curve.date >= start) & (curve.date <= end)]
    if len(sub) < 30:
        return {"status": "insufficient", "days": len(sub)}
    normalized = sub.copy()
    normalized["equity"] /= normalized.equity.iloc[0]
    return metrics(normalized)


def rank_ic(frame: pd.DataFrame, feature: pd.Series, horizon: int = 20) -> dict:
    label = frame.close.shift(-horizon) / frame.close - 1
    valid = feature.notna() & label.notna()
    if valid.sum() < 100:
        return {"status": "insufficient", "n": int(valid.sum())}
    return {"n": int(valid.sum()), "spearman": float(feature[valid].corr(label[valid], method="spearman"))}


def exposure_control(frame: pd.DataFrame, first_index: int, exposure: float, dividends: pd.Series, splits: pd.Series) -> dict:
    """Retrospective, same-average-exposure partial hold; not a tradeable rule."""
    low, high = 0., 1.
    for _ in range(24):
        middle = (low + high) / 2
        curve, _, _ = simulate(frame, pd.Series(middle, index=frame.index), first_index, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
        if curve.asset_weight.mean() < exposure:
            low = middle
        else:
            high = middle
    return {"initial_weight": middle, "realized_exposure": float(curve.asset_weight.mean()), **metrics(curve)}


def residual_diagnostics(curve: pd.DataFrame, hold: pd.DataFrame) -> dict:
    market = hold.equity.pct_change().iloc[1:].to_numpy()
    strategy = curve.equity.pct_change().iloc[1:].to_numpy()
    design = np.column_stack([np.ones(len(market)), market])
    intercept, beta = np.linalg.lstsq(design, strategy, rcond=None)[0]
    residuals = strategy - design @ np.array([intercept, beta])
    fit = sm.OLS(strategy, design).fit(cov_type="HAC", cov_kwds={"maxlags": 20})
    return {
        "daily_intercept": float(intercept), "annualized_intercept_approx": float(intercept * 244),
        "beta": float(beta), "residual_vol_annualized": float(np.std(residuals, ddof=2) * np.sqrt(244)),
        "intercept_hac_t": float(fit.tvalues[0]), "intercept_hac_p": float(fit.pvalues[0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/research/dividend_etf"))
    parser.add_argument("--output", type=Path, default=Path("data/research/dividend_etf/exploratory_results.json"))
    args = parser.parse_args()
    report: dict = {"status": "exploratory", "cost_per_trade_side": ROUND_TRIP_SIDE_COST, "execution": "close signal, next open fill", "price": "raw OHLC plus inferred cash distributions and verified split; distributions remain in cash", "symbols": {}}
    for symbol in SYMBOLS:
        frame, adjusted = load_etf_pair(args.input, symbol)
        dividends, splits = corporate_actions(frame, adjusted, symbol)
        signal_frame = total_return_bars(frame, dividends) if symbol == "510880.SH" else adjusted
        return_frame = signal_frame if symbol == "512890.SH" else total_return_bars(frame, dividends)
        signal = signals(signal_frame)
        first = 199
        item = {"first": frame.date.iloc[0].date().isoformat(), "first_trade": frame.date.iloc[first + 1].date().isoformat(), "last": frame.date.iloc[-1].date().isoformat(), "bars": len(frame), "inferred_dividend_events": int((dividends > 0).sum()), "strategies": {}}
        hold_curve, _, _ = simulate(frame, signal["hold"], first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
        for name in ("hold", "ma200", "macd", "channel", "ma200_channel", "core70_macd30", "core70_channel30"):
            curve, changes, turnover = simulate(frame, signal[name], first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
            exposure = float(curve.asset_weight.mean())
            control = exposure_control(frame, first, exposure, dividends, splits)
            item["strategies"][name] = {
                "overall": metrics(curve), "allocation_changes": changes,
                "turnover": turnover, "mean_exposure": exposure,
                "same_exposure_control": control,
                "cagr_excess_vs_same_exposure_control": metrics(curve)["cagr"] - control["cagr"],
                "residual_vs_hold": residual_diagnostics(curve, hold_curve),
                "2019_2022": period_metrics(curve, "2019-01-01", "2022-12-31"),
                "2023_2024": period_metrics(curve, "2023-01-01", "2024-12-31"),
                "2025_2026": period_metrics(curve, "2025-01-01", "2026-09-24"),
            }
        item["rank_ic_20d"] = {name: rank_ic(return_frame, signal[name]) for name in ("channel_position", "macd_histogram", "mom60")}
        report["symbols"][symbol] = item
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
