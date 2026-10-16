from __future__ import annotations

from datetime import date

from app.services.strategy_signal_events import StrategySignalEventRepository

from .models import (
    AnnotationEvidence,
    AnnotationLine,
    AnnotationMarker,
    AnnotationZone,
    ChartAnnotationLayer,
    ChartLayerContext,
)
from .patterns import pattern_providers
from .registry import ChartLayerRegistry


class MarketEventLayerProvider:
    layer_id = "event.market"
    category = "event"

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        markers: list[AnnotationMarker] = []
        evidence: list[AnnotationEvidence] = []
        for row in context.rows:
            role = label = reason = None
            if row.get("signal_limit_up"):
                role, label, reason = "market_event", "涨停", "limit_up"
            elif row.get("signal_broken_limit_up"):
                role, label, reason = "market_event", "炸板", "broken_limit_up"
            if not role:
                continue
            day = str(row["date"])
            evidence_id = f"{self.layer_id}:{reason}:{day}"
            markers.append(AnnotationMarker(id=evidence_id, layer_id=self.layer_id, date=day, price=float(row["high"]), role=role, label=label, evidence_id=evidence_id, detected_at=day, confirmed_at=day))
            evidence.append(AnnotationEvidence(id=evidence_id, title=label, summary=f"标准市场事件: {label}", reason_codes=[reason], metadata={"event_date": day}))
        return ChartAnnotationLayer(id=self.layer_id, category="event", title="市场事件", status="available", price_basis=context.price_basis, algorithm_version="market-events-v1", input_fingerprint=context.input_fingerprint, markers=markers, evidence=evidence)


class StrategySignalLayerProvider:
    layer_id = "strategy.signals"
    category = "strategy"

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        if context.data_dir is None:
            return ChartAnnotationLayer(id=self.layer_id, category="strategy", title="策略信号", status="unavailable", price_basis=context.price_basis, input_fingerprint=context.input_fingerprint, warnings=["策略事件仓库不可用"])
        events = StrategySignalEventRepository(context.data_dir).query(
            symbol=context.symbol,
            strategy_ids=context.strategy_ids,
            start_date=date.fromisoformat(context.visible_start[:10]),
            end_date=date.fromisoformat(context.visible_end[:10]),
            source_run_id=context.source_run_id,
            params_fingerprint=context.params_fingerprint,
        )
        markers: list[AnnotationMarker] = []
        evidence: list[AnnotationEvidence] = []
        date_strategies: dict[str, set[str]] = {}
        for event in events:
            day = event["event_date"]
            date_strategies.setdefault(day, set()).add(str(event["strategy_id"]))
        role_map = {
            "candidate": "candidate", "entry": "strategy_entry", "exit": "strategy_exit",
            "failure": "failure", "support": "support", "retrigger": "retrigger",
        }
        for event in events:
            day = event["event_date"]
            event_type = event["event_type"]
            evidence_id = f"strategy:{event['strategy_id']}:{event_type}:{day}:{event['source_run_id']}"
            levels = event.get("levels") or []
            price = next((float(item["value"]) for item in levels if item.get("value") is not None), None)
            signal_kind = event.get("signal_kind") or "strategy_signal"
            role = role_map.get(event_type, "candidate")
            if signal_kind == "backtest_fill":
                role = "backtest_entry" if event_type == "entry" else "backtest_exit"
            elif signal_kind == "realtime_trigger":
                role = "realtime_trigger"
            kind_label = {
                "strategy_signal": "策略信号",
                "backtest_fill": "回测成交",
                "realtime_trigger": "实时触发",
            }.get(signal_kind, signal_kind)
            markers.append(AnnotationMarker(id=evidence_id, layer_id=self.layer_id, date=day, price=price, role=role, label=f"{kind_label} · {event_type}", evidence_id=evidence_id, detected_at=day, confirmed_at=day))
            metadata = {
                key: event.get(key)
                for key in (
                    "strategy_id", "strategy_version", "params_fingerprint",
                    "source_run_id", "provenance", "input_fingerprint", "pattern_refs",
                )
            }
            metadata["event_date"] = day
            metadata["event_type"] = event_type
            metadata["signal_kind"] = signal_kind
            metadata["anchors"] = event.get("anchors") or []
            metadata["levels"] = event.get("levels") or []
            summary = {
                "strategy_signal": "策略条件成立记录, 不代表真实账户成交",
                "backtest_fill": "回测撮合器产生的模拟成交, 不代表真实账户成交",
                "realtime_trigger": "盘中监控规则即时触发, 不代表真实账户成交",
            }.get(signal_kind, "派生策略事件")
            evidence.append(AnnotationEvidence(id=evidence_id, title=f"{event['strategy_id']} · {kind_label}", summary=summary, metrics=event.get("metrics") or [], reason_codes=event.get("reason_codes") or [], metadata=metadata))
        for day, strategies in sorted(date_strategies.items()):
            if len(strategies) < 2:
                continue
            evidence_id = f"strategy:confluence:{day}"
            related = [item for item in events if item["event_date"] == day]
            price = next((float(level["value"]) for item in related for level in (item.get("levels") or []) if level.get("value") is not None), None)
            markers.append(AnnotationMarker(
                id=evidence_id,
                layer_id=self.layer_id,
                date=day,
                price=price,
                role="confluence",
                label=f"{len(strategies)} 策略共振",
                evidence_id=evidence_id,
                detected_at=day,
                confirmed_at=day,
                count=len(strategies),
            ))
            evidence.append(AnnotationEvidence(
                id=evidence_id,
                title=f"{len(strategies)} 策略同日共振",
                summary="同一股票在同一交易日被多个独立策略记录, 这不是成交确认。",
                reason_codes=["multi_strategy_confluence"],
                metadata={
                    "event_date": day,
                    "event_type": "confluence",
                    "strategy_ids": sorted(strategies),
                    "signal_kind": "strategy_signal",
                },
            ))
        return ChartAnnotationLayer(id=self.layer_id, category="strategy", title="策略信号", status="available", price_basis=context.price_basis, algorithm_version="strategy-events-v1", input_fingerprint=context.input_fingerprint, markers=markers, evidence=evidence)


