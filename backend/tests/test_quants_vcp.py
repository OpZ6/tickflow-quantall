from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_vcp import (
    QuantsVcpStrategy,
    apply_candidate_rankings,
    apply_turnover_ranking,
    cross_sectional_percentile_ranks,
    entry_allowed,
    market_breadth_allowed,
    technical_score,
    trend_context,
)
from app.strategy.engine import StrategyDataContext, StrategyEngine

BUILTIN = Path(__file__).resolve().parents[1] / "app/strategy/builtin"


def test_snapshot_rejects_silent_zero_when_252_day_history_is_missing():
    frame = pl.DataFrame(
        {
            "symbol": [f"{i:06d}.SZ" for i in range(500)],
            "date": [date(2026, 9, 4)] * 500,
            "open": [10.0] * 500,
            "high": [10.1] * 500,
            "low": [9.9] * 500,
            "close": [10.0] * 500,
            "volume": [1_000_000.0] * 500,
        }
    )
    market = build_market_data_matrix(frame)

    with pytest.raises(ValueError, match="VCP 历史覆盖不足"):
        QuantsVcpStrategy().screen_snapshot(market, {}, 0)


def test_turnover_ranking_blends_only_same_day_entry_candidates():
    score = np.array([[80.0, 60.0, 40.0], [20.0, 30.0, 40.0]], dtype=np.float32)
    entry = np.array([[1, 1, 0], [0, 0, 0]], dtype=np.uint8)
    turnover = np.array([[2.0, 6.0, 9.0], [9.0, 8.0, 7.0]])

    result = apply_turnover_ranking(score.copy(), entry, turnover, 0.25)

    assert result[0].tolist() == pytest.approx([72.5, 70.0, 40.0])
    assert result[1].tolist() == pytest.approx(score[1].tolist())
    assert np.array_equal(apply_turnover_ranking(score.copy(), entry, turnover, 0.0), score)


def test_cross_sectional_percentile_ranks_are_same_day_and_average_ties():
    values = np.array([[1.0, 2.0, 2.0, 4.0], [4.0, np.nan, 1.0, 2.0]])

    ranks = cross_sectional_percentile_ranks(values)

    assert ranks[0].tolist() == pytest.approx([25.0, 62.5, 62.5, 100.0])
    assert ranks[1, [0, 2, 3]].tolist() == pytest.approx([100.0, 100 / 3, 200 / 3])
    assert np.isnan(ranks[1, 1])


def test_candidate_rankings_combine_fields_and_preserve_missing_values():
    score = np.array([[80.0, 60.0, 40.0]], dtype=np.float32)
    entry = np.array([[1, 1, 1]], dtype=np.uint8)
    turnover = np.array([[2.0, 6.0, 9.0]])
    roe = np.array([[20.0, np.nan, 10.0]])

    result = apply_candidate_rankings(
        score.copy(), entry, [(turnover, 0.25), (roe, 0.25)]
    )

    assert result[0].tolist() == pytest.approx([73.3333, 61.6667, 57.5], abs=1e-4)


def test_short_scale_penalty_only_changes_research_ranking():
    short = {"quality": 7.0, "volume_ratio": 1.25, "scale": "short"}
    medium = {**short, "scale": "medium"}
    assert technical_score(short, 90.0, {}) == technical_score(medium, 90.0, {})
    assert technical_score(short, 90.0, {"short_scale_score_penalty": 8.0}) == 66.0


def test_optional_pivot_cross_only_changes_breakout_entry():
    breakout = {"status": "executable", "setup": "breakout", "pivot": 10.0}
    cheat = {"status": "executable", "setup": "cheat", "pivot": 10.0}
    assert entry_allowed(breakout, 10.1, {})
    assert not entry_allowed(breakout, 10.1, {"require_pivot_cross": True})
    assert entry_allowed(breakout, 9.9, {"require_pivot_cross": True})
    assert entry_allowed(cheat, 10.1, {"require_pivot_cross": True})


