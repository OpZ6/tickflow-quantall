from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.quantx_data.risk_radar import (
    ALL_A_INDEX, MARKET_INDICES, SENTIMENT_INDICES,
    build_risk_radar, index_ma10,
)
from app.services.index_sync import QUANTX_SENTIMENT_SYMBOLS, sync_quantx_sentiment_indices


def _indices(day_change: float) -> dict:
    values = {code: {"deviation_pct": -1.0, "change_pct": day_change} for code in MARKET_INDICES}
    values[ALL_A_INDEX] = {"deviation_pct": -1.0, "change_pct": day_change}
    for code, *_ in SENTIMENT_INDICES:
        values[code] = {"deviation_pct": -1.0, "change_pct": day_change}
    values["880823.SH"]["deviation_pct"] = 1.7
    return values


def _liquidity(day: date, today: float, baseline: float) -> list[dict]:
    return [
        {"trade_date": day - timedelta(days=offset), "total_amount_yi": baseline}
        for offset in range(5, 0, -1)
    ] + [{"trade_date": day, "total_amount_yi": today, "top5pct_amount_ratio_pct": 43.0}]


def test_index_ma10_uses_only_ten_completed_bars_and_requires_target_day():
    target = date(2026, 9, 29)
    bars = [{"date": target - timedelta(days=10 - index), "close": 100.0} for index in range(10)]
    bars[-1]["date"] = target
    bars.append({"date": target + timedelta(days=1), "close": 200.0})
    result = index_ma10(bars, target)
    assert result["ma10"] == 100.0
    assert result["deviation_pct"] == 0.0
    assert index_ma10(bars[:-2], target) is None


def test_four_dimensions_classify_two_contrasting_published_days():
    down_day = date(2026, 9, 28)
    stressed_indices = _indices(-2.73)
    stressed_indices["880699.SH"]["deviation_pct"] = -4.1
    stressed_indices["880880.SH"]["deviation_pct"] = 8.4
    stressed = build_risk_radar(
        down_day,
        breadth={"up_count": 896, "down_count": 4555, "flat_count": 105, "total_count": 5557, "up_ratio_pct": 16.12, "mean_up_pct": 1.94, "mean_down_pct": -3.12, "down_gt7_count": 410, "down_gt7_ratio_pct": 7.38},
        state={"limit_down_count": 56, "premium_rate_pct": -1.95, "advance_rate_pct": 13.5, "seal_rate_pct": 75.0},
        liquidity=_liquidity(down_day, 17167, 19494),
        ladder=[{"board_height": 1, "count": 26}, {"board_height": 2, "count": 3}, {"board_height": 3, "count": 3}, {"board_height": 5, "count": 1}],
        indices=stressed_indices,
    )
    assert stressed["headline"] == "普跌与接力亏损共振"
    assert [row["tone"] for row in stressed["dimensions"]] == ["red", "red", "amber", "amber"]
    assert [row["title"] for row in stressed["dimensions"]] == ["广度与尾部", "接力与封板", "量能与承接", "指数与趋势"]
    assert stressed["coverage"] == {"complete": 4, "total": 4}
    assert "4 板缺档" in stressed["summary"]
    assert len(stressed["dimensions"][0]["metrics"]) == 7
    assert "跌幅超过 7% 的个股占 7.38%" in stressed["summary"]
    assert {item["label"] for item in stressed["dimensions"][0]["metrics"]}.isdisjoint({"平盘", "未知"})
    assert all(
        metric["judgement"] and metric["judgement"] in stressed["summary"]
        for row in stressed["dimensions"] for metric in row["metrics"]
        if metric["tone"] in ("red", "amber")
    )
    assert len(stressed["dimensions"][3]["series"]) == 12
    stressed_trend = {item["label"]: item["tone"] for item in stressed["dimensions"][3]["metrics"]}
    assert stressed_trend["普通指数站上 MA10"] == "red"
    assert stressed_trend["龙头情绪"] == stressed_trend["题材效应"] == "red"

    recover_day = date(2026, 9, 29)
    recovering = build_risk_radar(
        recover_day,
        breadth={"up_count": 3457, "down_count": 1942, "flat_count": 155, "total_count": 5559, "up_ratio_pct": 62.19, "mean_up_pct": 1.84, "mean_down_pct": -1.36, "down_gt7_count": 38, "down_gt7_ratio_pct": 0.68},
        state={"limit_down_count": 10, "premium_rate_pct": 2.64, "advance_rate_pct": 30.3, "seal_rate_pct": 87.7},
        liquidity=_liquidity(recover_day, 14216, 18742),
        ladder=[{"board_height": 1, "count": 47}, {"board_height": 2, "count": 7}, {"board_height": 3, "count": 1}, {"board_height": 4, "count": 1}, {"board_height": 6, "count": 1}],
        indices=_indices(0.36),
        state_history=[{"trade_date": down_day, "up_ratio_pct": 16.12, "premium_rate_pct": -1.95, "advance_rate_pct": 13.5, "max_board": 5}],
    )
    assert recovering["headline"] == "广度与接力修复，量能继续收缩"
    assert [row["tone"] for row in recovering["dimensions"]] == ["green", "green", "amber", "amber"]
    assert "前日 13.5%" in recovering["counter_evidence"]
    recovering_liquidity = {item["label"]: item["tone"] for item in recovering["dimensions"][2]["metrics"]}
    assert recovering_liquidity["相对前 5 日"] == recovering_liquidity["较前日"] == "red"
    assert any(item["label"] == "平均跌幅" and item["value"] == "-1.36%" for item in recovering["dimensions"][0]["metrics"])
    assert all(
        metric["judgement"] and metric["judgement"] in recovering["summary"]
        for row in recovering["dimensions"] for metric in row["metrics"]
        if metric["tone"] in ("red", "amber")
    )


