from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.quantx_data.candidate_funnel import build_candidate_funnel_from_frames

DAY = date(2026, 9, 1)


def _prices(specs: dict[str, dict[str, float]]) -> pl.DataFrame:
    rows = []
    for symbol, spec in specs.items():
        for offset in range(25):
            close = spec.get("base", 10.0) + offset * spec.get("slope", 0.08)
            if offset == 24:
                close *= 1 + spec.get("pct", 0.0) / 100
            rows.append(
                {
                    "symbol": symbol,
                    "date": DAY - timedelta(days=24 - offset),
                    "open": close * (1 - spec.get("body", 0.01)),
                    "high": close * (1 + spec.get("wick", 0.015)),
                    "low": close * (1 - spec.get("low_wick", 0.01)),
                    "close": close,
                    "amount": 100_000_000.0 * spec.get("amount_ratio", 1.0),
                    "turnover_rate": spec.get("turnover", 4.0),
                }
            )
    return pl.DataFrame(rows)


def _candidates(items: list[dict[str, object]]) -> pl.DataFrame:
    rows = []
    for item in items:
        rows.append(
            {
                "trade_date": item.get("trade_date", DAY),
                "symbol": item["symbol"],
                "name": item.get("name", item["symbol"]),
                "exchange": item.get("exchange", "SZSE"),
                "candidate_type": item.get("candidate_type", "deterministic_rule_screen"),
                "priority": item.get("priority", "rule"),
                "score": item.get("score"),
                "pct_chg": item.get("pct_chg"),
                "industry": item.get("industry", ""),
                "rules_matched": item.get("rules_matched", []),
                "included": True,
            }
        )
    return pl.DataFrame(rows)


def _state(*, heat: float, short: float, trend: float, up_ratio: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "market_heat_score": [heat],
            "short_term_sentiment_score": [short],
            "trend_sentiment_score": [trend],
            "up_ratio_pct": [up_ratio],
            "seal_rate_pct": [80.0],
            "crash_triggered": [False],
            "ebb_signal_count": [0],
        }
    )


def _limits(symbols: list[str], *, board_height: int = 2) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": symbols,
            "event_type": ["limit_up"] * len(symbols),
            "board_height": [board_height] * len(symbols),
            "limit_reason": ["题材催化"] * len(symbols),
        }
    )


def _ladder(items: list[tuple[str, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [item[0] for item in items],
            "theme_name": [item[1] for item in items],
            "board_height": [item[2] for item in items],
            "interpretation": ["产业逻辑"] * len(items),
            "turnover_pct": [6.0] * len(items),
        }
    )


def test_final_pool_is_capped_and_theme_is_diversified() -> None:
    symbols = [f"0000{i:02d}" for i in range(12)]
    result = build_candidate_funnel_from_frames(
        DAY,
        _state(heat=72, short=75, trend=68, up_ratio=63),
        _candidates([{"symbol": symbol, "pct_chg": 9.9} for symbol in symbols]),
        _limits(symbols),
        _ladder([(symbol, "同一题材" if index < 5 else f"题材{index}", 2) for index, symbol in enumerate(symbols)]),
        _prices({symbol: {"pct": 9.9} for symbol in symbols}),
    )

    assert len(result["candidates"]) <= 10
    assert sum(row["theme"] == "同一题材" for row in result["candidates"]) <= 2


def test_strong_market_prefers_tradable_front_row() -> None:
    result = build_candidate_funnel_from_frames(
        DAY,
        _state(heat=75, short=78, trend=70, up_ratio=65),
        _candidates(
            [
                {"symbol": "000001", "pct_chg": 9.8},
                {"symbol": "000002", "candidate_type": "new_high_100d", "pct_chg": -1.0},
            ]
        ),
        _limits(["000001"], board_height=3),
        _ladder([("000001", "主线", 3)]),
        _prices({"000001": {"pct": 9.8, "turnover": 8, "wick": 0.0}, "000002": {"pct": -1.0}}),
    )

    assert result["regime"]["key"] == "strong_attack"
    assert result["candidates"][0]["code"] == "000001"
    assert result["candidates"][0]["setup_type"] == "momentum_leader"


def test_weak_market_can_select_slightly_down_healthy_pullback() -> None:
    history = _candidates(
        [
            {"symbol": "000010", "trade_date": DAY - timedelta(days=3), "pct_chg": 8.0},
            {"symbol": "000011", "pct_chg": 9.9},
        ]
    )
    result = build_candidate_funnel_from_frames(
        DAY,
        _state(heat=32, short=35, trend=42, up_ratio=31),
        history,
        _limits(["000011"]),
        _ladder([("000011", "孤立涨停", 2)]),
        _prices({"000010": {"pct": -1.2, "slope": 0.12}, "000011": {"pct": 9.9}}),
    )

    assert result["regime"]["key"] == "weak_defense"
    assert result["candidates"][0]["code"] == "000010"
    assert result["candidates"][0]["setup_type"] == "healthy_pullback"


def test_one_word_and_twenty_percent_closed_limit_are_anchors_not_finalists() -> None:
    candidates = _candidates(
        [
            {"symbol": "000020", "pct_chg": 10.0},
            {"symbol": "300020", "pct_chg": 20.0},
            {"symbol": "000021", "candidate_type": "new_high_100d", "pct_chg": 1.0},
        ]
    )
    prices = _prices(
        {
            "000020": {"pct": 10.0, "wick": 0.0, "low_wick": 0.0, "body": 0.0, "turnover": 0.1},
            "300020": {"pct": 20.0},
            "000021": {"pct": 1.0},
        }
    )
    result = build_candidate_funnel_from_frames(
        DAY,
        _state(heat=70, short=72, trend=65, up_ratio=60),
        candidates,
        _limits(["000020", "300020"]),
        _ladder([("000020", "主线", 2), ("300020", "主线", 2)]),
        prices,
    )

    finalist_codes = {row["code"] for row in result["candidates"]}
    assert "000020" not in finalist_codes
    assert "300020" not in finalist_codes
    anchors = {row["code"]: row for row in result["market_anchors"]}
    assert anchors["000020"]["action_status"] == "context_only"
    assert anchors["300020"]["action_status"] == "wait_divergence"


def test_same_input_is_deterministic() -> None:
    args = (
        DAY,
        _state(heat=55, short=52, trend=58, up_ratio=51),
        _candidates([{"symbol": "000030", "candidate_type": "new_high_100d", "pct_chg": 2.0}]),
        pl.DataFrame(),
        pl.DataFrame(),
        _prices({"000030": {"pct": 2.0}}),
    )
    assert build_candidate_funnel_from_frames(*args) == build_candidate_funnel_from_frames(*args)