class StrategyPlanLayerProvider:
    layer_id = "plan.strategy"
    category = "plan"

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        if context.data_dir is None:
            return ChartAnnotationLayer(id=self.layer_id, category="plan", title="策略计划价位", status="unavailable", price_basis=context.price_basis, input_fingerprint=context.input_fingerprint)
        events = StrategySignalEventRepository(context.data_dir).query(
            symbol=context.symbol,
            strategy_ids=context.strategy_ids,
            start_date=date.fromisoformat(context.visible_start[:10]),
            end_date=date.fromisoformat(context.visible_end[:10]),
            source_run_id=context.source_run_id,
            params_fingerprint=context.params_fingerprint,
        )
        lines: list[AnnotationLine] = []
        zones: list[AnnotationZone] = []
        for event in events:
            evidence_id = f"strategy:{event['strategy_id']}:{event['event_type']}:{event['event_date']}:{event['source_run_id']}"
            for index, level in enumerate(event.get("levels") or []):
                value = level.get("value")
                if value is None:
                    continue
                lines.append(AnnotationLine(id=f"{evidence_id}:level:{index}", layer_id=self.layer_id, role=str(level.get("role") or "candidate_trigger"), value=float(value), start_date=event["event_date"], end_date=context.visible_end, label=str(level.get("label") or level.get("role") or "策略价位"), evidence_id=evidence_id))
            zone = next((metric for metric in event.get("metrics") or [] if metric.get("name") == "zone" and isinstance(metric.get("value"), dict)), None)
            if zone:
                value = zone["value"]
                zones.append(AnnotationZone(id=f"{evidence_id}:zone", layer_id=self.layer_id, role="plan", start_date=event["event_date"], end_date=context.visible_end, low=value.get("low"), high=value.get("high"), label="策略观察区", evidence_id=evidence_id, confirmed_at=event["event_date"]))
        return ChartAnnotationLayer(id=self.layer_id, category="plan", title="策略计划价位", status="available", price_basis=context.price_basis, algorithm_version="strategy-plan-v1", input_fingerprint=context.input_fingerprint, lines=lines, zones=zones)


class KeyLevelLayerProvider:
    layer_id = "plan.key_levels"
    category = "plan"

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        lines = [
            AnnotationLine(
                id=f"{self.layer_id}:{level_type}:{index}",
                layer_id=self.layer_id,
                role=f"key_level_{level_type}",
                value=float(level["value"]),
                start_date=context.visible_start,
                end_date=context.visible_end,
                label=str(level.get("label") or level_type),
            )
            for level_type, values in sorted(context.key_levels.items())
            for index, level in enumerate(values)
            if level.get("value") is not None
        ]
        return ChartAnnotationLayer(
            id=self.layer_id,
            category="plan",
            title="关键价位",
            status="available",
            price_basis=context.price_basis,
            algorithm_version="tickflow-key-levels-v1",
            input_fingerprint=context.input_fingerprint,
            lines=lines,
        )


def default_chart_layer_registry() -> ChartLayerRegistry:
    return ChartLayerRegistry([
        MarketEventLayerProvider(),
        *pattern_providers(),
        KeyLevelLayerProvider(),
        StrategySignalLayerProvider(),
        StrategyPlanLayerProvider(),
    ])
