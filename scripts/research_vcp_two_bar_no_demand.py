#!/usr/bin/env python3
"""Same VCP leader fills; add two-bar no-demand sell vs baseline exits.

Does not re-run the detector. Independent-trade stats only; no 仓位/资金曲线 pass metric.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_right_side_short_windows import COST_CONFIG, TRAINING_END, net_round_trip  # noqa: E402

from app.backtest.engine import MatcherConfig  # noqa: E402

TRAINING_START = date(2016, 1, 1)
BASELINE_RUN = "20260908T024521089151Z"
DEFAULT_PROTOCOL = ROOT / "docs/research/vcp/two-bar-no-demand-exit-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/vcp/two-bar-no-demand-exit-v1-analysis.json"
DEMAND_PCT = 0.03


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def one_price_limit_down(open_: float, high: float, low: float, close: float) -> bool:
    prices = (open_, high, low, close)
    if not all(np.isfinite(p) and p > 0 for p in prices):
        return False
    return max(prices) - min(prices) <= max(abs(close) * 1e-4, 0.01)


def apply_two_bar_no_demand_to_fill(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    baseline_pnl: float,
    sessions: list[dict],
    market_calendar: list[date],
    config: MatcherConfig = COST_CONFIG,
    demand_pct: float = DEMAND_PCT,
    require_underwater: bool = False,
) -> dict:
    """Shorten a filled T+1 trade when the first two *market* session highs never reach +demand_pct.

    A hole in the stock's bars on a market session does not roll to the next stock bar.
    """
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if entry_date not in calendar:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "missing_entry_bar"}
    idx = calendar.index(entry_date)
    if idx + 2 >= len(calendar):
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "missing_early_exit_bar"}
    day0, day1, early_day = calendar[idx], calendar[idx + 1], calendar[idx + 2]
    if day0 not in by_date:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "missing_entry_bar"}
    if day1 not in by_date or early_day not in by_date:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "missing_early_exit_bar"}
    first = by_date[day0]
    second = by_date[day1]
    early = by_date[early_day]
    if day1 > exit_date:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "baseline_already_out"}
    highs = [float(first["high"]), float(second["high"])]
    if not all(np.isfinite(h) and h > 0 for h in highs) or not np.isfinite(entry_price) or entry_price <= 0:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "missing_high"}
    mfe = max(highs) / float(entry_price) - 1.0
    if mfe >= demand_pct:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "demand_printed", "mfe": mfe}
    if early_day >= exit_date:
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "baseline_already_out", "mfe": mfe}
    if require_underwater:
        second_close = float(second.get("close") or 0.0)
        if not np.isfinite(second_close) or second_close <= 0:
            return {"pnl": float(baseline_pnl), "shortened": False, "reason": "missing_close", "mfe": mfe}
        if second_close >= entry_price:
            return {"pnl": float(baseline_pnl), "shortened": False, "reason": "entry_price_held", "mfe": mfe}
    open_px = float(early["open"])
    volume = float(early.get("volume") or 0.0)
    if (
        not np.isfinite(open_px)
        or open_px <= 0
        or volume <= 0
        or one_price_limit_down(
            open_px,
            float(early["high"]),
            float(early["low"]),
            float(early["close"]),
        )
    ):
        return {"pnl": float(baseline_pnl), "shortened": False, "reason": "early_exit_blocked", "mfe": mfe}
    gross = open_px / float(entry_price) - 1.0
    pnl = net_round_trip(gross, config.buy_cost_pct(), config.sell_cost_pct(early_day))
    return {
        "pnl": float(pnl),
        "shortened": True,
        "reason": "two_bar_no_demand",
        "mfe": mfe,
        "early_exit_date": early_day.isoformat(),
        "early_exit_price": open_px,
    }


def apply_breakeven_after_gain_to_fill(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    baseline_pnl: float,
    sessions: list[dict],
    market_calendar: list[date],
    config: MatcherConfig = COST_CONFIG,
    activate_pct: float = 0.05,
    last_bar: date | None = None,
) -> dict:
    """After a close reaches +activate_pct, sell next open if close falls back below entry."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    unchanged = {"pnl": float(baseline_pnl), "shortened": False, "reason": "no_breakeven"}
    if entry_date not in calendar or not np.isfinite(entry_price) or entry_price <= 0:
        return {**unchanged, "reason": "missing_entry_bar"}
    start = calendar.index(entry_date)
    armed = False
    for i in range(start, len(calendar)):
        day = calendar[i]
        if day >= exit_date:
            break
        bar = by_date.get(day)
        if bar is None:
            return {**unchanged, "reason": "missing_bar"}
        close = float(bar.get("close") or 0.0)
        if not np.isfinite(close) or close <= 0:
            return {**unchanged, "reason": "missing_close"}
        if close >= float(entry_price) * (1.0 + activate_pct):
            armed = True
        if not armed or close >= float(entry_price):
            continue
        if i + 1 >= len(calendar):
            return {**unchanged, "reason": "missing_exit_bar"}
        next_day = calendar[i + 1]
        if next_day >= exit_date:
            return {**unchanged, "reason": "baseline_already_out"}
        fill = by_date.get(next_day)
        if fill is None:
            return {**unchanged, "reason": "missing_exit_bar"}
        open_px = float(fill.get("open") or 0.0)
        volume = float(fill.get("volume") or 0.0)
        if (
            not np.isfinite(open_px)
            or open_px <= 0
            or volume <= 0
            or one_price_limit_down(
                open_px,
                float(fill.get("high") or 0.0),
                float(fill.get("low") or 0.0),
                float(fill.get("close") or 0.0),
            )
        ):
            return {**unchanged, "reason": "early_exit_blocked"}
        pnl = net_round_trip(
            open_px / float(entry_price) - 1.0,
            config.buy_cost_pct(),
            config.sell_cost_pct(next_day),
        )
        return {
            "pnl": float(pnl),
            "shortened": True,
            "reason": "breakeven_after_gain",
            "signal_date": day.isoformat(),
            "early_exit_date": next_day.isoformat(),
            "early_exit_price": open_px,
        }
    return unchanged


