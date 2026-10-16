"""BSP v5: bi-level + segment-level divergence detection.

Bi-level: rules from decision tree + segment-endpoint constraints.
Segment-level: same rules applied to segments with seg-level zhongshu.

Divergence uses direction-aware MACD area (up=red, down=green),
matching chanlun-pro's query_macd_ld.

Verified rules (48 symbols, 581 bi-level official points):
- 1/1p: extrema + on segment endpoint + zhongshu chain
- 2/2s/3a: non-extrema classified by position, pull_ratio, dif_ratio
"""

from __future__ import annotations

from typing import Any


def _hist_area(macd_rows: list[dict], i0: int, i1: int, direction: str = "") -> float:
    """MACD histogram area. If direction given, only count same-sign bars
    (up=red/positive, down=green/negative) — matches chanlun-pro's query_macd_ld."""
    s = 0.0
    for r in macd_rows[max(0, i0) : i1 + 1]:
        h = r.get("histogram", 0.0) or 0.0
        if direction == "up" and h > 0:
            s += h
        elif direction == "down" and h < 0:
            s += abs(h)
        elif not direction:
            s += h
    return abs(s)


def _detect_bsp_level(
    candles: list[dict[str, Any]],
    strokes: list[dict[str, Any]],
    zhongshu: list[dict[str, Any]],
    macd_rows: list[dict[str, Any]],
    seg_times: set[int] | None,
    level: str = "bi",
    *,
    leave_thr: float = 100.0,
    dif_thr: float = 0.5,
    pull_thr_inside: float = 1.0,
    pull_thr_outside: float = 1.0,
    three_b_thr: float = 100.0,
) -> list[dict[str, Any]]:
    """Generic BSP detection for any stroke level (bi or seg)."""
    t2i = {c["time"]: i for i, c in enumerate(candles)}

    bi_by_t: dict[int, list[int]] = {}
    for i, x in enumerate(strokes):
        bi_by_t.setdefault(x["start_time"], []).append(i)
        bi_by_t.setdefault(x["end_time"], []).append(i)

    classified: list[dict] = []
    ones: list[dict] = []

    for t, idxs in bi_by_t.items():
        i = idxs[0]
        cur = strokes[i]
        if t != cur["end_time"]:
            continue
        direction = "buy" if cur["direction"] == "down" else "sell"

        prev_same = None
        for j in range(i - 1, -1, -1):
            if strokes[j]["direction"] == cur["direction"]:
                prev_same = strokes[j]
                break
        if prev_same is None:
            continue

        zs_before = [z for z in zhongshu if z["end_time"] <= t]

        # New feature: stroke count since last zhongshu
        strokes_since_zs = 0
        if zs_before:
            last_zs_end = zs_before[-1]["end_time"]
            for j in range(i, -1, -1):
                if strokes[j]["start_time"] >= last_zs_end:
                    strokes_since_zs += 1
                else:
                    break
        else:
            strokes_since_zs = len(strokes)  # no zhongshu, all strokes
        pos = "no_zs"
        if zs_before:
            last = zs_before[-1]
            if cur["end_price"] > last["high"]:
                pos = "above"
            elif cur["end_price"] < last["low"]:
                pos = "below"
            else:
                pos = "inside"

        is_ext = (
            cur["end_price"] < prev_same["end_price"]
            if cur["direction"] == "down"
            else cur["end_price"] > prev_same["end_price"]
        )
        on_seg = t in seg_times if seg_times else True

        # ratios — direction-aware (up=red/positive, down=green/negative)
        bi_dir = cur["direction"]  # "up" or "down"
        pull_ratio = None
        leaving_ratio = None
        consolidation_ratio = None
        if macd_rows:
            i0 = t2i.get(cur["start_time"], 0)
            i1 = t2i.get(cur["end_time"], len(macd_rows) - 1)
            j0 = t2i.get(prev_same["start_time"], 0)
            j1 = t2i.get(prev_same["end_time"], i0)
            a0 = _hist_area(macd_rows, j0, j1, bi_dir)
            a1 = _hist_area(macd_rows, i0, i1, bi_dir)
            if a0 > 1e-12:
                pull_ratio = a1 / a0
            # Consolidation divergence: leaving vs entering segment of last zhongshu
            if zs_before:
                z = zs_before[-1]
                z_end_idx = t2i.get(z["end_time"], 0)
                a_leave_zs = _hist_area(macd_rows, z_end_idx, i1, bi_dir)
                # Find entering stroke: last stroke ending at/before zhongshu start
                enter_stroke = None
                for j2 in range(i - 1, -1, -1):
                    if strokes[j2]["end_time"] <= z["start_time"]:
                        enter_stroke = strokes[j2]
                        break
                if enter_stroke is not None:
                    e0 = t2i.get(enter_stroke["start_time"], 0)
                    e1 = t2i.get(enter_stroke["end_time"], e0)
                    a_enter = _hist_area(macd_rows, e0, e1, bi_dir)
                    if a_enter > 1e-12:
                        consolidation_ratio = a_leave_zs / a_enter
            # Trend divergence: 2+ zhongshu
            if len(zs_before) >= 2:
                z2 = zs_before[-1]
                z1 = zs_before[-2]
                t0 = t2i.get(z1["end_time"], 0)
                t1 = t2i.get(z2["start_time"], t0)
                t2_ = t2i.get(z2["end_time"], t1)
                t3 = t2i.get(t, len(macd_rows) - 1)
                a_leave = _hist_area(macd_rows, t2_, t3, bi_dir)
                a_prev = _hist_area(macd_rows, t0, t1, bi_dir)
                if a_prev > 1e-12:
                    leaving_ratio = a_leave / a_prev

        # Retracement ratio: how deep current stroke goes vs previous same-direction
        retracement = None
        if cur["direction"] == "down":
            price_range = prev_same["start_price"] - prev_same["end_price"]
            if abs(price_range) > 1e-12:
                retracement = (prev_same["start_price"] - cur["end_price"]) / price_range
        else:
            price_range = prev_same["end_price"] - prev_same["start_price"]
            if abs(price_range) > 1e-12:
                retracement = (cur["end_price"] - prev_same["start_price"]) / price_range

        bsp = {"time": t, "direction": direction, "level": level}
        typ = None

        def _has_prior_one(anchor_dist: int | None = None) -> bool:
            for o in ones:
                if o["direction"] != direction or o["time"] >= t:
                    continue
                oi = bi_by_t.get(o["time"], [None])[0]
                if oi is None or oi >= i:
                    continue
                if anchor_dist is None or i - oi <= anchor_dist:
                    return True
            return False

        # DIF peak ratio
        dif_ratio = None
        if macd_rows:
            sign = -1.0 if cur["direction"] == "down" else 1.0
            d1_vals = [r.get("dif", 0.0) * sign for r in macd_rows[i0:i1 + 1]]
            d0_vals = [r.get("dif", 0.0) * sign for r in macd_rows[j0:j1 + 1]]
            d1 = max(d1_vals) if d1_vals else 0.0
            d0 = max(d0_vals) if d0_vals else 0.0
            if abs(d0) > 1e-12:
                dif_ratio = d1 / d0

        bsp["_feat"] = {
            "pull_ratio": pull_ratio,
            "leaving_ratio": leaving_ratio,
            "consolidation_ratio": consolidation_ratio,
            "retracement": retracement,
            "dif_ratio": dif_ratio,
            "is_ext": is_ext,
            "on_seg": on_seg,
            "pos": pos,
            "chain": 0,
            "outside": (direction == "buy" and pos == "above") or (
                direction == "sell" and pos == "below"
            ),
            "has_prior_one": _has_prior_one(),
            "has_prior_one_5": _has_prior_one(5),
            "strokes_since_zs": strokes_since_zs,
        }

        if is_ext and (on_seg or seg_times is None):
            if leaving_ratio is not None and leaving_ratio > leave_thr:
                typ = None
            else:
                chain = 0
                if zs_before:
                    chain = 1
                    last_h = zs_before[-1]["high"]
                    for z in reversed(zs_before[:-1]):
                        if cur["direction"] == "down":
                            ok = z["high"] < last_h
                            last_h = z["high"]
                        else:
                            ok = z["low"] > last_h
                            last_h = z["low"]
                        if not ok:
                            break
                        chain += 1
                bsp["_feat"]["chain"] = chain
                if chain >= 2 and leaving_ratio is not None and leaving_ratio < 1.0:
                    typ = "1"
                else:
                    typ = "1p"
        else:
            outside = bsp["_feat"]["outside"]
            hp5 = _has_prior_one(5)
            hp1 = _has_prior_one()
            cr = consolidation_ratio
            lr_v = leaving_ratio
            rt_v = retracement
            ss = strokes_since_zs

            if pull_ratio is None:
                if outside:
                    typ = "3a"
                elif hp1:
                    typ = "2s"
                else:
                    typ = None
            elif pull_ratio < 0.31:
                if outside:
                    if lr_v is not None and lr_v < 0.787:
                        typ = "2,3b" if hp5 else "3a"
                    elif ss < 5.5:
                        typ = "3a"
                    else:
                        typ = "2" if hp1 else "3a"
                else:
                    if hp5:
                        typ = "2" if hp1 else None
                    elif ss < 5.5:
                        typ = "2" if hp1 else None
                    else:
                        typ = "2s" if hp1 else None
            else:
                if outside:
                    if ss < 2.5:
                        typ = "3a"
                    elif rt_v is not None and rt_v < 0.32:
                        typ = "3a"
                    else:
                        typ = "2s" if hp1 else "3a"
                else:
                    if ss < 5.5:
                        if rt_v is not None and rt_v < 1.0:
                            typ = "2" if hp1 else None
                        else:
                            typ = "2s" if hp1 else None
                    elif on_seg:
                        typ = "2" if hp1 else None
                    else:
                        typ = "2s" if hp1 else None

        if typ in ("1", "1p"):
            ones.append(bsp)
        if typ is not None:
            bsp["type"] = typ
            classified.append(bsp)

    result = []
    for bsp in classified:
        c = t2i.get(bsp["time"])
        bsp["price"] = candles[c]["close"] if c is not None else 0.0
        bsp["fx_confirmed"] = True
        result.append(bsp)

    result.sort(key=lambda b: b["time"])
    return result


