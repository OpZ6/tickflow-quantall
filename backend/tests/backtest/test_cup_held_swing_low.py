import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_cup_held_swing_low import (
    COST_CONFIG,
    apply_swing_exit,
    net_round_trip,
    paired_diagnostics,
)


def bars():
    # Middle low=10 confirmed on day 2; closes below it on day 3; fills day 4.
    prices = [(11, 12, 10.5, 11), (11, 12, 10, 11),
              (11, 12, 10.5, 11), (10.5, 11, 9.5, 9.8),
              (9.7, 10, 9.4, 9.6), (12, 13, 11, 12)]
    return [dict(date=date(2020, 1, 6) + timedelta(days=i if i < 5 else i + 2),
                 open=o, high=h, low=low, close=c, volume=1e6)
            for i, (o, h, low, c) in enumerate(prices)]


def run(rows, calendar=None, exit_day=None):
    return apply_swing_exit(
        entry_date=rows[0]["date"], exit_date=exit_day or date(2020, 1, 13),
        entry_price=11, baseline_pnl=0.08, sessions=rows,
        market_calendar=calendar or [r["date"] for r in rows])


def test_confirmed_support_break_exits_next_open_with_costs():
    rows = bars()
    result = run(rows)
    assert result["shortened"]
    assert result["support"] == 10
    assert result["confirmed_date"] == rows[2]["date"].isoformat()
    assert result["signal_date"] == rows[3]["date"].isoformat()
    assert result["early_exit_date"] == rows[4]["date"].isoformat()
    assert result["pnl"] < 9.7 / 11 - 1
    assert result["pnl"] == pytest.approx(net_round_trip(
        9.7 / 11 - 1, COST_CONFIG.buy_cost_pct(), COST_CONFIG.sell_cost_pct(rows[4]["date"])))


def test_prefix_invariance_ignores_bars_after_fill():
    rows = bars()
    original = run(rows)
    rows[-1].update(low=0.5, high=100, close=100)
    assert run(rows) == original


def test_unconfirmed_low_cannot_trigger_or_use_preentry_bars():
    rows = bars()
    # Day 2 undercuts the supposed swing. Neither candidate is yet confirmed.
    rows[2].update(low=9, close=9.5)
    assert not run(rows)["shortened"]


def test_equal_support_close_does_not_trigger():
    rows = bars()
    rows[3]["close"] = 10
    assert not run(rows)["shortened"]


@pytest.mark.parametrize("missing_index", [2, 4])
def test_market_hole_cannot_roll(missing_index):
    rows = bars()
    calendar = [r["date"] for r in rows]
    del rows[missing_index]
    result = run(rows, calendar)
    assert not result["shortened"]
    assert result["reason"].startswith("missing")
    assert result["pnl"] == 0.08


def test_original_exit_has_precedence():
    rows = bars()
    assert not run(rows, exit_day=rows[4]["date"])["shortened"]


def test_blocked_fill_does_not_roll_to_later_price():
    rows = bars()
    rows[4].update(open=9, high=9, low=9, close=9)
    result = run(rows)
    assert not result["shortened"]
    assert result["reason"] == "early_exit_blocked"
    assert result["pnl"] == 0.08


def test_lower_later_pivot_cannot_loosen_confirmed_support():
    rows = bars()
    # Intraday undercut does not break support on a close; it later confirms
    # a lower swing. The existing support must remain 10.
    rows[3].update(low=9, close=10.5)
    rows[4].update(open=10.5, high=11, low=9.5, close=10.5)
    rows[5].update(open=10.5, high=11, low=9.2, close=9.8)
    rows.extend([
        dict(date=date(2020, 1, 14), open=9.7, high=10, low=9.5, close=9.8, volume=1e6),
        dict(date=date(2020, 1, 15), open=12, high=13, low=11, close=12, volume=1e6),
    ])
    result = run(rows, exit_day=rows[-1]["date"])
    assert result["shortened"]
    assert result["support"] == 10
    assert result["signal_date"] == rows[5]["date"].isoformat()


def rally_bars():
    # H1 on 1; L on 3; H2 on 5. H2 is only confirmed on 6.
    highs = [12, 14, 13, 12, 12.5, 13, 12, 10, 12]
    lows = [10.5, 11, 10.5, 10, 10.5, 11, 9.5, 9.4, 10]
    days = [date(2020, 1, 6) + timedelta(days=i + 2 * (i // 5)) for i in range(9)]
    rows = [dict(date=d, open=(h + low) / 2, high=h, low=low,
                 close=(h + low) / 2, volume=1e6)
            for d, h, low in zip(days, highs, lows, strict=True)]
    rows[6]["close"] = 9.8
    rows[7]["open"] = 9.7
    return rows


def rally_run(rows):
    return apply_swing_exit(
        entry_date=rows[0]["date"], exit_date=rows[-1]["date"], entry_price=11,
        baseline_pnl=0.08, sessions=rows, market_calendar=[r["date"] for r in rows],
        failed_rally=True)


def test_lower_high_confirmation_can_signal_same_close_but_fills_next_open():
    rows = rally_bars()
    result = rally_run(rows)
    assert result["shortened"]
    assert result["support"] == 10
    assert result["confirmed_date"] == result["signal_date"] == rows[6]["date"].isoformat()
    assert result["early_exit_date"] == rows[7]["date"].isoformat()


@pytest.mark.parametrize("second_high", [14, 15])
def test_equal_or_higher_high_does_not_form_failed_rally(second_high):
    rows = rally_bars()
    rows[5]["high"] = second_high
    assert not rally_run(rows)["shortened"]


def test_new_high_invalidates_armed_reversal_even_if_close_breaks_support():
    rows = rally_bars()
    rows[6].update(low=10.2, close=10.5)
    rows[7].update(high=13.5, close=9.8)
    assert not rally_run(rows)["shortened"]


def test_unconfirmed_second_high_is_not_retroactive():
    rows = rally_bars()
    # Break occurs on the putative H2 bar itself. Without its right bar it
    # cannot be confirmed, and the low on H2 also cannot count as intervening L.
    rows[5].update(low=9, close=9.5)
    assert not rally_run(rows)["shortened"]


def test_paired_diagnostics_resamples_whole_dates_and_keeps_constant_delta():
    calendar = [date(2020, 1, 6) + timedelta(days=i) for i in range(60)]
    ledger = [dict(entry_signal_date=d.isoformat(), pnl_pct=-0.01,
                   overlay={"pnl": 0.0, "shortened": True})
              for d in calendar for _ in range(2)]
    result = paired_diagnostics(ledger, calendar)
    assert result["changed_signal_days"] == 60
    assert result["event_mean"]["ci95"] == pytest.approx([0.01, 0.01])
    assert result["signal_day_mean"]["ci95"] == pytest.approx([0.01, 0.01])
