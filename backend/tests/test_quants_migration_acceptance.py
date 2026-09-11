"""Business checks for the versioned migration strategies (no source checkout needed)."""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_legacy_patterns import pullback_detect
from app.strategy.engine import StrategyEngine

BUILTIN = Path(__file__).resolve().parents[1] / "app/strategy/builtin"
NAMES = {
    "quants_vcp_legacy_v1": "VCP 宽泛候选池（股票魔法师形态）",
    "quants_growth_trend_legacy_v1": "成长趋势(经典 VCP)",
    "quants_cup_handle_legacy_v1": "杯柄候选池（多尺度形态）",
    "quants_high_tight_flag_legacy_v1": "高而紧旗形候选池（多尺度形态）",
    "quants_pullback_low_absorb_legacy_v1": "回调低吸候选池（龙吸水·需资金流）",
}

CASES = json.loads(
    (Path(__file__).parent / "fixtures/quants_core_cases.json").read_text(encoding="utf-8")
)["cases"]
IDS = {
    "v1": "quants_vcp_legacy_v1",
    "v3": "quants_cup_handle_legacy_v1",
    "v4": "quants_high_tight_flag_legacy_v1",
    "v5": "quants_pullback_low_absorb_legacy_v1",
}


def case_frame(case):
    frame = (
        pl.DataFrame(case["history"])
        .rename(
            {
                "trade_date": "date",
                **{
                    name + "_for_factor": name
                    for name in ("open", "high", "low", "close", "volume")
                },
            }
        )
        .with_columns(pl.col("date").str.to_date(), pl.lit("600000.SH").alias("symbol"))
    )
    return frame.with_columns(
        pl.col(name).cast(pl.Float64) for name in ("open", "high", "low", "close", "volume")
    )


def case_market(frame):
    return build_market_data_matrix(
        frame,
        field_columns=[
            c for c in ("net_mf_amount", "pct_chg", "ma10", "vol_ma20") if c in frame.columns
        ],
    )


@pytest.mark.parametrize("kind", ["cup", "pullback"])
@pytest.mark.parametrize("field,value", [("open", np.nan), ("low", 0), ("volume", 0)])
def test_long_history_validation_is_not_lost_after_420_bars(monkeypatch, kind, field, value):
    from app.strategy.builtin import _quants_legacy_patterns as patterns

    # Isolate the shared validity gate from the shape detectors.
    monkeypatch.setattr(patterns, "cup_detect", lambda *args: {"status": "executable"})
    monkeypatch.setattr(patterns, "pullback_detect", lambda *args: {"status": "executable"})
    frame = pl.DataFrame(
        {
            "date": [date(2020, 1, 1) + timedelta(days=i) for i in range(500)],
            "symbol": ["600000.SH"] * 500,
            **{
                name: [10.0] * 500
                for name in ("open", "high", "low", "close", "volume", "net_mf_amount")
            },
        }
    )
    market = case_market(frame)
    strategy = patterns.LegacyPatternStrategy(kind)
    assert strategy.compute_signals(market, {}).entry[-1, 0]
    market = case_market(
        frame.with_columns(
            pl.when(pl.col("date") == date(2020, 1, 1))
            .then(value)
            .otherwise(pl.col(field))
            .alias(field)
        )
    )
    assert strategy._detect(market, 0, 499, {})["reason"] == "invalid_history"
    assert not strategy.compute_signals(market, {}).entry.any()


