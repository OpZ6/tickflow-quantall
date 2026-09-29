from __future__ import annotations

import pandas as pd
import pytest

from research_dividend_etf_backtest import load_etf_pair, metrics, simulate


def test_close_signal_trades_next_open_and_marks_daily_close() -> None:
    bars = pd.DataFrame({
        "date": pd.date_range("2026-01-05", periods=4, freq="B"),
        "open": [100., 100., 100., 100.],
        "close": [100., 100., 80., 100.],
    })
    target = pd.Series([0., 1., 0., 0.])
    curve, changes, _ = simulate(bars, target, first_index=0, cost=0.)
    assert changes == 2
    assert curve.equity.tolist() == pytest.approx([1., .8, 1.])
    assert metrics(curve)["mdd"] == pytest.approx(-.2)


def test_buy_fee_does_not_borrow_cash() -> None:
    bars = pd.DataFrame({
        "date": pd.date_range("2026-01-05", periods=2, freq="B"),
        "open": [100., 100.],
        "close": [100., 100.],
    })
    curve, _, _ = simulate(bars, pd.Series([1., 1.]), first_index=0, cost=.001)
    assert curve.equity.iloc[0] == pytest.approx(1 / 1.001)
    assert curve.asset_weight.iloc[0] == pytest.approx(1.)


def test_dividend_and_split_preserve_holder_equity() -> None:
    bars = pd.DataFrame({
        "date": pd.date_range("2026-01-05", periods=4, freq="B"),
        "open": [1., 1., .8, .4],
        "close": [1., 1., .8, .4],
    })
    curve, changes, _ = simulate(
        bars,
        pd.Series([1., 1., 1., 1.]),
        first_index=0,
        cost=0.,
        dividends=pd.Series([0., 0., .2, 0.]),
        splits=pd.Series([1., 1., 1., 2.]),
    )
    assert changes == 1
    assert curve.equity.tolist() == pytest.approx([1., 1., 1.])


def test_known_upstream_duplicate_is_removed_only_when_verified(tmp_path) -> None:
    rows = pd.DataFrame({
        "date": ["2008-01-02", "2008-01-03", "2008-12-31"],
        "open": [1., 3., 1.], "high": [1.1, 3.1, 1.1],
        "low": [.9, 2.9, .9], "close": [1., 3., 1.],
        "volume": [100., 300., 100.],
    })
    rows.to_csv(tmp_path / "510880.SH_raw.csv", index=False)
    rows.to_csv(tmp_path / "510880.SH_qfq.csv", index=False)
    raw, adjusted = load_etf_pair(tmp_path, "510880.SH")
    assert len(raw) == len(adjusted) == 2
    rows.loc[0, "volume"] = 101.
    rows.to_csv(tmp_path / "510880.SH_raw.csv", index=False)
    with pytest.raises(ValueError, match="known bad row changed"):
        load_etf_pair(tmp_path, "510880.SH")


def test_unpaid_dividend_is_equity_but_cannot_fund_buy() -> None:
    bars = pd.DataFrame({
        "date": pd.date_range("2026-01-05", periods=5, freq="B"),
        "open": [1., 1., .8, .8, .8],
        "close": [1., 1., .8, .8, .8],
    })
    target = pd.Series([1., 1., 0., 1., 1.])
    dividends = pd.Series([0., 0., .2, 0., 0.])
    immediate, _, _ = simulate(bars, target, 0, 0., dividends=dividends)
    delayed, _, _ = simulate(bars, target, 0, 0., dividends=dividends, dividend_lag_bars=3)
    assert immediate.equity.iloc[-1] == pytest.approx(delayed.equity.iloc[-1])
    assert immediate.asset_weight.iloc[-1] == pytest.approx(1.)
    assert delayed.asset_weight.iloc[-1] == pytest.approx(.8)


def test_published_payment_date_controls_when_dividend_can_be_spent() -> None:
    bars = pd.DataFrame({"date": pd.date_range("2026-01-05", periods=5, freq="B"), "open": [1., 1., .8, .8, .8], "close": [1., 1., .8, .8, .8]})
    target = pd.Series([1., 1., 0., 1., 1.])
    dividends = pd.Series([0., 0., .2, 0., 0.])
    due = pd.Series([0, 0, 4, 0, 0])
    paid, _, _ = simulate(bars, target, 0, 0., dividends=dividends, payment_indices=due)
    due.iloc[2] = 5
    unpaid, _, _ = simulate(bars, target, 0, 0., dividends=dividends, payment_indices=due)
    assert paid.asset_weight.iloc[3] == pytest.approx(1.)
    assert unpaid.asset_weight.iloc[3] == pytest.approx(.8)