def test_pivot_cross_can_require_two_closes_above_pivot():
    breakout = {"status": "executable", "setup": "breakout", "pivot": 10.0}
    params = {"require_pivot_cross": True, "breakout_confirmation_days": 2}
    assert entry_allowed(breakout, 10.1, params, [9.9, 10.05, 10.1])
    assert not entry_allowed(breakout, 10.1, params, [10.01, 10.05, 10.1])
    assert not entry_allowed(breakout, 9.99, params, [9.9, 9.99, 10.1])


def test_breakout_close_location_can_reject_upper_wick():
    breakout = {
        "status": "executable",
        "setup": "breakout",
        "pivot": 10.0,
        "close_location": 0.55,
    }
    assert entry_allowed(breakout, 9.9, {})
    assert not entry_allowed(breakout, 9.9, {"breakout_close_location_min": 0.6})


def test_prebreakout_pivot_closes_can_reject_worn_out_pivot():
    breakout = {
        "status": "executable",
        "setup": "breakout",
        "pivot": 10.0,
        "close_location": 0.8,
    }
    closes = [9.8] * 16 + [10.1, 9.9, 10.2, 9.95, 10.3]

    assert entry_allowed(breakout, 9.95, {}, closes)
    assert entry_allowed(
        breakout, 9.95, {"prebreakout_pivot_closes_max": 2}, closes
    )
    assert not entry_allowed(
        breakout, 9.95, {"prebreakout_pivot_closes_max": 1}, closes
    )


def test_market_breadth_gate_uses_cross_section_above_ma20():
    close = np.array([[11.0, 9.0, np.nan], [12.0, 13.0, 8.0]])
    ma20 = np.array([[10.0, 10.0, np.nan], [10.0, 10.0, 10.0]])
    allowed, breadth = market_breadth_allowed(
        close, ma20, {"market_breadth_ma20_min": 0.4, "market_breadth_ma20_max": 0.6}
    )

    np.testing.assert_allclose(breadth, [0.5, 2 / 3])
    assert allowed.tolist() == [True, False]


def test_market_breadth_gate_can_require_improvement():
    close = np.array([[9.0, 9.0], [11.0, 9.0], [11.0, 9.0], [12.0, 13.0]])
    ma20 = np.full_like(close, 10.0)
    allowed, breadth = market_breadth_allowed(
        close,
        ma20,
        {
            "market_breadth_ma20_min": 0.4,
            "market_breadth_ma20_max": 1.0,
            "market_breadth_rising_days": 2,
        },
    )
    np.testing.assert_allclose(breadth, [0.0, 0.5, 0.5, 1.0])
    assert allowed.tolist() == [False, False, True, True]


def test_market_breadth_gate_can_use_causal_rolling_percentile():
    breadth = np.linspace(0.10, 0.90, 80)
    ma20 = np.full((80, 10), 10.0)
    close = np.where(
        np.arange(10)[None, :] < np.rint(breadth[:, None] * 10), 11.0, 9.0
    )
    params = {
        "market_breadth_percentile_lookback": 60,
        "market_breadth_percentile_min": 0.0,
        "market_breadth_percentile_max": 0.6,
    }

    allowed, calculated = market_breadth_allowed(close, ma20, params)

    assert not allowed[:59].any()  # minimum causal history
    assert np.isfinite(calculated).all()
    assert not allowed[59:].any()  # current breadth is always near its rolling maximum


def test_market_breadth_gate_can_require_positive_equal_weight_return():
    close = np.array(
        [
            [10.0, 10.0],
            [10.5, 9.0],
            [11.0, 8.0],
            [13.0, 9.0],
        ]
    )
    ma20 = np.full_like(close, 5.0)
    allowed, _ = market_breadth_allowed(
        close,
        ma20,
        {
            "market_equal_weight_return_lookback": 1,
            "market_equal_weight_return_min": 0.0,
        },
    )

    assert allowed.tolist() == [False, False, False, True]


