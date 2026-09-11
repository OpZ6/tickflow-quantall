"""Causal supply-wave representation for the independent VCP v3 candidate."""
from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np

from app.strategy.builtin._quants_vcp import _swings


def _downside_pressure(close: np.ndarray, volume: np.ndarray, start: int, end: int) -> float | None:
    """Volume-weighted adverse return within one completed wave."""
    wave_close = close[start : end + 1]
    wave_volume = volume[start : end + 1]
    if len(wave_close) < 2 or not np.all(np.isfinite(wave_close)) or not np.all(np.isfinite(wave_volume)):
        return None
    returns = np.diff(wave_close) / wave_close[:-1]
    weights = wave_volume[1:]
    total = float(np.sum(weights))
    return float(np.sum(weights * np.maximum(-returns, 0.0)) / total) if total > 0 else None


def represent_supply_waves(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    dates: np.ndarray,
) -> dict[str, Any]:
    """Represent two completed shrinking supply waves through a causal signal close."""
    arrays = [np.asarray(values, dtype=float) for values in (high, low, close, volume)]
    high, low, close, volume = arrays
    dates = np.asarray(dates)
    if len(close) < 30 or any(len(values) != len(close) for values in arrays) or len(dates) != len(close):
        return {"supported": False, "reason": "history_too_short", "waves": []}
    if any(not np.all(np.isfinite(values)) for values in arrays) or np.any(low <= 0) or np.any(volume <= 0):
        return {"supported": False, "reason": "invalid_input", "waves": []}

    pattern_high, pattern_low, pattern_close, pattern_volume = (
        high[:-1],
        low[:-1],
        close[:-1],
        volume[:-1],
    )
    points = _swings(pattern_high, pattern_low, pattern_close)
    waves: list[dict[str, Any]] = []
    for index in range(len(points) - 2):
        left, trough, recovery = points[index : index + 3]
        if (left[1], trough[1], recovery[1]) != ("high", "low", "high"):
            continue
        depth = 1.0 - trough[2] / left[2]
        recovered_fraction = (recovery[2] - trough[2]) / (left[2] - trough[2]) if left[2] > trough[2] else 0.0
        if not (0.0 < depth < 0.45 and recovered_fraction >= 0.5 and recovery[2] <= left[2] * 1.04):
            continue
        pressure = _downside_pressure(pattern_close, pattern_volume, left[0], recovery[0])
        if pressure is None:
            continue
        waves.append(
            {
                "start_index": left[0],
                "low_index": trough[0],
                "end_index": recovery[0],
                "start_date": str(dates[left[0]]),
                "low_date": str(dates[trough[0]]),
                "end_date": str(dates[recovery[0]]),
                "start_high": float(left[2]),
                "low": float(trough[2]),
                "recovery_high": float(recovery[2]),
                "depth": float(depth),
                "recovered_fraction": float(recovered_fraction),
                "downside_pressure": pressure,
            }
        )

    adjacent_pairs = [
        (left, right)
        for left, right in pairwise(waves)
        if left["end_index"] == right["start_index"]
    ]
    if not adjacent_pairs:
        return {"supported": False, "reason": "fewer_than_two_completed_waves", "waves": waves[-2:]}
    first, final = adjacent_pairs[-1]
    contracting_depth = final["depth"] < first["depth"]
    contracting_supply = final["downside_pressure"] < first["downside_pressure"]

    pivot = final["recovery_high"]
    after_pivot = pattern_close[final["end_index"] + 1 :]
    daily_ranges = pattern_high[-14:] - pattern_low[-14:]
    tolerance = float(np.median(daily_ranges)) if len(daily_ranges) else 0.0
    pivot_integrity = bool(np.all(after_pivot <= pivot + tolerance))
    right_edge_position = (
        float((pattern_close[-1] - final["low"]) / (pivot - final["low"]))
        if pivot > final["low"]
        else float("nan")
    )
    right_edge = bool(np.isfinite(right_edge_position) and 0.5 <= right_edge_position <= 1.0 + tolerance / pivot)

    signal_range = high[-1] - low[-1]
    signal_close_location = float((close[-1] - low[-1]) / signal_range) if signal_range > 0 else 0.5
    volume_baseline = float(np.median(pattern_volume[-20:]))
    demand = bool(close[-1] > pivot and signal_close_location >= 0.5 and volume[-1] > volume_baseline)
    checks = {
        "contracting_depth": contracting_depth,
        "contracting_supply": contracting_supply,
        "pivot_integrity": pivot_integrity,
        "right_edge": right_edge,
        "breakout_demand": demand,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "supported": not failed,
        "reason": "supported" if not failed else "+".join(failed),
        "waves": [first, final],
        "pivot": pivot,
        "pivot_date": final["end_date"],
        "right_edge_position": right_edge_position,
        "signal_close_location": signal_close_location,
        "signal_volume_ratio": float(volume[-1] / volume_baseline) if volume_baseline > 0 else None,
        "checks": checks,
    }
