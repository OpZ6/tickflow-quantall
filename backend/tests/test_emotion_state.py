"""emotion_state 情绪算法测试。

验证从 QuantX computed.py 移植的情绪三件套 + 退潮/参与度/crash 算法正确性。
"""
from __future__ import annotations

import json

import pytest

from app.services.emotion_state import (
    _calc_crash_signals,
    _calc_ebb_risk_check,
    _calc_market_heat,
    _calc_participation_check,
    _calc_short_term_sentiment,
    _calc_trend_sentiment,
    _dx_fallback,
    _lerp_score,
    _max_board_from_ladder,
    _stretch_around_mid,
    _zone_for_score,
    compute,
)

# ---- 纯函数 ----

class TestLerpScore:
    def test_below_first_anchor(self):
        assert _lerp_score(-10, [(0, 5), (100, 95)]) == 5.0

    def test_above_last_anchor(self):
        assert _lerp_score(200, [(0, 5), (100, 95)]) == 95.0

    def test_midpoint(self):
        assert _lerp_score(50, [(0, 5), (100, 95)]) == pytest.approx(50.0)

    def test_multi_anchor_midpoint(self):
        result = _lerp_score(50, [(0, 0), (50, 50), (100, 100)])
        assert result == pytest.approx(50.0)

    def test_invalid_input(self):
        assert _lerp_score(None, [(0, 5), (100, 95)]) == 5.0

    def test_empty_anchors(self):
        assert _lerp_score(50, []) == 0.0


class TestStretchAroundMid:
    def test_midpoint_unchanged(self):
        assert _stretch_around_mid(50, 1.7) == 50

    def test_stretch_up(self):
        result = _stretch_around_mid(60, 1.7)
        assert result == 67

    def test_stretch_down(self):
        result = _stretch_around_mid(40, 1.7)
        assert result == 33

    def test_clamp_high(self):
        assert _stretch_around_mid(90, 3.0) == 100

    def test_clamp_low(self):
        assert _stretch_around_mid(10, 3.0) == 0


class TestZoneForScore:
    @pytest.mark.parametrize("score,zone", [
        (0, "冰点"), (29, "冰点"), (30, "偏冷"), (39, "偏冷"),
        (40, "正常"), (59, "正常"), (60, "偏热"), (69, "偏热"),
        (70, "过热"), (100, "过热"),
    ])
    def test_zones(self, score, zone):
        assert _zone_for_score(score) == zone


class TestMaxBoardFromLadder:
    def test_normal_ladder(self):
        ladder = {"1": ["A", "B"], "2": ["C"], "3": ["D"]}
        assert _max_board_from_ladder(ladder) == 3

    def test_with_suffix(self):
        ladder = {"1板": ["A"], "3板": ["B"]}
        assert _max_board_from_ladder(ladder) == 3

    def test_empty(self):
        assert _max_board_from_ladder({}) == 0


# ---- dx_fallback ----

class TestDxFallback:
    def test_pywencai_good(self):
        py = {"limit_up": {"count": 50}, "seal_rate": 75}
        dx = {"sentiment": {"涨停家数": "50", "今日封板率": "75%", "连板高度": "3", "跌停家数": "5"}}
        fb = _dx_fallback(py, dx)
        assert fb["py_bad"] is False
        assert fb["limit_up_count"] == 50
        assert fb["seal_rate"] == 75

    def test_pywencai_bad_uses_duanxianxia(self):
        py = {"limit_up": {"count": 0}, "seal_rate": 70}
        dx = {"sentiment": {"涨停家数": "40", "今日封板率": "68%", "连板高度": "5", "跌停家数": "3"}}
        fb = _dx_fallback(py, dx)
        assert fb["py_bad"] is True
        assert fb["limit_up_count"] == 40
        assert fb["seal_rate"] == 68.0
        assert fb["max_board"] == 5
        assert fb["limit_down_count"] == 3


# ---- 短线情绪 ----

class TestShortTermSentiment:
    def test_basic(self):
        py = {
            "limit_up": {"count": 80, "ladder": {"1": ["A"] * 50, "2": ["B"] * 20, "3": ["C"] * 10}},
            "seal_rate": 75,
            "yesterday_perf": {"status": "ok", "metric_semantics_version": 2, "advance_rate": 15.0, "premium_rate": 2.0},
            "limit_down": {"status": "ok", "count": 5},
            "broken_board": {"count": 3, "stocks": []},
        }
        dx = {"sentiment": {"涨停家数": "80", "今日封板率": "75%"}}
        result = _calc_short_term_sentiment(py, dx)
        assert 0 <= result["score"] <= 100
        assert result["zone"] in ("冰点", "偏冷", "正常", "偏热", "过热")
        assert result["metric_semantics_version"] == 2
        assert result["inputs"]["limit_up_count"] == 80
        assert result["inputs"]["seal_rate"] == 75
        assert result["inputs"]["max_board"] == 3
        assert len(result["missing_metrics"]) == 0

    def test_missing_data(self):
        py = {"limit_up": {"count": 0, "ladder": {}}, "seal_rate": 0}
        dx = {"sentiment": {"涨停家数": "0"}}
        result = _calc_short_term_sentiment(py, dx)
        assert 0 <= result["score"] <= 100
        assert len(result["missing_metrics"]) > 0


