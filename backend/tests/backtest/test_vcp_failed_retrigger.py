from datetime import date, timedelta

import numpy as np
import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_vcp import (
    build_failed_breakout_retriggers,
)


def _market(closes: list[float], lows: list[float] | None = None):
    count = len(closes)
    return build_market_data_matrix(
        pl.DataFrame(
            {
                "symbol": ["600001.SH"] * count,
                "date": [date(2024, 1, 1) + timedelta(days=i) for i in range(count)],
                "open": closes,
                "high": [value + 0.05 for value in closes],
                "low": lows or [value - 0.05 for value in closes],
                "close": closes,
                "volume": [100.0] * count,
            }
        )
    )


def test_retrigger_requires_failure_then_three_completed_recovery_bars():
    closes = [10.0] * 5 + [10.1, 9.90, 9.90, 9.94, 10.0, 10.0]
    lows = [9.95] * 5 + [10.0, 9.70, 9.85, 9.89, 9.95, 9.95]
    market = _market(closes, lows)
    breakout = np.zeros(market.shape, dtype=np.uint8)
    breakout[5, 0] = 1
    breakout_score = np.zeros(market.shape, dtype=np.float32)
    breakout_score[5, 0] = 77.0
    pivot = np.full(market.shape, np.nan, dtype=np.float32)
    pivot[5, 0] = 10.0

    entry, score = build_failed_breakout_retriggers(
        market, breakout, breakout_score, pivot
    )

    assert np.flatnonzero(entry[:, 0]).tolist() == [9]
    assert score[9, 0] == 77.0


def test_retrigger_does_not_fire_without_a_pivot_failure():
    market = _market([10.0] * 5 + [10.1] + [10.0] * 8)
    breakout = np.zeros(market.shape, dtype=np.uint8)
    breakout[5, 0] = 1
    breakout_score = np.ones(market.shape, dtype=np.float32)
    pivot = np.full(market.shape, np.nan, dtype=np.float32)
    pivot[5, 0] = 10.0

    entry, _ = build_failed_breakout_retriggers(
        market, breakout, breakout_score, pivot
    )

    assert not entry.any()


def test_future_bars_do_not_change_an_existing_retrigger():
    closes = [10.0] * 5 + [10.1, 9.90, 9.90, 9.94, 10.0]
    lows = [9.95] * 5 + [10.0, 9.70, 9.85, 9.89, 9.95]

    def calculate(extra: int):
        market = _market(closes + [20.0] * extra, lows + [5.0] * extra)
        breakout = np.zeros(market.shape, dtype=np.uint8)
        breakout[5, 0] = 1
        breakout_score = np.ones(market.shape, dtype=np.float32)
        pivot = np.full(market.shape, np.nan, dtype=np.float32)
        pivot[5, 0] = 10.0
        return build_failed_breakout_retriggers(
            market, breakout, breakout_score, pivot
        )[0]

    prefix = calculate(0)
    extended = calculate(4)
    np.testing.assert_array_equal(prefix, extended[: len(prefix)])