def apply_ma_cross_exit_to_fill(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    baseline_pnl: float,
    sessions: list[dict],
    market_calendar: list[date],
    config: MatcherConfig = COST_CONFIG,
    ma_days: int = 10,
    last_bar: date | None = None,
) -> dict:
    """Sell next market open after close crosses below MA`ma_days`. Holes and incomplete MA do not roll."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    unchanged = {"pnl": float(baseline_pnl), "shortened": False, "reason": "no_cross"}
    if entry_date not in calendar:
        return {**unchanged, "reason": "missing_entry_bar"}
    closes = np.full(len(calendar), np.nan)
    for i, day in enumerate(calendar):
        bar = by_date.get(day)
        if bar is None:
            continue
        close = float(bar.get("close") or np.nan)
        if np.isfinite(close) and close > 0:
            closes[i] = close

    def _ma(idx: int) -> float:
        if idx + 1 < ma_days:
            return np.nan
        chunk = closes[idx - ma_days + 1 : idx + 1]
        if not np.all(np.isfinite(chunk)):
            return np.nan
        return float(chunk.mean())

    start = calendar.index(entry_date)
    saw_complete_ma = False
    for i in range(start, len(calendar)):
        day = calendar[i]
        if day >= exit_date:
            break
        if not np.isfinite(closes[i]):
            return {**unchanged, "reason": "missing_bar"}
        if i < 1 or not np.isfinite(closes[i - 1]):
            if i >= 1 and not np.isfinite(closes[i - 1]):
                return {**unchanged, "reason": "missing_bar"}
            continue
        ma = _ma(i)
        prev_ma = _ma(i - 1)
        if not np.isfinite(ma) or not np.isfinite(prev_ma):
            continue
        saw_complete_ma = True
        if not (closes[i - 1] >= prev_ma and closes[i] < ma):
            continue
        if i + 1 >= len(calendar):
            return {**unchanged, "reason": "missing_exit_bar"}
        next_day = calendar[i + 1]
        if next_day >= exit_date:
            return {**unchanged, "reason": "baseline_already_out"}
        fill = by_date.get(next_day)
        if fill is None:
            return {**unchanged, "reason": "missing_exit_bar"}
        open_px = float(fill.get("open") or 0.0)
        volume = float(fill.get("volume") or 0.0)
        if (
            not np.isfinite(open_px)
            or open_px <= 0
            or volume <= 0
            or one_price_limit_down(
                open_px,
                float(fill.get("high") or 0.0),
                float(fill.get("low") or 0.0),
                float(fill.get("close") or 0.0),
            )
        ):
            return {**unchanged, "reason": "early_exit_blocked"}
        if not np.isfinite(entry_price) or entry_price <= 0:
            return {**unchanged, "reason": "missing_entry_bar"}
        pnl = net_round_trip(
            open_px / float(entry_price) - 1.0,
            config.buy_cost_pct(),
            config.sell_cost_pct(next_day),
        )
        return {
            "pnl": float(pnl),
            "shortened": True,
            "reason": "ma_cross",
            "signal_date": day.isoformat(),
            "early_exit_date": next_day.isoformat(),
            "early_exit_price": open_px,
        }
    if not saw_complete_ma:
        return {**unchanged, "reason": "incomplete_ma"}
    return unchanged


DRAWDOWN_PCT = 0.08


def apply_peak_close_drawdown_to_fill(
    *,
    entry_date: date,
    exit_date: date,
    entry_price: float,
    baseline_pnl: float,
    sessions: list[dict],
    market_calendar: list[date],
    config: MatcherConfig = COST_CONFIG,
    drawdown_pct: float = DRAWDOWN_PCT,
    last_bar: date | None = None,
) -> dict:
    """Sell next market open after close retraces `drawdown_pct` from the post-entry peak close.

    Peak is max completed close from entry day, not high. A stock hole on a market
    session does not roll; the original exit is kept.
    """
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    unchanged = {"pnl": float(baseline_pnl), "shortened": False, "reason": "no_drawdown"}
    if entry_date not in calendar:
        return {**unchanged, "reason": "missing_entry_bar"}
    start = calendar.index(entry_date)
    peak = None
    floor = 1.0 - float(drawdown_pct)
    for i in range(start, len(calendar)):
        day = calendar[i]
        if day >= exit_date:
            break
        bar = by_date.get(day)
        if bar is None:
            return {**unchanged, "reason": "missing_bar"}
        close = float(bar.get("close") or 0.0)
        if not np.isfinite(close) or close <= 0:
            return {**unchanged, "reason": "missing_close"}
        peak = close if peak is None else max(peak, close)
        if close > peak * floor:
            continue
        if i + 1 >= len(calendar):
            return {**unchanged, "reason": "missing_exit_bar", "peak": peak}
        next_day = calendar[i + 1]
        if next_day >= exit_date:
            return {**unchanged, "reason": "baseline_already_out", "peak": peak}
        fill = by_date.get(next_day)
        if fill is None:
            return {**unchanged, "reason": "missing_exit_bar", "peak": peak}
        open_px = float(fill.get("open") or 0.0)
        volume = float(fill.get("volume") or 0.0)
        if (
            not np.isfinite(open_px)
            or open_px <= 0
            or volume <= 0
            or one_price_limit_down(
                open_px,
                float(fill.get("high") or 0.0),
                float(fill.get("low") or 0.0),
                float(fill.get("close") or 0.0),
            )
        ):
            return {**unchanged, "reason": "early_exit_blocked", "peak": peak}
        if not np.isfinite(entry_price) or entry_price <= 0:
            return {**unchanged, "reason": "missing_entry_bar"}
        pnl = net_round_trip(
            open_px / float(entry_price) - 1.0,
            config.buy_cost_pct(),
            config.sell_cost_pct(next_day),
        )
        return {
            "pnl": float(pnl),
            "shortened": True,
            "reason": "peak_close_drawdown",
            "peak": peak,
            "signal_date": day.isoformat(),
            "early_exit_date": next_day.isoformat(),
            "early_exit_price": open_px,
        }
    return unchanged


def find_stabilize_entry(
    *,
    signal_date: date,
    exit_date: date,
    sessions: list[dict],
    market_calendar: list[date],
    window: int = 3,
    last_bar: date | None = None,
) -> dict:
    """First yang bar that closes above the prior session close, within `window` sessions after signal."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    miss = {"filled": False, "reason": "no_stabilize"}
    if signal_date not in calendar:
        return {**miss, "reason": "missing_signal_bar"}
    idx = calendar.index(signal_date)
    for j in range(1, window + 1):
        day_idx = idx + j
        buy_idx = day_idx + 1
        if day_idx >= len(calendar) or buy_idx >= len(calendar):
            return {**miss, "reason": "window_end"}
        day = calendar[day_idx]
        prev_day = calendar[day_idx - 1]
        buy_day = calendar[buy_idx]
        if day >= exit_date or buy_day >= exit_date:
            return {**miss, "reason": "baseline_already_out"}
        bar = by_date.get(day)
        prev = by_date.get(prev_day)
        if bar is None or prev is None:
            return {**miss, "reason": "missing_bar"}
        open_px = float(bar.get("open") or 0.0)
        close = float(bar.get("close") or 0.0)
        prev_close = float(prev.get("close") or 0.0)
        if not all(np.isfinite(v) and v > 0 for v in (open_px, close, prev_close)):
            return {**miss, "reason": "missing_bar"}
        if not (close > open_px and close > prev_close):
            continue
        fill = by_date.get(buy_day)
        if fill is None:
            return {**miss, "reason": "blocked_buy"}
        buy_open = float(fill.get("open") or 0.0)
        volume = float(fill.get("volume") or 0.0)
        if (
            not np.isfinite(buy_open)
            or buy_open <= 0
            or volume <= 0
            or one_price_limit_down(
                buy_open,
                float(fill.get("high") or 0.0),
                float(fill.get("low") or 0.0),
                float(fill.get("close") or 0.0),
            )
        ):
            return {**miss, "reason": "blocked_buy"}
        return {
            "filled": True,
            "reason": "stabilize",
            "stabilize_date": day.isoformat(),
            "entry_date": buy_day.isoformat(),
            "entry_price": buy_open,
        }
    return miss


