"""Chan inclusion-processing (K-line merging).

Aligns with ZenChart's `merged_klines` output. Each merged K-line reports
{start_time, end_time, high, low, dir, n}. Direction is set by comparing the
new merged segment to the previous one; containment merging follows the
ongoing direction (up -> max/max, down -> min/min).

Boundary note: for the *first* segment the official engine derives `dir` from
an internal context window that precedes the returned candle slice, so the
local default ("up") may differ. This is the only known source of mismatch
and is confined to index 0 when n == 1 (no containment merge on the first row).
"""

from __future__ import annotations

from typing import Any


def merge_klines(
    candles: list[dict[str, Any]], initial_dir: str | None = None
) -> list[dict[str, Any]]:
    """Merge inclusive K-lines into ZenChart-style merged_klines rows.

    `initial_dir` overrides the boundary guess for the first segment; it is
    exposed for tests/alignment but defaults to "up".
    """
    if not candles:
        return []
    out: list[dict[str, Any]] = []
    first = candles[0]
    seg: dict[str, Any] = {
        "start_time": first["time"],
        "end_time": first["time"],
        "high": first["high"],
        "low": first["low"],
        "dir": initial_dir or "up",
        "n": 1,
    }
    for c in candles[1:]:
        h, l, t = c["high"], c["low"], c["time"]
        contains = (seg["high"] >= h and seg["low"] <= l) or (
            seg["high"] <= h and seg["low"] >= l
        )
        if contains:
            if seg["dir"] == "down":
                seg["high"] = min(seg["high"], h)
                seg["low"] = min(seg["low"], l)
            else:
                seg["high"] = max(seg["high"], h)
                seg["low"] = max(seg["low"], l)
            seg["end_time"] = t
            seg["n"] += 1
        else:
            new_dir = "up" if (h > seg["high"] and l >= seg["low"]) or (
                h >= seg["high"] and l > seg["low"]
            ) else "down"
            out.append(seg)
            seg = {
                "start_time": t,
                "end_time": t,
                "high": h,
                "low": l,
                "dir": new_dir,
                "n": 1,
            }
    out.append(seg)
    return out