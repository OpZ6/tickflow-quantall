#!/usr/bin/env python3
"""Sequence-2 leader-universe + dual-regime gate contrast.

Membership, T+1 window labels and date-EW metrics are pure functions over
signal-day-visible arrays. Does not run a VCP / cup-handle / flag detector.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_right_side_short_windows import (  # noqa: E402
    COST_CONFIG,
    TRAINING_END,
    WINDOWS,
    geometric_excess,
    net_round_trip,
    signal_day_equal_weight,
)
from app.backtest.engine import MatcherConfig  # noqa: E402
from app.backtest.matrix import (  # noqa: E402
    MarketDataMatrix,
    build_market_data_matrix,
    valid_rolling_max,
    valid_rolling_mean,
    valid_shift,
)
from app.strategy.builtin._quants_vcp import (  # noqa: E402
    fresh_20d_breakout_opportunity_mask,
    market_breadth_allowed,
    market_outperformance_allowed,
    trend_context,
)

TRAINING_START = date(2016, 1, 1)
DATA_START = date(2015, 1, 5)
RS_MIN = 85.0
EXCLUDE_NEW_DAYS = 30
PRICE_MIN = 3.0
PRICE_MAX = 300.0
AMOUNT_MIN = 20_000_000.0
DUAL_REGIME_PARAMS = {
    "a_share_dual_regime": True,
    "include_middle_expansion_regime": False,
}
RS_PARAMS = {"trend_filter": False, "rs_min": RS_MIN}
ST_TOKENS = ("ST", "*ST", "退")
RETURN_CLIP = 0.5
UNIVERSE_RS85 = "rs85"
UNIVERSE_SAME_DAY_OUTPERFORMANCE = "same_day_outperformance"
DEFAULT_PROTOCOL = ROOT / "docs/research/leader-universe-market-gate-v2.json"
DEFAULT_OUTPUT = ROOT / "docs/research/leader-universe-market-gate-v2-analysis.json"


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def hs_board_mask(symbols: Sequence[str]) -> np.ndarray:
    return np.array(
        [str(symbol).endswith(".SH") or str(symbol).endswith(".SZ") for symbol in symbols],
        dtype=bool,
    )


def st_name_mask(names: Sequence[str]) -> np.ndarray:
    """True when the shipped basic-filter ST tokens appear in the name."""
    flags = []
    for name in names:
        text = str(name or "").upper()
        flags.append(any(token in text for token in ST_TOKENS))
    return np.array(flags, dtype=bool)


def listing_session_age(
    calendar: list[date], listing_dates: list[date | None]
) -> np.ndarray:
    """Market-session age; listing session is day one. Unknown listing_date is NaN.

    Listings before the first calendar date are older than this sample prefix, so
    age is treated as infinite rather than restarting at 1 on calendar[0].
    """
    cal = np.array([day.toordinal() for day in calendar], dtype=np.int32)
    listed = np.array(
        [day.toordinal() if day is not None else -1 for day in listing_dates],
        dtype=np.int32,
    )
    first = np.searchsorted(cal, np.maximum(listed, 0), side="left").astype(np.int32)
    unknown = listed < 0
    before = (listed >= 0) & (listed < int(cal[0]))
    times = np.arange(len(calendar), dtype=np.int32)[:, None]
    age = (times - first[None, :] + 1).astype(np.float64)
    age[:, unknown] = np.nan
    age[:, before] = np.inf
    age[times < first[None, :]] = np.nan
    age[:, (~unknown) & (~before) & (first >= len(calendar))] = np.nan
    return age


def observed_valid_bar_count(valid: np.ndarray) -> np.ndarray:
    return np.cumsum(np.asarray(valid, dtype=np.int32), axis=0)


def tradable_eligibility_mask(
    *,
    symbols: Sequence[str],
    names: Sequence[str],
    listing_dates: Sequence[date | None],
    calendar: list[date],
    raw_close: np.ndarray,
    amount: np.ndarray,
    valid: np.ndarray,
    tradable: np.ndarray,
    volume: np.ndarray,
    price_min: float = PRICE_MIN,
    price_max: float = PRICE_MAX,
    amount_min: float = AMOUNT_MIN,
    exclude_new_days: int = EXCLUDE_NEW_DAYS,
) -> np.ndarray:
    """Signal-day 可交易资格. Not a score. No market-cap / 年高 / 趋势模板 / VCP."""
    board = hs_board_mask(symbols)
    st = st_name_mask(names)
    age = listing_session_age(calendar, list(listing_dates))
    observed = observed_valid_bar_count(valid)
    listing_ok = np.where(np.isfinite(age) | np.isinf(age), age > exclude_new_days, observed > exclude_new_days)
    price_ok = np.isfinite(raw_close) & (raw_close >= price_min) & (raw_close <= price_max)
    amount_ok = np.isfinite(amount) & (amount >= amount_min)
    liquid = (
        np.asarray(valid, dtype=bool)
        & np.asarray(tradable, dtype=bool)
        & np.isfinite(volume)
        & (volume > 0)
    )
    return liquid & price_ok & amount_ok & listing_ok & board[None, :] & ~st[None, :]


def dual_regime_gate(market: MarketDataMatrix) -> tuple[np.ndarray, np.ndarray]:
    valid = np.isfinite(market.close) & (market.close > 0)
    ma20 = valid_rolling_mean(market.close, valid, 20, bar_index=market.valid_bars)
    return market_breadth_allowed(
        market.close, ma20, DUAL_REGIME_PARAMS, market.valid_bars
    )


def rs_universe_mask(
    market: MarketDataMatrix, rs_min: float = RS_MIN
) -> tuple[np.ndarray, np.ndarray]:
    """Frozen leader RS ranks without 趋势模板 or 距年高. v1 universe (failed)."""
    return trend_context(market, {"trend_filter": False, "rs_min": float(rs_min)})


def same_day_outperformance_mask(market: MarketDataMatrix) -> np.ndarray:
    """Signal-day close-to-close beat of the same-day equal-weight market. v2 universe."""
    return market_outperformance_allowed(market.close, market.valid_bars)


def universe_mask(
    market: MarketDataMatrix, definition: str = UNIVERSE_SAME_DAY_OUTPERFORMANCE
) -> np.ndarray:
    if definition == UNIVERSE_RS85:
        in_rs, _ranks = rs_universe_mask(market)
        return in_rs
    if definition == UNIVERSE_SAME_DAY_OUTPERFORMANCE:
        return same_day_outperformance_mask(market)
    raise ValueError(f"unknown universe definition: {definition}")


def selected_and_unselected(
    gate: np.ndarray, eligible: np.ndarray, in_rs_universe: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    open_gate = np.asarray(gate, dtype=bool)[:, None]
    selected = open_gate & eligible & in_rs_universe
    unselected = open_gate & eligible & ~in_rs_universe
    return selected, unselected


def watch_list_mask(
    gate: np.ndarray, eligible: np.ndarray, in_rs_universe: np.ndarray
) -> np.ndarray:
    """Look-at set: dual-regime open ∩ RS>=85 ∩ 可买. Not a buy-all book."""
    return np.asarray(gate, dtype=bool)[:, None] & eligible & in_rs_universe


def triggered_and_untriggered(
    watch: np.ndarray, breakout: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    watch = np.asarray(watch, dtype=bool)
    breakout = np.asarray(breakout, dtype=bool)
    return watch & breakout, watch & ~breakout


def close_above_prior_20_high_mask(market: MarketDataMatrix) -> np.ndarray:
    """Close above the prior 20 valid-bar high. No cooldown. Causal high is shifted one valid bar."""
    valid = np.isfinite(market.close) & (market.close > 0)
    prior_high = valid_shift(
        valid_rolling_max(market.high, valid, 20, bar_index=market.valid_bars),
        1,
        valid,
        bar_index=market.valid_bars,
    )
    return (
        valid
        & np.isfinite(prior_high)
        & (market.close > prior_high)
    )


def inside_bar_breakout_mask(market: MarketDataMatrix) -> np.ndarray:
    """Close above the prior bar's high after that bar was inside the bar before it."""
    high = np.asarray(market.high, dtype=np.float64)
    low = np.asarray(market.low, dtype=np.float64)
    close = np.asarray(market.close, dtype=np.float64)
    prior_high = np.full_like(high, np.nan)
    prior_low = np.full_like(low, np.nan)
    two_high = np.full_like(high, np.nan)
    two_low = np.full_like(low, np.nan)
    prior_high[1:] = high[:-1]
    prior_low[1:] = low[:-1]
    two_high[2:] = high[:-2]
    two_low[2:] = low[:-2]
    inside_prev = (
        np.isfinite(prior_high)
        & np.isfinite(prior_low)
        & np.isfinite(two_high)
        & np.isfinite(two_low)
        & (prior_high > 0)
        & (prior_low > 0)
        & (two_high > 0)
        & (two_low > 0)
        & (prior_high <= two_high)
        & (prior_low >= two_low)
    )
    return (
        inside_prev
        & np.isfinite(close)
        & (close > 0)
        & np.isfinite(prior_high)
        & (close > prior_high)
    )


