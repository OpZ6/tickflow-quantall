"""Chan zhongshu (pivot) construction from strokes within segments.

Verified against official full-history samples:
  - A pivot forms when 3 consecutive alternating strokes have mutual range
    overlap. ZG = min(a.high, b.high, c.high), ZD = max(a.low, b.low, c.low).
  - The pivot EXTENDS while subsequent strokes still overlap the FIXED
    [ZD, ZG] range (range does NOT change during extension).
  - Pivots are built WITHIN each segment, starting from the 2nd stroke
    (the entry stroke is skipped). Segments with < 4 strokes produce
    no pivots (not enough non-entry strokes for a 3-stroke overlap).
"""

from __future__ import annotations

from typing import Any


def _stroke_range(s: dict) -> tuple[float, float]:
    """High/low of a stroke: endpoints define its price range."""
    if "high" in s and "low" in s:
        return s["high"], s["low"]
    p0 = s.get("start_price", s.get("high", 0.0))
    p1 = s.get("end_price", s.get("low", 0.0))
    return max(p0, p1), min(p0, p1)


def _build_in_range(
    strokes: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    dynamic_range: bool = False,
) -> list[dict[str, Any]]:
    """Build pivots from strokes[start_idx:end_idx+1].

    Args:
        dynamic_range: if True, ZG/ZD recalculated with each extension stroke (所有段).
                       if False (default), ZG/ZD fixed from first 3 strokes (前三段).
    """
    pivots: list[dict[str, Any]] = []
    n = end_idx + 1
    i = start_idx
    while i < n - 2:
        a, b, c = strokes[i], strokes[i + 1], strokes[i + 2]
        if a["direction"] == b["direction"] or b["direction"] == c["direction"]:
            i += 1
            continue
        ah, al = _stroke_range(a)
        bh, bl = _stroke_range(b)
        ch, cl = _stroke_range(c)
        if not (ah > cl and ch > al):
            i += 1
            continue
        zg = min(ah, bh, ch)
        zd = max(al, bl, cl)
        if zd >= zg:
            i += 1
            continue
        start_time = a["start_time"]
        start_index = a.get("start_index")
        j = i + 3
        end = None
        while j < n:
            sh, sl = _stroke_range(strokes[j])
            if dynamic_range:
                # Recalculate ZG/ZD with each stroke
                zg = min(zg, sh)
                zd = max(zd, sl)
            if sl < zg and sh > zd:
                j += 1
            else:
                end = strokes[j - 1]
                break
        if end is None:
            end = strokes[n - 1]
        pivots.append(
            {
                "start_time": start_time,
                "end_time": end["end_time"],
                "low": zd,
                "high": zg,
                "start_index": start_index,
                "end_index": end.get("end_index"),
                "confirm_index": end.get("confirm_index"),
            }
        )
        i = j + 1
    return pivots


def build_zhongshu(
    strokes: list[dict[str, Any]],
    segments: list[dict[str, Any]] | None = None,
    dynamic_range: bool = False,
) -> list[dict[str, Any]]:
    """Build zhongshu from strokes, optionally constrained by segments.

    When segments are provided, pivots are built within each segment
    starting from the 2nd stroke (entry stroke skipped). Segments with
    fewer than 4 strokes produce no pivots.
    """
    if not strokes:
        return []

    if not segments:
        # no segment info: build across all strokes (legacy mode)
        return _build_in_range(strokes, 0, len(strokes) - 1, dynamic_range)

    # map stroke start_time -> index
    t2i = {s["start_time"]: i for i, s in enumerate(strokes)}

    pivots: list[dict[str, Any]] = []
    for seg in segments:
        si = t2i.get(seg["start_time"])
        if si is None:
            continue
        # find end index: last stroke with end_time <= seg.end_time
        ei = si
        for j in range(si, len(strokes)):
            if strokes[j]["end_time"] <= seg["end_time"]:
                ei = j
            else:
                break
        # need >= 4 strokes in segment (skip entry, need 3 for overlap)
        seg_n = ei - si + 1
        if seg_n < 4:
            continue
        # build from 2nd stroke of segment
        pivots.extend(_build_in_range(strokes, si + 1, ei, dynamic_range))

    return pivots
