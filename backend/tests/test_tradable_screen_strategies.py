from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix, make_signal_matrix
from app.strategy.builtin._quants_vcp import (
    leader_open_entry_mask,
    market_breadth_allowed,
    mask_entry_signals,
    snapshot_entries_only,
    trend_context,
)
from app.strategy.engine import StrategyDataContext, StrategyEngine
from tests.test_price_structure_strategies import _market
from tests.test_quants_vcp import vcp_history

BUILTIN = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _vcp_market(frame):
    return build_market_data_matrix(
        frame.with_columns([pl.col(f).alias("raw_" + f) for f in ("high", "low", "close")]),
        field_columns={"raw_high", "raw_low", "raw_close"},
    )


def _sessions(count: int, start: date = date(2020, 1, 2)) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_leader_open_mask_is_rs85_and_dual_regime_gate():
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
                }
            )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})
    mask = leader_open_entry_mask(market, {"rs_min": 85.0})
    rs_mask, _ = trend_context(market, {"trend_filter": False, "rs_min": 85.0})
    from app.backtest.matrix import valid_rolling_mean

    valid = np.isfinite(market.close) & (market.close > 0)
    ma20 = valid_rolling_mean(market.close, valid, 20, bar_index=market.valid_bars)
    gate, _ = market_breadth_allowed(
        market.close,
        ma20,
        {"a_share_dual_regime": True, "include_middle_expansion_regime": False},
        market.valid_bars,
    )
    np.testing.assert_array_equal(mask, rs_mask & gate[:, None])


def test_mask_entry_signals_keeps_exit_and_zeros_blocked_entries():
    shape = (3, 2)
    signals = make_signal_matrix(
        shape,
        entry=np.array([[1, 1], [1, 0], [0, 1]], dtype=np.uint8),
        exit=np.array([[0, 1], [1, 0], [0, 0]], dtype=np.uint8),
        score=np.array([[9.0, 8.0], [7.0, 0.0], [0.0, 6.0]], dtype=np.float32),
        entry_signal_code=np.array([[0, 1], [2, -1], [-1, 3]], dtype=np.int16),
        exit_signal_code=np.array([[-1, 0], [0, -1], [-1, -1]], dtype=np.int16),
        entry_signal_ids=("buy",),
        exit_signal_ids=("sell",),
    )
    masked = mask_entry_signals(signals, np.array([[True, False], [False, True], [True, True]]))
    np.testing.assert_array_equal(masked.entry, [[1, 0], [0, 0], [0, 1]])
    np.testing.assert_array_equal(masked.exit, signals.exit)
    np.testing.assert_array_equal(masked.entry_signal_code, [[0, -1], [-1, -1], [-1, 3]])
    assert masked.score[0, 1] == 0
    assert masked.score[0, 0] == pytest.approx(9.0)


def test_snapshot_entries_only_drops_watch_names():
    market = build_market_data_matrix(vcp_history())
    watch = make_signal_matrix(
        market.shape,
        entry=np.zeros(market.shape, dtype=np.uint8),
        exit=np.zeros(market.shape, dtype=np.uint8),
    )
    rows = {"600000.SH": {"vcp_status": "wait_breakout", "vcp_pivot": 100.0}}
    _, kept = snapshot_entries_only(watch, rows, market, market.shape[0] - 1)
    assert kept == {}

    entry = np.zeros(market.shape, dtype=np.uint8)
    entry[-1, 0] = 1
    bought = make_signal_matrix(market.shape, entry=entry, exit=np.zeros(market.shape, dtype=np.uint8))
    _, kept = snapshot_entries_only(bought, rows, market, market.shape[0] - 1)
    assert set(kept) == {"600000.SH"}
    assert kept["600000.SH"]["buy_ready"] is True
    assert kept["600000.SH"]["vcp_entry_triggered"] is True


def test_frozen_vcp_leader_defaults_are_unchanged():
    definition = StrategyEngine([BUILTIN]).get("vcp_leader_breakout")
    defaults = StrategyEngine.resolve_params(definition)
    assert defaults["breakout_close_location_min"] == 0.0
    assert definition.meta["profit_lock_steps"] == [
        {"activate_pct": 0.10, "floor_return_pct": 0.0},
        {"activate_pct": 0.20, "trailing_drawdown_pct": 0.10},
    ]
    assert definition.meta["live_qualified"] is False
    assert definition.meta["id"] == "vcp_leader_breakout"
    assert definition.meta["version"] == "forward-v2"


def test_vcp_tradable_defaults_require_upper_half_and_five_pct_lock():
    engine = StrategyEngine([BUILTIN])
    definition = engine.get("vcp_leader_tradable_v1")
    defaults = StrategyEngine.resolve_params(definition)
    assert defaults["breakout_close_location_min"] == 0.5
    assert defaults["min_legs"] == 2  # Primary is selected before the separate three-leg gate.
    assert definition.meta["close_breakeven_activate_pct"] == 0.05
    assert definition.meta["profit_lock_steps"] == [
        {"activate_pct": 0.10, "floor_return_pct": 0.0},
        {"activate_pct": 0.20, "trailing_drawdown_pct": 0.10},
    ]
    assert definition.meta["live_qualified"] is False
    assert definition.meta.get("research_only") is not True
    public_ids = {row["id"] for row in engine.list_strategies()}
    assert "vcp_leader_tradable_v1" in public_ids
    assert "vcp_leader_breakout" not in public_ids
    hidden_ids = {row["id"] for row in engine.list_strategies(include_research=True)}
    assert "vcp_leader_breakout" in hidden_ids