def test_a_share_dual_regime_allows_early_recovery_and_broad_advance():
    breadth_counts = [1, 1, 1, 1, 1, 2, 8]
    close = np.array(
        [[11.0 if asset < count else 9.0 for asset in range(10)] for count in breadth_counts]
    )
    # Give the final broad-advance row positive equal-weight momentum with enough history.
    close = np.vstack([np.full((63, 10), 10.0), close])
    close[-1] = 11.0
    ma20 = np.full_like(close, 10.0)

    allowed, breadth = market_breadth_allowed(
        close, ma20, {"a_share_dual_regime": True}
    )

    assert allowed[-2]  # 20% breadth, up from 10% five sessions earlier
    assert allowed[-1]  # broad advance with positive 63-session market return
    assert breadth[-2] == pytest.approx(0.2)


def test_breakout_volume_can_rank_candidates_without_changing_default_score():
    pattern = {"quality": 7.0, "volume_ratio": 2.0}
    assert technical_score(pattern, 90.0, {}) == 74.0
    assert technical_score(pattern, 90.0, {"breakout_volume_score_weight": 10.0}) == 81.5


def vcp_history(breakout=False):
    # Quants' three-contraction fixture, with an optional confirmed breakout.
    rows, close = [], 92.0
    for i in range(70):
        close += (
            0.55
            if i < 10
            else -1.25
            if i < 18
            else 0.9
            if i < 30
            else -0.65
            if i < 38
            else 0.42
            if i < 52
            else -0.2
            if i < 60
            else 0.08
        )
        rows.append(
            dict(
                symbol="600000.SH",
                date=date(2026, 1, 1) + timedelta(days=i),
                open=close * 0.995,
                high=100.0 if i in {12, 32, 54} else min(100.0, close * 1.012),
                low=close * 0.985,
                close=close,
                volume=float(2_000_000 - min(i, 50) * 20_000),
            )
        )
    if breakout:
        rows.append(
            dict(
                symbol="600000.SH",
                date=rows[-1]["date"] + timedelta(days=1),
                open=100.0,
                high=102.0,
                low=99.8,
                close=101.0,
                volume=2_000_000.0,
            )
        )
    return pl.DataFrame(rows)


def strategy():
    return StrategyEngine._load_file(BUILTIN / "quants_vcp.py")


def test_setup_deduplication_emits_only_first_signal_for_same_pivot():
    rows = vcp_history(breakout=True).to_dicts()
    for offset in (1, 2):
        close = 101.0 + offset * 0.2
        rows.append({
            "symbol": "600000.SH",
            "date": rows[-1]["date"] + timedelta(days=1),
            "open": close - 0.2,
            "high": close + 0.8,
            "low": close - 0.5,
            "close": close,
            "volume": 2_000_000.0,
        })
    market = build_market_data_matrix(pl.DataFrame(rows))
    matrix_strategy = strategy().matrix_strategy
    repeated = matrix_strategy.compute_signals(
        market, {"trend_filter": False, "rs_min": 0, "deduplicate_setups": False}
    )
    deduplicated = matrix_strategy.compute_signals(
        market, {"trend_filter": False, "rs_min": 0, "deduplicate_setups": True}
    )

    assert int(repeated.entry.sum()) == 3
    assert int(deduplicated.entry.sum()) == 1


def test_recovery_breakout_production_defaults_are_frozen():
    definition = StrategyEngine([BUILTIN]).get("vcp_recovery_breakout")
    params = StrategyEngine.resolve_params(definition)

    assert definition.meta["name"] == "VCP 复苏突破(研究)"
    assert definition.meta["live_qualified"] is False
    assert definition.basic_filter == {
        "enabled": True,
        "price_min": 3.0,
        "price_max": 300.0,
        "market_cap_min": 1_000_000_000.0,
        "float_cap_min": None,
        "float_cap_max": None,
        "amount_min": 20_000_000.0,
        "amount_max": None,
        "turnover_min": None,
        "turnover_max": None,
        "exclude_st": True,
        "exclude_new_days": 30,
        "boards": ["沪主板", "深主板", "创业板", "科创板", "北交所"],
    }
    assert definition.stop_loss == -0.03
    assert definition.max_hold_days == 40
    assert params == {
        "trend_filter": True,
        "rs_min": 85.0,
        "distance_high_max": 0.12,
        "min_legs": 2,
        "contraction_ratio_max": 0.95,
        "tightness_min": 0.25,
        "dry_volume_ratio_max": 0.90,
        "max_chase": 0.025,
        "plan_stop_pct": 0.03,
        "require_pivot_cross": True,
        "allow_cheat": False,
        "breakout_volume_ratio_min": 1.25,
        "breakout_volume_score_weight": 0.0,
        "breakout_close_location_min": 0.0,
        "exit_ma_days": 20,
        "market_breadth_ma20_min": 0.30,
        "market_breadth_ma20_max": 0.35,
        "legacy_semantics": False,
    }


