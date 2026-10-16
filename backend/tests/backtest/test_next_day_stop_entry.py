import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_next_day_stop_entry import next_day_stop_entry

from app.backtest.engine import BacktestEngine, MatcherConfig
from app.backtest.matrix import build_market_matrix


def matrix(opening=9., high=11., missing=False, locked=False):
    panel = pl.DataFrame([
        {"symbol": "A", "date": date(2020, 1, 6) + timedelta(days=i),
         "open": opening if i == 1 else 10., "high": high if i == 1 else 12. if i == 2 else 10.,
         "low": 5. if i == 1 else 9., "close": 9. if i == 1 else 10.,
         "volume": 0 if missing and i == 1 else 100000,
         "signal_limit_up": locked and i == 1, "entry": i == 0, "exit": i == 1}
        for i in range(4)
    ])
    return build_market_matrix(panel, panel["entry"], panel["exit"],
                               entry_delay_bars=1, exit_delay_bars=1)


@pytest.mark.parametrize("opening,high,expected", [(9., 11., 10.), (11., 12., 11.), (9., 10., None)])
def test_stop_price_and_expiry(opening, high, expected):
    original = matrix(opening, high)
    changed, stats = next_day_stop_entry(original)
    result = BacktestEngine(repo=None).simulate_independent_market_matrix(
        changed, 1, MatcherConfig(matching="open_t+1", fees_pct=0, slippage_bps=0, stop_loss_pct=-.07))
    assert original.entry[1, 0] == 1
    assert stats["orders"] == 1
    if expected is None:
        assert not result.trades  # day 2 exceeds trigger, but day 1 order expired
    else:
        trade = result.trades[0]
        assert trade.entry_price == expected
        assert str(trade.entry_signal_date) == "2020-01-06"
        assert str(trade.entry_date) == "2020-01-07"
        assert str(trade.exit_date) == "2020-01-08"  # deep entry-day low cannot sell


@pytest.mark.parametrize("missing,locked", [(True, False), (False, True)])
def test_stop_entry_preserves_nontradable_constraints(missing, locked):
    original = matrix(opening=11., high=11.) if locked else matrix()
    tradable, flags = original.tradable.copy(), original.limit_up_locked.copy()
    low, close = original.low.copy(), original.close.copy()
    tradable[1, 0] = not missing
    flags[1, 0] = locked
    if locked:
        low[1, 0] = close[1, 0] = 11.
    original = replace(original, tradable=tradable, limit_up_locked=flags, low=low, close=close)
    changed, _ = next_day_stop_entry(original)
    result = BacktestEngine(repo=None).simulate_independent_market_matrix(changed, 1, MatcherConfig())
    assert not result.trades


def test_unshifted_order_rejected():
    original = matrix()
    original.entry_signal_time.flags.writeable = True
    original.entry_signal_time[1, 0] = 1
    with pytest.raises(ValueError, match="next-market-session"):
        next_day_stop_entry(original)