def detect_bsp(
    candles: list[dict[str, Any]],
    bi: list[dict[str, Any]],
    zhongshu: list[dict[str, Any]],
    macd_rows: list[dict[str, Any]] | None = None,
    segments: list[dict[str, Any]] | None = None,
    zhongshu_seg: list[dict[str, Any]] | None = None,
    *,
    leave_thr: float = 100.0,
    dif_thr: float = 0.5,
    pull_thr_inside: float = 1.0,
    pull_thr_outside: float = 1.0,
    three_b_thr: float = 100.0,
) -> list[dict[str, Any]]:
    """Detect buy/sell points at both bi and segment levels."""
    if macd_rows is None:
        from chanlun.macd import macd

        macd_rows = macd(candles)

    seg_times: set[int] = set()
    if segments:
        for s in segments:
            seg_times.add(s["start_time"])
            seg_times.add(s["end_time"])

    # Bi-level BSP
    result = _detect_bsp_level(
        candles, bi, zhongshu, macd_rows, seg_times,
        level="bi",
        leave_thr=leave_thr, dif_thr=dif_thr,
        pull_thr_inside=pull_thr_inside, pull_thr_outside=pull_thr_outside,
        three_b_thr=three_b_thr,
    )

    # Segment-level BSP
    if segments and len(segments) >= 3:
        zs_seg = zhongshu_seg
        if zs_seg is None:
            from chanlun.zhongshu import build_zhongshu
            zs_seg = build_zhongshu(segments)
        seg_result = _detect_bsp_level(
            candles, segments, zs_seg, macd_rows, None,
            level="seg",
            leave_thr=leave_thr, dif_thr=dif_thr,
            pull_thr_inside=pull_thr_inside, pull_thr_outside=pull_thr_outside,
            three_b_thr=three_b_thr,
        )
        result.extend(seg_result)

    result.sort(key=lambda b: (b["time"], b["level"]))
    return result
