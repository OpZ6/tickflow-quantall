from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.quantx_data.review_contract import (
    audit_review_fields,
    classify_frontend_review_paths,
    extract_frontend_review_paths,
    review_v2_contract_manifest,
)
from app.quantx_data.review_repository import _clear_canonical_cache_fields
from app.quantx_data.review_schema import QuantXReviewResponseV2
from app.quantx_data.review_view import (
    apply_deterministic_review_view,
    review_view_derivation_status,
)


def test_deterministic_review_view_replaces_cached_presentation_values():
    snapshot = {
        "emotion": {
            "height_trend": {"latest_max_board": 99},
            "daily_summary": "stale cache",
        },
        "sections": {
            "s0": {
                "diagnosis": [{"name": "stale"}],
                "risks": [{"name": "stale"}],
            },
            "s2": {
                "participation": {"verdict": "参与", "conditions": []},
                "ebb_risk": {"verdict": "未确认", "signal_count": 1},
            },
            "s3": {
                "emotion_scores": {
                    "market_heat": 65,
                    "short_term": 35,
                    "trend": 72,
                },
                "advance": {"advance_rate": 42.5, "premium_rate": 1.2},
                "height_history": [
                    {"date": "20260821", "height": 6},
                    {"date": "20260822", "height": 5},
                    {"date": "20260825", "height": 3},
                ],
                "ebb_signals": [
                    {
                        "name": "高度压缩",
                        "triggered": True,
                        "available": True,
                    }
                ],
                "crash_signals": [
                    {
                        "name": "跌停扩散",
                        "triggered": False,
                        "status": "未触发",
                        "evidence": "0只",
                    }
                ],
            },
        },
    }

    derived = apply_deterministic_review_view(
        snapshot,
        loss_severity="扩散",
    )

    assert snapshot["sections"]["s3"]["emotion_zones"] == {
        "market_heat": "偏热",
        "short_term": "偏冷",
        "trend": "过热",
    }
    assert snapshot["emotion"]["height_trend"] == {
        "days": [
            {"date": "20260821", "max_board": 6},
            {"date": "20260822", "max_board": 5},
            {"date": "20260825", "max_board": 3},
        ],
        "latest_max_board": 3,
        "previous_high_5d": 6,
        "height_compressed": True,
        "evidence": "最高3板\N{FULLWIDTH COMMA}近5日前高6板",
    }
    assert snapshot["emotion"]["daily_summary"] == (
        "市场热度65(偏热)\N{FULLWIDTH SEMICOLON}"
        "短线情绪35(偏冷)\N{FULLWIDTH SEMICOLON}"
        "趋势情绪72(过热)\N{FULLWIDTH SEMICOLON}"
        "晋级率42.5%\N{FULLWIDTH SEMICOLON}"
        "溢价率1.2%\N{FULLWIDTH SEMICOLON}"
        "亏钱效应扩散\N{FULLWIDTH SEMICOLON}"
        "参与度参与\N{FULLWIDTH SEMICOLON}"
        "退潮未确认"
    )
    assert snapshot["sections"]["s0"]["diagnosis"][0] == {
        "name": "市场热度",
        "value": "65",
        "zone": "偏热",
    }
    assert snapshot["sections"]["s0"]["risks"][-1] == {
        "name": "亏钱效应",
        "triggered": True,
        "status": "扩散",
        "evidence": "",
    }
    assert set(derived) == {
        "emotion.daily_summary",
        "emotion.height_trend",
        "emotion.market_heat.zone",
        "emotion.short_term_sentiment.zone",
        "emotion.trend_sentiment.zone",
        "sections.s0.diagnosis",
        "sections.s0.risks",
        "sections.s3.emotion_zones",
        "sections.s6.position",
        "sections.s6.scenes",
    }
    status = review_view_derivation_status(snapshot)
    assert status["emotion.height_trend"] == {
        "status": "available",
        "inputs": ["sections.s3.height_history"],
        "missing_inputs": [],
        "algorithm_version": "quantx-review-view-v1",
    }


