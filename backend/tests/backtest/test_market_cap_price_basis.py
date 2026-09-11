from datetime import date

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_basic_filter_mask, build_market_data_matrix
from app.backtest.strategy import _basic_filter_dependencies
from app.strategy.engine import StrategyEngine


def panel(adjusted=5.0, raw=10.0, shares=100.0):
    return pl.DataFrame({
        "symbol": ["600000.SH"], "date": [date(2020, 1, 2)],
        "open": [adjusted], "high": [adjusted], "low": [adjusted],
        "close": [adjusted], "raw_close": [raw], "volume": [1000.0],
        "total_shares": [shares], "float_shares": [shares],
    }, schema_overrides={"raw_close": pl.Float64, "total_shares": pl.Float64, "float_shares": pl.Float64})


def results(frame, config):
    market = build_market_data_matrix(frame, field_columns={"raw_close", "total_shares", "float_shares"})
    matrix = bool(build_basic_filter_mask(market, config)[0, 0])
    polars = StrategyEngine._apply_basic_filter(frame, config).height == 1
    return matrix, polars


@pytest.mark.parametrize("prefix", ["market_cap", "float_cap"])
def test_adjustment_scaling_does_not_change_cap_filter(prefix):
    config = {f"{prefix}_min": 900.0, f"{prefix}_max": 1100.0}
    assert results(panel(adjusted=5.0), config) == (True, True)
    assert results(panel(adjusted=2.0), config) == (True, True)
    assert "raw_close" in _basic_filter_dependencies(config)


@pytest.mark.parametrize("raw,shares", [(None, 100.0), (10.0, None), (np.nan, 100.0), (10.0, 0.0)])
def test_unknown_or_invalid_market_cap_does_not_pass(raw, shares):
    assert results(panel(raw=raw, shares=shares), {"market_cap_min": 1.0}) == (False, False)


def test_no_cap_filter_does_not_require_cap_fields():
    assert results(panel(raw=None, shares=None), {"price_min": 1.0}) == (True, True)


def test_raw_only_live_panel_preserves_unadjusted_close_contract():
    frame = panel(adjusted=10.0).drop("raw_close")
    assert results(frame, {"market_cap_min": 900.0}) == (True, True)


def test_absent_share_column_does_not_silently_disable_cap_filter():
    frame = panel().drop("total_shares")
    assert results(frame, {"market_cap_min": 1.0}) == (False, False)
