from __future__ import annotations

from datetime import date

import polars as pl

from app.quantx_data.advanced import (
    CARD_KEYS,
    _gini_lorenz,
    _state_transition,
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


def test_snapshot_has_exactly_the_sixteen_supported_cards(tmp_path) -> None:
    snapshot = build_advanced_snapshot(tmp_path, date(2026, 8, 28))

    assert snapshot["schema_version"] == "tickflow-quantx-advanced-v1"
    assert set(snapshot["cards"]) == set(CARD_KEYS)
    assert len(snapshot["cards"]) == 16
    assert "cross_day_survival_sankey" not in snapshot["cards"]
    assert "leader_handoff_timeline" not in snapshot["cards"]
    assert all(card["status"] == "unavailable" for card in snapshot["cards"].values())
