"""Chan segments (线段) — v2 with 4 additional split types.

Base algorithm: E1 (fractal apex + post-confirmation) + E2 (breakout).
Additional splits (from chanlun-pro 6-type system):
  3. 非标准拆分: ≥9 strokes, start/end not extremes → split at actual extreme
  4. 中枢扩展拆分: two adjacent zhongshu overlap → split at boundary
  5. 中枢不同向拆分: zhongshu opposite to segment direction → split
  6. 中枢多段拆分: zhongshu > N strokes → split at Nth stroke
"""

from __future__ import annotations

from typing import Any


def _stroke_range(s: dict) -> tuple[float, float]:
    p0 = s.get("start_price", 0.0)
    p1 = s.get("end_price", 0.0)
    return max(p0, p1), min(p0, p1)


def _build_zs_in_seg(strokes: list[dict], si: int, ei: int) -> list[dict]:
    """Build zhongshu within strokes[si:ei+1], starting from 2nd stroke."""
    pivots: list[dict] = []
    n = ei + 1
    i = si + 1  # skip entry stroke
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
        zs_start = a["start_time"]
        zs_start_idx = i
        j = i + 3
        while j < n:
            sh, sl = _stroke_range(strokes[j])
            if sl < zg and sh > zd:
                j += 1
            else:
                break
        zs_end_idx = j - 1 if j < n else n - 1
        pivots.append({
            "start_time": zs_start,
            "end_time": strokes[zs_end_idx]["end_time"],
            "low": zd, "high": zg,
            "start_stroke_idx": zs_start_idx,
            "end_stroke_idx": zs_end_idx,
            "stroke_count": zs_end_idx - zs_start_idx + 1,
        })
        i = j + 1
    return pivots


def _make_seg(strokes: list[dict], si: int, ei: int, direction: str) -> dict:
    s = strokes[si]
    e = strokes[ei]
    return {
        "start_time": s["start_time"], "start_price": s["start_price"],
        "end_time": e["end_time"], "end_price": e["end_price"],
        "direction": direction, "is_sure": True,
        "start_index": s.get("start_index"),
        "end_index": e.get("end_index"),
        "confirm_index": e.get("confirm_index"),
    }


def _try_split_nonstandard(strokes: list[dict], si: int, ei: int,
                           seg: dict, min_strokes: int = 9) -> int | None:
    """Type 3: ≥9 strokes, start/end not extremes → split at actual extreme."""
    n = ei - si + 1
    if n < min_strokes:
        return None
    d0 = seg["direction"]
    if d0 == "up":
        # Start should be lowest, end should be highest
        prices = [(j, strokes[j]["end_price"]) for j in range(si, ei + 1)]
        prices.append((si, strokes[si]["start_price"]))
        lo_idx = min(prices, key=lambda x: x[1])[0]
        hi_idx = max(prices, key=lambda x: x[1])[0]
        # If end is not the highest, split at the highest point
        if hi_idx != ei and hi_idx > si + 2:
            return hi_idx
        # If start is not the lowest, split at the lowest point
        if lo_idx != si and lo_idx < ei - 2 and lo_idx > si:
            return lo_idx
    else:
        prices = [(j, strokes[j]["end_price"]) for j in range(si, ei + 1)]
        prices.append((si, strokes[si]["start_price"]))
        hi_idx = max(prices, key=lambda x: x[1])[0]
        lo_idx = min(prices, key=lambda x: x[1])[0]
        if lo_idx != ei and lo_idx > si + 2:
            return lo_idx
        if hi_idx != si and hi_idx < ei - 2 and hi_idx > si:
            return hi_idx
    return None


def _try_split_zs_multistroke(strokes: list[dict], si: int, ei: int,
                              max_zs_strokes: int = 9) -> int | None:
    """Type 6: zhongshu > N strokes → split at Nth stroke."""
    pivots = _build_zs_in_seg(strokes, si, ei)
    for p in pivots:
        if p["stroke_count"] > max_zs_strokes:
            # Split at the max_zs_strokes-th stroke of the zhongshu
            split_idx = p["start_stroke_idx"] + max_zs_strokes
            if split_idx < ei:
                return split_idx
    return None


