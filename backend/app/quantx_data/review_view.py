"""Deterministic presentation derivations for the QuantX single-day view."""

from __future__ import annotations

from typing import Any

VIEW_ALGORITHM_VERSION = "quantx-review-view-v1"

DERIVED_FIELD_INPUTS: dict[str, tuple[str, ...]] = {
    "emotion.market_heat.zone": ("sections.s3.emotion_scores.market_heat",),
    "emotion.short_term_sentiment.zone": (
        "sections.s3.emotion_scores.short_term",
    ),
    "emotion.trend_sentiment.zone": ("sections.s3.emotion_scores.trend",),
    "sections.s3.emotion_zones": ("sections.s3.emotion_scores",),
    "emotion.height_trend": ("sections.s3.height_history",),
    "sections.s0.diagnosis": (
        "sections.s3.emotion_scores",
        "sections.s3.advance",
        "sections.s2.participation",
        "sections.s2.ebb_risk",
    ),
    "sections.s0.risks": (
        "sections.s3.ebb_signals",
        "sections.s3.crash_signals",
        "emotion.loss_effect.severity",
    ),
    "emotion.daily_summary": (
        "sections.s3.emotion_scores",
        "sections.s3.advance",
        "sections.s2.participation",
        "sections.s2.ebb_risk",
        "emotion.loss_effect.severity",
    ),
    "sections.s6.position": ("sections.s3.emotion_scores.market_heat",),
    "sections.s6.scenes": ("sections.s3.emotion_scores.market_heat",),
}