def find_shrink_pullback_entry(
    *,
    signal_date: date,
    exit_date: date,
    sessions: list[dict],
    market_calendar: list[date],
    lookback: int = 20,
    window: int = 8,
    last_bar: date | None = None,
) -> dict:
    """First shrink-volume pullback within `window` market sessions after the signal bar."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if last_bar is not None:
        calendar = [day for day in calendar if day <= last_bar]
    miss = {"filled": False, "reason": "no_pullback"}
    if signal_date not in calendar:
        return {**miss, "reason": "missing_signal_bar"}
    signal = by_date.get(signal_date)
    if signal is None:
        return {**miss, "reason": "missing_signal_bar"}
    signal_close = float(signal.get("close") or 0.0)
    signal_low = float(signal.get("low") or 0.0)
    if not np.isfinite(signal_close) or not np.isfinite(signal_low) or signal_close <= 0 or signal_low <= 0:
        return {**miss, "reason": "missing_signal_bar"}
    idx = calendar.index(signal_date)

    def _mean_volume(end_idx: int) -> float | None:
        if end_idx < lookback:
            return None
        vols: list[float] = []
        for day in calendar[end_idx - lookback : end_idx]:
            row = by_date.get(day)
            if row is None:
                return None
            volume = float(row.get("volume") or 0.0)
            if not np.isfinite(volume) or volume <= 0:
                return None
            vols.append(volume)
        return float(sum(vols) / len(vols))

    for j in range(1, window + 1):
        day_idx = idx + j
        buy_idx = day_idx + 1
        if day_idx >= len(calendar) or buy_idx >= len(calendar):
            return {**miss, "reason": "window_end"}
        day = calendar[day_idx]
        buy_day = calendar[buy_idx]
        if day >= exit_date or buy_day >= exit_date:
            return {**miss, "reason": "baseline_already_out"}
        bar = by_date.get(day)
        if bar is None:
            return {**miss, "reason": "missing_bar"}
        mean_volume = _mean_volume(day_idx)
        if mean_volume is None:
            return {**miss, "reason": "missing_volume_history"}
        volume = float(bar.get("volume") or 0.0)
        close = float(bar.get("close") or 0.0)
        low = float(bar.get("low") or 0.0)
        if not all(np.isfinite(v) and v > 0 for v in (volume, close, low)):
            return {**miss, "reason": "missing_bar"}
        if volume >= mean_volume or close >= signal_close or low < signal_low:
            continue
        fill = by_date.get(buy_day)
        if fill is None:
            return {**miss, "reason": "blocked_buy"}
        open_px = float(fill.get("open") or 0.0)
        fill_volume = float(fill.get("volume") or 0.0)
        if (
            not np.isfinite(open_px)
            or open_px <= 0
            or fill_volume <= 0
            or one_price_limit_down(
                open_px,
                float(fill.get("high") or 0.0),
                float(fill.get("low") or 0.0),
                float(fill.get("close") or 0.0),
            )
        ):
            return {**miss, "reason": "blocked_buy"}
        return {
            "filled": True,
            "reason": "shrink_pullback",
            "pullback_date": day.isoformat(),
            "entry_date": buy_day.isoformat(),
            "entry_price": open_px,
        }
    return miss


def pullback_round_trip(
    *,
    new_entry_price: float,
    exit_price: float,
    exit_date: date,
    config: MatcherConfig = COST_CONFIG,
) -> float:
    return float(
        net_round_trip(
            float(exit_price) / float(new_entry_price) - 1.0,
            config.buy_cost_pct(),
            config.sell_cost_pct(exit_date),
        )
    )


def breakout_bullish_bar(
    *,
    signal_date: date,
    sessions: list[dict],
    market_calendar: list[date],
) -> dict:
    """True when the breakout bar closes above its open."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if signal_date not in calendar:
        return {"bullish": False, "reason": "missing_breakout_bar"}
    bar = by_date.get(signal_date)
    if bar is None:
        return {"bullish": False, "reason": "missing_breakout_bar"}
    open_px = float(bar.get("open") or 0.0)
    close = float(bar.get("close") or 0.0)
    if not np.isfinite(open_px) or not np.isfinite(close) or open_px <= 0 or close <= 0:
        return {"bullish": False, "reason": "missing_range"}
    bullish = close > open_px
    return {"bullish": bullish, "reason": "yang" if bullish else "yin"}