def _try_split_zs_extension(strokes: list[dict], si: int, ei: int) -> int | None:
    """Type 4: two adjacent zhongshu overlap → split at boundary."""
    pivots = _build_zs_in_seg(strokes, si, ei)
    for k in range(len(pivots) - 1):
        p1, p2 = pivots[k], pivots[k + 1]
        # Check price overlap
        if p1["low"] <= p2["high"] and p2["low"] <= p1["high"]:
            # Split at the boundary between p1 and p2
            boundary = p1["end_stroke_idx"]
            if boundary > si + 2 and boundary < ei - 2:
                return boundary
    return None


def _try_split_zs_direction(strokes: list[dict], si: int, ei: int,
                            seg: dict) -> int | None:
    """Type 5: zhongshu opposite to segment direction → split."""
    pivots = _build_zs_in_seg(strokes, si, ei)
    d0 = seg["direction"]
    for p in pivots:
        # Determine zhongshu direction: compare first and last stroke
        first_s = strokes[p["start_stroke_idx"]]
        last_s = strokes[p["end_stroke_idx"]]
        if first_s["end_price"] > last_s["end_price"]:
            zs_dir = "up" if first_s["direction"] == "up" else "down"
        else:
            zs_dir = "down" if first_s["direction"] == "up" else "up"
        # If zhongshu direction is opposite to segment direction
        if zs_dir != d0:
            split_idx = p["start_stroke_idx"]
            if split_idx > si + 2 and split_idx < ei - 2:
                return split_idx
    return None


def _apply_additional_splits(
    strokes: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    max_zs_strokes: int = 9,
    min_seg_strokes: int = 9,
) -> list[dict[str, Any]]:
    """Apply 4 additional split types as post-processing."""
    if not segments or not strokes:
        return segments

    t2i = {s["start_time"]: i for i, s in enumerate(strokes)}

    result: list[dict] = []
    for seg in segments:
        si = t2i.get(seg["start_time"])
        if si is None:
            result.append(seg)
            continue
        ei = si
        for j in range(si, len(strokes)):
            if strokes[j]["end_time"] <= seg["end_time"]:
                ei = j
            else:
                break

        split_idx = None
        d0 = seg["direction"]

        # Try each split type in priority order
        if split_idx is None:
            split_idx = _try_split_zs_multistroke(strokes, si, ei, max_zs_strokes)
        if split_idx is None:
            split_idx = _try_split_nonstandard(strokes, si, ei, seg, min_seg_strokes)
        if split_idx is None:
            split_idx = _try_split_zs_extension(strokes, si, ei)
        if split_idx is None:
            split_idx = _try_split_zs_direction(strokes, si, ei, seg)

        if split_idx is not None and split_idx > si + 3 and split_idx < ei - 3:
            left = _make_seg(strokes, si, split_idx, d0)
            next_dir = strokes[split_idx + 1]["direction"] if split_idx + 1 <= ei else ("down" if d0 == "up" else "up")
            right = _make_seg(strokes, split_idx + 1, ei, next_dir)
            left_segs = _apply_additional_splits(
                strokes, [left], max_zs_strokes, min_seg_strokes)
            right_segs = _apply_additional_splits(
                strokes, [right], max_zs_strokes, min_seg_strokes)
            result.extend(left_segs)
            result.extend(right_segs)
        else:
            result.append(seg)

    return result


