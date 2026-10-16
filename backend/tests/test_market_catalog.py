"""market_catalog 多日驾驶舱测试。"""
from __future__ import annotations

import json

from app.services.market_catalog import (
    _build_change_summary,
    _compute_deltas,
    _extract_record,
    build_and_save_catalog,
    build_catalog,
    build_catalog_html,
)


class TestExtractRecord:
    def test_complete(self, tmp_path):
        d = tmp_path / "20260825"
        d.mkdir()
        computed = {
            "market_heat": {"score": 65, "zone": "偏热"},
            "short_term_sentiment": {"score": 60, "zone": "偏热"},
            "trend_sentiment": {"score": 50, "zone": "正常"},
            "advance_stats": {"advance_rate": 15.0, "premium_rate": 2.0},
            "loss_effect": {"severity": "稳定", "limit_down_count": 3, "down_count": 2000},
            "participation_check": {"verdict": "参与", "satisfied": 3},
            "ebb_risk_check": {"verdict": "未见退潮", "signal_count": 0},
            "crash_signals": {"any_triggered": False},
            "height_trend": {"previous_high_5d": 5, "height_compressed": False},
        }
        py = {"limit_up": {"themes": [{"name": "AI", "count": 15}]}}
        (d / "_computed.json").write_text(json.dumps(computed), encoding="utf-8")
        (d / "pywencai.json").write_text(json.dumps(py), encoding="utf-8")
        (d / "review.html").write_text("<html></html>", encoding="utf-8")

        rec = _extract_record(d)
        assert rec is not None
        assert rec["trade_date"] == "20260825"
        assert rec["stage"] == "complete"
        assert rec["metrics"]["market_heat_score"] == 65
        assert rec["metrics"]["market_heat_zone"] == "偏热"
        assert len(rec["themes"]) == 1
        assert rec["themes"][0]["name"] == "AI"

    def test_data_only(self, tmp_path):
        d = tmp_path / "20260824"
        d.mkdir()
        (d / "_computed.json").write_text(json.dumps({"market_heat": {"score": 50}}), encoding="utf-8")
        rec = _extract_record(d)
        assert rec is not None
        assert rec["stage"] == "data_only"

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "20260823"
        d.mkdir()
        rec = _extract_record(d)
        assert rec is None


class TestComputeDeltas:
    def test_basic(self):
        records = [
            {"metrics": {"market_heat_score": 50, "limit_up_count": 80}},
            {"metrics": {"market_heat_score": 60, "limit_up_count": 90}},
        ]
        _compute_deltas(records)
        assert records[0]["deltas"] == {}
        assert records[1]["deltas"]["market_heat_score"] == 10.0
        assert records[1]["deltas"]["limit_up_count"] == 10.0


class TestChangeSummary:
    def test_zone_change(self):
        rec = {"metrics": {"market_heat_zone": "偏热"}, "deltas": {"market_heat_score": 5, "limit_up_count": 10}}
        prev = {"metrics": {"market_heat_zone": "正常"}}
        summary = _build_change_summary(rec, prev)
        assert "正常→偏热" in summary
        assert "热度+5" in summary


class TestBuildCatalog:
    def test_e2e(self, tmp_path):
        quantx_dir = tmp_path / "quantx"
        quantx_dir.mkdir()

        for date, heat in [("20260821", 50), ("20260822", 60), ("20260823", 70)]:
            d = quantx_dir / date
            d.mkdir()
            computed = {
                "market_heat": {"score": heat, "zone": "正常" if heat < 60 else "偏热"},
                "short_term_sentiment": {"score": heat, "zone": "正常"},
                "trend_sentiment": {"score": heat, "zone": "正常"},
                "advance_stats": {},
                "loss_effect": {},
                "participation_check": {"verdict": "参与", "satisfied": 3},
                "ebb_risk_check": {"verdict": "未见退潮", "signal_count": 0},
                "crash_signals": {"any_triggered": False},
                "height_trend": {},
            }
            py = {"limit_up": {"themes": [{"name": "AI", "count": 10}]}}
            (d / "_computed.json").write_text(json.dumps(computed), encoding="utf-8")
            (d / "pywencai.json").write_text(json.dumps(py), encoding="utf-8")

        catalog = build_catalog(quantx_dir)
        assert catalog["schema_version"] == 1
        assert catalog["stats"]["total_dates"] == 3
        assert catalog["stats"]["data_only"] == 3
        assert len(catalog["records"]) == 3
        assert catalog["records"][0]["trade_date"] == "20260821"
        assert catalog["records"][-1]["trade_date"] == "20260823"
        assert "deltas" in catalog["records"][1]
        assert len(catalog["theme_events"]) > 0
        assert (quantx_dir / "catalog.json").exists()

    def test_html(self, tmp_path):
        catalog = {
            "schema_version": 1,
            "stats": {"total_dates": 2, "complete": 1, "data_only": 1},
            "records": [
                {"trade_date": "20260821", "stage": "complete", "metrics": {"market_heat_score": 65, "market_heat_zone": "偏热"}, "themes": [], "change_summary": "", "artifacts": {"review": "review.html"}},
                {"trade_date": "20260822", "stage": "data_only", "metrics": {"market_heat_score": 55, "market_heat_zone": "正常"}, "themes": [], "change_summary": "偏热→正常", "artifacts": {}},
            ],
            "theme_events": [],
        }
        html = build_catalog_html(catalog)
        assert "多日驾驶舱" in html
        assert "20260821" in html
        assert "20260822" in html
        assert "score-badge" in html

    def test_build_and_save(self, tmp_path):
        quantx_dir = tmp_path / "quantx"
        quantx_dir.mkdir()
        d = quantx_dir / "20260825"
        d.mkdir()
        (d / "_computed.json").write_text(json.dumps({"market_heat": {"score": 65, "zone": "偏热"}}), encoding="utf-8")
        catalog, html = build_and_save_catalog(quantx_dir)
        assert (quantx_dir / "catalog.json").exists()
        assert (quantx_dir / "index.html").exists()
        assert "多日驾驶舱" in html