def test_multileg_pivot_and_watch_are_not_buy_signals():
    s = strategy().matrix_strategy
    market = build_market_data_matrix(vcp_history())
    signals, rows = s.screen_snapshot(
        market, {"trend_filter": False, "rs_min": 0}, market.shape[0] - 1
    )
    row = rows["600000.SH"]
    assert row["vcp_pivot"] == 100.0
    assert row["vcp_leg_count"] >= 2
    assert row["vcp_status"] == "wait_breakout"
    assert not signals.entry[-1, 0]
    assert len(row["vcp_structure"]["primary"]["legs"]) >= 2


def test_volume_breakout_and_chase_band():
    s = strategy().matrix_strategy
    frame = vcp_history(True)
    params = {"trend_filter": False, "rs_min": 0}
    signals = s.compute_signals(build_market_data_matrix(frame), params)
    assert signals.entry[-1, 0]
    assert not s.compute_signals(
        build_market_data_matrix(frame), {**params, "breakout_volume_ratio_min": 3.0}
    ).entry[-1, 0]
    assert not s.compute_signals(
        build_market_data_matrix(frame), {**params, "max_chase": 0.005}
    ).entry[-1, 0]


def test_prefix_causality_and_snapshot_match():
    s = strategy().matrix_strategy
    frame = vcp_history(True)
    params = {"trend_filter": False, "rs_min": 0}
    full = s.compute_signals(build_market_data_matrix(frame), params)
    for size in (20, 35, 50, 60, 70, 71):
        market = build_market_data_matrix(frame.head(size))
        prefix = s.compute_signals(market, params)
        snap, _ = s.screen_snapshot(market, params, size - 1)
        np.testing.assert_array_equal(prefix.entry, full.entry[:size])
        np.testing.assert_array_equal(snap.entry[-1], prefix.entry[-1])


def test_default_requires_long_trend_and_rs_history():
    s = strategy().matrix_strategy
    market = build_market_data_matrix(vcp_history(True))
    signals, rows = s.screen_snapshot(market, {}, market.shape[0] - 1)
    assert not signals.entry.any()
    assert rows == {}


def test_engine_keeps_candidates_separate_from_entries():
    engine = StrategyEngine([BUILTIN])
    frame = vcp_history()
    as_of = frame["date"][-1]
    result = engine.run(
        "quants_vcp",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=as_of,
            current=frame.tail(1),
            history=frame,
            market=build_market_data_matrix(frame),
        ),
        params={"trend_filter": False, "rs_min": 0},
        overrides={"basic_filter": {"enabled": False}},
    )
    assert result.total == 1
    assert result.rows[0]["vcp_status"] == "wait_breakout"
    assert result.rows[0]["score"] > 0
    assert result.entry_signal_hits == []
    assert engine.get("vcp_breakout") is not None


def long_universe():
    frame = vcp_history(True)
    start = frame["date"][0] - timedelta(days=220)
    prefix = pl.DataFrame(
        [
            dict(
                symbol="600000.SH",
                date=start + timedelta(days=i),
                open=50.0 + i * 0.18,
                high=(50.0 + i * 0.18) * 1.01,
                low=(50.0 + i * 0.18) * 0.99,
                close=50.0 + i * 0.18,
                volume=2_000_000.0,
            )
            for i in range(220)
        ]
    )
    leader = pl.concat([prefix, frame])
    peers = [
        leader.with_columns(
            pl.lit(f"{i:06d}.SZ").alias("symbol"),
            *[pl.lit(30.0 + i).alias(c) for c in ("open", "high", "low", "close")],
        )
        for i in range(1, 5)
    ]
    return pl.concat([leader, *peers])


