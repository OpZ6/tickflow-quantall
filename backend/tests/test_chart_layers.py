from __future__ import annotations

from datetime import date, timedelta

from app.chart_layers.models import ChartAnnotationLayer, ChartLayerContext
from app.chart_layers.patterns import detect_classic
from app.chart_layers.providers import StrategySignalLayerProvider
from app.chart_layers.registry import ChartLayerRegistry
from app.services.strategy_signal_events import StrategySignalEventRepository


def _context(rows: list[dict], *, fingerprint: str = "fixture") -> ChartLayerContext:
    return ChartLayerContext(
        symbol="600000.SH",
        asset_type="stock",
        interval="1d",
        price_basis="qfq",
        rows=rows,
        visible_start=rows[0]["date"],
        visible_end=rows[-1]["date"],
        input_fingerprint=fingerprint,
    )


def _rows(closes: list[float], volumes: list[float] | None = None) -> list[dict]:
    start = date(2025, 1, 2)
    volumes = volumes or [100.0] * len(closes)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "open": close * 0.995,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": volumes[index],
        }
        for index, close in enumerate(closes)
    ]


def test_registry_rejects_duplicates_and_isolates_failure():
    class Good:
        layer_id = "event.good"
        category = "event"

        def build(self, context):
            return ChartAnnotationLayer(id=self.layer_id, category="event", title="good", status="available", price_basis=context.price_basis)

    class Bad:
        layer_id = "event.bad"
        category = "event"

        def build(self, _context):
            raise RuntimeError("broken fixture")

    registry = ChartLayerRegistry([Good(), Bad()])
    layers = registry.build(_context(_rows([10.0] * 20)), {"event"})
    assert [layer.id for layer in layers] == ["event.bad", "event.good"]
    assert layers[0].status == "error"
    assert "broken fixture" in layers[0].warnings[0]
    assert layers[1].status == "available"

    try:
        registry.register(Good())
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate provider must be rejected")


def test_pattern_layers_report_insufficient_data_without_throwing():
    context = _context(_rows([10.0] * 10))
    layer = detect_classic(context)
    assert layer.schema_version == 1
    assert layer.status == "insufficient_data"
    assert layer.input_fingerprint == "fixture"


def test_strategy_confluence_requires_distinct_strategies(tmp_path):
    base = {
        "strategy_version": "1", "params_fingerprint": "p", "symbol": "600000.SH",
        "asset_type": "stock", "event_date": "2025-01-21", "event_type": "entry",
        "signal_kind": "strategy_signal", "source_run_id": "run", "levels": [{"value": 10.0}],
    }
    StrategySignalEventRepository(tmp_path).upsert([
        {**base, "strategy_id": "s1", "event_type": "candidate"},
        {**base, "strategy_id": "s1", "event_type": "entry"},
    ])
    context = _context(_rows([10.0] * 25))
    context = ChartLayerContext(**{**context.__dict__, "data_dir": tmp_path})
    one = StrategySignalLayerProvider().build(context)
    assert not any(marker.role == "confluence" for marker in one.markers)

    StrategySignalEventRepository(tmp_path).upsert([{**base, "strategy_id": "s2"}])
    two = StrategySignalLayerProvider().build(context)
    confluence = [marker for marker in two.markers if marker.role == "confluence"]
    assert len(confluence) == 1
    assert confluence[0].count == 2


def test_strategy_provider_renders_the_full_signal_lifecycle(tmp_path):
    base = {
        "strategy_id": "lifecycle", "strategy_version": "1", "params_fingerprint": "p",
        "symbol": "600000.SH", "asset_type": "stock", "signal_kind": "strategy_signal",
        "source_run_id": "run", "levels": [{"value": 10.0}],
    }
    event_types = ("entry", "exit", "failure", "support", "retrigger")
    StrategySignalEventRepository(tmp_path).upsert([
        {**base, "event_date": f"2025-01-{20 + index:02d}", "event_type": event_type}
        for index, event_type in enumerate(event_types)
    ])
    context = _context(_rows([10.0] * 30))
    context = ChartLayerContext(**{**context.__dict__, "data_dir": tmp_path})
    layer = StrategySignalLayerProvider().build(context)
    assert {marker.role for marker in layer.markers} >= {
        "strategy_entry", "strategy_exit", "failure", "support", "retrigger",
    }


def test_classic_layer_keeps_all_five_legacy_pattern_names():
    top = [10] * 5 + [12, 11, 10, 11, 15, 11, 10, 11, 12, 11, 10] + [10] * 5
    bottom = [10] * 5 + [8, 9, 10, 9, 5, 9, 10, 9, 8, 9, 10] + [10] * 5
    titles = {
        evidence.title
        for closes in (top, bottom)
        for evidence in detect_classic(_context(_rows(closes))).evidence
    }
    assert titles == {"头肩顶", "头肩底", "双顶", "双底", "三角形"}
