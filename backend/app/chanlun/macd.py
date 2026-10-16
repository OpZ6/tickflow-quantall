"""MACD (12/26/9) calculation aligned with ZenChart.

Official rows: {time, dif, dea, histogram} where histogram = 2*(dif-dea).
The EMA uses seed = first close and standard recursive smoothing. Because the
official engine computes over a longer internal history, early in-window rows
may differ slightly; rows after EMA warm-up match closely.
"""

from __future__ import annotations

from typing import Any


def _ema(values: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1.0)
    out: list[float] = []
    prev: float | None = None
    for v in values:
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def macd(
    candles: list[dict[str, Any]], fast: int = 12, slow: int = 26, signal: int = 9
) -> list[dict[str, Any]]:
    """Return [{time, dif, dea, histogram}] aligned with candles."""
    closes = [c["close"] for c in candles]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [a - b for a, b in zip(ema_fast, ema_slow)]
    dea = _ema(dif, signal)
    result: list[dict[str, Any]] = []
    for c, d, e in zip(candles, dif, dea):
        result.append(
            {
                "time": c["time"],
                "dif": round(d, 4),
                "dea": round(e, 4),
                "histogram": round(2 * (d - e), 4),
            }
        )
    return result