def no_gap_up_entry_mask(market: MarketDataMatrix) -> np.ndarray:
    """Signal-day aligned: next open is not above this close."""
    entry_open = shift_forward(np.asarray(market.open, dtype=np.float64), 1)
    close = np.asarray(market.close, dtype=np.float64)
    return np.isfinite(entry_open) & np.isfinite(close) & (entry_open <= close)


def ma20_reclaim_mask(market: MarketDataMatrix) -> np.ndarray:
    """Prior close below MA20, signal close back above MA20. Causal rolling mean."""
    valid = np.isfinite(market.close) & (market.close > 0)
    ma20 = valid_rolling_mean(market.close, valid, 20, bar_index=market.valid_bars)
    prior_close = np.full_like(market.close, np.nan, dtype=np.float64)
    prior_ma = np.full_like(ma20, np.nan, dtype=np.float64)
    prior_close[1:] = np.asarray(market.close[:-1], dtype=np.float64)
    prior_ma[1:] = np.asarray(ma20[:-1], dtype=np.float64)
    return (
        valid
        & np.isfinite(ma20)
        & np.isfinite(prior_close)
        & np.isfinite(prior_ma)
        & (prior_close < prior_ma)
        & (market.close > ma20)
    )


def close_above_prior_bar_high_mask(market: MarketDataMatrix) -> np.ndarray:
    """Close above the prior session high. Calendar lag, no inside-bar filter."""
    high = np.asarray(market.high, dtype=np.float64)
    close = np.asarray(market.close, dtype=np.float64)
    prior_high = np.full_like(high, np.nan)
    prior_high[1:] = high[:-1]
    return (
        np.isfinite(close)
        & (close > 0)
        & np.isfinite(prior_high)
        & (prior_high > 0)
        & (close > prior_high)
    )


