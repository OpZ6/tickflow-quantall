from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from app.quantx_data.advanced import (
    CARD_KEYS,
    _anomaly_calendar,
    _density,
    _detect_ad_divergences,
    _gini_lorenz,
    _industry_correlation,
    _mainline_waterfall,
    _promotion_funnel,
    _rotation_clock,
    _sector_diffusion,
    _state_transition,
    _stock_returns,
    _sunburst,
    _theme_river,
    _turnover_lorenz,
    build_advanced_snapshot,
)


def test_gini_lorenz_is_bounded_and_ends_at_one() -> None:
    result = _gini_lorenz([1.0, 2.0, 7.0])

    assert 0 < result["gini"] < 1
    assert result["points"][0] == {"population_pct": 0.0, "amount_pct": 0.0}
    assert result["points"][-1] == {"population_pct": 100.0, "amount_pct": 100.0}


def test_turnover_lorenz_adds_previous_and_trailing_period_baselines() -> None:
    days = [date(2026, 8, 26), date(2026, 8, 27), date(2026, 8, 28)]
    frame = pl.DataFrame(
        {
            "date": [day for day in days for _ in range(2)],
            "amount": [1.0, 9.0, 2.0, 8.0, 5.0, 5.0],
        }
    )

    result = _turnover_lorenz(frame, days[-1], period_days=20)

    assert result["gini"] == 0.0
    assert result["previous"]["date"] == "2026-08-27"
    assert result["previous"]["gini"] == 0.3
    assert result["period_mean"]["days"] == 2
    assert result["period_mean"]["start_date"] == "2026-08-26"
    assert result["period_mean"]["end_date"] == "2026-08-27"
    assert result["period_mean"]["gini"] == 0.35
    assert result["period_mean"]["points"][0] == {
        "population_pct": 0.0,
        "amount_pct": 0.0,
    }
    assert result["period_mean"]["points"][-1] == {
        "population_pct": 100.0,
        "amount_pct": 100.0,
    }


def test_stock_returns_prefers_repository_computed_turnover(tmp_path) -> None:
    days = [date(2026, 8, 27), date(2026, 8, 28)]
    persisted = pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "date": [days[0]],
            "close": [10.0],
            "amount": [100.0],
            "turnover_rate": [None],
        },
        schema_overrides={"turnover_rate": pl.Float64},
    )
    for day in days:
        target = tmp_path / "kline_daily_enriched" / f"date={day.isoformat()}"
        target.mkdir(parents=True)
        persisted.with_columns(pl.lit(day).cast(pl.Date).alias("date")).write_parquet(
            target / "part.parquet"
        )

    repository_frame = pl.DataFrame(
        {
            "symbol": ["600000.SH", "600000.SH"],
            "date": days,
            "close": [10.0, 11.0],
            "amount": [100.0, 120.0],
            "turnover_rate": [1.5, 1.8],
        }
    )

    class Repository:
        def get_enriched_range(self, start, end, *, columns):
            assert (start, end) == (days[0], days[-1])
            assert set(columns) == {
                "symbol",
                "date",
                "close",
                "amount",
                "turnover_rate",
            }
            return repository_frame

    result = _stock_returns(tmp_path, days[-1], repo=Repository())

    assert result["turnover_rate"].to_list() == [1.5, 1.8]
    assert result["return"][0] is None
    assert result["return"][1] == pytest.approx(0.1)


def test_state_transition_normalizes_each_non_empty_row() -> None:
    frame = pl.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "state": ["weak", "range", "weak"],
        }
    )

    result = _state_transition(frame)
    weak_row = result["matrix"][result["states"].index("weak")]
    range_row = result["matrix"][result["states"].index("range")]

    assert sum(weak_row) == 100.0
    assert sum(range_row) == 100.0
    assert result["visual_max"] == 50.0


def test_sector_diffusion_exposes_level_and_ma_views() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 27), date(2026, 8, 28)] * 2,
            "dimension": ["sw_level1", "sw_level1", "sw_level2", "sw_level2"],
            "sector_name": ["电子", "电子", "半导体", "半导体"],
            "above_ma5_pct": [60.0, 70.0, 50.0, 55.0],
            "above_ma10_pct": [50.0, 60.0, 40.0, 45.0],
            "above_ma20_pct": [40.0, 50.0, 30.0, 35.0],
        }
    )

    result = _sector_diffusion(frame)

    assert set(result["views"]) == {"sw_level1", "sw_level2"}
    assert set(result["views"]["sw_level2"]["metrics"]) == {"5", "10", "20"}
    assert result["views"]["sw_level2"]["dates"] == ["2026-08-27", "2026-08-28"]
    assert result["views"]["sw_level2"]["metrics"]["5"] == [[50.0, 55.0]]


