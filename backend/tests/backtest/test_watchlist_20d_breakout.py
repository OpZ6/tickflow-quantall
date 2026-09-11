import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.engine import MatcherConfig
from app.backtest.matrix import build_market_data_matrix
from app.strategy.builtin._quants_vcp import fresh_20d_breakout_opportunity_mask

SEQ2_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_leader_universe_market_gate.py"
SEQ3_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_watchlist_20d_breakout.py"
SPEC = importlib.util.spec_from_file_location("research_leader_universe_market_gate", SEQ2_PATH)
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


def test_date_ew_is_mean_of_daily_means_not_pooled() -> None:
    mask = np.array([[True, True, False], [True, False, False]])
    values = np.array([[0.10, -0.04, 9.0], [0.16, 9.0, 9.0]])
    date_ew = MODULE.date_ew_from_mask(mask, values)
    pooled = (0.10 + -0.04 + 0.16) / 3
    assert date_ew == pytest.approx(0.095)
    assert date_ew != pytest.approx(pooled)


def test_same_day_untriggered_is_watchlist_not_breakout() -> None:
    gate = np.array([True, True, False])
    eligible = np.ones((3, 4), dtype=bool)
    rs = np.array(
        [
            [True, True, True, False],
            [True, True, False, True],
            [True, True, True, True],
        ]
    )
    watch = MODULE.watch_list_mask(gate, eligible, rs)
    breakout = np.array(
        [
            [True, False, True, True],
            [False, True, True, False],
            [True, False, False, True],
        ]
    )
    selected, untriggered = MODULE.triggered_and_untriggered(watch, breakout)
    assert selected[0].tolist() == [True, False, True, False]
    assert untriggered[0].tolist() == [False, True, False, False]
    assert selected[1].tolist() == [False, True, False, False]
    assert untriggered[1].tolist() == [True, False, False, True]
    assert not selected[2].any()
    assert not untriggered[2].any()
    summary = MODULE.summarize_window(
        10,
        selected,
        untriggered,
        {
            "complete": np.ones_like(selected, dtype=bool),
            "net": np.zeros(selected.shape),
            "net_excess": np.array(
                [
                    [0.02, -0.01, 0.03, 9.0],
                    [0.00, 0.04, 9.0, 9.0],
                    [9.0, 9.0, 9.0, 9.0],
                ]
            ),
        },
        [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)],
        date(2020, 1, 1),
        date(2020, 12, 31),
        control_tag="watchlist_no_breakout",
    )
    assert summary["same_day_unselected"] == "watchlist_no_breakout"
    assert summary["same_day_unselected"] != "unavailable_not_in_frozen_inputs"


def test_fresh_20d_high_reuses_shipped_mask_and_cooldown() -> None:
    closes = [10.0] * 20 + [11.0, 12.0] + [12.0] * 18 + [13.0]
    sessions = [date(2020, 1, 2) + timedelta(days=i) for i in range(len(closes))]
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(closes),
            "date": sessions,
            "open": closes,
            "high": closes,
            "low": [value - 0.1 for value in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
            "amount": [30_000_000.0] * len(closes),
        }
    )
    market = build_market_data_matrix(frame, field_columns={"amount"})
    shipped = fresh_20d_breakout_opportunity_mask(market)
    got = MODULE.fresh_20d_breakout_opportunity_mask(market)
    np.testing.assert_array_equal(got, shipped)
    assert np.flatnonzero(got[:, 0]).tolist() == [20, 40]
    watch = np.ones(market.shape, dtype=bool)
    selected, untriggered = MODULE.triggered_and_untriggered(watch, got)
    np.testing.assert_array_equal(selected, got)
    assert untriggered[20, 0] is np.False_ or not untriggered[20, 0]
    assert untriggered[21, 0]


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
    symbols = list(market.symbols)
    by_symbol = {symbol: i for i, symbol in enumerate(symbols)}
    assert ten["complete"][0, by_symbol["600000.SH"]]
    assert not ten["complete"][0, by_symbol["600001.SH"]]
    assert not ten["complete"][0, by_symbol["000001.SZ"]]
    gross = ten["gross"][0, by_symbol["600000.SH"]]
    net = ten["net"][0, by_symbol["600000.SH"]]
    assert net < gross
    config = MatcherConfig(
        matching="open_t+1",
        commission_pct=0.0003,
        slippage_bps=10.0,
        stamp_tax_policy="a_share_historical",
    )
    exit_day = sessions[1 + 10]
    expected = MODULE.net_round_trip(gross, config.buy_cost_pct(), config.sell_cost_pct(exit_day))
    assert net == pytest.approx(expected)


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