# ---- 趋势情绪 ----

class TestTrendSentiment:
    def test_basic(self):
        tu = {
            "daily_market": {"up_ratio": 55, "total_amount_yi": 8000, "down_count": 2000},
            "advance_decline": {"history": [{"total_amount_yi": 7000}] * 6},
            "indexes": {"000001.SH": {"pct_chg": 0.5}},
        }
        ak = {"sector_fund_flow": [{"net_inflow_yi": 100}, {"net_inflow_yi": -50}]}
        result = _calc_trend_sentiment(tu, ak)
        assert 0 <= result["score"] <= 100
        assert result["inputs"]["up_ratio"] == 55
        assert result["inputs"]["index_pct"] == 0.5
        assert result["main_inflow_yi"] == 50.0

    def test_no_sector_flow(self):
        tu = {"daily_market": {"up_ratio": 50}, "advance_decline": {}, "indexes": {}}
        ak = {}
        result = _calc_trend_sentiment(tu, ak)
        assert result["main_inflow_yi"] is None
        assert result["inputs"]["volume_ratio"] == 100


# ---- 市场热度 ----

class TestMarketHeat:
    def test_blend(self):
        py = {"limit_up": {"count": 80, "ladder": {"3": ["C"]}}, "seal_rate": 75}
        dx = {"sentiment": {"涨停家数": "80"}}
        tu = {"daily_market": {"up_ratio": 55, "total_amount_yi": 8000}, "advance_decline": {"history": []}, "indexes": {"000001.SH": {"pct_chg": 0.5}}}
        ak = {"sector_fund_flow": [{"net_inflow_yi": 100}]}
        st = _calc_short_term_sentiment(py, dx)
        tr = _calc_trend_sentiment(tu, ak)
        mh = _calc_market_heat(tu, py, dx, ak, st, tr)
        assert mh["score"] == round(st["score"] * 0.5 + tr["score"] * 0.5)
        assert 0 <= mh["score"] <= 100


# ---- 参与度 ----

class TestParticipationCheck:
    def test_all_satisfied(self):
        py = {
            "limit_up": {"count": 80, "ladder": {"1": ["A"] * 60, "2": ["B"] * 5, "4": ["C"]}, "themes": [{"name": "AI", "count": 20}]},
            "seal_rate": 75,
        }
        dx = {"sentiment": {"涨停家数": "80"}}
        tu = {"daily_market": {"total_amount_yi": 8000}, "advance_decline": {"history": [{"total_amount_yi": 7000}] * 6}, "indexes": {"000001.SH": {"pct_chg": 0.5}}}
        th = {"reason_tags": [{"tag": "AI", "count": 20}]}
        result = _calc_participation_check(py, dx, tu, th)
        assert result["total"] == 4
        assert result["satisfied"] >= 3
        assert result["verdict"] == "参与"

    def test_insufficient_data(self):
        py = {"limit_up": {"count": 0, "ladder": {}}, "seal_rate": 0}
        dx = {"sentiment": {}}
        tu = {"daily_market": {}, "advance_decline": {}, "indexes": {}}
        result = _calc_participation_check(py, dx, tu)
        assert result["verdict"] == "数据不足"


# ---- 退潮风险 ----

class TestEbbRiskCheck:
    def test_no_signals(self):
        py = {"limit_up": {"count": 80, "ladder": {"5": ["A"]}}, "seal_rate": 80,
              "yesterday_perf": {"status": "ok", "metric_semantics_version": 2, "advance_rate": 20.0, "premium_rate": 3.0}}
        dx = {"sentiment": {"涨停家数": "80", "今日封板率": "80%"}}
        tu = {"daily_market": {"down_count": 1000}}
        height_trend = {"days": [{"max_board": 5, "advance_rate": 20, "premium_rate": 3, "seal_rate": 80, "limit_down_count": 5} for _ in range(5)]}
        advance = {"advance_rate": 20.0, "premium_rate": 3.0}
        loss = {"limit_down_count": 5, "down_count": 1000}
        result = _calc_ebb_risk_check(py, dx, tu, height_trend, advance, loss)
        assert result["total"] == 4
        assert result["signal_count"] == 0
        assert result["verdict"] == "未见退潮"

    def test_seal_quality_weak(self):
        py = {"limit_up": {"count": 80, "ladder": {"5": ["A"]}}, "seal_rate": 50,
              "yesterday_perf": {"status": "ok", "metric_semantics_version": 2, "advance_rate": 20.0, "premium_rate": 3.0}}
        dx = {"sentiment": {"涨停家数": "80", "今日封板率": "50%"}}
        tu = {"daily_market": {"down_count": 1000}}
        height_trend = {"days": [{"max_board": 5, "advance_rate": 20, "premium_rate": 3, "seal_rate": 80, "limit_down_count": 5} for _ in range(5)]}
        advance = {"advance_rate": 20.0, "premium_rate": 3.0}
        loss = {"limit_down_count": 5, "down_count": 1000}
        result = _calc_ebb_risk_check(py, dx, tu, height_trend, advance, loss)
        assert result["signals"]["seal_quality_weak"]["triggered"] is True
        assert result["signal_count"] >= 1


