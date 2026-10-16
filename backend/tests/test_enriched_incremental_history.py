from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from app.indicators.pipeline import _restore_raw_daily_history


def test_restore_raw_daily_history_prevents_double_adjustment() -> None:
    stored = pl.DataFrame(
        {
            "symbol": ["002084.SZ"],
            "date": [date(2026, 8, 31)],
            "open": [1.80],
            "high": [1.95],
            "low": [1.75],
            "close": [1.90],
            "raw_close": [6.38],
            "raw_high": [6.55],
            "raw_low": [5.88],
        }
    )

    restored = _restore_raw_daily_history(stored).row(0, named=True)

    assert restored["open"] == pytest.approx(1.80 * 6.38 / 1.90)
    assert restored["high"] == 6.55
    assert restored["low"] == 5.88
    assert restored["close"] == 6.38
