"""Self-contained price/volume pattern detectors for chart annotations.

The algorithms intentionally consume only the final chart candles.  They do not import
Quants and every result carries the candle fingerprint and a confirmation date so replay
can hide patterns that were not knowable yet.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from statistics import fmean
from typing import Any

from .models import (
    AnnotationEvidence,
    AnnotationLine,
    AnnotationMarker,
    AnnotationSegment,
    AnnotationZone,
    ChartAnnotationLayer,
    ChartLayerContext,
)


@dataclass(frozen=True)
class Swing:
    index: int
    date: str
    price: float
    kind: str


def _number(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if value is not None else 0.0


def _metric(name: str, value: Any, *, threshold: Any = None, unit: str = "", passed: bool | None = None) -> dict[str, Any]:
    return {"name": name, "value": value, "threshold": threshold, "unit": unit, "passed": passed}


def _empty(context: ChartLayerContext, layer_id: str, title: str, minimum: int) -> ChartAnnotationLayer:
    return ChartAnnotationLayer(
        id=layer_id,
        category="pattern",
        title=title,
        status="insufficient_data",
        price_basis=context.price_basis,
        algorithm_version="tickflow-patterns-v1",
        input_fingerprint=context.input_fingerprint,
        warnings=[f"至少需要 {minimum} 根同口径 K 线, 当前 {len(context.rows)} 根"],
    )


def _swings(rows: list[dict[str, Any]], span: int = 2) -> list[Swing]:
    result: list[Swing] = []
    for index in range(span, len(rows) - span):
        window = rows[index - span:index + span + 1]
        high = _number(rows[index], "high")
        low = _number(rows[index], "low")
        if high > 0 and high == max(_number(row, "high") for row in window):
            result.append(Swing(index, str(rows[index]["date"]), high, "high"))
        if low > 0 and low == min(_number(row, "low") for row in window):
            result.append(Swing(index, str(rows[index]["date"]), low, "low"))
    result.sort(key=lambda item: (item.index, 0 if item.kind == "low" else 1))
    compressed: list[Swing] = []
    for point in result:
        if compressed and compressed[-1].kind == point.kind:
            previous = compressed[-1]
            if (point.kind == "high" and point.price >= previous.price) or (point.kind == "low" and point.price <= previous.price):
                compressed[-1] = point
        else:
            compressed.append(point)
    return compressed


def detect_vcp(context: ChartLayerContext) -> ChartAnnotationLayer:
    layer_id, title = "pattern.vcp", "VCP 波动收缩"
    rows = context.rows
    if len(rows) < 45:
        return _empty(context, layer_id, title, 45)
    window = rows[-260:]
    swings = _swings(window)
    pullbacks: list[tuple[Swing, Swing, float]] = []
    for left, right in pairwise(swings):
        if left.kind == "high" and right.kind == "low" and left.price > 0:
            pullbacks.append((left, right, (left.price - right.price) / left.price))
    recent = pullbacks[-4:]
    if len(recent) < 2:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-vcp-v1", input_fingerprint=context.input_fingerprint)
    best: list[tuple[Swing, Swing, float]] = [recent[0]]
    for item in recent[1:]:
        if item[2] <= best[-1][2] * 0.97:
            best.append(item)
        elif len(best) < 2:
            best = [item]
    if len(best) < 2:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-vcp-v1", input_fingerprint=context.input_fingerprint)
    pivot = best[-1][0].price
    latest = _number(window[-1], "close")
    # The contraction is knowable once its final low has printed.  Later lifecycle
    # markers keep their own confirmation dates so replay does not reveal a future
    # breakout, failure, support test, or retrigger.
    confirmed = best[-1][1].date
    evidence_id = f"{layer_id}:{confirmed}"
    depths = [round(item[2] * 100, 2) for item in best]
    lows = [item[1].price for item in best]
    rising_lows = all(current >= previous * 0.97 for previous, current in pairwise(lows))
    volumes = [_number(row, "volume") for row in window]
    recent_volume = fmean(volumes[-5:]) if any(volumes[-5:]) else 0.0
    base_volume = fmean(volumes[-25:-5]) if any(volumes[-25:-5]) else 0.0
    dry_ratio = recent_volume / base_volume if base_volume > 0 else None
    markers = [AnnotationMarker(id=f"{evidence_id}:base", layer_id=layer_id, date=best[0][0].date, price=best[0][0].price, role="pattern_anchor", label="Base", evidence_id=evidence_id, detected_at=confirmed, confirmed_at=confirmed)]
    for index, (_, low, _) in enumerate(best, 1):
        markers.append(AnnotationMarker(id=f"{evidence_id}:c{index}", layer_id=layer_id, date=low.date, price=low.price, role="contraction_low", label=f"C{index}", evidence_id=evidence_id, detected_at=confirmed, confirmed_at=confirmed))
    last_low_index = best[-1][1].index
    lifecycle_rows = window[last_low_index + 1:]
    breakout_index: int | None = next(
        (index for index, row in enumerate(lifecycle_rows) if _number(row, "close") >= pivot),
        None,
    )
    failure_date: str | None = None
    support_date: str | None = None
    retrigger_date: str | None = None
    if breakout_index is not None:
        breakout_row = lifecycle_rows[breakout_index]
        breakout_date = str(breakout_row["date"])
        markers.append(AnnotationMarker(id=f"{evidence_id}:breakout", layer_id=layer_id, date=breakout_date, price=_number(breakout_row, "close"), role="breakout", label="突破", evidence_id=evidence_id, detected_at=breakout_date, confirmed_at=breakout_date))
        failed = False
        for row in lifecycle_rows[breakout_index + 1:]:
            row_date = str(row["date"])
            close = _number(row, "close")
            low = _number(row, "low")
            if not failed and close < pivot * 0.97:
                failed = True
                failure_date = row_date
                markers.append(AnnotationMarker(id=f"{evidence_id}:failure", layer_id=layer_id, date=row_date, price=close, role="failure", label="跌破 Pivot", evidence_id=evidence_id, detected_at=row_date, confirmed_at=row_date, invalidated_at=row_date))
            elif failed and close >= pivot:
                retrigger_date = row_date
                markers.append(AnnotationMarker(id=f"{evidence_id}:retrigger", layer_id=layer_id, date=row_date, price=close, role="retrigger", label="再触发", evidence_id=evidence_id, detected_at=row_date, confirmed_at=row_date))
                failed = False
            elif not failed and low <= pivot * 1.03 and close >= pivot:
                support_date = row_date
                markers.append(AnnotationMarker(id=f"{evidence_id}:support", layer_id=layer_id, date=row_date, price=close, role="support", label="守轴", evidence_id=evidence_id, detected_at=row_date, confirmed_at=row_date))
    upper_points = [{"date": item[0].date, "price": item[0].price} for item in best]
    lower_points = [{"date": item[1].date, "price": item[1].price} for item in best]
    start_date = best[0][0].date
    return ChartAnnotationLayer(
        id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis,
        algorithm_version="tickflow-vcp-v1", input_fingerprint=context.input_fingerprint,
        markers=markers,
        lines=[AnnotationLine(id=f"{evidence_id}:pivot", layer_id=layer_id, role="trigger", value=pivot, start_date=best[-1][0].date, end_date=str(window[-1]["date"]), label="Pivot", evidence_id=evidence_id)],
        zones=[AnnotationZone(id=f"{evidence_id}:zone", layer_id=layer_id, role="consolidation", start_date=start_date, end_date=confirmed, low=min(lows), high=max(item[0].price for item in best), label="VCP 收敛区", evidence_id=evidence_id, confirmed_at=confirmed)],
        segments=[
            AnnotationSegment(id=f"{evidence_id}:upper", layer_id=layer_id, role="convergence_upper", points=upper_points, label="收敛上沿", evidence_id=evidence_id, confirmed_at=confirmed),
            AnnotationSegment(id=f"{evidence_id}:lower", layer_id=layer_id, role="convergence_lower", points=lower_points, label="收敛下沿", evidence_id=evidence_id, confirmed_at=confirmed),
        ],
        evidence=[AnnotationEvidence(id=evidence_id, title="VCP 波动收缩", summary=f"识别 {len(best)} 段连续收缩, Pivot {pivot:.2f}", reason_codes=["vcp_contraction", "rising_lows" if rising_lows else "lows_not_rising"], metrics=[_metric("回撤深度", depths, unit="%", passed=True), _metric("低点抬高", rising_lows, passed=rising_lows), _metric("近5日量/前20日量", round(dry_ratio, 3) if dry_ratio is not None else None, threshold="<=0.9", unit="ratio", passed=dry_ratio is not None and dry_ratio <= 0.9), _metric("距Pivot", round((latest / pivot - 1) * 100, 2), unit="%")], metadata={"confirmed_at": confirmed, "start_date": start_date, "price_basis": context.price_basis, "pivot": pivot, "failure_at": failure_date, "support_at": support_date, "retrigger_at": retrigger_date})],
    )


def detect_cup_handle(context: ChartLayerContext) -> ChartAnnotationLayer:
    layer_id, title = "pattern.cup_handle", "杯柄形态"
    rows = context.rows
    if len(rows) < 60:
        return _empty(context, layer_id, title, 60)
    window = rows[-260:]
    n = len(window)
    left_end = max(10, int(n * 0.42))
    left_idx = max(range(left_end), key=lambda i: _number(window[i], "high"))
    if left_idx >= n - 15:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-cup-handle-v1", input_fingerprint=context.input_fingerprint)
    bottom_idx = min(range(left_idx + 1, n - 10), key=lambda i: _number(window[i], "low"))
    right_candidates = range(bottom_idx + 1, n - 4)
    if not list(right_candidates):
        return _empty(context, layer_id, title, 60)
    right_idx = max(right_candidates, key=lambda i: _number(window[i], "high"))
    left, bottom, right = _number(window[left_idx], "high"), _number(window[bottom_idx], "low"), _number(window[right_idx], "high")
    depth = (left - bottom) / left if left else 9.0
    rim_diff = abs(right - left) / left if left else 9.0
    handle_rows = window[right_idx + 1:]
    if not (0.12 <= depth <= 0.45 and rim_diff <= 0.12 and len(handle_rows) >= 3):
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-cup-handle-v1", input_fingerprint=context.input_fingerprint)
    neckline = max(left, right)
    handle_low = min(_number(row, "low") for row in handle_rows)
    handle_depth = (neckline - handle_low) / neckline
    if handle_depth > 0.18:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-cup-handle-v1", input_fingerprint=context.input_fingerprint)
    confirmed = str(window[-1]["date"])
    evidence_id = f"{layer_id}:{confirmed}"
    handle_volumes = [_number(row, "volume") for row in handle_rows]
    cup_volumes = [_number(row, "volume") for row in window[left_idx:right_idx + 1]]
    volume_ratio = (fmean(handle_volumes) / fmean(cup_volumes)) if any(handle_volumes) and any(cup_volumes) else None
    anchors = [("左杯沿", left_idx, left), ("杯底", bottom_idx, bottom), ("右杯沿", right_idx, right), ("柄部低点", right_idx + 1 + min(range(len(handle_rows)), key=lambda i: _number(handle_rows[i], "low")), handle_low)]
    markers = [AnnotationMarker(id=f"{evidence_id}:{index}", layer_id=layer_id, date=str(window[row_idx]["date"]), price=price, role="pattern_anchor", label=label, evidence_id=evidence_id, detected_at=confirmed, confirmed_at=confirmed) for index, (label, row_idx, price) in enumerate(anchors)]
    return ChartAnnotationLayer(
        id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-cup-handle-v1", input_fingerprint=context.input_fingerprint,
        markers=markers,
        lines=[AnnotationLine(id=f"{evidence_id}:neckline", layer_id=layer_id, role="candidate_trigger", value=neckline, start_date=str(window[left_idx]["date"]), end_date=confirmed, label="杯沿/候选突破位", evidence_id=evidence_id)],
        zones=[AnnotationZone(id=f"{evidence_id}:cup", layer_id=layer_id, role="pattern_body", start_date=str(window[left_idx]["date"]), end_date=str(window[right_idx]["date"]), low=bottom, high=neckline, label="杯体", evidence_id=evidence_id, confirmed_at=confirmed), AnnotationZone(id=f"{evidence_id}:handle", layer_id=layer_id, role="consolidation", start_date=str(handle_rows[0]["date"]), end_date=confirmed, low=handle_low, high=neckline, label="杯柄", evidence_id=evidence_id, confirmed_at=confirmed)],
        segments=[AnnotationSegment(id=f"{evidence_id}:shape", layer_id=layer_id, role="pattern_outline", points=[{"date": str(window[left_idx]["date"]), "price": left}, {"date": str(window[bottom_idx]["date"]), "price": bottom}, {"date": str(window[right_idx]["date"]), "price": right}], label="杯体轮廓", evidence_id=evidence_id, confirmed_at=confirmed)],
        evidence=[AnnotationEvidence(id=evidence_id, title=title, summary=f"杯深 {depth * 100:.1f}%, 柄深 {handle_depth * 100:.1f}%", reason_codes=["cup_depth_valid", "rim_similarity", "handle_tight"], metrics=[_metric("杯体深度", round(depth * 100, 2), threshold="12-45", unit="%", passed=True), _metric("杯沿差异", round(rim_diff * 100, 2), threshold="<=12", unit="%", passed=True), _metric("杯柄深度", round(handle_depth * 100, 2), threshold="<=18", unit="%", passed=True), _metric("杯柄量/杯体量", round(volume_ratio, 3) if volume_ratio is not None else None, unit="ratio")], metadata={"confirmed_at": confirmed})],
    )


def detect_high_tight_flag(context: ChartLayerContext) -> ChartAnnotationLayer:
    layer_id, title = "pattern.high_tight_flag", "高而紧旗形"
    rows = context.rows
    if len(rows) < 20:
        return _empty(context, layer_id, title, 20)
    window = rows[-120:]
    pole_part = window[:-4]
    low_idx = min(range(len(pole_part)), key=lambda i: _number(pole_part[i], "low"))
    high_options = range(low_idx + 1, len(pole_part))
    if not list(high_options):
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-htf-v1", input_fingerprint=context.input_fingerprint)
    high_idx = max(high_options, key=lambda i: _number(pole_part[i], "high"))
    pole_low, pole_high = _number(window[low_idx], "low"), _number(window[high_idx], "high")
    gain = pole_high / pole_low - 1 if pole_low else 0
    flag = window[high_idx + 1:]
    if gain < 0.8 or len(flag) < 4:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-htf-v1", input_fingerprint=context.input_fingerprint)
    flag_high, flag_low = max(_number(row, "high") for row in flag), min(_number(row, "low") for row in flag)
    depth = (pole_high - flag_low) / pole_high
    if depth > 0.22:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-htf-v1", input_fingerprint=context.input_fingerprint)
    confirmed = str(window[-1]["date"])
    evidence_id = f"{layer_id}:{confirmed}"
    pole_volume = fmean([_number(row, "volume") for row in window[low_idx:high_idx + 1]])
    flag_volume = fmean([_number(row, "volume") for row in flag])
    volume_ratio = flag_volume / pole_volume if pole_volume > 0 else None
    return ChartAnnotationLayer(
        id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-htf-v1", input_fingerprint=context.input_fingerprint,
        markers=[AnnotationMarker(id=f"{evidence_id}:start", layer_id=layer_id, date=str(window[low_idx]["date"]), price=pole_low, role="pattern_anchor", label="旗杆起点", evidence_id=evidence_id, confirmed_at=confirmed), AnnotationMarker(id=f"{evidence_id}:end", layer_id=layer_id, date=str(window[high_idx]["date"]), price=pole_high, role="pattern_anchor", label="旗杆顶", evidence_id=evidence_id, confirmed_at=confirmed)],
        lines=[AnnotationLine(id=f"{evidence_id}:trigger", layer_id=layer_id, role="candidate_trigger", value=flag_high, start_date=str(flag[0]["date"]), end_date=confirmed, label="旗形突破位", evidence_id=evidence_id)],
        zones=[AnnotationZone(id=f"{evidence_id}:flag", layer_id=layer_id, role="consolidation", start_date=str(flag[0]["date"]), end_date=confirmed, low=flag_low, high=flag_high, label="紧旗整理", evidence_id=evidence_id, confirmed_at=confirmed)],
        segments=[AnnotationSegment(id=f"{evidence_id}:pole", layer_id=layer_id, role="impulse", points=[{"date": str(window[low_idx]["date"]), "price": pole_low}, {"date": str(window[high_idx]["date"]), "price": pole_high}], label="旗杆", evidence_id=evidence_id, confirmed_at=confirmed)],
        evidence=[AnnotationEvidence(id=evidence_id, title=title, summary=f"旗杆涨幅 {gain * 100:.1f}%, 整理回撤 {depth * 100:.1f}%", reason_codes=["flagpole_gain", "tight_flag"], metrics=[_metric("旗杆涨幅", round(gain * 100, 2), threshold=80, unit="%", passed=True), _metric("旗杆交易日", high_idx - low_idx + 1, unit="bars"), _metric("整理深度", round(depth * 100, 2), threshold="<=22", unit="%", passed=True), _metric("整理量/旗杆量", round(volume_ratio, 3) if volume_ratio is not None else None, unit="ratio")], metadata={"confirmed_at": confirmed})],
    )


def detect_pullback_absorb(context: ChartLayerContext) -> ChartAnnotationLayer:
    layer_id, title = "pattern.pullback_absorb", "启动后缩量回踩"
    rows = context.rows
    if len(rows) < 25:
        return _empty(context, layer_id, title, 25)
    window = rows[-40:]
    anchor_idx = None
    for index in range(max(5, len(window) - 11), len(window) - 2):
        previous = _number(window[index - 1], "close")
        change = _number(window[index], "close") / previous - 1 if previous else 0
        prior_volumes = [_number(row, "volume") for row in window[max(0, index - 20):index]]
        volume_ratio = _number(window[index], "volume") / fmean(prior_volumes) if prior_volumes and fmean(prior_volumes) > 0 else 0
        if change >= 0.06 and volume_ratio >= 2.0:
            anchor_idx = index
    if anchor_idx is None:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-pullback-absorb-v1", input_fingerprint=context.input_fingerprint)
    anchor = window[anchor_idx]
    current = window[-1]
    midline = (_number(anchor, "open") + _number(anchor, "close")) / 2
    current_volume = _number(current, "volume")
    anchor_volume = _number(anchor, "volume")
    previous_close = _number(window[-2], "close")
    current_change = _number(current, "close") / previous_close - 1 if previous_close else 0
    volume_ratio = current_volume / anchor_volume if anchor_volume else 9
    valid = volume_ratio <= 0.6 and abs(current_change) <= 0.02 and _number(current, "close") >= midline
    if not valid:
        return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-pullback-absorb-v1", input_fingerprint=context.input_fingerprint)
    confirmed = str(current["date"])
    evidence_id = f"{layer_id}:{confirmed}"
    zone_rows = window[anchor_idx + 1:]
    return ChartAnnotationLayer(
        id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-pullback-absorb-v1", input_fingerprint=context.input_fingerprint,
        markers=[AnnotationMarker(id=f"{evidence_id}:anchor", layer_id=layer_id, date=str(anchor["date"]), price=_number(anchor, "close"), role="impulse", label="启动日", evidence_id=evidence_id, confirmed_at=confirmed), AnnotationMarker(id=f"{evidence_id}:test", layer_id=layer_id, date=confirmed, price=_number(current, "close"), role="support", label="缩量回踩", evidence_id=evidence_id, confirmed_at=confirmed)],
        lines=[AnnotationLine(id=f"{evidence_id}:support", layer_id=layer_id, role="support", value=midline, start_date=str(anchor["date"]), end_date=confirmed, label="启动中位支撑", evidence_id=evidence_id)],
        zones=[AnnotationZone(id=f"{evidence_id}:zone", layer_id=layer_id, role="pullback", start_date=str(zone_rows[0]["date"]), end_date=confirmed, low=min(_number(row, "low") for row in zone_rows), high=max(_number(row, "high") for row in zone_rows), label="缩量回调区", evidence_id=evidence_id, confirmed_at=confirmed)],
        evidence=[AnnotationEvidence(id=evidence_id, title=title, summary=f"启动后 {len(window) - anchor_idx - 1} 根 K 线回踩, 中位支撑 {midline:.2f}", reason_codes=["launch_day", "volume_dry_pullback", "support_held"], metrics=[_metric("回调量/启动量", round(volume_ratio, 3), threshold="<=0.60", unit="ratio", passed=True), _metric("回调涨跌", round(current_change * 100, 2), threshold="abs<=2", unit="%", passed=True), _metric("中位支撑", round(midline, 4), unit="price", passed=True)], metadata={"confirmed_at": confirmed})],
    )


def detect_classic(context: ChartLayerContext) -> ChartAnnotationLayer:
    layer_id, title = "pattern.classic", "经典价格形态(启发式)"
    rows = context.rows
    if len(rows) < 20:
        return _empty(context, layer_id, title, 20)
    swings = _swings(rows)[-24:]
    markers: list[AnnotationMarker] = []
    segments: list[AnnotationSegment] = []
    evidence: list[AnnotationEvidence] = []
    confirmed = str(rows[-1]["date"])

    def add(kind: str, label: str, points: list[Swing], reasons: list[str]) -> None:
        evidence_id = f"{layer_id}:{kind}:{points[-1].date}"
        evidence.append(AnnotationEvidence(id=evidence_id, title=label, summary="本地摆动点启发式识别, 不代表官方缠论结论", reason_codes=reasons, metadata={"confirmed_at": confirmed, "heuristic": True}))
        for index, point in enumerate(points):
            markers.append(AnnotationMarker(id=f"{evidence_id}:{index}", layer_id=layer_id, date=point.date, price=point.price, role="pattern_anchor", label=label if index == 0 else "", evidence_id=evidence_id, confirmed_at=confirmed))
        segments.append(AnnotationSegment(id=f"{evidence_id}:outline", layer_id=layer_id, role="pattern_outline", points=[{"date": point.date, "price": point.price} for point in points], label=label, evidence_id=evidence_id, confirmed_at=confirmed))

    for index in range(2, len(swings) - 2):
        five = swings[index - 2:index + 3]
        left, neck1, head, neck2, right = five
        if left.kind == head.kind == right.kind == "high" and head.price > max(left.price, right.price) * 1.01:
            add("head_shoulders_top", "头肩顶", [left, neck1, head, neck2, right], ["head_above_shoulders"])
            break
        if left.kind == head.kind == right.kind == "low" and head.price < min(left.price, right.price) * 0.99:
            add("head_shoulders_bottom", "头肩底", [left, neck1, head, neck2, right], ["head_below_shoulders"])
            break
    for first_index, first in enumerate(swings):
        for second in swings[first_index + 2:first_index + 7]:
            if first.kind == second.kind and abs(first.price - second.price) <= max(first.price, second.price) * 0.02:
                add("double_top" if first.kind == "high" else "double_bottom", "双顶" if first.kind == "high" else "双底", [first, second], ["two_extremes_within_2pct"])
                break
        else:
            continue
        break
    for index in range(max(0, len(swings) - 10), len(swings) - 5):
        group = swings[index:index + 6]
        highs = [point for point in group if point.kind == "high"]
        lows = [point for point in group if point.kind == "low"]
        if len(highs) >= 2 and len(lows) >= 2 and highs[-1].price <= highs[0].price * 1.01 and lows[-1].price >= lows[0].price * 0.99:
            add("triangle", "三角形", [highs[0], lows[0], highs[-1], lows[-1]], ["converging_extremes"])
            break
    return ChartAnnotationLayer(id=layer_id, category="pattern", title=title, status="available", price_basis=context.price_basis, algorithm_version="tickflow-classic-patterns-v1", input_fingerprint=context.input_fingerprint, markers=markers, segments=segments, evidence=evidence)


PatternDetector = Callable[[ChartLayerContext], ChartAnnotationLayer]


class PatternLayerProvider:
    category = "pattern"

    def __init__(self, layer_id: str, detector: PatternDetector) -> None:
        self.layer_id = layer_id
        self._detector = detector

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        return self._detector(context)


def pattern_providers() -> list[PatternLayerProvider]:
    return [
        PatternLayerProvider("pattern.classic", detect_classic),
        PatternLayerProvider("pattern.cup_handle", detect_cup_handle),
        PatternLayerProvider("pattern.high_tight_flag", detect_high_tight_flag),
        PatternLayerProvider("pattern.pullback_absorb", detect_pullback_absorb),
        PatternLayerProvider("pattern.vcp", detect_vcp),
    ]