def breakout_close_upper_half(
    *,
    signal_date: date,
    sessions: list[dict],
    market_calendar: list[date],
    min_location: float = 0.5,
) -> dict:
    """True when the breakout bar closes in the upper fraction of its high-low range."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if signal_date not in calendar:
        return {"upper": False, "reason": "missing_breakout_bar"}
    bar = by_date.get(signal_date)
    if bar is None:
        return {"upper": False, "reason": "missing_breakout_bar"}
    high = float(bar.get("high") or 0.0)
    low = float(bar.get("low") or 0.0)
    close = float(bar.get("close") or 0.0)
    if not all(np.isfinite(v) for v in (high, low, close)) or high <= 0 or close <= 0:
        return {"upper": False, "reason": "missing_range"}
    span = high - low
    if span <= 0:
        return {"upper": False, "reason": "zero_range"}
    location = (close - low) / span
    upper = location >= float(min_location)
    return {
        "upper": upper,
        "reason": "upper_half" if upper else "lower_half",
        "location": location,
    }


def breakout_low_holds_prior_low(
    *,
    signal_date: date,
    sessions: list[dict],
    market_calendar: list[date],
) -> dict:
    """True when the breakout bar's low does not undercut the prior market session low."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if signal_date not in calendar:
        return {"holds": False, "reason": "missing_breakout_bar"}
    idx = calendar.index(signal_date)
    if idx < 1:
        return {"holds": False, "reason": "missing_prior_bar"}
    prior_day, day = calendar[idx - 1], calendar[idx]
    prior = by_date.get(prior_day)
    cur = by_date.get(day)
    if prior is None:
        return {"holds": False, "reason": "missing_prior_bar"}
    if cur is None:
        return {"holds": False, "reason": "missing_breakout_bar"}
    prior_low = float(prior["low"])
    cur_low = float(cur["low"])
    if not np.isfinite(prior_low) or not np.isfinite(cur_low) or prior_low <= 0 or cur_low <= 0:
        return {"holds": False, "reason": "missing_low"}
    holds = cur_low >= prior_low
    return {
        "holds": holds,
        "reason": "holds_prior_low" if holds else "undercut_prior_low",
        "prior_low": prior_low,
        "breakout_low": cur_low,
    }


