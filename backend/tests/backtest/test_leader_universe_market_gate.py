import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.engine import MatcherConfig
from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_vcp import (
    market_breadth_allowed,
    market_outperformance_allowed,
    trend_context,
)

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_leader_universe_market_gate.py"
SPEC = importlib.util.spec_from_file_location("research_leader_universe_market_gate", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sessions(count: int, start: date = date(2020, 1, 2)) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _panel(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def test_date_ew_is_mean_of_daily_means_not_pooled() -> None:
    mask = np.array([[True, True, False], [True, False, False]])
    values = np.array([[0.10, -0.04, 9.0], [0.16, 9.0, 9.0]])
    date_ew = MODULE.date_ew_from_mask(mask, values)
    pooled = (0.10 + -0.04 + 0.16) / 3
    assert date_ew == pytest.approx(0.095)
    assert pooled == pytest.approx(0.073333, abs=1e-6)
    assert date_ew != pytest.approx(pooled)


def test_same_day_unselected_is_eligible_not_in_universe() -> None:
    gate = np.array([True, True, False])
    eligible = np.array(
        [
            [True, True, True, False],
            [True, True, False, True],
            [True, True, True, True],
        ]
    )
    rs = np.array(
        [
            [True, False, True, True],
            [True, False, False, False],
            [True, False, True, False],
        ]
    )
    selected, unselected = MODULE.selected_and_unselected(gate, eligible, rs)
    assert selected[0].tolist() == [True, False, True, False]
    assert unselected[0].tolist() == [False, True, False, False]
    assert selected[1].tolist() == [True, False, False, False]
    assert unselected[1].tolist() == [False, True, False, True]
    assert not selected[2].any()
    assert not unselected[2].any()
    summary_tag = MODULE.summarize_window(
        10,
        selected,
        unselected,
        {
            "complete": np.ones_like(selected, dtype=bool),
            "net": np.zeros(selected.shape),
            "net_excess": np.array(
                [
                    [0.02, -0.01, 0.03, 9.0],
                    [0.04, 0.00, 9.0, 9.0],
                    [9.0, 9.0, 9.0, 9.0],
                ]
            ),
        },
        [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)],
        date(2020, 1, 1),
        date(2020, 12, 31),
    )
    assert summary_tag["same_day_unselected"] == "eligible_not_in_universe"
    assert summary_tag["same_day_unselected"] != "unavailable_not_in_frozen_inputs"


def test_dual_regime_gate_reuses_shipped_early_recovery_and_broad_advance() -> None:
    from app.backtest.matrix import valid_rolling_mean

    sessions = _sessions(80)
    n_assets = 10
    rows = []
    for t, day in enumerate(sessions):
        for asset in range(n_assets):
            if t == 73:
                close = 11.0 if asset < 2 else 9.0
            elif t == 78:
                close = 11.0 if asset < 2 else 9.0
            elif t == 79:
                close = 11.0
            else:
                close = 10.0
            rows.append(
                {
                    "symbol": f"60000{asset}.SH",
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000.0,
                    "amount": 30_000_000.0,
                    "raw_close": close,
                }
            )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    gate, breadth = MODULE.dual_regime_gate(market)
    ma20 = valid_rolling_mean(
        market.close,
        np.isfinite(market.close) & (market.close > 0),
        20,
        bar_index=market.valid_bars,
    )
    shipped, shipped_breadth = market_breadth_allowed(
        market.close, ma20, {"a_share_dual_regime": True}, market.valid_bars
    )
    np.testing.assert_array_equal(gate, shipped)
    np.testing.assert_allclose(breadth, shipped_breadth)
    close = np.full((69, 10), 10.0)
    close[-6] = [11.0 if asset < 3 else 9.0 for asset in range(10)]
    close[-1] = [11.0 if asset < 5 else 9.0 for asset in range(10)]
    ma20_mid = np.full_like(close, 10.0)
    frozen, _ = market_breadth_allowed(close, ma20_mid, MODULE.DUAL_REGIME_PARAMS)
    expanded, _ = market_breadth_allowed(
        close,
        ma20_mid,
        {**MODULE.DUAL_REGIME_PARAMS, "include_middle_expansion_regime": True},
    )
    assert not frozen[-1]
    assert expanded[-1]


def test_rs_universe_reuses_trend_context_without_trend_template() -> None:
    sessions = _sessions(260)
    rows = []
    for t, day in enumerate(sessions):
        for asset, symbol in enumerate(("600000.SH", "600001.SH", "000001.SZ")):
            close = 10.0 + (0.05 * t if asset == 0 else 0.0)
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000.0,
                    "amount": 30_000_000.0,
                    "raw_close": close,
                }
            )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    mask, ranks = MODULE.rs_universe_mask(market)
    shipped_mask, shipped_ranks = trend_context(market, {"trend_filter": False, "rs_min": 85.0})
    np.testing.assert_array_equal(mask, shipped_mask)
    np.testing.assert_allclose(ranks, shipped_ranks, equal_nan=True)
    assert MODULE.RS_PARAMS["trend_filter"] is False