def context_for(frame):
    as_of = frame["date"].max()
    return StrategyDataContext(
        asset_type="stock",
        timeframe="1d",
        as_of=as_of,
        current=frame.filter(pl.col("date") == as_of),
        history=frame,
        market=build_market_data_matrix(frame),
    )


def test_default_full_universe_rs_trend_and_signal():
    market = build_market_data_matrix(long_universe())
    mask, ranks = trend_context(market, {})
    index = market.symbols.index("600000.SH")
    assert ranks[-1, index] == 100
    assert mask[-1, index]
    assert sorted(ranks[-1].tolist()) == [50.0, 50.0, 50.0, 50.0, 100.0]
    signals, rows = strategy().matrix_strategy.screen_snapshot(market, {}, market.shape[0] - 1)
    assert signals.entry[-1, index]
    assert set(rows) == {"600000.SH"}
    assert rows["600000.SH"]["vcp_rs"] == 100


def test_rs_and_signal_independent_of_future_and_input_order():
    frame = long_universe()
    market = build_market_data_matrix(frame)
    s = strategy().matrix_strategy
    past_date = sorted(frame["date"].unique().to_list())[-2]
    prefix_market = build_market_data_matrix(frame.filter(pl.col("date") <= past_date))
    a, rows_a = s.screen_snapshot(prefix_market, {}, prefix_market.shape[0] - 1)
    b, rows_b = s.screen_snapshot(market, {}, market.shape[0] - 2)
    assert rows_a == rows_b
    np.testing.assert_array_equal(a.entry[-1], b.entry[-2])
    shuffled = build_market_data_matrix(frame.reverse())
    _, rows_c = s.screen_snapshot(shuffled, {}, shuffled.shape[0] - 2)
    assert rows_b == rows_c


@pytest.mark.parametrize("column,value", [("volume", None), ("volume", -1.0), ("low", 0.0)])
def test_invalid_inputs_do_not_create_entries(column, value):
    frame = vcp_history(True).with_columns(
        pl.when(pl.col("date") == vcp_history(True)["date"][-1])
        .then(pl.lit(value))
        .otherwise(pl.col(column))
        .alias(column)
    )
    market = build_market_data_matrix(frame)
    signals, rows = strategy().matrix_strategy.screen_snapshot(
        market, {"trend_filter": False, "rs_min": 0}, market.shape[0] - 1
    )
    assert not signals.entry[-1, 0]
    assert rows == {}


def test_monotonic_narrowing_is_not_multileg_vcp():
    frame = vcp_history().with_columns(pl.Series("close", np.linspace(90, 100, 70)))
    frame = frame.with_columns(
        (pl.col("close") * 1.005).alias("high"), (pl.col("close") * 0.995).alias("low")
    )
    market = build_market_data_matrix(frame)
    _, rows = strategy().matrix_strategy.screen_snapshot(
        market, {"trend_filter": False, "rs_min": 0}, 69
    )
    assert rows == {}


