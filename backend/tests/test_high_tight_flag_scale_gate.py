"""The scale experiment filters primaries without promoting alternate flags."""

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin import _quants_high_tight_flag as flag


@pytest.mark.parametrize("scale", ["short", "medium", "long"])
def test_scale_gate_matches_screen_and_preserves_exits(monkeypatch, scale):
    market = build_market_data_matrix(pl.DataFrame({
        "symbol": ["600000.SH"] * 25,
        "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(25)],
        **{name: np.linspace(20, 10, 25) for name in ("open", "high", "low", "close")},
        "volume": [1000.0] * 25,
    }))
    monkeypatch.setattr(flag, "detect", lambda *args: {
        "valid": True, "status": "executable", "scale": scale,
        "alternates": [{"valid": True, "status": "executable", "scale": "long"}],
    })
    strategy = flag.QuantsHighTightFlagStrategy()
    baseline = strategy.compute_signals(market, {})
    restricted = strategy.compute_signals(market, {"exclude_short_scale": True})
    snapshot, _ = strategy.screen_snapshot(market, {"exclude_short_scale": True}, 24)
    assert baseline.entry.all()
    assert restricted.entry.all() == (scale != "short")
    assert bool(snapshot.entry[24, 0]) == (scale != "short")
    np.testing.assert_array_equal(baseline.exit, restricted.exit)
    assert baseline.exit.any()