def one_price_limit_mask(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    tradable: np.ndarray,
    flag: np.ndarray,
) -> np.ndarray:
    max_price = np.fmax(np.fmax(open_, high), np.fmax(low, close))
    min_price = np.fmin(np.fmin(open_, high), np.fmin(low, close))
    tolerance = np.maximum(np.abs(close) * 1e-4, 0.01)
    finite = (
        np.isfinite(open_)
        & np.isfinite(high)
        & np.isfinite(low)
        & np.isfinite(close)
        & (open_ > 0)
    )
    same = (max_price - min_price) <= tolerance
    return np.asarray(tradable, dtype=bool) & finite & same & np.asarray(flag, dtype=bool)


def can_buy_mask(market: MarketDataMatrix) -> np.ndarray:
    return (
        np.asarray(market.tradable, dtype=bool)
        & np.isfinite(market.open)
        & (market.open > 0)
        & ~one_price_limit_mask(
            market.open,
            market.high,
            market.low,
            market.close,
            market.tradable,
            market.limit_up_locked,
        )
    )


def can_sell_mask(market: MarketDataMatrix) -> np.ndarray:
    return (
        np.asarray(market.tradable, dtype=bool)
        & np.isfinite(market.open)
        & (market.open > 0)
        & ~one_price_limit_mask(
            market.open,
            market.high,
            market.low,
            market.close,
            market.tradable,
            market.limit_down_locked,
        )
    )


def shift_forward(values: np.ndarray, steps: int) -> np.ndarray:
    if steps <= 0:
        return np.asarray(values, dtype=np.float64)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    out[:-steps] = np.asarray(values[steps:], dtype=np.float64)
    return out


def shift_forward_bool(values: np.ndarray, steps: int) -> np.ndarray:
    if steps <= 0:
        return np.asarray(values, dtype=bool)
    out = np.zeros(values.shape, dtype=bool)
    out[:-steps] = np.asarray(values[steps:], dtype=bool)
    return out


