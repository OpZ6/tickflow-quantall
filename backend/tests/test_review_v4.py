"""review_v4 七区报告测试。"""
from __future__ import annotations

import json

from app.services.review_v4 import (
    BLOCK_ORDER,
    SECTION_TITLES,
    _build_metric_strip,
    _build_multi_dim_diagnosis,
    _build_next_day_plan,
    _build_sentiment_combined,
    _claude_analysis_marker,
    build_review_html,
)


class TestBlockOrder:
    def test_seven_blocks(self):
        assert len(BLOCK_ORDER) == 7

    def test_order(self):
        assert BLOCK_ORDER[0] == "decision_summary"
        assert BLOCK_ORDER[-1] == "summary_lessons"

    def test_sections(self):
        assert len(SECTION_TITLES) == 7
        assert SECTION_TITLES["s0"] == "一、顶部决断"
        assert SECTION_TITLES["s6"] == "七、次日预案与复盘校验"


class TestClaudeMarker:
    def test_contains_block_id(self):
        marker = _claude_analysis_marker("decision_summary")
        assert "CLAUDE_ANALYSIS_START:decision_summary" in marker
        assert "CLAUDE_ANALYSIS_END:decision_summary" in marker
        assert "data-claude-analysis" in marker


class TestMetricStrip:
    def test_basic(self):
        computed = {"advance_stats": {"advance_rate": 15.0}}
        tu = {
            "indexes": {
                "000001.SH": {"pct_chg": 0.5},
                "399006.SZ": {"pct_chg": -0.3},
                "000688.SH": {"pct_chg": 1.2},
            },
            "daily_market": {"up_count": 2500, "down_count": 2000, "flat_count": 800, "total_amount_yi": 8000},
        }
        html = _build_metric_strip(computed, tu)
        assert "metric-strip" in html
        assert "上证指数" in html
        assert "+0.50%" in html
        assert "8000" in html
        assert "15.0" in html


class TestMultiDimDiagnosis:
    def test_basic(self):
        computed = {
            "market_heat": {"score": 65, "zone": "偏热"},
            "short_term_sentiment": {"score": 60, "zone": "偏热"},
            "trend_sentiment": {"score": 50, "zone": "正常"},
            "participation_check": {"verdict": "参与"},
            "ebb_risk_check": {"signal_count": 0, "verdict": "未见退潮"},
            "crash_signals": {"any_triggered": False},
            "loss_effect": {"severity": "稳定"},
            "advance_stats": {"advance_rate": 15.0},
        }
        html = _build_multi_dim_diagnosis(computed)
        assert "dim-diagnosis" in html
        assert "市场热度" in html
        assert "65" in html
        assert "偏热" in html


class TestSentimentCombined:
    def test_basic(self):
        computed = {
            "market_heat": {"score": 65, "zone": "偏热"},
            "short_term_sentiment": {"score": 60, "zone": "偏热"},
            "trend_sentiment": {"score": 50, "zone": "正常"},
        }
        html = _build_sentiment_combined(computed)
        assert "sentiment-combined" in html
        assert "市场热度" in html
        assert "65" in html
        assert "sentiment-fill" in html


class TestNextDayPlan:
    def test_high_score(self):
        computed = {"market_heat": {"score": 75, "zone": "过热"}}
        py, tu = {}, {}
        html = _build_next_day_plan(computed, py, tu)
        assert "REVIEW_DECISION_PLAN_START" in html
        assert "REVIEW_DECISION_PLAN_END" in html
        assert "高仓位" in html

    def test_low_score(self):
        computed = {"market_heat": {"score": 25, "zone": "冰点"}}
        py, tu = {}, {}
        html = _build_next_day_plan(computed, py, tu)
        assert "空仓" in html


class TestBuildReviewHtml:
    def test_e2e(self, tmp_path):
        trade_date = "20260825"
        data_dir = tmp_path / trade_date
        data_dir.mkdir()

        computed = {
            "trade_date": trade_date,
            "market_heat": {"score": 60, "zone": "偏热"},
            "short_term_sentiment": {"score": 55, "zone": "正常", "inputs": {"limit_up_count": 80, "seal_rate": 75, "max_board": 3}},
            "trend_sentiment": {"score": 50, "zone": "正常", "inputs": {"up_ratio": 55, "index_pct": 0.5, "volume_ratio": 100, "main_inflow_yi": 50}},
            "advance_stats": {"advance_rate": 15.0, "premium_rate": 2.0},
            "loss_effect": {"severity": "稳定", "limit_down_count": 3, "down_count": 2000},
            "participation_check": {"verdict": "参与", "conditions": {}, "satisfied": 3, "available": 4, "total": 4},
            "ebb_risk_check": {"verdict": "未见退潮", "signal_count": 0, "signals": {}, "available": 4, "total": 4},
            "crash_signals": {"any_triggered": False, "signals": []},
            "height_trend": {"days": [], "previous_high_5d": None, "height_compressed": False},
            "limit_ladder": {"ladder_by_height": {"3": [{"name": "C"}]}, "ladder_stocks": []},
            "zhangtingke_height": {"available": False, "days": []},
        }
        tu = {
            "trade_date": trade_date,
            "daily_market": {"up_count": 2500, "down_count": 2000, "flat_count": 800, "total_amount_yi": 8000},
            "indexes": {"000001.SH": {"pct_chg": 0.5, "close": 3000, "name": "上证"}},
        }
        py = {"limit_up": {"count": 80, "ladder": {"3": [{"name": "C"}]}, "stocks": [{"name": "C", "code": "000001", "limit_times": 3, "reason": "AI"}], "themes": [{"name": "AI", "count": 15}]}, "new_high_100d": {"status": "ok", "stocks": []}}
        ak = {"sector_fund_flow": [{"net_inflow_yi": 100, "name": "电子"}]}
        th = {"reason_tags": [{"tag": "AI", "count": 15}]}

        for name, data in [("_computed.json", computed), ("tushare.json", tu), ("pywencai.json", py), ("akshare.json", ak), ("ths_hot.json", th)]:
            (data_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        html = build_review_html(data_dir)
        assert "<!DOCTYPE html>" in html
        assert "A股复盘报告" in html
        assert "CLAUDE_ANALYSIS_START:decision_summary" in html
        assert "CLAUDE_ANALYSIS_START:summary_lessons" in html
        assert 'id="s0"' in html
        assert 'id="s6"' in html
        assert "REVIEW_DECISION_PLAN" in html
        assert (data_dir / "review.html").exists()
        assert len(html) > 1000