def test_v2_is_hidden_but_compatibility_id_survives():
    engine = StrategyEngine([BUILTIN])
    assert "quants_growth_trend_legacy_v1" not in {row["id"] for row in engine.list_strategies()}
    assert engine.get("quants_growth_trend_legacy_v1") is not None


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case"])
def test_source_examples_preserve_core_pattern_and_entry_meaning(case):
    engine = StrategyEngine([BUILTIN])
    strategy = engine.get(IDS[case["strategy"]]).matrix_strategy
    frame = case_frame(case)
    market = case_market(frame)
    params = {"trend_filter": False, "rs_min": 0}
    signals, rows = strategy.screen_snapshot(market, params, market.shape[0] - 1)
    expected = case["reference"]
    assert bool(rows) == expected["valid"]
    if expected["valid"]:
        row = rows["600000.SH"]
        status = row.get("vcp_status", row.get("entry_status"))
        assert status == expected["status"]
        assert row.get("vcp_pivot", row.get("primary_trigger_price")) == pytest.approx(
            expected["pivot"], abs=1e-4
        )
        assert bool(signals.entry[-1, 0]) == (expected["status"] == "executable")
    else:
        assert not signals.entry[-1, 0]


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["reference"]["valid"]], ids=lambda c: c["case"]
)
def test_snapshot_history_and_future_prefix_are_consistent(case):
    strategy = StrategyEngine([BUILTIN]).get(IDS[case["strategy"]]).matrix_strategy
    frame = case_frame(case)
    params = {"trend_filter": False, "rs_min": 0}
    full = strategy.compute_signals(case_market(frame), params)
    for length in (len(frame) - 1, len(frame)):
        market = case_market(frame.head(length))
        prefix = strategy.compute_signals(market, params)
        snapshot, _ = strategy.screen_snapshot(market, params, length - 1)
        np.testing.assert_array_equal(prefix.entry, full.entry[:length])
        np.testing.assert_array_equal(snapshot.entry[-1], prefix.entry[-1])
    # Another asset's extra trading date must not turn alignment padding into a bar.
    peer = frame.with_columns(pl.lit("000001.SZ").alias("symbol"))
    extra = peer.head(1).with_columns(pl.lit(date(2025, 12, 31)).alias("date"))
    combined = case_market(pl.concat([extra, peer, frame]))
    _, aligned = strategy.screen_snapshot(combined, params, combined.shape[0] - 1)
    _, single = strategy.screen_snapshot(case_market(frame), params, len(frame) - 1)
    assert aligned.get("600000.SH") == single.get("600000.SH")


def test_pullback_missing_data_reports_unavailable():
    frame = case_frame(next(c for c in CASES if c["strategy"] == "v5")).drop("net_mf_amount")
    strategy = StrategyEngine([BUILTIN]).get(IDS["v5"]).matrix_strategy
    with pytest.raises(ValueError, match="net_mf_amount"):
        strategy.screen_snapshot(case_market(frame), {}, len(frame) - 1)


def test_pullback_declares_money_flow_and_is_hidden_until_data_is_available():
    engine = StrategyEngine([BUILTIN])
    public_ids = {row["id"] for row in engine.list_strategies()}
    strategy = engine.get(IDS["v5"])
    assert IDS["v5"] not in public_ids
    assert "net_mf_amount" in strategy.matrix_strategy.required_fields()


def test_vcp_research_variants_are_hidden_but_ids_survive():
    engine = StrategyEngine([BUILTIN])
    public_ids = {row["id"] for row in engine.list_strategies()}
    all_ids = {row["id"] for row in engine.list_strategies(include_research=True)}
    hidden = {"quants_vcp", "vcp_breakout", "vcp_recovery_breakout"}
    assert hidden.isdisjoint(public_ids)
    assert hidden <= all_ids


def test_real_names_and_completed_daily_contract():
    engine = StrategyEngine([BUILTIN])
    assert not engine.load_errors()
    for strategy_id, name in NAMES.items():
        meta = engine.get(strategy_id).meta
        assert meta["name"] == name
        assert meta["completed_daily_only"] is True
        assert meta["realtime_supported"] is False


def test_missing_money_flow_is_not_replaced_by_price_volume():
    close = np.array([100.0, 107.0] + [107.2] * 9 + [107.3])
    volume = np.array([100.0, 300.0] + [40.0] * 10)
    result = pullback_detect(close, close + 1, close - 1, close, volume, {})
    assert not result["valid"]
    assert result["reason"] == "money_flow_missing"


def test_invalid_patterns_are_not_screener_candidates():
    engine = StrategyEngine([BUILTIN])
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 30,
            "date": pl.date_range(pl.date(2026, 1, 1), pl.date(2026, 1, 30), eager=True),
            "open": [10.0] * 30,
            "high": [10.1] * 30,
            "low": [9.9] * 30,
            "close": [10.0] * 30,
            "volume": [1000.0] * 30,
        }
    )
    market = build_market_data_matrix(frame)
    for strategy_id in (
        "quants_cup_handle_legacy_v1",
        "quants_high_tight_flag_legacy_v1",
    ):
        strategy = engine.get(strategy_id).matrix_strategy
        signals, candidates = strategy.screen_snapshot(market, {}, 29)
        assert candidates == {}
        assert not signals.entry.any()


def test_cup_warmup_covers_extended_scale():
    strategy = StrategyEngine([BUILTIN]).get("quants_cup_handle_legacy_v1").matrix_strategy
    assert strategy.required_warmup_bars({}) >= 420
