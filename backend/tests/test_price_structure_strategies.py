from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.chart_layers.models import ChartLayerContext
from app.chart_layers.patterns import pattern_providers
from app.chart_layers.providers import StrategySignalLayerProvider
from app.services.strategy_evidence import enrich_and_persist_strategy_result
from app.strategy.engine import StrategyDataContext, StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _history(
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pl.DataFrame:
    start = date(2025, 1, 2)
    volumes = volumes or [1_000.0] * len(closes)
    highs = highs or [close * 1.005 for close in closes]
    lows = lows or [close * 0.995 for close in closes]
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(closes),
            "date": [start + timedelta(days=index) for index in range(len(closes))],
            "open": [close * 0.998 for close in closes],
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _market(
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
):
    return build_market_data_matrix(
        _history(
            closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
        )
    )


@pytest.mark.parametrize(
    ("strategy_id", "strategy_file", "entry_signal", "market"),
    [
        (
            "vcp_breakout",
            "vcp_breakout.py",
            "signal_vcp_breakout",
            _market(
                [10.0 + index * 0.12 for index in range(35)]
                + [14.35, 14.55, 14.42, 14.62, 14.48, 14.66, 14.54, 14.70, 14.61, 14.72]
                + [15.05],
                volumes=[1_000.0] * 35 + [520.0] * 10 + [1_300.0],
            ),
        ),
        (
            "cup_handle_breakout",
            "cup_handle_breakout.py",
            "signal_cup_handle_breakout",
            _market(
                [
                    18.0,
                    18.8,
                    19.5,
                    20.0,
                    *np.linspace(19.5, 14.0, 18),
                    *np.linspace(14.3, 19.7, 22),
                    19.45,
                    19.30,
                    19.55,
                    19.42,
                    19.60,
                    20.35,
                ],
                volumes=[1_100.0] * 44 + [600.0] * 5 + [1_500.0],
            ),
        ),
        (
            "high_tight_flag_breakout",
            "high_tight_flag_breakout.py",
            "signal_high_tight_flag_breakout",
            _market(
                [
                    *np.linspace(10.0, 19.0, 25),
                    18.7,
                    18.5,
                    18.8,
                    18.6,
                    18.9,
                    18.75,
                    19.35,
                ],
                volumes=[1_200.0] * 25 + [650.0] * 6 + [1_600.0],
            ),
        ),
        (
            "launch_pullback_support",
            "launch_pullback_support.py",
            "signal_launch_pullback_support",
            _market(
                [10.0] * 25 + [11.0, 11.20, 11.10, 11.05, 10.98],
                volumes=[1_000.0] * 25 + [3_000.0, 1_000.0, 850.0, 700.0, 500.0],
            ),
        ),
    ],
)
def test_registered_price_structure_strategy_emits_real_entry_signal(
    strategy_id: str,
    strategy_file: str,
    entry_signal: str,
    market,
):
    strategy = StrategyEngine._load_file(BUILTIN_DIR / strategy_file)
    assert strategy.meta["id"] == strategy_id
    assert strategy.source == "builtin"
    assert strategy.entry_signals == [entry_signal]
    assert strategy.exit_signals
    assert strategy.execution_backend == "matrix_native"

    signals = strategy.matrix_strategy.compute_signals(
        market,
        {item["id"]: item["default"] for item in strategy.meta["params"]},
    )
    assert bool(signals.entry[-1, 0]), strategy_id


def test_price_structure_strategies_are_not_registered_as_pattern_layers():
    ids = {provider.layer_id for provider in pattern_providers()}
    assert ids == {"pattern.classic"}


def test_kline_signal_is_created_only_after_registered_strategy_run(tmp_path):
    closes = (
        [10.0 + index * 0.12 for index in range(35)]
        + [14.35, 14.55, 14.42, 14.62, 14.48, 14.66, 14.54, 14.70, 14.61, 14.72]
        + [15.05]
    )
    volumes = [1_000.0] * 35 + [520.0] * 10 + [1_300.0]
    history = _history(closes, volumes=volumes)
    market = build_market_data_matrix(history)
    as_of = history["date"][-1]
    layer_context = ChartLayerContext(
        symbol="600000.SH",
        asset_type="stock",
        interval="1d",
        price_basis="qfq",
        rows=history.to_dicts(),
        visible_start=str(history["date"][0]),
        visible_end=str(as_of),
        input_fingerprint="fixture",
        data_dir=tmp_path,
    )
    provider = StrategySignalLayerProvider()
    assert provider.build(layer_context).markers == []

    engine = StrategyEngine([BUILTIN_DIR])
    expected_ids = {
        "vcp_breakout",
        "cup_handle_breakout",
        "high_tight_flag_breakout",
        "launch_pullback_support",
    }
    assert expected_ids <= {item["id"] for item in engine.list_strategies(include_research=True)}
    assert engine.load_errors() == []

    context = StrategyDataContext(
        asset_type="stock",
        timeframe="1d",
        as_of=as_of,
        current=history.filter(pl.col("date") == as_of),
        history=history,
        market=market,
    )
    result = engine.run(
        "vcp_breakout",
        context,
        overrides={"basic_filter": {"enabled": False}},
    )
    assert result.total == 1
    assert result.entry_signal_hits == [{"symbol": "600000.SH", "signals": ["signal_vcp_breakout"]}]
    strategy = engine.get("vcp_breakout")
    params = engine.resolve_params(strategy, None, {})
    enrich_and_persist_strategy_result(
        data_dir=tmp_path,
        result=result,
        strategy=strategy,
        params=params,
        context=context,
    )

    layer = provider.build(layer_context)
    assert any(marker.role == "strategy_entry" for marker in layer.markers)
    assert all(marker.layer_id == "strategy.signals" for marker in layer.markers)
