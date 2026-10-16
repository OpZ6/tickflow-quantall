from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import ChartAnnotationLayer, ChartLayerContext


class ChartLayerProvider(Protocol):
    layer_id: str
    category: str

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer: ...


class ChartLayerRegistry:
    """Stable provider registry with duplicate rejection and per-layer isolation."""

    def __init__(self, providers: Iterable[ChartLayerProvider] = ()) -> None:
        self._providers: dict[str, ChartLayerProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ChartLayerProvider) -> None:
        if provider.layer_id in self._providers:
            raise ValueError(f"duplicate chart layer provider: {provider.layer_id}")
        self._providers[provider.layer_id] = provider

    def build(self, context: ChartLayerContext, categories: set[str]) -> list[ChartAnnotationLayer]:
        layers: list[ChartAnnotationLayer] = []
        for provider_id in sorted(self._providers):
            provider = self._providers[provider_id]
            if provider.category not in categories:
                continue
            try:
                layer = provider.build(context)
                if layer.schema_version != 1:
                    raise ValueError(f"unsupported chart layer schema: {layer.schema_version}")
            except Exception as exc:  # the layer must not break candles
                layer = ChartAnnotationLayer(
                    id=provider.layer_id,
                    category=provider.category,  # type: ignore[arg-type]
                    title=provider.layer_id,
                    status="error",
                    price_basis=context.price_basis,
                    input_fingerprint=context.input_fingerprint,
                    warnings=[f"图层计算失败: {type(exc).__name__}: {exc}"],
                )
            layers.append(layer)
        return layers
