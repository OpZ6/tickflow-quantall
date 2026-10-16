import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_vcp_profitable_distribution import distribution_exit


@pytest.mark.parametrize("close,volume,expected", [(10.5, 200, True), (10.5, 100, False), (9.9, 200, False), (10.8, 200, False)])
def test_requires_profit_price_break_and_expanding_volume(close, volume, expected):
    days = [date(2020, 1, 6) + timedelta(days=i) for i in range(4)]
    bars = [dict(date=d, open=11, high=11.2, low=10.8, close=11, volume=100) for d in days]
    bars[1].update(close=close, low=min(close, 10.8), volume=volume)
    trade = dict(entry_date=days[0], exit_date=days[3], entry_price=10, pnl_pct=0.2)
    result = distribution_exit(trade, bars, days)
    assert result["shortened"] is expected
    if expected:
        assert result["signal_date"] == days[1].isoformat()
        assert result["exit_date"] == days[2].isoformat()
        assert 0.09 < result["pnl"] < 0.10
        # The fill day's close must not affect the prior close signal.
        bars[2]["close"] = 9.5
        assert distribution_exit(trade, bars, days)["pnl"] == result["pnl"]
        assert distribution_exit(trade, bars[:2] + bars[3:], days)["reason"] == "blocked_exit"
    else:
        assert result["pnl"] == 0.2