def build_segments(
    strokes: list[dict[str, Any]],
    *,
    enable_additional_splits: bool = False,
    max_zs_strokes: int = 9,
    min_seg_strokes: int = 9,
) -> list[dict[str, Any]]:
    if not strokes:
        return []
    n = len(strokes)
    segments: list[dict[str, Any]] = []
    i = 0

    # First segment is always the first stroke (Chan theory fundamental rule)
    first = strokes[0]
    segments.append(_make_seg(strokes, 0, 0, first["direction"]))
    i = 1
    if i >= n:
        return segments

    while i < n:
        d0 = strokes[i]["direction"]
        start_p = strokes[i]["start_price"]

        # E2: breakout — opposite-direction stroke breaks segment start
        e2_end: int | None = None
        for j in range(i + 1, n):
            if strokes[j]["direction"] == d0:
                continue
            if d0 == "up":
                if strokes[j]["end_price"] < start_p:
                    # E2 confirmation: next up bi should also stay below start
                    if j + 1 < n and strokes[j + 1]["direction"] == d0 and strokes[j + 1]["end_price"] >= start_p:
                        continue  # false breakout, price recovers
                    e2_end = j - 1
                    break
            else:
                if strokes[j]["end_price"] > start_p:
                    # E2 confirmation: next down bi should also stay above start
                    if j + 1 < n and strokes[j + 1]["direction"] == d0 and strokes[j + 1]["end_price"] <= start_p:
                        continue  # false breakout, price drops back
                    e2_end = j - 1
                    break

        # E1: fractal + post-confirmation
        feats = [j for j in range(i + 1, n) if strokes[j]["direction"] != d0]
        e1_apex_t: int | None = None
        # Special case: 2 feats — check if the last one is a valid apex
        if len(feats) == 2:
            f1, f2 = feats[0], feats[1]
            e2s = strokes[f2]
            if d0 == "up":
                apex = e2s["start_price"] > strokes[f1]["start_price"]
            else:
                apex = e2s["start_price"] < strokes[f1]["start_price"]
            if apex:
                e1_apex_t = e2s["start_time"]
        # Standard case: 3+ feats — find middle apex
        for k in range(len(feats) - 2):
            f1, f2, f3 = feats[k], feats[k + 1], feats[k + 2]
            e2s = strokes[f2]
            if d0 == "up":
                apex = e2s["start_price"] > strokes[f1]["start_price"] and e2s["start_price"] > strokes[f3]["start_price"]
            else:
                apex = e2s["start_price"] < strokes[f1]["start_price"] and e2s["start_price"] < strokes[f3]["start_price"]
            if not apex:
                continue
            apex_p = e2s["start_price"]
            nxt_i = f3 + 1
            # S4: require at least 1 confirmation stroke in segment direction
            if nxt_i >= n or strokes[nxt_i]["direction"] != d0:
                continue
            if d0 == "up":
                if strokes[nxt_i]["end_price"] > apex_p:
                    continue
            else:
                if strokes[nxt_i]["end_price"] < apex_p:
                    continue
            e1_apex_t = e2s["start_time"]
            break

        cand = []
        if e1_apex_t is not None:
            cand.append(e1_apex_t)
        if e2_end is not None:
            cand.append(strokes[e2_end]["end_time"])
        if not cand:
            last = strokes[-1]
            segments.append({"start_time": strokes[i]["start_time"], "start_price": strokes[i]["start_price"],
                "end_time": last["end_time"], "end_price": last["end_price"], "direction": d0,
                "is_sure": bool(last.get("is_sure", True)), "start_index": strokes[i].get("start_index"),
                "end_index": last.get("end_index"), "confirm_index": last.get("confirm_index")})
            break
        end_t = min(cand)
        end_price = end_idx = end_conf = None
        for s in strokes:
            if s["end_time"] == end_t:
                end_price = s["end_price"]; end_idx = s.get("end_index"); end_conf = s.get("confirm_index")
        segments.append({"start_time": strokes[i]["start_time"], "start_price": strokes[i]["start_price"],
            "end_time": end_t, "end_price": end_price if end_price is not None else strokes[i]["end_price"],
            "direction": d0, "is_sure": True, "start_index": strokes[i].get("start_index"),
            "end_index": end_idx, "confirm_index": end_conf})
        nxt = None
        for j in range(i + 1, n):
            if strokes[j]["start_time"] == end_t:
                nxt = j; break
        if nxt is None:
            break
        i = nxt

    if enable_additional_splits and segments:
        segments = _apply_additional_splits(
            strokes, segments, max_zs_strokes, min_seg_strokes)

    return segments