def test_committed_reclaim_analysis_beats_same_day_untriggered() -> None:
    import json

    path = Path(__file__).resolve().parents[3] / "docs" / "research" / "watchlist-ma20-reclaim-v1-analysis.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["selector"]["trigger"] == "ma20_reclaim"
    assert payload["selector"]["pattern_detector"] is None
    assert payload["training_end"] == "2022-12-31"
    for hold in ("10", "20"):
        row = payload["windows"][hold]
        assert row["date_ew_vs_unselected"] >= 0
        assert row["same_day_unselected"] == "watchlist_no_breakout"
        assert row["labels_past_training_end"] is False
    windows = {
        "10": {"date_ew_vs_unselected": payload["windows"]["10"]["date_ew_vs_unselected"]},
        "20": {"date_ew_vs_unselected": payload["windows"]["20"]["date_ew_vs_unselected"]},
    }
    assert MODULE.trigger_verdict(windows) == "pass_keep_breakout_trigger"


def test_playbook_one_plan_is_reclaim_versus_same_day_untriggered() -> None:
    text = (
        Path(__file__).resolve().parents[3] / "docs" / "research" / "right-side-playbook-v1.md"
    ).read_text(encoding="utf-8")
    assert "MA20 收回" in text
    assert "突破：停止" in text
    assert "假突破 / 无需求：停止" in text
    assert "+0.16%" in text
    assert "+0.40%" in text
    assert "只对照一件事" in text
    assert "同日名单内不收回" in text
    assert "不进入" in text


def test_selector_source_has_no_pattern_detector() -> None:
    source = SEQ3_PATH.read_text(encoding="utf-8") + SEQ2_PATH.read_text(encoding="utf-8")
    assert "fresh_20d_breakout_opportunity_mask" in source
    assert "watch_list_mask" in source
    seq3 = SEQ3_PATH.read_text(encoding="utf-8")
    assert "detect(" not in seq3
    assert "cup_handle" not in seq3
    assert "high_tight_flag" not in seq3
    assert "vcp_structure" not in seq3


def test_close_above_prior_20_high_has_no_cooldown() -> None:
    closes = [10.0] * 20 + [11.0, 12.0] + [12.0] * 18 + [13.0]
    sessions = [date(2020, 1, 2) + timedelta(days=i) for i in range(len(closes))]
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(closes),
            "date": sessions,
            "open": closes,
            "high": closes,
            "low": [value - 0.1 for value in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
            "amount": [30_000_000.0] * len(closes),
        }
    )
    market = build_market_data_matrix(frame, field_columns={"amount"})
    fresh = MODULE.fresh_20d_breakout_opportunity_mask(market)
    rolling = MODULE.close_above_prior_20_high_mask(market)
    assert np.flatnonzero(fresh[:, 0]).tolist() == [20, 40]
    assert rolling[20, 0] and rolling[21, 0]
    assert not fresh[21, 0]


def test_inside_bar_breakout_needs_enclosed_prior_bar() -> None:
    rows = []
    sessions = [date(2020, 1, 2) + timedelta(days=i) for i in range(4)]
    bars = [
        (10.0, 9.0, 9.5),
        (9.8, 9.2, 9.4),
        (10.2, 9.3, 10.1),
        (10.0, 9.0, 9.1),
    ]
    for day, (high, low, close) in zip(sessions, bars, strict=True):
        rows.append(
            {
                "symbol": "600000.SH",
                "date": day,
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000.0,
                "amount": 30_000_000.0,
            }
        )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})
    mask = MODULE.inside_bar_breakout_mask(market)
    assert mask[:, 0].tolist() == [False, False, True, False]


