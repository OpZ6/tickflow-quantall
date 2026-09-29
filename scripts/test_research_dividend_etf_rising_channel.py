from __future__ import annotations

import pandas as pd
import pytest

from research_dividend_etf_rising_channel import rising_channel


def test_rising_channel_uses_only_past_bars_for_fit() -> None:
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    base = pd.DataFrame({"date": dates, "close": [1 + i * .005 + (i % 4) * .001 for i in range(30)]})
    target, position = rising_channel(base, 20, 2., True)
    changed = base.copy()
    changed.loc[25:, "close"] *= 4
    new_target, new_position = rising_channel(changed, 20, 2., True)
    assert target.iloc[:25].tolist() == pytest.approx(new_target.iloc[:25].tolist(), nan_ok=True)
    assert position.iloc[:25].tolist() == pytest.approx(new_position.iloc[:25].tolist(), nan_ok=True)
