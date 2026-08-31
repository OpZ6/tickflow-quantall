"""Shared, causal matrix calculations for registered price-structure strategies."""

from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    matrix_feature,
    valid_rolling_max,
    valid_rolling_mean,
    valid_rolling_min,
    valid_shift,
)


def _previous(values: np.ndarray, market: MarketDataMatrix, periods: int = 1) -> np.ndarray:
    return valid_shift(
        values,
        periods,
        np.isfinite(market.close),
        bar_index=market.valid_bars,
    )


def _prior_max(values: np.ndarray, market: MarketDataMatrix, window: int) -> np.ndarray:
    previous = _previous(values, market)
    return valid_rolling_max(
        previous,
        np.isfinite(previous),
        window,
        bar_index=market.valid_bars,
    )


def _prior_min(values: np.ndarray, market: MarketDataMatrix, window: int) -> np.ndarray:
    previous = _previous(values, market)
    return valid_rolling_min(
        previous,
        np.isfinite(previous),
        window,
        bar_index=market.valid_bars,
    )


def _prior_mean(values: np.ndarray, market: MarketDataMatrix, window: int) -> np.ndarray:
    previous = _previous(values, market)
    return valid_rolling_mean(
        previous,
        np.isfinite(previous),
        window,
        bar_index=market.valid_bars,
    )


def _ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    result = np.full(numerator.shape, np.nan, dtype=np.float32)
    np.divide(
        numerator, denominator, out=result, where=np.isfinite(denominator) & (denominator != 0)
    )
    return result


def _crosses_above(market: MarketDataMatrix, level: np.ndarray) -> np.ndarray:
    previous_close = _previous(market.close, market)
    previous_level = _previous(level, market)
    return (market.close > level) & (previous_close <= previous_level)


def ma20_breakdown(market: MarketDataMatrix) -> np.ndarray:
    ma20 = matrix_feature(market, "ma20")
    return (market.close < ma20) & (_previous(market.close, market) >= _previous(ma20, market))


def vcp_breakout(market: MarketDataMatrix, params: dict) -> np.ndarray:
    base_window = int(params.get("base_window", 40))
    contraction_window = int(params.get("contraction_window", 10))
    prior_high = _prior_max(market.high, market, base_window)
    prior_low = _prior_min(market.low, market, base_window)
    recent_high = _prior_max(market.high, market, contraction_window)
    recent_low = _prior_min(market.low, market, contraction_window)
    base_depth = _ratio(prior_high - prior_low, prior_high)
    recent_depth = _ratio(recent_high - recent_low, recent_high)
    short_volume = _prior_mean(market.volume, market, 5)
    base_volume = _prior_mean(market.volume, market, 20)
    return (
        (base_depth >= float(params.get("base_depth_min", 0.08)))
        & (base_depth <= float(params.get("base_depth_max", 0.45)))
        & (recent_depth <= base_depth * float(params.get("contraction_ratio_max", 0.65)))
        & (short_volume <= base_volume * float(params.get("dry_volume_ratio_max", 0.85)))
        & (market.volume >= short_volume * float(params.get("breakout_volume_ratio_min", 1.2)))
        & _crosses_above(market, prior_high)
    )


def cup_handle_breakout(market: MarketDataMatrix, params: dict) -> np.ndarray:
    cup_window = int(params.get("cup_window", 45))
    handle_window = int(params.get("handle_window", 5))
    rim = _prior_max(market.high, market, cup_window)
    cup_low = _prior_min(market.low, market, cup_window)
    cup_depth = _ratio(rim - cup_low, rim)
    handle_high = _prior_max(market.high, market, handle_window)
    handle_low = _prior_min(market.low, market, handle_window)
    handle_depth = _ratio(rim - handle_low, rim)
    handle_volume = _prior_mean(market.volume, market, handle_window)
    cup_volume = _prior_mean(market.volume, market, cup_window)
    return (
        (cup_depth >= float(params.get("cup_depth_min", 0.12)))
        & (cup_depth <= float(params.get("cup_depth_max", 0.45)))
        & (handle_high >= rim * (1.0 - float(params.get("rim_tolerance", 0.08))))
        & (handle_depth <= float(params.get("handle_depth_max", 0.18)))
        & (handle_volume <= cup_volume * float(params.get("handle_volume_ratio_max", 0.85)))
        & (market.volume >= handle_volume * float(params.get("breakout_volume_ratio_min", 1.2)))
        & _crosses_above(market, rim)
    )


def high_tight_flag_breakout(market: MarketDataMatrix, params: dict) -> np.ndarray:
    pole_window = int(params.get("pole_window", 30))
    flag_window = int(params.get("flag_window", 6))
    pole_high = _prior_max(market.high, market, pole_window)
    pole_low = _prior_min(market.low, market, pole_window)
    pole_gain = _ratio(pole_high - pole_low, pole_low)
    flag_high = _prior_max(market.high, market, flag_window)
    flag_low = _prior_min(market.low, market, flag_window)
    flag_depth = _ratio(pole_high - flag_low, pole_high)
    flag_volume = _prior_mean(market.volume, market, flag_window)
    pole_volume = _prior_mean(market.volume, market, pole_window)
    return (
        (pole_gain >= float(params.get("pole_gain_min", 0.80)))
        & (flag_depth >= 0)
        & (flag_depth <= float(params.get("flag_depth_max", 0.22)))
        & (flag_volume <= pole_volume * float(params.get("flag_volume_ratio_max", 0.85)))
        & (market.volume >= flag_volume * float(params.get("breakout_volume_ratio_min", 1.2)))
        & _crosses_above(market, flag_high)
    )


def _latest_prior_launch(
    market: MarketDataMatrix,
    launch: np.ndarray,
    value: np.ndarray,
    lookback: int,
) -> np.ndarray:
    result = np.full(market.shape, np.nan, dtype=np.float32)
    unresolved = np.ones(market.shape, dtype=bool)
    launch_values = launch.astype(np.float32)
    for periods in range(1, lookback + 1):
        prior_launch = _previous(launch_values, market, periods) > 0.5
        prior_value = _previous(value, market, periods)
        use = unresolved & prior_launch & np.isfinite(prior_value)
        result[use] = prior_value[use]
        unresolved[use] = False
    return result


def launch_pullback_support(
    market: MarketDataMatrix, params: dict
) -> tuple[np.ndarray, np.ndarray]:
    previous_close = _previous(market.close, market)
    change = _ratio(market.close - previous_close, previous_close)
    prior_volume = _prior_mean(market.volume, market, 20)
    launch = (change >= float(params.get("launch_gain_min", 0.06))) & (
        market.volume >= prior_volume * float(params.get("launch_volume_ratio_min", 2.0))
    )
    lookback = int(params.get("launch_lookback", 10))
    launch_support = _latest_prior_launch(
        market,
        launch,
        (market.open + market.close) / 2.0,
        lookback,
    )
    launch_volume = _latest_prior_launch(market, launch, market.volume, lookback)
    tolerance = float(params.get("support_tolerance", 0.02))
    entry = (
        np.isfinite(launch_support)
        & (np.abs(change) <= float(params.get("pullback_change_abs_max", 0.02)))
        & (market.volume <= launch_volume * float(params.get("pullback_volume_ratio_max", 0.60)))
        & (market.low <= launch_support * (1.0 + tolerance))
        & (market.close >= launch_support * (1.0 - tolerance))
    )
    exit_ = np.isfinite(launch_support) & (
        market.close < launch_support * (1.0 - float(params.get("failure_buffer", 0.02)))
    )
    return entry, exit_