def test_vcp_tradable_screen_lists_only_true_buy_entries():
    engine = StrategyEngine([BUILTIN])
    watch = vcp_history()
    as_of = watch["date"][-1]
    context = StrategyDataContext(
        asset_type="stock",
        timeframe="1d",
        as_of=as_of,
        current=watch.tail(1),
        history=watch,
        market=_vcp_market(watch),
    )
    frozen = engine.run(
        "vcp_leader_breakout",
        context,
        params={"trend_filter": False, "rs_min": 0},
        overrides={"basic_filter": {"enabled": False}},
    )
    tradable = engine.run(
        "vcp_leader_tradable_v1",
        context,
        params={"trend_filter": False, "rs_min": 0},
        overrides={"basic_filter": {"enabled": False}},
    )
    assert frozen.total == 1
    assert frozen.rows[0]["vcp_status"] == "wait_breakout"
    assert frozen.rows[0]["buy_ready"] is False
    assert frozen.rows[0]["vcp_entry_triggered"] is False
    assert frozen.entry_signal_hits == []
    assert tradable.total == 0
    assert tradable.entry_signal_hits == []


def test_upper_wick_breakout_is_not_a_tradable_buy():
    rows = vcp_history(True).to_dicts()
    rows[-1] = {
        **rows[-1],
        "high": 110.0,
        "low": 99.8,
        "close": 101.0,
    }
    frame = pl.DataFrame(rows)
    market = _vcp_market(frame)
    engine = StrategyEngine([BUILTIN])
    frozen_params = StrategyEngine.resolve_params(
        engine.get("vcp_leader_breakout"), {"trend_filter": False, "rs_min": 0}
    )
    tradable_params = StrategyEngine.resolve_params(
        engine.get("vcp_leader_tradable_v1"), {"trend_filter": False, "rs_min": 0}
    )
    frozen = engine.get("vcp_leader_breakout").matrix_strategy.compute_signals(
        market, frozen_params
    )
    tradable = engine.get("vcp_leader_tradable_v1").matrix_strategy.compute_signals(
        market, tradable_params
    )
    assert frozen_params["breakout_close_location_min"] == 0.0
    assert tradable_params["breakout_close_location_min"] == 0.5
    assert frozen.entry[-1, 0]
    assert not tradable.entry[-1, 0]


def test_two_leg_upper_half_breakout_is_not_a_main_book_buy():
    frame = vcp_history(True)
    market = _vcp_market(frame)
    params = {"trend_filter": False, "rs_min": 0}
    strategy = StrategyEngine([BUILTIN]).get("vcp_leader_tradable_v1").matrix_strategy
    signals, rows = strategy.screen_snapshot(market, params, market.shape[0] - 1)
    assert not signals.entry[-1, 0]
    assert rows == {}


def test_three_leg_primary_is_kept_without_changing_detector_parameters(monkeypatch):
    import copy

    market = _vcp_market(vcp_history(True))
    strategy = StrategyEngine([BUILTIN]).get("vcp_leader_tradable_v1").matrix_strategy
    detector_globals = type(strategy._inner).__mro__[1]._evaluate.__globals__
    original = detector_globals["detect"]

    def three_leg_primary(high, low, close, volume, dates, params):
        assert params.get("min_legs", 2) == 2
        result = original(high, low, close, volume, dates, params)
        if result and result["primary"]["valid"]:
            result = copy.deepcopy(result)
            result["primary"]["legs"] = result["primary"]["legs"][:1] * 3
        return result

    monkeypatch.setitem(detector_globals, "detect", three_leg_primary)
    params = {"trend_filter": False, "rs_min": 0, "min_legs": 2}
    signals, rows = strategy.screen_snapshot(market, params, market.shape[0] - 1)
    assert signals.entry[-1, 0]
    assert rows["600000.SH"]["buy_ready"] is True
    assert rows["600000.SH"]["vcp_leg_count"] == 3
    assert strategy.compute_signals(market, params).entry[-1, 0]


def test_pullback_and_cup_leader_variants_are_public_htf_is_not_wrapped():
    engine = StrategyEngine([BUILTIN])
    public = {row["id"] for row in engine.list_strategies()}
    assert "launch_pullback_leader_v1" in public
    assert "cup_handle_leader_v1" in public
    assert "high_tight_flag_leader_v1" not in public
    assert "quants_high_tight_flag_legacy_v1" in {row["id"] for row in engine.list_strategies(include_research=True)}
    pullback = StrategyEngine.resolve_params(engine.get("launch_pullback_leader_v1"))
    cup = StrategyEngine.resolve_params(engine.get("cup_handle_leader_v1"))
    assert pullback["rs_min"] == 85.0
    assert cup["rs_min"] == 85.0
    assert engine.get("launch_pullback_leader_v1").matrix_strategy.required_warmup_bars(pullback) >= 260


def test_pullback_leader_drops_entries_when_rs_floor_is_impossible():
    market = _market(
        [10.0] * 25 + [11.0, 11.20, 11.10, 11.05, 10.98],
        volumes=[1_000.0] * 25 + [3_000.0, 2_000.0, 2_000.0, 2_000.0, 500.0],
    )
    engine = StrategyEngine([BUILTIN])
    base = engine.get("launch_pullback_support").matrix_strategy.compute_signals(
        market,
        {item["id"]: item["default"] for item in engine.get("launch_pullback_support").meta["params"]},
    )
    blocked = engine.get("launch_pullback_leader_v1").matrix_strategy.compute_signals(
        market,
        {
            **{
                item["id"]: item["default"]
                for item in engine.get("launch_pullback_leader_v1").meta["params"]
            },
            "rs_min": 101.0,
        },
    )
    assert base.entry[-1, 0]
    assert not blocked.entry.any()