def test_eligibility_enforces_board_st_listing_price_amount() -> None:
    sessions = _sessions(40, start=date(2020, 1, 2))
    calendar = sessions
    symbols = ["600000.SH", "600001.SH", "430001.BJ", "000001.SZ"]
    names = ["浦发银行", "ST 示例", "北交所", "平安银行"]
    listing = [date(2019, 1, 2), date(2019, 1, 2), date(2019, 1, 2), date(2020, 2, 10)]
    n_t, n_a = len(calendar), len(symbols)
    raw = np.full((n_t, n_a), 10.0)
    raw[:, 0] = 2.0
    amount = np.full((n_t, n_a), 30_000_000.0)
    amount[:, 2] = 1_000.0
    valid = np.ones((n_t, n_a), dtype=bool)
    tradable = np.ones((n_t, n_a), dtype=bool)
    volume = np.full((n_t, n_a), 1_000_000.0)
    eligible = MODULE.tradable_eligibility_mask(
        symbols=symbols,
        names=names,
        listing_dates=listing,
        calendar=calendar,
        raw_close=raw,
        amount=amount,
        valid=valid,
        tradable=tradable,
        volume=volume,
    )
    last = eligible[-1]
    assert last.tolist() == [False, False, False, False]
    raw[-1, 0] = 10.0
    eligible = MODULE.tradable_eligibility_mask(
        symbols=symbols,
        names=names,
        listing_dates=listing,
        calendar=calendar,
        raw_close=raw,
        amount=amount,
        valid=valid,
        tradable=tradable,
        volume=volume,
    )
    assert eligible[-1, 0]
    assert not eligible[-1, 1]
    assert not eligible[-1, 2]
    assert not eligible[-1, 3]


def test_pre_calendar_listing_is_not_treated_as_new() -> None:
    calendar = _sessions(5)
    age = MODULE.listing_session_age(calendar, [date(1999, 11, 10), None])
    assert np.isinf(age[0, 0])
    assert np.isnan(age[0, 1])
    assert age[-1, 0] > 30 or np.isinf(age[-1, 0])