def test_relay_flags_height_below_four_without_a_separate_ladder_dimension():
    day = date(2026, 9, 29)
    result = build_risk_radar(
        day,
        breadth={"up_count": 3000, "down_count": 2000, "flat_count": 100, "total_count": 5100},
        state={"limit_down_count": 8, "premium_rate_pct": 1.0, "advance_rate_pct": 30.0, "seal_rate_pct": 85.0},
        liquidity=_liquidity(day, 10000, 10000),
        ladder=[{"board_height": 1, "count": 30}, {"board_height": 2, "count": 6}, {"board_height": 3, "count": 2}],
        indices=_indices(1.0),
    )
    assert [row["key"] for row in result["dimensions"]] == ["breadth", "relay", "liquidity", "trend"]
    assert result["dimensions"][1]["tone"] == "amber"
    assert "最高板 3 板，未达到 4 板" in result["summary"]


def test_four_normal_dimensions_have_no_triggered_judgements():
    day = date(2026, 9, 29)
    indices = _indices(1.0)
    for row in indices.values():
        row["deviation_pct"] = 1.0
    result = build_risk_radar(
        day,
        breadth={"up_count": 3000, "down_count": 2000, "flat_count": 100, "total_count": 5100},
        state={"limit_down_count": 8, "premium_rate_pct": 1.0, "advance_rate_pct": 30.0, "seal_rate_pct": 85.0},
        liquidity=_liquidity(day, 10000, 10000),
        ladder=[{"board_height": 1, "count": 30}, {"board_height": 3, "count": 2}, {"board_height": 4, "count": 1}],
        indices=indices,
    )
    assert [row["tone"] for row in result["dimensions"]] == ["green"] * 4
    assert result["summary"] == "四维条件未触发风险阈值。"


def test_single_mild_warning_keeps_dimension_green_and_judgement_visible():
    day = date(2026, 9, 29)
    indices = _indices(1.0)
    for row in indices.values():
        row["deviation_pct"] = 1.0
    liquidity = _liquidity(day, 8700, 10325)
    liquidity[-2]["total_amount_yi"] = 8700
    result = build_risk_radar(
        day,
        breadth={"up_count": 3000, "down_count": 2000, "total_count": 5100, "down_gt7_ratio_pct": 2.1},
        state={"limit_down_count": 8, "premium_rate_pct": -0.2, "advance_rate_pct": 30.0, "seal_rate_pct": 85.0},
        liquidity=liquidity,
        ladder=[{"board_height": 1, "count": 30}, {"board_height": 3, "count": 2}, {"board_height": 4, "count": 1}],
        indices=indices,
    )
    assert [row["tone"] for row in result["dimensions"]] == ["green"] * 4
    assert [row["status"] for row in result["dimensions"][:3]] == ["基本正常"] * 3
    assert result["headline"] == "四维整体正常，局部信号需留意"
    assert all(
        any(metric["tone"] == "amber" and metric["judgement"] in result["summary"] for metric in row["metrics"])
        for row in result["dimensions"][:3]
    )
    assert result["algorithm_version"] == "risk-radar-v3"


