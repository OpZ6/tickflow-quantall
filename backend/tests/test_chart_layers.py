from __future__ import annotations

from datetime import date, timedelta

from app.chart_layers.models import ChartAnnotationLayer, ChartLayerContext
from app.chart_layers.patterns import (
    detect_classic,
    detect_cup_handle,
    detect_high_tight_flag,
    detect_pullback_absorb,
    detect_vcp,
)
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
    for detector in (detect_classic, detect_cup_handle, detect_high_tight_flag, detect_pullback_absorb, detect_vcp):
        layer = detector(context)
        assert layer.schema_version == 1
        assert layer.status == "insufficient_data"
        assert layer.input_fingerprint == "fixture"


def test_vcp_layer_contains_confirmation_evidence_and_convergence_geometry():
    closes = [20.0] * 50
    closes += [30, 27, 24, 27, 29, 27, 25, 27, 28.5, 27.3, 26.0, 27.2, 28.2, 27.4, 26.8, 27.5, 28.3]
    layer = detect_vcp(_context(_rows(closes, [120.0] * 55 + [80.0] * (len(closes) - 55))))
    assert layer.status == "available"
    assert layer.algorithm_version == "tickflow-vcp-v1"
    assert layer.evidence
    assert any(marker.label.startswith("C") for marker in layer.markers)
    assert {segment.role for segment in layer.segments} == {"convergence_upper", "convergence_lower"}
    base_confirmation = layer.evidence[0].metadata["confirmed_at"]
    assert all(marker.confirmed_at >= base_confirmation for marker in layer.markers)


def test_vcp_lifecycle_markers_use_their_own_confirmation_dates():
    closes = [20.0] * 50
    closes += [30, 27, 24, 27, 29, 27, 25, 27, 28.5, 27.3, 26.0, 27.2, 28.2, 27.4, 26.8, 27.5, 28.3]
    closes += [29.2, 26.5, 29.4]
    layer = detect_vcp(_context(_rows(closes)))
    lifecycle = {marker.role: marker for marker in layer.markers}
    assert lifecycle["breakout"].confirmed_at == lifecycle["breakout"].date
    assert lifecycle["failure"].confirmed_at == lifecycle["failure"].date
    assert lifecycle["failure"].invalidated_at == lifecycle["failure"].date
    assert lifecycle["retrigger"].confirmed_at == lifecycle["retrigger"].date
    assert lifecycle["breakout"].date < lifecycle["failure"].date < lifecycle["retrigger"].date


def test_high_tight_flag_and_pullback_layers_have_structural_evidence():
    pole = [10 + index * 0.65 for index in range(18)]
    flag = [21.2, 20.7, 20.3, 20.8, 20.5, 20.9, 21.0]
    htf = detect_high_tight_flag(_context(_rows([10.0] * 20 + pole + flag, [100] * 20 + [240] * len(pole) + [80] * len(flag))))
    assert htf.evidence
    assert any(segment.role == "impulse" for segment in htf.segments)
    assert any(zone.role == "consolidation" for zone in htf.zones)

    closes = [10.0 + index * 0.02 for index in range(25)]
    volumes = [100.0] * 25
    closes += [11.2, 11.12, 11.14, 11.18]
    volumes += [300.0, 120.0, 100.0, 90.0]
    pullback = detect_pullback_absorb(_context(_rows(closes, volumes)))
    assert pullback.evidence
    assert any(line.role == "support" for line in pullback.lines)


def test_cup_handle_layer_uses_candidate_language_not_strategy_entry():
    left = [20.0 + index * 0.05 for index in range(18)]
    cup_down = [21.0 - index * 0.32 for index in range(18)]
    cup_up = [15.6 + index * 0.29 for index in range(19)]
    handle = [20.8, 20.2, 20.4, 20.1, 20.5, 20.6]
    layer = detect_cup_handle(_context(_rows(left + cup_down + cup_up + handle)))
    assert layer.evidence
    assert any(line.role == "candidate_trigger" for line in layer.lines)
    assert all(marker.role != "strategy_entry" for marker in layer.markers)


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