def test_theme_river_preserves_rank_and_missing_days() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 28)],
            "theme_name": ["机器人", "机器人", "创新药"],
            "rank": [2, 1, 3],
        }
    )

    result = _theme_river(frame)

    robot = result["themes"].index("机器人")
    medicine = result["themes"].index("创新药")
    assert result["values"][robot] == [2.0, 1.0]
    assert result["values"][medicine] == [None, 3.0]
    assert result["metric"] == "rank"


def test_theme_river_uses_one_rank_source_instead_of_mixing_scales() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 27)] * 2 + [date(2026, 8, 28)] * 2,
            "theme_name": ["机器人", "机器人", "机器人", "机器人"],
            "rank": [8, 1, 6, 1],
            "source": ["ths_hot", "deepq", "ths_hot", "deepq"],
        }
    )

    result = _theme_river(frame)

    assert result["source"] == "ths_hot"
    assert result["values"] == [[8.0, 6.0]]


def test_promotion_ladder_includes_first_board_seal_and_all_observed_heights() -> None:
    ladder = pl.DataFrame(
        {
            "trade_date": [
                date(2026, 8, 26), date(2026, 8, 26), date(2026, 8, 26),
                date(2026, 8, 27), date(2026, 8, 27), date(2026, 8, 27), date(2026, 8, 27),
                date(2026, 8, 28), date(2026, 8, 28), date(2026, 8, 28),
            ],
            "symbol": ["A", "B", "H", "A", "B", "H", "N", "A", "H", "Y"],
            "board_height": [1, 2, 6, 2, 3, 7, 1, 3, 8, 1],
        }
    )
    events = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 27), date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 28), date(2026, 8, 28), date(2026, 8, 28)],
            "symbol": ["N", "X", "Y", "N", "Z", "W"],
            "event_type": ["limit_up", "broken_board", "limit_up", "broken_board", "broken_board", "broken_board"],
            "board_height": [1, None, 1, None, None, 2],
        },
        schema_overrides={"board_height": pl.UInt32},
    )

    result = _promotion_funnel(ladder, events)

    first_board = result["stages"][0]
    assert first_board == {
        "name": "0→1 首板封板",
        "pool": 4,
        "promoted": 2,
        "failed": 2,
        "rate": 50.0,
        "basis": "same_day_seal",
    }
    assert next(row for row in result["stages"] if row["name"] == "1→2")['rate'] == 50.0
    assert next(row for row in result["stages"] if row["name"] == "7→8")['rate'] == 100.0
    assert result["max_observed_board"] == 8
    assert result["default_view"] == "current"
    assert result["baseline"]["sample_days"] == 2
    assert result["baseline"]["stages"] == result["stages"]

    current = result["views"]["current"]
    assert current["label"] == "当天"
    assert current["start_date"] == "2026-08-28"
    assert current["end_date"] == "2026-08-28"
    assert current["sample_days"] == 1
    current_first = next(row for row in current["stages"] if row["name"] == "0→1 首板封板")
    current_second = next(row for row in current["stages"] if row["name"] == "1→2")
    assert (current_first["pool"], current_first["promoted"], current_first["rate"]) == (2, 1, 50.0)
    assert (current_second["pool"], current_second["promoted"], current_second["rate"]) == (1, 0, 0.0)

    five_day = result["views"]["5"]
    assert five_day["label"] == "5日均值"
    assert five_day["sample_days"] == 2
    assert next(row for row in five_day["stages"] if row["name"] == "1→2")["rate"] == 50.0
    assert result["views"]["20"]["sample_days"] == 2


def test_anomaly_calendar_keeps_recent_weekdays_only() -> None:
    frame = pl.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 8, 28), date(2026, 8, 29)],
            "state": ["range", "strong", "strong"],
            "index_pct": [0.0, 0.01, 0.02],
            "up_count": [1000, 2000, 2500],
        }
    )

    result = _anomaly_calendar(frame)

    assert [row["date"] for row in result["records"]] == [
        "2026-01-01",
        "2026-08-28",
    ]


def test_ad_divergence_marks_sustained_direction_disagreement() -> None:
    dates = [f"2026-08-{day:02d}" for day in range(1, 9)]
    divergences = _detect_ad_divergences(
        dates,
        [100, 90, 80, 70, 60, 50, 40, 30],
        [100, 100, 100, 100, 100, 101, 102, 103],
        window=5,
    )

    assert divergences == [
        {
            "start_date": "2026-08-01",
            "end_date": "2026-08-08",
            "type": "bearish",
            "label": "指数强、广度弱",
        }
    ]