def test_deep_decliner_share_flags_breadth_even_when_more_stocks_rise():
    day = date(2026, 9, 29)
    result = build_risk_radar(
        day,
        breadth={"up_count": 3000, "down_count": 2000, "flat_count": 100, "total_count": 5100, "mean_up_pct": 2.0, "mean_down_pct": -2.0, "down_gt7_ratio_pct": 5.2},
        state={"limit_down_count": 8, "premium_rate_pct": 1.0, "advance_rate_pct": 30.0, "seal_rate_pct": 85.0},
        liquidity=_liquidity(day, 10000, 10000),
        ladder=[{"board_height": 1, "count": 30}, {"board_height": 3, "count": 2}, {"board_height": 4, "count": 1}],
        indices=_indices(1.0),
    )
    assert result["dimensions"][0]["tone"] == "red"
    assert "跌幅超过 7% 的个股占 5.20%" in result["summary"]


def test_missing_input_is_reported_without_a_false_normal_state():
    result = build_risk_radar(
        date(2026, 9, 29), breadth=None, state=None,
        liquidity=[], ladder=[], indices={},
    )
    assert result["headline"] == "风险画像数据待同步"
    assert len(result["missing"]) == 4
    assert all(row["tone"] is None for row in result["dimensions"])

    partial = build_risk_radar(
        date(2026, 9, 29),
        breadth={"up_count": 3000, "down_count": 2000, "flat_count": 100, "total_count": 5100},
        state={"limit_down_count": 8, "premium_rate_pct": 1.0, "advance_rate_pct": 30.0},
        liquidity=_liquidity(date(2026, 9, 29), 10000, 10000),
        ladder=[{"board_height": 1, "count": 30}, {"board_height": 2, "count": 6}, {"board_height": 3, "count": 2}],
        indices={code: value for code, value in _indices(1.0).items() if not code.startswith("880")},
    )
    assert partial["missing"] == ["通达信四情绪"]
    assert partial["headline"] == "风险画像数据待同步"


def test_tdx_sync_publishes_all_four_indices_only_with_target_day(monkeypatch):
    class Repo:
        def __init__(self):
            self.raw = None
            self.enriched = None
            self.refreshed = False

        def get_index_daily(self, *_args):
            return pl.DataFrame()

        def append_index_daily(self, frame):
            self.raw = frame

        def append_index_enriched(self, frame):
            self.enriched = frame

        def refresh_index_views(self):
            self.refreshed = True

    class Provider:
        symbols = list(QUANTX_SENTIMENT_SYMBOLS)

        def get_daily(self, symbols, _start, end, *, asset_type):
            assert symbols == list(QUANTX_SENTIMENT_SYMBOLS)
            assert asset_type == "index"
            return pl.DataFrame([
                {
                    "symbol": symbol, "date": end.date() - timedelta(days=offset),
                    "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                    "volume": 1000.0, "amount": 100000.0, "data_source": "tdx",
                }
                for symbol in self.symbols for offset in range(20)
            ])

        def close(self):
            pass

    monkeypatch.setattr("app.plugins.tdx.provider.availability", lambda: (True, "ok"))
    monkeypatch.setattr("app.plugins.tdx.provider.TdxProvider", Provider)
    end = date(2026, 9, 29)
    from datetime import datetime

    repo = Repo()
    assert sync_quantx_sentiment_indices(repo, end_date=datetime.combine(end, datetime.min.time())) == 80
    assert repo.raw.height == repo.enriched.height == 80
    assert repo.refreshed

    Provider.symbols = list(QUANTX_SENTIMENT_SYMBOLS[:-1])
    incomplete = Repo()
    with pytest.raises(RuntimeError, match="missing target-day bars"):
        sync_quantx_sentiment_indices(incomplete, end_date=datetime.combine(end, datetime.min.time()))
    assert incomplete.raw is None