# ---- crash signals ----

class TestCrashSignals:
    def test_no_trigger(self):
        py = {"broken_board": {"count": 10}, "limit_up": {"ladder": {"5": ["A"]}}}
        dx = {"pool_stats": {"跌停": {"today": "3"}}}
        tu = {"daily_market": {"down_count": 1000}}
        result = _calc_crash_signals(py, dx, tu)
        assert result["any_triggered"] is False

    def test_broken_board_trigger(self):
        py = {"broken_board": {"count": 40}, "limit_up": {"ladder": {"5": ["A"]}}}
        dx = {"pool_stats": {"跌停": {"today": "3"}}}
        tu = {"daily_market": {"down_count": 1000}}
        result = _calc_crash_signals(py, dx, tu)
        assert result["signals"][0]["triggered"] is True
        assert result["any_triggered"] is True

    def test_plunge_trigger(self):
        py = {"broken_board": {"count": 5}, "limit_up": {"ladder": {}}}
        dx = {"pool_stats": {"跌停": {"today": "15"}}}
        tu = {"daily_market": {"down_count": 2500}}
        result = _calc_crash_signals(py, dx, tu)
        assert result["signals"][2]["triggered"] is True
        assert result["any_triggered"] is True


# ---- compute() 端到端 ----

class TestCompute:
    def test_e2e(self, tmp_path):
        trade_date = "20260825"
        data_dir = tmp_path / trade_date
        data_dir.mkdir()

        py = {
            "trade_date": trade_date,
            "limit_up": {"count": 80, "ladder": {"1": ["A"] * 50, "2": ["B"] * 20, "3": ["C"] * 10}, "themes": [{"name": "AI", "count": 15}]},
            "broken_board": {"count": 5, "stocks": [{"code": "000001", "name": "Test"}]},
            "limit_down": {"status": "ok", "count": 3, "stocks": []},
            "yesterday_perf": {"status": "ok", "metric_semantics_version": 2, "advance_rate": 15.0, "premium_rate": 2.0, "count": 50, "as_of": "20260824"},
            "new_high_100d": {"status": "ok", "stocks": []},
            "seal_rate": 75,
        }
        dx = {"sentiment": {"涨停家数": "80", "今日封板率": "75%", "连板高度": "3", "跌停家数": "3"}, "pool_stats": {"跌停": {"today": "3"}}}
        tu = {
            "trade_date": trade_date,
            "daily_market": {"up_ratio": 55, "up_count": 2500, "down_count": 2000, "flat_count": 800, "total_amount_yi": 8000},
            "advance_decline": {"history": [{"total_amount_yi": 7000}] * 6},
            "indexes": {"000001.SH": {"pct_chg": 0.5, "close": 3000, "name": "上证"}},
            "suspended_stocks": {},
        }
        ak = {"sector_fund_flow": [{"net_inflow_yi": 100, "name": "电子"}, {"net_inflow_yi": -50, "name": "地产"}]}
        th = {"reason_tags": [{"tag": "AI", "count": 15}]}
        ztk = {"trade_date": trade_date, "ladder_by_height": {"3": [{"code": "000001", "name": "C"}]}, "ladder_stocks": [], "height_history": []}
        ll = {"congestion": {"pct": 45.2}}

        for name, data in [("pywencai.json", py), ("duanxianxia.json", dx), ("tushare.json", tu), ("akshare.json", ak), ("ths_hot.json", th), ("zhangtingke.json", ztk), ("legulegu.json", ll)]:
            (data_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = compute(data_dir, tmp_path)

        assert result["trade_date"] == trade_date
        assert "market_heat" in result
        assert "short_term_sentiment" in result
        assert "trend_sentiment" in result
        assert "advance_stats" in result
        assert "loss_effect" in result
        assert "participation_check" in result
        assert "ebb_risk_check" in result
        assert "crash_signals" in result
        assert "height_trend" in result
        assert "daily_summary" in result
        assert 0 <= result["market_heat"]["score"] <= 100
        assert (data_dir / "_computed.json").exists()
