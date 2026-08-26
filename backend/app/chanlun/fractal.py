"""Chan fractal (fenxing) detection.

Fractal points are strict left/mid/right extremes on the merged K-line
sequence, then type-switched (same-direction keeps the more extreme point).

The fractal timestamp is the LAST raw candle inside the merged row whose
extreme equals the fractal value (matching ZenChart's day attribution).

Value: the merged row's low (bottom) or high (top).
"""

from __future__ import annotations

from typing import Any


def _extreme_time(
    candles: list[dict[str, Any]],
    seg_start: int,
    seg_end: int,
    kind: str,
    value: float,
) -> int:
    """Last raw candle time in [seg_start, seg_end] matching the extreme value."""
    hit: int | None = None
    for c in candles:
        if not (seg_start <= c["time"] <= seg_end):
            continue
        if kind == "bottom" and abs(c["low"] - value) < 1e-9:
            hit = c["time"]
        if kind == "top" and abs(c["high"] - value) < 1e-9:
            hit = c["time"]
    return hit if hit is not None else seg_end


def raw_fractals(
    merged: list[dict[str, Any]], candles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """All strict left/mid/right extreme candidates before type-switching."""
    result: list[dict[str, Any]] = []
    for i in range(1, len(merged) - 1):
        left, mid, right = merged[i - 1], merged[i], merged[i + 1]
        if mid["low"] < left["low"] and mid["low"] < right["low"]:
            t = _extreme_time(
                candles, mid["start_time"], mid["end_time"], "bottom", mid["low"]
            )
            result.append({"time": t, "type": "bottom", "value": mid["low"]})
        elif mid["high"] > left["high"] and mid["high"] > right["high"]:
            t = _extreme_time(
                candles, mid["start_time"], mid["end_time"], "top", mid["high"]
            )
            result.append({"time": t, "type": "top", "value": mid["high"]})
    return result


def switch_fractals(
    fractals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Type-switch: keep alternating types; same type keeps the more extreme."""
    result: list[dict[str, Any]] = []
    for fx in fractals:
        if not result:
            result.append(fx)
            continue
        last = result[-1]
        if last["type"] == fx["type"]:
            if (
                fx["type"] == "bottom" and fx["value"] < last["value"]
            ) or (fx["type"] == "top" and fx["value"] > last["value"]):
                result[-1] = fx
        else:
            result.append(fx)
    return result


def detect_fractals(
    merged: list[dict[str, Any]], candles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return switch_fractals(raw_fractals(merged, candles))