def test_close_above_prior_bar_high_does_not_need_inside_bar() -> None:
    rows = []
    sessions = [date(2020, 1, 2) + timedelta(days=i) for i in range(3)]
    bars = [(10.0, 9.0, 9.5), (10.5, 8.5, 10.2), (10.0, 9.0, 9.2)]
    for day, (high, low, close) in zip(sessions, bars, strict=True):
        rows.append(
            {
                "symbol": "600000.SH",
                "date": day,
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000.0,
                "amount": 30_000_000.0,
            }
        )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})
    prior = MODULE.close_above_prior_bar_high_mask(market)
    inside = MODULE.inside_bar_breakout_mask(market)
    assert prior[:, 0].tolist() == [False, True, False]
    assert not inside[1, 0]


def test_ma20_reclaim_requires_prior_close_below_mean() -> None:
    closes = [10.0] * 20 + [9.0, 11.0]
    sessions = [date(2020, 1, 2) + timedelta(days=i) for i in range(len(closes))]
    frame = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(closes),
            "date": sessions,
            "open": closes,
            "high": [c + 0.1 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
            "amount": [30_000_000.0] * len(closes),
        }
    )
    market = build_market_data_matrix(frame, field_columns={"amount"})
    mask = MODULE.ma20_reclaim_mask(market)
    assert not mask[20, 0]
    assert mask[21, 0]


def test_no_gap_up_entry_skips_higher_next_open() -> None:
    rows = []
    sessions = [date(2020, 1, 2) + timedelta(days=i) for i in range(3)]
    opens = [10.0, 11.0, 10.0]
    closes = [10.0, 10.0, 10.0]
    for day, open_px, close in zip(sessions, opens, closes, strict=True):
        rows.append(
            {
                "symbol": "600000.SH",
                "date": day,
                "open": open_px,
                "high": max(open_px, close),
                "low": min(open_px, close) - 0.1,
                "close": close,
                "volume": 1_000_000.0,
                "amount": 30_000_000.0,
            }
        )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})
    mask = MODULE.no_gap_up_entry_mask(market)
    assert mask[0, 0] is np.False_ or not mask[0, 0]
    assert mask[1, 0]


def test_entry_filter_verdict_compares_to_same_trigger_baseline() -> None:
    treated = {"10": {"date_ew_net": 0.01}, "20": {"date_ew_net": 0.02}}
    baseline = {"10": {"date_ew_net": 0.01}, "20": {"date_ew_net": 0.03}}
    assert MODULE.entry_filter_verdict(treated, baseline) == "fail_stop_entry_filter"
    treated["20"]["date_ew_net"] = 0.03
    assert MODULE.entry_filter_verdict(treated, baseline) == "pass_keep_entry_filter"


def test_two_bar_no_demand_cuts_flat_path() -> None:
    sessions = _sessions(16)
    rows = []
    for t, day in enumerate(sessions):
        price = 10.0 if t < 4 else 10.0 + (t - 3) * 0.5
        rows.append(
            {
                "symbol": "600000.SH",
                "date": day,
                "open": price,
                "high": price,
                "low": price - 0.05,
                "close": price,
                "volume": 1_000_000.0,
                "amount": 30_000_000.0,
                "raw_close": price,
            }
        )
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"raw_close", "amount"})
    calendar = MODULE.calendar_from_market(market)
    labeled = MODULE.label_signal_windows(market, calendar, training_end=date(2020, 12, 31))
    selected = np.zeros(market.shape, dtype=bool)
    selected[0, 0] = True
    overlaid = MODULE.overlay_two_bar_no_demand(market, calendar, labeled, selected)
    assert overlaid[10]["net"][0, 0] != labeled[10]["net"][0, 0]


def test_trigger_verdict_uses_spread_not_vs_market() -> None:
    windows = {
        "10": {"date_ew_vs_unselected": 0.001, "date_ew_net_excess": -0.01},
        "20": {"date_ew_vs_unselected": 0.0, "date_ew_net_excess": -0.02},
    }
    assert MODULE.trigger_verdict(windows) == "pass_keep_breakout_trigger"
    windows["20"]["date_ew_vs_unselected"] = -0.001
    assert MODULE.trigger_verdict(windows) == "fail_rewrite_breakout_event"