def breakout_volume_expanded(
    *,
    signal_date: date,
    sessions: list[dict],
    market_calendar: list[date],
    lookback: int = 20,
) -> dict:
    """True when breakout-day volume >= mean of the prior `lookback` market sessions.

    A hole on any of those market sessions is not expanded (no roll).
    """
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if signal_date not in calendar:
        return {"expanded": False, "reason": "missing_breakout_bar"}
    idx = calendar.index(signal_date)
    if idx < lookback:
        return {"expanded": False, "reason": "insufficient_lookback"}
    prior = calendar[idx - lookback : idx]
    vols: list[float] = []
    for day in prior:
        row = by_date.get(day)
        if row is None:
            return {"expanded": False, "reason": "missing_prior_bar"}
        volume = float(row.get("volume") or 0.0)
        if not np.isfinite(volume) or volume <= 0:
            return {"expanded": False, "reason": "missing_prior_bar"}
        vols.append(volume)
    mean_volume = float(sum(vols) / len(vols))
    breakout = by_date.get(signal_date)
    if breakout is None:
        return {"expanded": False, "reason": "missing_breakout_bar", "mean_volume": mean_volume}
    volume = float(breakout.get("volume") or 0.0)
    if not np.isfinite(volume) or volume <= 0:
        return {"expanded": False, "reason": "missing_breakout_bar", "mean_volume": mean_volume}
    expanded = volume >= mean_volume
    return {
        "expanded": expanded,
        "reason": "expanded" if expanded else "quiet_breakout",
        "volume": volume,
        "mean_volume": mean_volume,
    }


