from __future__ import annotations

from datetime import date

import polars as pl

from app.quantx_data.advanced import (
    CARD_KEYS,
    _anomaly_calendar,
    _density,
    _detect_ad_divergences,
    _gini_lorenz,
    _industry_correlation,
    _rotation_clock,
    _sector_diffusion,
    _state_transition,
    _sunburst,
    _theme_river,
    build_advanced_snapshot,
)


def test_gini_lorenz_is_bounded_and_ends_at_one() -> None:
    result = _gini_lorenz([1.0, 2.0, 7.0])

    assert 0 < result["gini"] < 1
    assert result["points"][0] == {"population_pct": 0.0, "amount_pct": 0.0}
    assert result["points"][-1] == {"population_pct": 100.0, "amount_pct": 100.0}


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


def test_snapshot_has_exactly_the_sixteen_supported_cards(tmp_path) -> None:
    snapshot = build_advanced_snapshot(tmp_path, date(2026, 8, 28))

    assert snapshot["schema_version"] == "tickflow-quantx-advanced-v1"
    assert set(snapshot["cards"]) == set(CARD_KEYS)
    assert len(snapshot["cards"]) == 16
    assert "cross_day_survival_sankey" not in snapshot["cards"]
    assert "leader_handoff_timeline" not in snapshot["cards"]
    assert all(card["status"] == "unavailable" for card in snapshot["cards"].values())
