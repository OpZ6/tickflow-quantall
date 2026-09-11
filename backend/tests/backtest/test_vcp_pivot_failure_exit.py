from datetime import date, timedelta

import numpy as np
import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_vcp import build_pivot_failure_exits


def _market(closes: list[float]):
    return build_market_data_matrix(
        pl.DataFrame(
            {
                "symbol": ["600001.SH"] * len(closes),
                "date": [date(2024, 1, 1) + timedelta(days=i) for i in range(len(closes))],
                "open": closes,
                "high": [value + 0.1 for value in closes],
                "low": [value - 0.1 for value in closes],
                "close": closes,
                "volume": [100.0] * len(closes),
            }
        )
    )


def test_pivot_loss_exit_uses_first_completed_bar_after_breakout():
    market = _market([9.8, 10.1, 9.95, 10.2])
    breakout = np.zeros(market.shape, dtype=np.uint8)
    breakout[1, 0] = 1
    pivots = np.full(market.shape, np.nan, dtype=np.float32)
    pivots[1, 0] = 10.0
    base_exit = np.zeros(market.shape, dtype=np.uint8)

    result = build_pivot_failure_exits(market, breakout, pivots, base_exit)

    assert np.flatnonzero(result[:, 0]).tolist() == [2]


def test_pivot_exit_does_not_use_intraday_low_or_future_close():
    prefix = _market([9.8, 10.1, 10.01])
    extended = _market([9.8, 10.1, 10.01, 8.0])

    def calculate(market):
        breakout = np.zeros(market.shape, dtype=np.uint8)
        breakout[1, 0] = 1
        pivots = np.full(market.shape, np.nan, dtype=np.float32)
        pivots[1, 0] = 10.0
        base_exit = np.zeros(market.shape, dtype=np.uint8)
        return build_pivot_failure_exits(market, breakout, pivots, base_exit)

    assert not calculate(prefix).any()
    np.testing.assert_array_equal(calculate(prefix), calculate(extended)[:3])