def prebreakout_volume_contracted(
    *,
    signal_date: date,
    sessions: list[dict],
    market_calendar: list[date],
    short: int = 5,
    long: int = 20,
) -> dict:
    """True when mean volume of the last `short` market sessions before the break < long-window mean."""
    by_date = {_as_date(row["date"]): row for row in sessions}
    calendar = sorted({_as_date(day) for day in market_calendar})
    if signal_date not in calendar:
        return {"contracted": False, "reason": "missing_breakout_bar"}
    idx = calendar.index(signal_date)
    if idx < long:
        return {"contracted": False, "reason": "insufficient_lookback"}
    long_days = calendar[idx - long : idx]
    short_days = calendar[idx - short : idx]
    def _mean(days: list[date]) -> float | None:
        vols: list[float] = []
        for day in days:
            row = by_date.get(day)
            if row is None:
                return None
            volume = float(row.get("volume") or 0.0)
            if not np.isfinite(volume) or volume <= 0:
                return None
            vols.append(volume)
        return float(sum(vols) / len(vols))

    long_mean = _mean(long_days)
    short_mean = _mean(short_days)
    if long_mean is None or short_mean is None:
        return {"contracted": False, "reason": "missing_prior_bar"}
    contracted = short_mean < long_mean
    return {
        "contracted": contracted,
        "expanding": not contracted,
        "reason": "contracted" if contracted else "not_contracted",
        "short_mean": short_mean,
        "long_mean": long_mean,
    }


def independent_trade_stats(pnls: list[float]) -> dict:
    values = np.asarray(pnls, dtype=np.float64)
    if values.size == 0:
        return {
            "n_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "avg_pnl": None,
            "avg_win": None,
            "avg_loss": None,
        }
    wins = values[values > 0]
    losses = values[values <= 0]
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = abs(float(losses.mean())) if losses.size else 0.0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else None
    return {
        "n_trades": int(values.size),
        "win_rate": _round(float((values > 0).mean())),
        "profit_factor": None if profit_factor is None else round(profit_factor, 2),
        "avg_pnl": _round(float(values.mean())),
        "avg_win": _round(avg_win),
        "avg_loss": _round(avg_loss),
    }


def verdict(variant: dict, baseline: dict) -> str:
    if variant["avg_pnl"] is None or baseline["avg_pnl"] is None:
        return "blocked_incomplete"
    if variant["avg_pnl"] < baseline["avg_pnl"]:
        return "drop"
    if (
        variant["profit_factor"] is not None
        and baseline["profit_factor"] is not None
        and variant["profit_factor"] < baseline["profit_factor"]
        and variant["avg_pnl"] <= 0
    ):
        return "drop"
    return "keep"


def training_trades(trades: list[dict]) -> list[dict]:
    out = []
    for trade in trades:
        entry = _as_date(trade["entry_date"])
        exit_day = _as_date(trade["exit_date"])
        if TRAINING_START <= entry <= TRAINING_END and exit_day <= TRAINING_END:
            out.append(trade)
    return out