def test_sunburst_merges_stocks_into_second_level() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 28)] * 2,
            "theme_name": ["机器人", "机器人"],
            "board_height": [2, 2],
            "name": ["甲公司", "乙公司"],
            "symbol": ["000001.SZ", "000002.SZ"],
        }
    )

    result = _sunburst(frame, date(2026, 8, 28))

    level = result["children"][0]["children"][0]
    assert "children" not in level
    assert level["value"] == 2
    assert level["stocks"] == ["甲公司", "乙公司"]


def test_density_includes_zero_count_cells() -> None:
    returns = pl.DataFrame(
        {
            "date": [date(2026, 8, 28)],
            "return": [0.01],
            "turnover_rate": [2.5],
        }
    )

    result = _density(returns, date(2026, 8, 28))

    assert len(result["values"]) == len(result["x_bins"]) * len(result["y_bins"])
    assert any(row[2] == 0 for row in result["values"])


def test_industry_correlation_exposes_level_views() -> None:
    days = [date(2026, 8, value) for value in range(24, 29)]
    frame = pl.DataFrame(
        {
            "date": days * 4,
            "dimension": ["industry_level1"] * 10 + ["industry_level2"] * 10,
            "industry": (["一级甲"] * 5 + ["一级乙"] * 5 + ["二级甲"] * 5 + ["二级乙"] * 5),
            "return": [0.01, 0.02, 0.0, 0.03, 0.01] * 4,
        }
    )

    result = _industry_correlation(frame)

    assert set(result["views"]) == {"industry_level1", "industry_level2"}
    assert set(result["views"]["industry_level2"]["industries"]) == {"二级甲", "二级乙"}
    rankings = result["views"]["industry_level2"]["pair_rankings"]
    assert len(rankings["highest"]) == 1
    assert {rankings["highest"][0]["left"], rankings["highest"][0]["right"]} == {
        "二级甲",
        "二级乙",
    }
    assert rankings["highest"][0]["correlation"] == 1.0
    assert rankings["highest"][0]["sample_days"] == 5
    assert rankings["lowest"] == rankings["highest"]


def test_rotation_clock_uses_cross_sectional_rps() -> None:
    days = [date(2026, 8, value) for value in range(19, 29)]
    rows = []
    for index, name in enumerate(("行业甲", "行业乙", "行业丙")):
        for day_index, day in enumerate(days):
            rows.append(
                {
                    "date": day,
                    "dimension": "industry_level1",
                    "industry": name,
                    "return": (index - 1) * 0.01 + day_index * index * 0.001,
                }
            )
    result = _rotation_clock(pl.DataFrame(rows))

    assert result["metric"] == "cross_sectional_rps"
    assert min(row["momentum"] for row in result["points"]) < 0
    assert max(row["momentum"] for row in result["points"]) > 0


def test_mainline_waterfall_exposes_every_ranked_mainline(tmp_path) -> None:
    target = tmp_path / "mainline_history"
    target.mkdir()
    pl.DataFrame(
        {
            "date": [date(2026, 8, 28)] * 3,
            "kind": ["concept"] * 3,
            "member": ["穿戴设备", "机器人", "消费电子"],
            "limit_up_count": [9, 7, 5],
            "max_boards": [4, 6, 3],
            "rungs_filled": [3, 4, 2],
            "ge2_count": [4, 5, 2],
            "leader_symbol": ["A", "B", "C"],
            "score": [88.0, 82.0, 55.0],
            "rank": [1, 2, 3],
        }
    ).write_parquet(target / "part.parquet")

    result = _mainline_waterfall(tmp_path, date(2026, 8, 28))

    assert result["focus"] == "穿戴设备"
    assert [row["focus"] for row in result["mainlines"]] == [
        "穿戴设备",
        "机器人",
        "消费电子",
    ]
    assert result["mainlines"][1]["leader_symbol"] == "B"
    assert result["mainlines"][1]["rank"] == 2
    assert {row["name"] for row in result["mainlines"][1]["components"]} == {
        "涨停广度",
        "连板高度",
        "梯队完整",
        "二板以上",
    }


def test_snapshot_has_exactly_the_fifteen_supported_cards(tmp_path) -> None:
    snapshot = build_advanced_snapshot(tmp_path, date(2026, 8, 28))

    assert snapshot["schema_version"] == "tickflow-quantx-advanced-v1"
    assert set(snapshot["cards"]) == set(CARD_KEYS)
    assert len(snapshot["cards"]) == 15
    assert "risk_transmission" not in snapshot["cards"]
    assert "cross_day_survival_sankey" not in snapshot["cards"]
    assert "leader_handoff_timeline" not in snapshot["cards"]
    assert all(card["status"] == "unavailable" for card in snapshot["cards"].values())