def test_filter_parameters_persistence_and_structure_events(tmp_path):
    from app.services.strategy_evidence import enrich_and_persist_strategy_result
    from app.services.strategy_signal_events import StrategySignalEventRepository
    from app.strategy.config import load_override, save_override

    engine = StrategyEngine([BUILTIN])
    context = context_for(long_universe())
    override = {"basic_filter": {"enabled": False}}
    save_override(tmp_path, "quants_vcp", override)
    restored = load_override(tmp_path, "quants_vcp")
    result = engine.run("quants_vcp", context, overrides=restored)
    assert result.total == 1
    s = engine.get("quants_vcp")
    for _ in range(2):
        enrich_and_persist_strategy_result(
            data_dir=tmp_path,
            result=result,
            strategy=s,
            params=engine.resolve_params(s, None, restored),
            context=context,
        )
    events = StrategySignalEventRepository(tmp_path).query(symbol="600000.SH")
    assert {e["event_type"] for e in events} == {"candidate", "entry"}
    assert len(events) == 2
    assert events[0]["pattern_refs"][0]["primary"]["pivot"] == 100
    assert any(
        level["role"] == "trigger" and level["value"] == 100 for level in events[0]["levels"]
    )
    assert engine.run("quants_vcp", context, params={"min_legs": 4}, overrides=override).total == 0
    assert (
        engine.run(
            "quants_vcp",
            context,
            overrides={"basic_filter": {"price_min": 1000, "amount_min": None}},
        ).total
        == 0
    )
    assert engine.run("quants_vcp", context, pool=["000001.SZ"], overrides=override).total == 0


def test_backtest_uses_executable_signals_and_next_open():
    from app.backtest.engine import BacktestEngine
    from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService

    panel = long_universe()
    last = panel["date"].max()
    panel = pl.concat(
        [
            panel,
            *[
                panel.filter(pl.col("date") == last).with_columns(
                    pl.lit(last + timedelta(days=day)).alias("date")
                )
                for day in (1, 2)
            ],
        ]
    )
    engine = BacktestEngine(repo=None)
    engine.load_market_data_matrix_for_backtest = lambda *args, **kwargs: build_market_data_matrix(
        panel
    )
    strategies = StrategyEngine([BUILTIN])
    service = StrategyBacktestService(engine=engine, strategy_engine=strategies)
    result = service.run(
        StrategyBacktestConfig(
            strategy_id="quants_vcp",
            symbols=None,
            start=last - timedelta(days=2),
            end=last + timedelta(days=2),
            overrides={"basic_filter": {"enabled": False}},
            fees_pct=0,
            slippage_bps=0,
            max_positions=1,
        )
    )
    assert result.error is None
    assert result.trades
    assert str(result.trades[0]["entry_date"])[:10] == str(last + timedelta(days=1))
    assert result.trades[0]["entry_signal_id"] == "signal_quants_vcp_breakout"


def test_incomplete_today_is_rejected(monkeypatch):
    from datetime import datetime

    from app import market_time

    context = context_for(vcp_history())
    monkeypatch.setattr(
        market_time,
        "cn_now",
        lambda: datetime.combine(context.as_of, datetime.min.time()).replace(hour=10),
    )
    with pytest.raises(ValueError, match="已完成日线"):
        StrategyEngine([BUILTIN]).run("quants_vcp", context)


def test_realtime_monitor_does_not_treat_partial_bars_as_completed():
    from app.strategy.monitor import MonitorRuleEngine

    monitor = MonitorRuleEngine()
    monitor.set_strategy_engine(StrategyEngine([BUILTIN]))
    monitor.set_rules(
        [
            {
                "id": "vcp",
                "name": "vcp",
                "type": "strategy",
                "asset_type": "stock",
                "strategy_id": "quants_vcp",
                "scope": "all",
                "cooldown_seconds": 0,
            }
        ]
    )
    assert monitor.evaluate(vcp_history(True).tail(1)) == []
    assert monitor.latest_strategy_results() == {}


def test_vcp_leader_breakout_freezes_forward_observation_defaults():
    definition = StrategyEngine([BUILTIN]).get("vcp_leader_breakout")
    defaults = StrategyEngine.resolve_params(definition)

    assert definition.meta["live_qualified"] is False
    assert definition.meta["recommended_max_positions"] == 4
    assert definition.meta["profit_lock_steps"] == [
        {"activate_pct": 0.10, "floor_return_pct": 0.0},
        {"activate_pct": 0.20, "trailing_drawdown_pct": 0.10},
    ]
    assert defaults["a_share_dual_regime"] is True
    assert defaults["contraction_strength_rank_weight"] == 0.25
    assert definition.stop_loss == -0.05
    assert definition.max_hold_days == 40