def load_symbol_sessions(
    data_root: Path, symbols: list[str], start: date, end: date
) -> tuple[dict[str, list[dict]], list[date]]:
    files = [
        path
        for path in sorted((data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={start.isoformat()}" <= path.parent.name <= f"date={end.isoformat()}"
    ]
    if not files:
        return {}, []
    calendar = [_as_date(path.parent.name.removeprefix("date=")) for path in files]
    wanted = set(symbols)
    bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").is_in(sorted(wanted)))
        .select("symbol", "date", "open", "high", "low", "close", "volume")
        .collect()
    )
    grouped: dict[str, list[dict]] = {}
    for row in bars.sort(["symbol", "date"]).iter_rows(named=True):
        grouped.setdefault(str(row["symbol"]), []).append(row)
    return grouped, calendar


def run_contrast(
    trades: list[dict], sessions: dict[str, list[dict]], market_calendar: list[date],
    *, require_underwater: bool = False, ledger: list[dict] | None = None,
) -> dict:
    baseline_pnls = []
    variant_pnls = []
    shortened = 0
    blocked = 0
    for trade in trades:
        symbol = str(trade["symbol"])
        applied = apply_two_bar_no_demand_to_fill(
            entry_date=_as_date(trade["entry_date"]),
            exit_date=_as_date(trade["exit_date"]),
            entry_price=float(trade["entry_price"]),
            baseline_pnl=float(trade["pnl_pct"]),
            sessions=sessions.get(symbol, []),
            market_calendar=market_calendar,
            require_underwater=require_underwater,
        )
        if ledger is not None:
            ledger.append({"symbol": symbol, "entry_date": trade["entry_date"],
                           "signal_date": trade["entry_signal_date"],
                           "baseline_pnl": float(trade["pnl_pct"]), **applied})
        baseline_pnls.append(float(trade["pnl_pct"]))
        variant_pnls.append(float(applied["pnl"]))
        if applied.get("shortened"):
            shortened += 1
        if applied.get("reason") in {"missing_entry_bar", "missing_early_exit_bar", "early_exit_blocked", "missing_high", "missing_close"}:
            blocked += 1
    baseline = independent_trade_stats(baseline_pnls)
    variant = independent_trade_stats(variant_pnls)
    return {
        "experiment": "vcp-two-bar-no-demand-exit-v1",
        "baseline_run": BASELINE_RUN,
        "training_start": TRAINING_START.isoformat(),
        "training_end": TRAINING_END.isoformat(),
        "shortened": shortened,
        "blocked_kept_baseline": blocked,
        "baseline": baseline,
        "variant": variant,
        "delta": {
            "avg_pnl": _round((variant["avg_pnl"] or 0) - (baseline["avg_pnl"] or 0))
            if variant["avg_pnl"] is not None and baseline["avg_pnl"] is not None
            else None,
            "win_rate": _round((variant["win_rate"] or 0) - (baseline["win_rate"] or 0))
            if variant["win_rate"] is not None and baseline["win_rate"] is not None
            else None,
            "profit_factor": None
            if variant["profit_factor"] is None or baseline["profit_factor"] is None
            else round(variant["profit_factor"] - baseline["profit_factor"], 2),
        },
        "rule": verdict(variant, baseline),
        "pass_metric": "independent_avg_pnl_and_payoff",
        "gaps": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--baseline-run", default=BASELINE_RUN)
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ledger")
    args = parser.parse_args()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_file():
        raise SystemExit(f"protocol missing: {protocol_path}")
    result_path = Path(args.runs_root) / args.baseline_run / "result.json"
    if not result_path.is_file():
        report = {
            "experiment": "vcp-two-bar-no-demand-exit-v1",
            "gaps": [f"missing frozen ledger {result_path}"],
            "rule": "blocked_missing_bars",
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 1
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    trades = training_trades(payload.get("trades") or [])
    symbols = sorted({str(t["symbol"]) for t in trades})
    starts = [_as_date(t["entry_date"]) for t in trades]
    ends = [_as_date(t["exit_date"]) for t in trades]
    sessions, calendar = load_symbol_sessions(Path(args.data_root), symbols, min(starts), max(ends))
    if not sessions or not calendar:
        report = {
            "experiment": "vcp-two-bar-no-demand-exit-v1",
            "gaps": ["no kline_daily_enriched bars for frozen fills"],
            "rule": "blocked_missing_bars",
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 1
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    ledger = [] if args.ledger else None
    report = run_contrast(trades, sessions, calendar,
                          require_underwater=protocol.get("require_underwater", False), ledger=ledger)
    if ledger is not None:
        pl.DataFrame(ledger, infer_schema_length=None).write_parquet(args.ledger)
    report["baseline_run"] = args.baseline_run
    report["experiment"] = json.loads(protocol_path.read_text(encoding="utf-8"))["experiment"]
    report["protocol"] = str(protocol_path)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "rule": report["rule"], **report["variant"], "baseline": report["baseline"], "delta": report["delta"], "shortened": report["shortened"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