def _clip_return(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(out) & (np.abs(out) <= RETURN_CLIP)
    return np.where(finite, out, np.nan)


def market_open_components(market: MarketDataMatrix) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SH/SZ equal-weight oc / cc / co on the market calendar. Calendar lag, not stock-bar lag."""
    board = hs_board_mask(market.symbols)
    usable = (
        np.asarray(market.tradable, dtype=bool)
        & np.isfinite(market.open)
        & (market.open > 0)
        & np.isfinite(market.close)
        & (market.close > 0)
        & board[None, :]
    )
    oc = _clip_return(np.where(usable, market.close / market.open - 1.0, np.nan))
    prior_close = np.full(market.close.shape, np.nan, dtype=np.float64)
    prior_close[1:] = market.close[:-1]
    prior_usable = np.zeros(market.close.shape, dtype=bool)
    prior_usable[1:] = usable[:-1]
    step_ok = usable & prior_usable & (prior_close > 0)
    cc = _clip_return(np.where(step_ok, market.close / prior_close - 1.0, np.nan))
    co = _clip_return(np.where(step_ok, market.open / prior_close - 1.0, np.nan))
    def _row_mean(values: np.ndarray) -> np.ndarray:
        counts = np.isfinite(values).sum(axis=1)
        totals = np.nansum(np.where(np.isfinite(values), values, 0.0), axis=1)
        out = np.full(values.shape[0], np.nan)
        np.divide(totals, counts, out=out, where=counts > 0)
        return out

    return _row_mean(oc), _row_mean(cc), _row_mean(co)


def window_market_returns(oc: np.ndarray, cc: np.ndarray, co: np.ndarray, hold: int) -> np.ndarray:
    """Indexed by entry session. Signal t uses entry t+1, so look up [t+1]."""
    n = len(oc)
    out = np.full(n, np.nan)
    for entry_idx in range(n):
        exit_idx = entry_idx + hold
        if exit_idx >= n:
            break
        start = oc[entry_idx]
        finish = co[exit_idx]
        if not np.isfinite(start) or not np.isfinite(finish):
            continue
        wealth = 1.0 + float(start)
        complete = True
        for idx in range(entry_idx + 1, exit_idx):
            step = cc[idx]
            if not np.isfinite(step):
                complete = False
                break
            wealth *= 1.0 + float(step)
        if complete:
            out[entry_idx] = wealth * (1.0 + float(finish)) - 1.0
    return out


def label_signal_windows(
    market: MarketDataMatrix,
    calendar: list[date],
    *,
    training_end: date = TRAINING_END,
    config: MatcherConfig = COST_CONFIG,
    holds: tuple[int, ...] = WINDOWS,
) -> dict[int, dict[str, np.ndarray]]:
    """T+1 open entry, scheduled open exit. Missing/limit/halt do not roll.

    Completeness does not include membership; callers intersect with selected
    or unselected so the same-day unselected set is a real eligible-not-in-universe book.
    """
    can_buy = can_buy_mask(market)
    can_sell = can_sell_mask(market)
    entry_open = shift_forward(market.open, 1)
    entry_ok = shift_forward_bool(can_buy, 1)
    oc, cc, co = market_open_components(market)
    buy_cost = config.buy_cost_pct()
    labeled: dict[int, dict[str, np.ndarray]] = {}
    n_times = len(calendar)
    for hold in holds:
        exit_open = shift_forward(market.open, 1 + hold)
        exit_ok = shift_forward_bool(can_sell, 1 + hold)
        market_at_entry = window_market_returns(oc, cc, co, hold)
        market_at_signal = shift_forward(market_at_entry, 1)
        gross = np.divide(
            exit_open,
            entry_open,
            out=np.full(entry_open.shape, np.nan),
            where=entry_open > 0,
        ) - 1.0
        net = np.full(gross.shape, np.nan)
        excess = np.full(gross.shape, np.nan)
        complete = np.zeros(gross.shape, dtype=bool)
        for t in range(n_times):
            exit_idx = t + 1 + hold
            if exit_idx >= n_times:
                break
            day = calendar[exit_idx]
            if day > training_end:
                continue
            filled = (
                entry_ok[t]
                & exit_ok[t]
                & np.isfinite(entry_open[t])
                & np.isfinite(exit_open[t])
                & np.isfinite(gross[t])
                & np.isfinite(market_at_signal[t])
            )
            if not np.any(filled):
                continue
            sell_cost = config.sell_cost_pct(day)
            net[t, filled] = net_round_trip(gross[t, filled], buy_cost, sell_cost)
            excess[t, filled] = geometric_excess(net[t, filled], float(market_at_signal[t]))
            complete[t] = filled
        labeled[hold] = {
            "complete": complete,
            "gross": gross,
            "net": net,
            "net_excess": excess,
            "market": market_at_signal,
            "entry_open": entry_open,
            "entry_ok": entry_ok,
        }
    return labeled


def date_ew_from_mask(mask: np.ndarray, values: np.ndarray) -> float | None:
    """Mean of per-signal-day means. Empty days are skipped."""
    pairs: list[tuple[str, float]] = []
    for t in range(mask.shape[0]):
        chosen = mask[t] & np.isfinite(values[t])
        if not np.any(chosen):
            continue
        pairs.append((str(t), float(values[t, chosen].mean())))
    return signal_day_equal_weight(pairs)


def date_ew_spread(
    selected_mask: np.ndarray, unselected_mask: np.ndarray, values: np.ndarray
) -> float | None:
    spreads: list[tuple[str, float]] = []
    for t in range(values.shape[0]):
        left = selected_mask[t] & np.isfinite(values[t])
        right = unselected_mask[t] & np.isfinite(values[t])
        if not np.any(left) or not np.any(right):
            continue
        spreads.append((str(t), float(values[t, left].mean() - values[t, right].mean())))
    return signal_day_equal_weight(spreads)


def summarize_window(
    hold: int,
    selected: np.ndarray,
    unselected: np.ndarray,
    labeled: dict[str, np.ndarray],
    calendar: list[date],
    training_start: date,
    training_end: date,
    control_tag: str = "eligible_not_in_universe",
) -> dict:
    in_training = np.array(
        [training_start <= day <= training_end for day in calendar], dtype=bool
    )
    executable = labeled["complete"] & in_training[:, None]
    sel = executable & selected
    unsel = executable & unselected
    net_ex = labeled["net_excess"]
    net = labeled["net"]
    yearly = {}
    for year in range(training_start.year, training_end.year + 1):
        year_mask = np.array([day.year == year for day in calendar], dtype=bool)
        group = sel & year_mask[:, None]
        yearly[str(year)] = {
            "complete": int(group.sum()),
            "signal_days": int(np.any(group, axis=1).sum()),
            "date_ew_net_excess": _round(date_ew_from_mask(group, net_ex)),
        }
    return {
        "hold_days": hold,
        "complete": int(sel.sum()),
        "signal_days": int(np.any(sel, axis=1).sum()),
        "unselected_complete": int(unsel.sum()),
        "unselected_signal_days": int(np.any(unsel, axis=1).sum()),
        "date_ew_net": _round(date_ew_from_mask(sel, net)),
        "date_ew_net_excess": _round(date_ew_from_mask(sel, net_ex)),
        "unselected_date_ew_net_excess": _round(date_ew_from_mask(unsel, net_ex)),
        "date_ew_vs_unselected": _round(date_ew_spread(sel, unsel, net)),
        "date_ew_net_excess_vs_unselected": _round(date_ew_spread(sel, unsel, net_ex)),
        "trade_mean_net_excess": _round(
            float(net_ex[sel].mean()) if np.any(sel) else None
        ),
        "positive_excess_years": sum(
            1 for row in yearly.values() if (row["date_ew_net_excess"] or 0) > 0
        ),
        "years_evaluated": sum(1 for row in yearly.values() if row["signal_days"] > 0),
        "yearly": yearly,
        "same_day_unselected": control_tag,
        "labels_past_training_end": False,
    }


def trigger_verdict(windows: dict[str, dict]) -> str:
    ten_vs = windows["10"]["date_ew_vs_unselected"]
    twenty_vs = windows["20"]["date_ew_vs_unselected"]
    if None in (ten_vs, twenty_vs):
        return "blocked_incomplete_labels"
    if ten_vs < 0 or twenty_vs < 0:
        return "fail_rewrite_breakout_event"
    return "pass_keep_breakout_trigger"


def verdict(windows: dict[str, dict]) -> str:
    ten = windows["10"]["date_ew_net_excess"]
    twenty = windows["20"]["date_ew_net_excess"]
    ten_vs = windows["10"]["date_ew_net_excess_vs_unselected"]
    twenty_vs = windows["20"]["date_ew_net_excess_vs_unselected"]
    if None in (ten, twenty, ten_vs, twenty_vs):
        return "blocked_incomplete_labels"
    if ten < 0 or twenty < 0 or ten_vs < 0 or twenty_vs < 0:
        return "fail_rewrite_gate_or_universe"
    return "pass_keep_as_selector_layer"


def calendar_from_market(market: MarketDataMatrix) -> list[date]:
    return [_as_date(label) for label in market.timestamp_labels]


def gaps_for_training(data_root: Path, start: date, end: date) -> list[str]:
    files = [
        path
        for path in sorted((data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={start.isoformat()}" <= path.parent.name <= f"date={end.isoformat()}"
    ]
    if not files:
        return [f"no kline_daily_enriched partitions between {start} and {end}"]
    return []


def load_training_market(
    data_root: Path, start: date, end: date
) -> tuple[MarketDataMatrix, list[date | None], list[str]]:
    files = [
        path
        for path in sorted((data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={start.isoformat()}" <= path.parent.name <= f"date={end.isoformat()}"
    ]
    if not files:
        raise RuntimeError(f"no kline_daily_enriched partitions between {start} and {end}")
    instruments = pl.read_parquet(data_root / "instruments" / "instruments.parquet").select(
        "symbol", "name", "listing_date"
    )
    bars = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "date", "open", "high", "low", "close", "volume", "raw_close", "amount")
        .collect()
        .join(instruments, on="symbol", how="left")
    )
    market = build_market_data_matrix(bars, field_columns={"raw_close", "amount"})
    by_symbol = {
        str(row["symbol"]): row
        for row in instruments.unique(subset=["symbol"]).iter_rows(named=True)
    }
    listing_dates: list[date | None] = []
    names: list[str] = []
    for symbol in market.symbols:
        row = by_symbol.get(str(symbol))
        names.append(str(row["name"]) if row and row.get("name") else "")
        listing = row.get("listing_date") if row else None
        listing_dates.append(_as_date(listing) if listing is not None else None)
    return market, listing_dates, names


def run_contrast(
    market: MarketDataMatrix,
    listing_dates: list[date | None],
    names: list[str],
    *,
    universe: str = UNIVERSE_SAME_DAY_OUTPERFORMANCE,
    experiment: str = "leader-universe-market-gate-v2",
) -> dict:
    calendar = calendar_from_market(market)
    valid = np.isfinite(market.close) & (market.close > 0)
    raw_close = np.asarray(market.fields.get("raw_close", market.close), dtype=np.float64)
    amount = np.asarray(market.fields["amount"], dtype=np.float64)
    eligible = tradable_eligibility_mask(
        symbols=list(market.symbols),
        names=names,
        listing_dates=listing_dates,
        calendar=calendar,
        raw_close=raw_close,
        amount=amount,
        valid=valid,
        tradable=market.tradable,
        volume=market.volume,
    )
    print("computing dual-regime gate", flush=True)
    gate, breadth = dual_regime_gate(market)
    print(f"computing universe={universe}", flush=True)
    in_universe = universe_mask(market, universe)
    selected, unselected = selected_and_unselected(gate, eligible, in_universe)
    print(
        f"selected_cells={int(selected.sum())} unselected_cells={int(unselected.sum())}",
        flush=True,
    )
    print("labeling T+1 windows", flush=True)
    labeled = label_signal_windows(market, calendar)
    windows = {
        str(hold): summarize_window(
            hold,
            selected,
            unselected,
            labeled[hold],
            calendar,
            TRAINING_START,
            TRAINING_END,
        )
        for hold in WINDOWS
    }
    training_days = [day for day in calendar if TRAINING_START <= day <= TRAINING_END]
    return {
        "experiment": experiment,
        "training_start": TRAINING_START.isoformat(),
        "training_end": TRAINING_END.isoformat(),
        "cost": {
            "commission_pct": 0.0003,
            "slippage_bps": 10.0,
            "stamp_tax_policy": "a_share_historical",
        },
        "selector": {
            "gate": "a_share_dual_regime",
            "include_middle_expansion_regime": False,
            "universe": universe,
            "rs_min": RS_MIN if universe == UNIVERSE_RS85 else None,
            "trend_filter": False,
            "pattern_detector": None,
        },
        "coverage": {
            "market_sessions": len(calendar),
            "training_sessions": len(training_days),
            "gate_open_sessions": int(np.asarray(gate, dtype=bool).sum()),
            "symbols": len(market.symbols),
            "mean_breadth": _round(float(np.nanmean(breadth))),
            "selected_signal_cells": int(selected.sum()),
            "unselected_signal_cells": int(unselected.sum()),
        },
        "windows": windows,
        "rule": verdict(windows),
        "gaps": [],
    }


def run_watchlist_breakout_contrast(
    market: MarketDataMatrix,
    listing_dates: list[date | None],
    names: list[str],
    *,
    experiment: str = "watchlist-20d-high-breakout-v1",
    trigger: str = "fresh_20d",
    entry_filter: str | None = None,
    exit_rule: str | None = None,
) -> dict:
    calendar = calendar_from_market(market)
    valid = np.isfinite(market.close) & (market.close > 0)
    raw_close = np.asarray(market.fields.get("raw_close", market.close), dtype=np.float64)
    amount = np.asarray(market.fields["amount"], dtype=np.float64)
    eligible = tradable_eligibility_mask(
        symbols=list(market.symbols),
        names=names,
        listing_dates=listing_dates,
        calendar=calendar,
        raw_close=raw_close,
        amount=amount,
        valid=valid,
        tradable=market.tradable,
        volume=market.volume,
    )
    print("computing dual-regime gate", flush=True)
    gate, breadth = dual_regime_gate(market)
    print("computing RS watch list", flush=True)
    in_rs, _ranks = rs_universe_mask(market)
    watch = watch_list_mask(gate, eligible, in_rs)
    print(f"computing breakout trigger={trigger}", flush=True)
    if trigger == "fresh_20d":
        breakout = fresh_20d_breakout_opportunity_mask(market)
    elif trigger == "close_above_prior_20_high":
        breakout = close_above_prior_20_high_mask(market)
    elif trigger == "inside_bar_breakout":
        breakout = inside_bar_breakout_mask(market)
    elif trigger == "close_above_prior_bar_high":
        breakout = close_above_prior_bar_high_mask(market)
    elif trigger == "ma20_reclaim":
        breakout = ma20_reclaim_mask(market)
    else:
        raise ValueError(f"unknown breakout trigger: {trigger}")
    selected, untriggered = triggered_and_untriggered(watch, breakout)
    baseline_selected = selected
    if entry_filter == "no_gap_up":
        selected = selected & no_gap_up_entry_mask(market)
    elif entry_filter not in (None, "", "none"):
        raise ValueError(f"unknown entry filter: {entry_filter}")
    print(
        f"watch_cells={int(watch.sum())} triggered={int(selected.sum())} "
        f"untriggered={int(untriggered.sum())} entry_filter={entry_filter}",
        flush=True,
    )
    print("labeling T+1 windows", flush=True)
    scheduled = label_signal_windows(market, calendar)
    labeled = scheduled
    if exit_rule == "two_bar_no_demand":
        labeled = overlay_two_bar_no_demand(
            market, calendar, scheduled, baseline_selected
        )
    elif exit_rule not in (None, "", "none"):
        raise ValueError(f"unknown exit rule: {exit_rule}")
    windows = {
        str(hold): summarize_window(
            hold,
            selected,
            untriggered,
            labeled[hold],
            calendar,
            TRAINING_START,
            TRAINING_END,
            control_tag="watchlist_no_breakout",
        )
        for hold in WINDOWS
    }
    training_days = [day for day in calendar if TRAINING_START <= day <= TRAINING_END]
    report = {
        "experiment": experiment,
        "training_start": TRAINING_START.isoformat(),
        "training_end": TRAINING_END.isoformat(),
        "cost": {
            "commission_pct": 0.0003,
            "slippage_bps": 10.0,
            "stamp_tax_policy": "a_share_historical",
        },
        "selector": {
            "watch_list": "dual_regime_open ∩ rs>=85 ∩ eligible",
            "trigger": trigger,
            "entry_filter": entry_filter,
            "exit_rule": exit_rule,
            "pattern_detector": None,
        },
        "coverage": {
            "market_sessions": len(calendar),
            "training_sessions": len(training_days),
            "gate_open_sessions": int(np.asarray(gate, dtype=bool).sum()),
            "symbols": len(market.symbols),
            "mean_breadth": _round(float(np.nanmean(breadth))),
            "watch_signal_cells": int(watch.sum()),
            "selected_signal_cells": int(selected.sum()),
            "unselected_signal_cells": int(untriggered.sum()),
        },
        "windows": windows,
        "rule": trigger_verdict(windows),
        "gaps": [],
    }
    if entry_filter == "no_gap_up":
        baseline = {
            str(hold): summarize_window(
                hold,
                baseline_selected,
                untriggered,
                scheduled[hold],
                calendar,
                TRAINING_START,
                TRAINING_END,
                control_tag="watchlist_no_breakout",
            )
            for hold in WINDOWS
        }
        report["baseline_windows"] = baseline
        report["rule"] = entry_filter_verdict(windows, baseline)
    if exit_rule == "two_bar_no_demand":
        baseline = {
            str(hold): summarize_window(
                hold,
                baseline_selected,
                untriggered,
                scheduled[hold],
                calendar,
                TRAINING_START,
                TRAINING_END,
                control_tag="watchlist_no_breakout",
            )
            for hold in WINDOWS
        }
        report["baseline_windows"] = baseline
        report["rule"] = entry_filter_verdict(windows, baseline)
    return report


def overlay_two_bar_no_demand(
    market: MarketDataMatrix,
    calendar: list[date],
    labeled: dict[int, dict[str, np.ndarray]],
    selected: np.ndarray,
    *,
    training_end: date = TRAINING_END,
    config: MatcherConfig = COST_CONFIG,
) -> dict[int, dict[str, np.ndarray]]:
    """If two-bar MFE from entry is < 3%, replace scheduled exit with open two sessions after entry."""
    entry_open = labeled[WINDOWS[0]]["entry_open"]
    high1 = shift_forward(np.asarray(market.high, dtype=np.float64), 1)
    high2 = shift_forward(np.asarray(market.high, dtype=np.float64), 2)
    early_open = shift_forward(np.asarray(market.open, dtype=np.float64), 3)
    early_ok = shift_forward_bool(can_sell_mask(market), 3)
    with np.errstate(divide="ignore", invalid="ignore"):
        mfe = np.fmax(high1 / entry_open - 1.0, high2 / entry_open - 1.0)
    need = np.isfinite(mfe) & (mfe < 0.03)
    buy_cost = config.buy_cost_pct()
    oc, cc, co = market_open_components(market)
    early_mkt = shift_forward(window_market_returns(oc, cc, co, 2), 1)
    gross_early = np.divide(
        early_open, entry_open, out=np.full(entry_open.shape, np.nan), where=entry_open > 0
    ) - 1.0
    out: dict[int, dict[str, np.ndarray]] = {}
    for hold, slot in labeled.items():
        net = np.array(slot["net"], copy=True)
        excess = np.array(slot["net_excess"], copy=True)
        complete = np.array(slot["complete"], copy=True)
        for t in range(len(calendar)):
            exit_idx = t + 3
            if exit_idx >= len(calendar) or calendar[exit_idx] > training_end:
                continue
            hit = (
                selected[t]
                & complete[t]
                & need[t]
                & early_ok[t]
                & np.isfinite(gross_early[t])
                & np.isfinite(early_mkt[t])
            )
            if not np.any(hit):
                continue
            sell_cost = config.sell_cost_pct(calendar[exit_idx])
            net[t, hit] = net_round_trip(gross_early[t, hit], buy_cost, sell_cost)
            excess[t, hit] = geometric_excess(net[t, hit], float(early_mkt[t]))
        out[hold] = {**slot, "net": net, "net_excess": excess, "complete": complete}
    return out


def entry_filter_verdict(treated: dict[str, dict], baseline: dict[str, dict]) -> str:
    ten = treated["10"]["date_ew_net"]
    twenty = treated["20"]["date_ew_net"]
    ten_b = baseline["10"]["date_ew_net"]
    twenty_b = baseline["20"]["date_ew_net"]
    if None in (ten, twenty, ten_b, twenty_b):
        return "blocked_incomplete_labels"
    if ten < ten_b or twenty < twenty_b:
        return "fail_stop_entry_filter"
    return "pass_keep_entry_filter"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--universe", default=UNIVERSE_SAME_DAY_OUTPERFORMANCE)
    args = parser.parse_args()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_file():
        raise SystemExit(f"protocol missing: {protocol_path}")
    data_root = Path(args.data_root)
    gaps = gaps_for_training(data_root, DATA_START, TRAINING_END)
    if gaps:
        report = {
            "experiment": Path(args.protocol).stem,
            "protocol": str(protocol_path),
            "gaps": gaps,
            "windows": {},
            "rule": "blocked_missing_bars",
        }
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"output": args.output, "gaps": gaps}, ensure_ascii=False))
        return 1
    print("loading market matrix", flush=True)
    market, listing_dates, names = load_training_market(data_root, DATA_START, TRAINING_END)
    print(
        f"loaded sessions={market.shape[0]} symbols={market.shape[1]}",
        flush=True,
    )
    report = run_contrast(
        market,
        listing_dates,
        names,
        universe=args.universe,
        experiment=Path(args.protocol).stem,
    )
    report["protocol"] = str(protocol_path)
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": args.output,
                "rule": report["rule"],
                "date_ew_net_excess": {
                    hold: report["windows"][hold]["date_ew_net_excess"]
                    for hold in ("5", "10", "20")
                },
                "date_ew_net_excess_vs_unselected": {
                    hold: report["windows"][hold]["date_ew_net_excess_vs_unselected"]
                    for hold in ("5", "10", "20")
                },
                "signal_days": {
                    hold: report["windows"][hold]["signal_days"] for hold in ("5", "10", "20")
                },
                "complete": {
                    hold: report["windows"][hold]["complete"] for hold in ("5", "10", "20")
                },
                "gaps": report["gaps"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
