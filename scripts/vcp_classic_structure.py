"""Outcome-independent classic VCP structure representation for research audits."""
from __future__ import annotations

from itertools import pairwise
from typing import Any

import numpy as np

from app.strategy.builtin._quants_vcp import _swings


def represent_classic_structure(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    dates: np.ndarray,
) -> dict[str, Any]:
    """Represent pre-breakout supply topology; the final bar is demand-only."""
    if len(close) < 8:
        return {"supported": False, "reason": "history_too_short", "legs": []}
    pattern_high = np.asarray(high[:-1], dtype=float)
    pattern_low = np.asarray(low[:-1], dtype=float)
    pattern_close = np.asarray(close[:-1], dtype=float)
    pattern_volume = np.asarray(volume[:-1], dtype=float)
    pattern_dates = np.asarray(dates[:-1])
    points = _swings(pattern_high, pattern_low, pattern_close)
    pullbacks: list[dict[str, Any]] = []
    for left, right in pairwise(points):
        if left[1] != "high" or right[1] != "low":
            continue
        depth = 1 - right[2] / left[2]
        if 0 < depth < 0.45:
            pullbacks.append(
                {
                    "high_index": left[0],
                    "low_index": right[0],
                    "high_date": str(pattern_dates[left[0]]),
                    "low_date": str(pattern_dates[right[0]]),
                    "high": float(left[2]),
                    "low": float(right[2]),
                    "depth": float(depth),
                }
            )
    if len(pullbacks) < 2:
        return {"supported": False, "reason": "fewer_than_two_pullbacks", "legs": pullbacks}

    chain = [pullbacks[-1]]
    for item in reversed(pullbacks[:-1]):
        if item["depth"] > chain[0]["depth"]:
            chain.insert(0, item)
        else:
            break
    if len(chain) < 2:
        return {
            "supported": False,
            "reason": "latest_pullbacks_do_not_contract",
            "legs": chain,
        }

    final = chain[-1]
    pivot = final["high"]
    closes_after_pivot = pattern_close[final["high_index"] + 1 :]
    pivot_integrity = bool(len(closes_after_pivot) and np.all(closes_after_pivot <= pivot))
    right_edge_position = (
        float((pattern_close[-1] - final["low"]) / (pivot - final["low"]))
        if pivot > final["low"]
        else float("nan")
    )
    right_edge = bool(np.isfinite(right_edge_position) and 0.5 <= right_edge_position <= 1.0)

    earlier_volume = pattern_volume[chain[0]["high_index"] : final["high_index"]]
    final_volume = pattern_volume[final["high_index"] + 1 :]
    valid_earlier_volume = earlier_volume[np.isfinite(earlier_volume) & (earlier_volume > 0)]
    valid_final_volume = final_volume[np.isfinite(final_volume) & (final_volume > 0)]
    supply_ratio = (
        float(np.median(valid_final_volume) / np.median(valid_earlier_volume))
        if len(valid_earlier_volume) and len(valid_final_volume)
        else None
    )
    supply_reduction = bool(supply_ratio is not None and supply_ratio < 1.0)
    signal_volume_history = pattern_volume[-19:]
    valid_signal_history = signal_volume_history[
        np.isfinite(signal_volume_history) & (signal_volume_history > 0)
    ]
    demand_ratio = (
        float(volume[-1] / np.median(valid_signal_history))
        if len(valid_signal_history) and np.isfinite(volume[-1]) and volume[-1] > 0
        else None
    )
    signal_above_pivot = bool(np.isfinite(close[-1]) and close[-1] >= pivot)
    supported = pivot_integrity and right_edge and supply_reduction
    failed = [
        name
        for name, passed in (
            ("pivot_integrity", pivot_integrity),
            ("right_edge", right_edge),
            ("supply_reduction", supply_reduction),
        )
        if not passed
    ]
    return {
        "supported": supported,
        "reason": "supported" if supported else "+".join(failed),
        "legs": chain,
        "pivot": pivot,
        "pivot_date": final["high_date"],
        "structure_low": final["low"],
        "structure_low_date": final["low_date"],
        "right_edge_position": right_edge_position,
        "prebreakout_supply_ratio": supply_ratio,
        "breakout_demand_ratio": demand_ratio,
        "signal_above_pivot": signal_above_pivot,
        "checks": {
            "contiguous_contracting_chain": True,
            "pivot_integrity": pivot_integrity,
            "right_edge": right_edge,
            "supply_reduction": supply_reduction,
        },
    }