def _section(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    sections = snapshot.setdefault("sections", {})
    value = sections.setdefault(name, {})
    if isinstance(value, dict):
        return value
    replacement: dict[str, Any] = {}
    sections[name] = replacement
    return replacement


def _score_zone(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return ""
    if score < 30:
        return "冰点"
    if score < 40:
        return "偏冷"
    if score < 60:
        return "正常"
    if score < 70:
        return "偏热"
    return "过热"


def _display(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _path_value(snapshot: dict[str, Any], path: str) -> Any:
    current: Any = snapshot
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def review_view_derivation_status(
    snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Describe deterministic inputs without exposing or duplicating values."""
    status: dict[str, dict[str, Any]] = {}
    for field, inputs in DERIVED_FIELD_INPUTS.items():
        missing = [
            path for path in inputs if _path_value(snapshot, path) is None
        ]
        status[field] = {
            "status": "available" if not missing else "missing_inputs",
            "inputs": list(inputs),
            "missing_inputs": missing,
            "algorithm_version": VIEW_ALGORITHM_VERSION,
        }
    return status


def _height_trend(history: list[dict[str, Any]]) -> dict[str, Any]:
    days = [
        {
            "date": str(row.get("date") or ""),
            "max_board": int(row.get("height") or 0),
        }
        for row in history[-20:]
        if isinstance(row, dict)
    ]
    if not days:
        return {
            "days": [],
            "latest_max_board": 0,
            "previous_high_5d": None,
            "height_compressed": False,
            "evidence": "",
        }
    latest = days[-1]["max_board"]
    previous = days[:-1][-5:]
    previous_high = max(
        (int(row.get("max_board") or 0) for row in previous),
        default=None,
    )
    compressed = (
        previous_high is not None and latest < previous_high and latest <= 3
    )
    evidence = (
        f"最高{latest}板\N{FULLWIDTH COMMA}近5日前高{previous_high}板"
        if previous_high is not None
        else f"最高{latest}板"
    )
    return {
        "days": days,
        "latest_max_board": latest,
        "previous_high_5d": previous_high,
        "height_compressed": compressed,
        "evidence": evidence,
    }


def apply_deterministic_review_view(
    snapshot: dict[str, Any],
    *,
    loss_severity: str = "",
) -> list[str]:
    """Replace cache-only summaries with deterministic canonical derivations."""
    section0 = _section(snapshot, "s0")
    section2 = _section(snapshot, "s2")
    section3 = _section(snapshot, "s3")
    section6 = _section(snapshot, "s6")
    scores = section3.get("emotion_scores") or {}
    zones = {
        "market_heat": _score_zone(scores.get("market_heat")),
        "short_term": _score_zone(scores.get("short_term")),
        "trend": _score_zone(scores.get("trend")),
    }
    section3["emotion_zones"] = zones

    emotion = snapshot.setdefault("emotion", {})
    for key, score_key in (
        ("market_heat", "market_heat"),
        ("short_term_sentiment", "short_term"),
        ("trend_sentiment", "trend"),
    ):
        value = emotion.setdefault(key, {})
        if isinstance(value, dict):
            value["zone"] = zones[score_key]

    history = section3.get("height_history") or []
    emotion["height_trend"] = _height_trend(history)

    advance = section3.get("advance") or {}
    participation = section2.get("participation") or {}
    ebb = section2.get("ebb_risk") or {}
    crash_signals = section3.get("crash_signals") or []
    crash_triggered = any(
        bool(row.get("triggered"))
        for row in crash_signals
        if isinstance(row, dict)
    )

    diagnosis = [
        {
            "name": "市场热度",
            "value": _display(scores.get("market_heat")),
            "zone": zones["market_heat"],
        },
        {
            "name": "短线情绪",
            "value": _display(scores.get("short_term")),
            "zone": zones["short_term"],
        },
        {
            "name": "趋势情绪",
            "value": _display(scores.get("trend")),
            "zone": zones["trend"],
        },
        {
            "name": "参与度",
            "value": "",
            "zone": str(participation.get("verdict") or ""),
        },
        {
            "name": "退潮风险",
            "value": _display(ebb.get("signal_count")),
            "zone": str(ebb.get("verdict") or ""),
        },
        {
            "name": "崩塌信号",
            "value": "",
            "zone": "已触发" if crash_triggered else "未触发",
        },
        {"name": "亏钱效应", "value": "", "zone": loss_severity},
        {
            "name": "晋级率",
            "value": (
                f"{_display(advance.get('advance_rate'))}%"
                if advance.get("advance_rate") is not None
                else ""
            ),
            "zone": "",
        },
    ]
    section0["diagnosis"] = diagnosis

    risks = [
        {
            "name": str(row.get("name") or ""),
            "triggered": bool(row.get("triggered")),
            "available": bool(row.get("available")),
        }
        for row in section3.get("ebb_signals") or []
        if isinstance(row, dict)
    ]
    risks.extend(
        {
            "name": str(row.get("name") or ""),
            "triggered": bool(row.get("triggered")),
            "status": str(row.get("status") or ""),
            "evidence": str(row.get("evidence") or ""),
        }
        for row in crash_signals
        if isinstance(row, dict)
    )
    risks.append(
        {
            "name": "亏钱效应",
            "triggered": loss_severity not in {"", "未知", "稳定"},
            "status": loss_severity,
            "evidence": "",
        }
    )
    section0["risks"] = risks

    parts = [
        f"市场热度{_display(scores.get('market_heat'))}({zones['market_heat']})",
        f"短线情绪{_display(scores.get('short_term'))}({zones['short_term']})",
        f"趋势情绪{_display(scores.get('trend'))}({zones['trend']})",
    ]
    if advance.get("advance_rate") is not None:
        parts.append(f"晋级率{_display(advance['advance_rate'])}%")
    if advance.get("premium_rate") is not None:
        parts.append(f"溢价率{_display(advance['premium_rate'])}%")
    parts.extend(
        [
            f"亏钱效应{loss_severity or '未知'}",
            f"参与度{participation.get('verdict') or '未知'}",
            f"退潮{ebb.get('verdict') or '未知'}",
        ]
    )
    if crash_triggered:
        parts.append("崩塌信号已触发")
    emotion["daily_summary"] = "\N{FULLWIDTH SEMICOLON}".join(parts)

    market_heat = scores.get("market_heat")
    if market_heat is None:
        section6["position"] = None
    elif market_heat >= 70:
        section6["position"] = {
            "band": "高仓位(70-90%)",
            "action": "积极参与主线,关注退潮信号",
        }
    elif market_heat >= 50:
        section6["position"] = {
            "band": "中等仓位(40-60%)",
            "action": "脉冲处理,关注主线确认",
        }
    elif market_heat >= 30:
        section6["position"] = {
            "band": "低仓位(10-30%)",
            "action": "谨慎参与,等待情绪修复",
        }
    else:
        section6["position"] = {
            "band": "空仓或极低仓位(0-10%)",
            "action": "规避风险,等待冰点反转",
        }
    section6["scenes"] = [
        {
            "name": "走强",
            "condition": "热度>70 + 参与度=参与 + 退潮未触发",
            "tone": "positive",
        },
        {
            "name": "震荡",
            "condition": "热度40-70 + 参与度=脉冲处理",
            "tone": "neutral",
        },
        {
            "name": "走弱",
            "condition": "热度<40 或 退潮确认 或 崩塌触发",
            "tone": "negative",
        },
    ]

    return [
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
    ]
