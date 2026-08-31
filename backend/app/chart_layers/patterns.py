"""Self-contained classic price-pattern annotations.

Executable price-structure rules belong in the strategy registry. This module only
keeps the five legacy, heuristic chart patterns that are useful as visual context.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import (
    AnnotationEvidence,
    AnnotationMarker,
    AnnotationSegment,
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


def _empty(
    context: ChartLayerContext,
    layer_id: str,
    title: str,
    minimum: int,
) -> ChartAnnotationLayer:
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
        window = rows[index - span : index + span + 1]
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
            more_extreme = (point.kind == "high" and point.price >= previous.price) or (
                point.kind == "low" and point.price <= previous.price
            )
            if more_extreme:
                compressed[-1] = point
        else:
            compressed.append(point)
    return compressed


def detect_classic(context: ChartLayerContext) -> ChartAnnotationLayer:
    layer_id, title = "pattern.classic", "经典价格形态 (启发式)"
    rows = context.rows
    if len(rows) < 20:
        return _empty(context, layer_id, title, 20)
    swings = _swings(rows)[-24:]
    markers: list[AnnotationMarker] = []
    segments: list[AnnotationSegment] = []
    evidence: list[AnnotationEvidence] = []
    confirmed = str(rows[-1]["date"])

    def add(
        kind: str,
        label: str,
        points: list[Swing],
        reasons: list[str],
    ) -> None:
        evidence_id = f"{layer_id}:{kind}:{points[-1].date}"
        evidence.append(
            AnnotationEvidence(
                id=evidence_id,
                title=label,
                summary="本地摆动点启发式识别, 不代表官方缠论结论",
                reason_codes=reasons,
                metadata={"confirmed_at": confirmed, "heuristic": True},
            )
        )
        for index, point in enumerate(points):
            markers.append(
                AnnotationMarker(
                    id=f"{evidence_id}:{index}",
                    layer_id=layer_id,
                    date=point.date,
                    price=point.price,
                    role="pattern_anchor",
                    label=label if index == 0 else "",
                    evidence_id=evidence_id,
                    confirmed_at=confirmed,
                )
            )
        segments.append(
            AnnotationSegment(
                id=f"{evidence_id}:outline",
                layer_id=layer_id,
                role="pattern_outline",
                points=[{"date": point.date, "price": point.price} for point in points],
                label=label,
                evidence_id=evidence_id,
                confirmed_at=confirmed,
            )
        )

    for index in range(2, len(swings) - 2):
        left, neck1, head, neck2, right = swings[index - 2 : index + 3]
        if (
            left.kind == head.kind == right.kind == "high"
            and head.price > max(left.price, right.price) * 1.01
        ):
            add(
                "head_shoulders_top",
                "头肩顶",
                [left, neck1, head, neck2, right],
                ["head_above_shoulders"],
            )
            break
        if (
            left.kind == head.kind == right.kind == "low"
            and head.price < min(left.price, right.price) * 0.99
        ):
            add(
                "head_shoulders_bottom",
                "头肩底",
                [left, neck1, head, neck2, right],
                ["head_below_shoulders"],
            )
            break
    for first_index, first in enumerate(swings):
        for second in swings[first_index + 2 : first_index + 7]:
            if (
                first.kind == second.kind
                and abs(first.price - second.price) <= max(first.price, second.price) * 0.02
            ):
                add(
                    "double_top" if first.kind == "high" else "double_bottom",
                    "双顶" if first.kind == "high" else "双底",
                    [first, second],
                    ["two_extremes_within_2pct"],
                )
                break
        else:
            continue
        break
    for index in range(max(0, len(swings) - 10), len(swings) - 5):
        group = swings[index : index + 6]
        highs = [point for point in group if point.kind == "high"]
        lows = [point for point in group if point.kind == "low"]
        if (
            len(highs) >= 2
            and len(lows) >= 2
            and highs[-1].price <= highs[0].price * 1.01
            and lows[-1].price >= lows[0].price * 0.99
        ):
            add(
                "triangle",
                "三角形",
                [highs[0], lows[0], highs[-1], lows[-1]],
                ["converging_extremes"],
            )
            break
    return ChartAnnotationLayer(
        id=layer_id,
        category="pattern",
        title=title,
        status="available",
        price_basis=context.price_basis,
        algorithm_version="tickflow-classic-patterns-v1",
        input_fingerprint=context.input_fingerprint,
        markers=markers,
        segments=segments,
        evidence=evidence,
    )


PatternDetector = Callable[[ChartLayerContext], ChartAnnotationLayer]


class PatternLayerProvider:
    category = "pattern"

    def __init__(self, layer_id: str, detector: PatternDetector) -> None:
        self.layer_id = layer_id
        self._detector = detector

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        return self._detector(context)


def pattern_providers() -> list[PatternLayerProvider]:
    return [PatternLayerProvider("pattern.classic", detect_classic)]
