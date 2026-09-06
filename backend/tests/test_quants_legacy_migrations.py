from pathlib import Path

import numpy as np

from app.strategy.builtin._quants_legacy_patterns import cup_detect, pullback_detect
from app.strategy.engine import StrategyEngine

BUILTIN = Path(__file__).resolve().parents[1] / "app/strategy/builtin"


def test_legacy_ids_load_independently():
    engine = StrategyEngine([BUILTIN])
    ids = {row["id"] for row in engine.list_strategies(include_research=True)}
    assert {
        "quants_growth_trend_legacy_v1",
        "quants_cup_handle_legacy_v1",
        "quants_pullback_low_absorb_legacy_v1",
    } <= ids
    assert not engine.load_errors()


def test_cup_detector_preserves_depth_and_breakout_semantics():
    close = np.array([100, 102, 104, 106, 108, 95, 90, 92, 96, 100, 105, 108, 110.0])
    high = close + 1
    low = close - 1
    volume = np.ones(close.size) * 100
    volume[-1] = 220
    result = cup_detect(
        high,
        low,
        close,
        volume,
        {
            "min_bars": 12,
            "cup_min_depth_pct": 0.12,
            "cup_max_depth_pct": 0.45,
            "breakout_volume_ratio_min": 1.4,
        },
    )
    assert result["valid"]
    assert result["cup_depth"] >= 0.12


def test_pullback_requires_positive_money_flow_and_dry_volume():
    close = np.array([100, 108] + [108.2] * 9 + [108.1], dtype=float)
    open_ = close.copy()
    high = close + 1
    low = close - 1
    volume = np.array([100, 300] + [40] * 10, dtype=float)
    result = pullback_detect(open_, high, low, close, volume, {})
    assert not result["valid"]
    assert result["reason"] == "money_flow_missing"