def test_costs_cut_gross_and_limits_do_not_roll() -> None:
    sessions = _sessions(26)
    rows = []
    for t, day in enumerate(sessions):
        for symbol, path in (
            ("600000.SH", 100.0 + t),
            ("600001.SH", 100.0),
            ("000001.SZ", 100.0),
        ):
            limit_up = symbol == "600001.SH" and t == 1
            missing = symbol == "000001.SZ" and t == 1
            if missing:
                continue
            open_px = 110.0 if (symbol == "600001.SH" and t == 1) else path
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": open_px,
                    "high": open_px,
                    "low": open_px,
                    "close": open_px,
                    "volume": 0.0 if limit_up else 1_000_000.0,
                    "amount": 30_000_000.0,
                    "raw_close": open_px,
                    "signal_limit_up": limit_up,
                    "signal_limit_down": False,
                }
            )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    calendar = MODULE.calendar_from_market(market)
    labeled = MODULE.label_signal_windows(market, calendar, training_end=date(2020, 12, 31))
    ten = labeled[10]
    signal0 = 0
    filled = ten["complete"][signal0]
    symbols = list(market.symbols)
    by_symbol = {symbol: i for i, symbol in enumerate(symbols)}
    assert filled[by_symbol["600000.SH"]]
    assert not filled[by_symbol["600001.SH"]]
    assert not filled[by_symbol["000001.SZ"]]
    gross = ten["gross"][signal0, by_symbol["600000.SH"]]
    net = ten["net"][signal0, by_symbol["600000.SH"]]
    assert net < gross
    config = MatcherConfig(
        matching="open_t+1",
        commission_pct=0.0003,
        slippage_bps=10.0,
        stamp_tax_policy="a_share_historical",
    )
    entry = sessions[1]
    exit_day = sessions[1 + 10]
    expected = MODULE.net_round_trip(gross, config.buy_cost_pct(), config.sell_cost_pct(exit_day))
    assert net == pytest.approx(expected)
    assert ten["complete"][0, by_symbol["600001.SH"]] is np.False_ or not ten["complete"][0, by_symbol["600001.SH"]]


def test_labels_do_not_cross_training_end() -> None:
    sessions = _sessions(16, start=date(2022, 12, 12))
    rows = []
    for day in sessions:
        rows.append(
            {
                "symbol": "600000.SH",
                "date": day,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 1_000_000.0,
                "amount": 30_000_000.0,
                "raw_close": 10.0,
            }
        )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    calendar = MODULE.calendar_from_market(market)
    labeled = MODULE.label_signal_windows(market, calendar, training_end=date(2022, 12, 31))
    for t, day in enumerate(calendar):
        exit_idx = t + 1 + 10
        if exit_idx < len(calendar) and calendar[exit_idx] > date(2022, 12, 31):
            assert not labeled[10]["complete"][t, 0]


def test_selector_source_has_no_pattern_detector() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "detect(" not in source
    assert "cup_handle" not in source
    assert "high_tight_flag" not in source
    assert "vcp_structure" not in source
    assert "trend_filter\": False" in source or "trend_filter': False" in source
    assert "market_breadth_allowed" in source
    assert "trend_context" in source
    assert "market_outperformance_allowed" in source


def test_v2_universe_is_same_day_outperformance_not_rs() -> None:
    sessions = _sessions(4)
    paths = {
        "600000.SH": [10.0, 11.0, 11.0, 11.0],
        "600001.SH": [10.0, 10.0, 10.0, 10.0],
        "000001.SZ": [10.0, 10.5, 10.5, 10.5],
    }
    rows = []
    for t, day in enumerate(sessions):
        for symbol, closes in paths.items():
            close = closes[t]
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000.0,
                    "amount": 30_000_000.0,
                    "raw_close": close,
                }
            )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    shipped = market_outperformance_allowed(market.close, market.valid_bars)
    got = MODULE.same_day_outperformance_mask(market)
    np.testing.assert_array_equal(got, shipped)
    v2 = MODULE.universe_mask(market, MODULE.UNIVERSE_SAME_DAY_OUTPERFORMANCE)
    np.testing.assert_array_equal(v2, shipped)
    symbols = list(market.symbols)
    by_symbol = {symbol: i for i, symbol in enumerate(symbols)}
    assert v2[1, by_symbol["600000.SH"]]
    assert not v2[1, by_symbol["600001.SH"]]
    assert not v2[1, by_symbol["000001.SZ"]]
    v1, _ = MODULE.rs_universe_mask(market)
    assert v1.shape == v2.shape