def test_review_field_audit_exposes_fallback_and_implicit_cache_paths():
    snapshot = {
        "trade_date": "20260825",
        "metric_strip": {"up_count": 1, "total_amount_yi": 2.3},
        "sections": {
            "s0": {
                "title": "决策",
                "llm_block": "decision_summary",
                "diagnosis": [{"name": "市场热度", "value": "65"}],
                "unknown_cache": "must be visible",
            },
            "s1": {"futures": [{"contract": "IF"}]},
        },
    }

    result = audit_review_fields(
        snapshot,
        canonical_fields=["metric_strip.market_breadth"],
        derived_fields=["sections.s0.diagnosis"],
    )

    assert result["schema_version"] == "quantx-review.v1.1"
    assert result["presentation_fields"] == ["sections.s0.title"]
    assert result["deprecated_fields"] == [
        "sections.s0.llm_block",
        "sections.s1.futures",
    ]
    assert result["fallback_fields"] == ["metric_strip.total_amount_yi"]
    assert result["implicit_cache_fields"] == [
        "sections.s0.unknown_cache"
    ]


def test_review_view_reports_missing_inputs_without_using_cache_values():
    snapshot = {
        "emotion": {
            "height_trend": {"latest_max_board": 99},
            "daily_summary": "stale cache",
        },
        "sections": {
            "s0": {"diagnosis": [{"name": "stale"}]},
            "s2": {},
            "s3": {},
        },
    }

    apply_deterministic_review_view(snapshot)
    status = review_view_derivation_status(snapshot)

    assert snapshot["emotion"]["height_trend"]["latest_max_board"] == 0
    assert snapshot["emotion"]["daily_summary"] != "stale cache"
    assert status["sections.s0.diagnosis"]["status"] == "missing_inputs"
    assert "sections.s3.emotion_scores" in status["sections.s0.diagnosis"][
        "missing_inputs"
    ]


def test_canonical_cache_fields_are_removed_before_repository_overlays():
    snapshot = {
        "metric_strip": {"up_count": 999, "custom_label": "keep"},
        "emotion": {
            "market_heat": {"score": 999},
            "daily_summary": "derived later",
        },
        "sections": {
            "s0": {"title": "keep"},
            "s1": {"indexes": [{"code": "stale"}], "futures": []},
            "s2": {"participation": {"verdict": "stale"}},
            "s3": {"ebb_signals": [{"name": "stale"}]},
            "s4": {"institution": [{"name": "compatibility"}]},
        },
    }

    _clear_canonical_cache_fields(snapshot)

    assert snapshot["metric_strip"] == {"custom_label": "keep"}
    assert snapshot["emotion"] == {"daily_summary": "derived later"}
    assert snapshot["sections"]["s0"] == {"title": "keep"}
    assert snapshot["sections"]["s1"] == {"futures": []}
    assert snapshot["sections"]["s2"] == {}
    assert snapshot["sections"]["s3"] == {}
    assert snapshot["sections"]["s4"] == {
        "institution": [{"name": "compatibility"}]
    }


def test_v2_schema_builds_seven_declared_sections_and_rejects_extra_fields():
    payload = QuantXReviewResponseV2.empty("20260825").model_dump()

    assert payload["trade_date"] == "20260825"
    assert set(payload["sections"]) == {f"s{index}" for index in range(7)}
    assert payload["metric_strip"]["indexes"] == []
    assert payload["metric_strip"]["total_amount_yi"] is None

    payload["sections"]["s0"]["undeclared"] = "not allowed"
    with pytest.raises(ValidationError):
        QuantXReviewResponseV2.model_validate(payload)


def test_frontend_review_consumers_have_one_declared_v2_classification():
    repository_root = Path(__file__).resolve().parents[2]
    source = (repository_root / "frontend/src/pages/QuantXReview.tsx").read_text(
        encoding="utf-8"
    )

    paths = extract_frontend_review_paths(source)
    result = classify_frontend_review_paths(paths)

    assert "metric_strip.total_amount_yi" in paths
    assert "emotion.daily_summary" in paths
    assert "sections.s3.height_history" in paths
    assert result == {"missing": [], "conflicts": []}
    manifest = review_v2_contract_manifest()
    assert all(
        set(manifest[path]) == {
            "classification",
            "unit",
            "null_behavior",
            "sort",
        }
        for path in paths
    )
