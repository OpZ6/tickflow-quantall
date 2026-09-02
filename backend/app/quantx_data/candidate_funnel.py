"""Deterministic, market-regime-aware candidate funnel for QuantX."""
# ruff: noqa: RUF001

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Protocol

import polars as pl

from app.market_facts.registry import DatasetId
from app.market_facts.repository import MarketFactRepository

ALGORITHM_VERSION = "quantx-candidate-funnel-v1"
FINAL_POOL_LIMIT = 10
THEME_LIMIT = 2

SETUP_LABELS = {
    "momentum_leader": "强势前排",
    "divergence_acceptance": "分歧承接",
    "healthy_pullback": "健康回调",
    "early_breakout": "低位启动",
}

REGIMES = {
    "strong_attack": {
        "label": "强势进攻",
        "weights": {"logic": 0.25, "strength": 0.35, "setup": 0.20, "execution": 0.20},
        "policy": "优先主线中可交易的强势前排，同时保留高质量分歧机会。",
    },
    "strong_divergence": {
        "label": "强势分歧",
        "weights": {"logic": 0.30, "strength": 0.25, "setup": 0.25, "execution": 0.20},
        "policy": "强逻辑与承接并重，避免追逐一致性最强的封板。",
    },
    "neutral_rotation": {
        "label": "震荡轮动",
        "weights": {"logic": 0.30, "strength": 0.15, "setup": 0.35, "execution": 0.20},
        "policy": "优先健康回调、分歧承接和低位启动，降低纯强度权重。",
    },
    "weak_defense": {
        "label": "弱势防守",
        "weights": {"logic": 0.30, "strength": 0.10, "setup": 0.40, "execution": 0.20},
        "policy": "优先此前强势且趋势未坏、缩量抗跌或承接良好的前排。",
    },
}


class CandidateKlineRepository(Protocol):
    def get_daily_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        columns: list[str] | None = None,
    ) -> pl.DataFrame: ...


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _code(value: Any) -> str:
    return str(value or "").split(".", 1)[0].zfill(6)


def _trade_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _frame_rows(frame: pl.DataFrame | None) -> list[dict[str, Any]]:
    return [] if frame is None or frame.is_empty() else frame.to_dicts()


def _market_regime(state: pl.DataFrame) -> dict[str, Any]:
    row = _frame_rows(state)
    values = row[0] if row else {}
    heat = _number(values.get("market_heat_score"), 50.0) or 50.0
    short = _number(values.get("short_term_sentiment_score"), 50.0) or 50.0
    trend = _number(values.get("trend_sentiment_score"), 50.0) or 50.0
    up_ratio = _number(values.get("up_ratio_pct"), 50.0) or 50.0
    ebb = _integer(values.get("ebb_signal_count"))
    crash = bool(values.get("crash_triggered"))
    if crash or heat < 42 or short < 42 or up_ratio < 40:
        key = "weak_defense"
    elif heat >= 60 and short >= 60 and trend >= 55 and up_ratio >= 52 and ebb == 0:
        key = "strong_attack"
    elif heat >= 55 or short >= 55:
        key = "strong_divergence"
    else:
        key = "neutral_rotation"
    config = REGIMES[key]
    return {
        "key": key,
        "label": config["label"],
        "policy": config["policy"],
        "weights": {name: round(weight * 100) for name, weight in config["weights"].items()},
        "evidence": {
            "market_heat": heat,
            "short_term": short,
            "trend": trend,
            "up_ratio_pct": up_ratio,
            "ebb_signal_count": ebb,
            "crash_triggered": crash,
        },
    }


def _price_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("date") or ""))
    closes = [_number(row.get("close")) for row in ordered]
    closes = [value for value in closes if value is not None and value > 0]
    if not closes:
        return {"available": False}
    latest = ordered[-1]
    close = closes[-1]
    previous = closes[-2] if len(closes) > 1 else close
    pct = (close / previous - 1) * 100 if previous else 0.0
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    prior_ma20_values = closes[-25:-5]
    prior_ma20 = (
        sum(prior_ma20_values) / len(prior_ma20_values)
        if prior_ma20_values
        else ma20
    )
    highs = [_number(row.get("high"), _number(row.get("close"), 0.0)) or 0.0 for row in ordered[-20:]]
    high20 = max(highs) if highs else close
    amounts = [_number(row.get("amount")) for row in ordered]
    amounts = [value for value in amounts if value is not None and value >= 0]
    prior_amounts = amounts[-21:-1]
    amount_mean = sum(prior_amounts) / len(prior_amounts) if prior_amounts else None
    amount_ratio = amounts[-1] / amount_mean if amount_mean and amounts else None
    high = _number(latest.get("high"), close) or close
    low = _number(latest.get("low"), close) or close
    position = (close - low) / (high - low) if high > low else 1.0
    return {
        "available": True,
        "pct_chg": round(pct, 2),
        "close": close,
        "ma20": ma20,
        "ma20_slope_pct": round((ma20 / prior_ma20 - 1) * 100, 2) if prior_ma20 else 0.0,
        "drawdown_20d_pct": round((close / high20 - 1) * 100, 2) if high20 else 0.0,
        "amount_ratio": round(amount_ratio, 2) if amount_ratio is not None else None,
        "close_position": round(position, 3),
        "turnover_rate": _number(latest.get("turnover_rate")),
        "one_word_shape": high > 0 and abs(high - low) / high <= 0.001,
    }


def _limit_class(code: str) -> int:
    if code.startswith(("30", "68")):
        return 20
    if code.startswith(("4", "8", "92")):
        return 30
    return 10


def _setup_type(
    *,
    current_types: set[str],
    prior_types: set[str],
    event_type: str,
    board_height: int,
    features: dict[str, Any],
) -> str | None:
    pct = _number(features.get("pct_chg"), 0.0) or 0.0
    close = _number(features.get("close"))
    ma20 = _number(features.get("ma20"))
    slope = _number(features.get("ma20_slope_pct"), 0.0) or 0.0
    drawdown = _number(features.get("drawdown_20d_pct"), 0.0) or 0.0
    position = _number(features.get("close_position"), 0.5) or 0.5
    amount_ratio = _number(features.get("amount_ratio"), 1.0) or 1.0
    trend_ok = close is None or ma20 is None or (close >= ma20 and slope >= -0.5)

    if event_type == "limit_up" and (board_height >= 2 or pct >= 5) and position >= 0.6:
        return "momentum_leader"
    if (
        "deterministic_rule_screen" in prior_types
        and -4.5 <= pct <= 3.0
        and position >= 0.55
        and trend_ok
    ):
        return "divergence_acceptance"
    if prior_types and -5.0 <= pct <= 1.5 and -12 <= drawdown <= 0.5 and amount_ratio <= 1.5 and trend_ok:
        return "healthy_pullback"
    if (
        "new_high_100d" in current_types
        and -1.0 <= drawdown <= 2.0
        and pct < _limit_class("") - 0.5
        and slope >= -0.2
    ):
        return "early_breakout"
    if event_type == "broken_board" and position >= 0.55 and trend_ok:
        return "divergence_acceptance"
    return None


def _component_scores(
    *,
    regime_key: str,
    setup: str,
    theme: str,
    interpretation: str,
    rules: list[str],
    active_days: int,
    board_height: int,
    features: dict[str, Any],
) -> dict[str, float]:
    pct = _number(features.get("pct_chg"), 0.0) or 0.0
    position = _number(features.get("close_position"), 0.5) or 0.5
    slope = _number(features.get("ma20_slope_pct"), 0.0) or 0.0
    amount_ratio = _number(features.get("amount_ratio"), 1.0) or 1.0
    logic = min(100.0, 38 + (18 if theme else 0) + (16 if interpretation else 0) + min(18, len(rules) * 6) + min(10, active_days * 2))
    strength = min(100.0, 35 + min(35, board_height * 9) + max(-12, min(20, pct * 2)) + max(-5, min(10, slope * 2)))
    setup_score = {
        "momentum_leader": 84.0,
        "divergence_acceptance": 86.0,
        "healthy_pullback": 90.0,
        "early_breakout": 78.0,
    }[setup]
    if regime_key == "strong_attack" and setup == "momentum_leader":
        setup_score += 10
    if regime_key == "weak_defense" and setup == "momentum_leader":
        setup_score -= 24
    if regime_key == "weak_defense" and setup in {"healthy_pullback", "divergence_acceptance"}:
        setup_score += 8
    execution = 55 + position * 25
    if 0.55 <= amount_ratio <= 1.5:
        execution += 12
    if setup == "healthy_pullback" and pct <= 0:
        execution += 6
    return {
        "logic": round(max(0, min(100, logic)), 1),
        "strength": round(max(0, min(100, strength)), 1),
        "setup": round(max(0, min(100, setup_score)), 1),
        "execution": round(max(0, min(100, execution)), 1),
    }


def build_candidate_funnel_from_frames(
    trade_day: date,
    market_state: pl.DataFrame,
    candidate_history: pl.DataFrame,
    limit_events: pl.DataFrame,
    ladder: pl.DataFrame,
    prices: pl.DataFrame,
) -> dict[str, Any]:
    """Build the complete deterministic funnel from point-in-time frames."""
    regime = _market_regime(market_state)
    history_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _frame_rows(candidate_history):
        if row.get("included") is False:
            continue
        observed_day = _trade_date(row.get("trade_date"))
        if observed_day is None or observed_day > trade_day:
            continue
        history_by_code[_code(row.get("symbol"))].append(row)

    event_by_code = {_code(row.get("symbol")): row for row in _frame_rows(limit_events)}
    ladder_by_code = {_code(row.get("symbol")): row for row in _frame_rows(ladder)}
    prices_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _frame_rows(prices):
        price_day = _trade_date(row.get("date"))
        if price_day is not None and price_day <= trade_day:
            prices_by_code[_code(row.get("symbol"))].append(row)

    audit_rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    setup_counter: Counter[str] = Counter()
    for code in sorted(history_by_code):
        observations = history_by_code[code]
        latest = max(observations, key=lambda row: str(row.get("trade_date") or ""))
        current = [row for row in observations if _trade_date(row.get("trade_date")) == trade_day]
        current_types = {str(row.get("candidate_type") or "") for row in current}
        prior_types = {
            str(row.get("candidate_type") or "")
            for row in observations
            if _trade_date(row.get("trade_date")) != trade_day
        }
        event = event_by_code.get(code, {})
        ladder_row = ladder_by_code.get(code, {})
        event_type = str(event.get("event_type") or "")
        board_height = max(_integer(event.get("board_height")), _integer(ladder_row.get("board_height")))
        features = _price_features(prices_by_code.get(code, []))
        if not features.get("available"):
            features["pct_chg"] = _number(latest.get("pct_chg"), 0.0)
            features["close_position"] = 1.0 if event_type == "limit_up" else 0.5
        setup = _setup_type(
            current_types=current_types,
            prior_types=prior_types,
            event_type=event_type,
            board_height=board_height,
            features=features,
        )
        limit_pct = _limit_class(code)
        one_word = event_type == "limit_up" and bool(features.get("one_word_shape"))
        high_limit_consensus = event_type == "limit_up" and limit_pct >= 20
        theme = str(ladder_row.get("theme_name") or latest.get("industry") or "独立逻辑")
        interpretation = str(
            ladder_row.get("interpretation")
            or ladder_row.get("theme_reason")
            or event.get("limit_reason")
            or ""
        )
        rules = sorted(
            {
                str(rule)
                for row in observations
                for rule in (row.get("rules_matched") or [])
                if rule
            }
        )
        active_days = len({_trade_date(row.get("trade_date")) for row in observations})
        risk_tags: list[str] = []
        action_status = "focus"
        eliminated_reason = ""
        if one_word:
            risk_tags.append("一字板不可交易")
            action_status = "context_only"
            eliminated_reason = "一字板仅作市场锚点，不占可执行候选名额"
        elif high_limit_consensus:
            risk_tags.append(f"{limit_pct}cm封板一致性风险")
            action_status = "wait_divergence"
            eliminated_reason = "高弹性封板等待分歧确认，不直接进入次日可执行池"
        elif setup is None:
            action_status = "context_only"
            eliminated_reason = "尚未形成强势前排、分歧承接、健康回调或低位启动形态"

        scores = None
        total_score = None
        if setup is not None:
            scores = _component_scores(
                regime_key=regime["key"],
                setup=setup,
                theme=theme,
                interpretation=interpretation,
                rules=rules,
                active_days=active_days,
                board_height=board_height,
                features=features,
            )
            weights = REGIMES[regime["key"]]["weights"]
            total_score = round(sum(scores[key] * weights[key] for key in weights), 1)
            setup_counter[setup] += 1
            if setup in {"divergence_acceptance", "healthy_pullback", "early_breakout"}:
                action_status = "wait_confirmation" if action_status == "focus" else action_status

        row = {
            "code": code,
            "name": str(latest.get("name") or event.get("name") or ladder_row.get("name") or ""),
            "theme": theme,
            "setup_type": setup,
            "setup_label": SETUP_LABELS.get(setup or "", "未通过形态筛选"),
            "score": total_score,
            "component_scores": scores,
            "action_status": action_status,
            "reason": interpretation or "、".join(rules) or SETUP_LABELS.get(setup or "", "缺少有效形态"),
            "confirmation": {
                "momentum_leader": "次日分歧后仍站在主线前排且保持可交易性",
                "divergence_acceptance": "回落不破趋势并出现主动承接",
                "healthy_pullback": "缩量企稳后重新转强",
                "early_breakout": "放量突破且不形成高位一致封板",
            }.get(setup or "", "等待有效形态出现"),
            "invalidation": "跌破20日趋势或放量失去承接" if setup != "momentum_leader" else "脱离主线前排或分歧时失去承接",
            "risk_tags": risk_tags,
            "source_signals": sorted(current_types | prior_types),
            "board_height": board_height,
            "limit_class_pct": limit_pct,
            "pct_chg": _number(features.get("pct_chg"), _number(latest.get("pct_chg"))),
            "active_days": active_days,
            "features": features,
            "stage": "risk_gate" if eliminated_reason else "scored",
            "eliminated_reason": eliminated_reason,
            "stage_path": ["候选并集", "形态识别"] + ([] if setup is None else ["风险门禁", "市场自适应评分"]),
        }
        audit_rows.append(row)
        if one_word or high_limit_consensus:
            anchors.append(row)

    ranked = sorted(
        [row for row in audit_rows if row["score"] is not None and not row["eliminated_reason"]],
        key=lambda row: (-float(row["score"]), row["code"]),
    )
    finalists: list[dict[str, Any]] = []
    theme_counts: Counter[str] = Counter()
    for row in ranked:
        if len(finalists) >= FINAL_POOL_LIMIT:
            row["stage"] = "capacity_gate"
            row["eliminated_reason"] = "最终池已达到10只硬上限"
            continue
        theme_key = row["theme"] or "独立逻辑"
        if theme_key != "独立逻辑" and theme_counts[theme_key] >= THEME_LIMIT:
            row["stage"] = "diversification_gate"
            row["eliminated_reason"] = "同一题材最多保留2只"
            continue
        row["stage"] = "final"
        row["stage_path"].append("最终关注池")
        finalists.append(row)
        theme_counts[theme_key] += 1

    stage_counts = [
        ("universe", "候选并集", len(history_by_code), len(history_by_code)),
        ("setup", "四类形态识别", len(history_by_code), sum(row["setup_type"] is not None for row in audit_rows)),
        ("risk", "可交易性与一致性门禁", sum(row["setup_type"] is not None for row in audit_rows), len(ranked)),
        ("final", "市场自适应评分与分散", len(ranked), len(finalists)),
    ]
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "regime": regime,
        "universe_count": len(history_by_code),
        "stages": [
            {"key": key, "label": label, "input_count": input_count, "passed_count": passed, "eliminated_count": max(0, input_count - passed)}
            for key, label, input_count, passed in stage_counts
        ],
        "branch_counts": {key: setup_counter.get(key, 0) for key in SETUP_LABELS},
        "candidates": finalists,
        "market_anchors": sorted(anchors, key=lambda row: (-row["board_height"], row["code"])),
        "audit_rows": sorted(audit_rows, key=lambda row: (row["stage"] != "final", -(row["score"] or 0), row["code"])),
    }


def _storage_symbol(symbol: str, exchange: str) -> str:
    suffix = {"SZSE": "SZ", "SSE": "SH", "BSE": "BJ"}.get(exchange.upper())
    if suffix is None:
        suffix = "SH" if symbol.startswith(("5", "6", "9")) else "BJ" if symbol.startswith(("4", "8")) else "SZ"
    return f"{symbol}.{suffix}"


def build_candidate_funnel(
    facts: MarketFactRepository,
    klines: CandidateKlineRepository | None,
    trade_day: date,
) -> dict[str, Any]:
    """Load point-in-time canonical inputs and build the candidate funnel."""
    history = facts.get_range(
        DatasetId.SCREENING_CANDIDATE_DAILY,
        trade_day - timedelta(days=45),
        trade_day,
    )
    state = facts.get_market_state(trade_day)
    events = facts.get_limit_events(trade_day)
    ladder = facts.get_limit_ladder(trade_day)
    prices = pl.DataFrame()
    if klines is not None and hasattr(klines, "get_daily_batch") and not history.is_empty():
        latest_identity: dict[str, str] = {}
        for row in history.sort("trade_date").to_dicts():
            code = _code(row.get("symbol"))
            latest_identity[code] = _storage_symbol(code, str(row.get("exchange") or ""))
        try:
            prices = klines.get_daily_batch(
                sorted(latest_identity.values()),
                trade_day - timedelta(days=120),
                trade_day,
                ["symbol", "date", "open", "high", "low", "close", "amount", "turnover_rate"],
            )
        except Exception:
            prices = pl.DataFrame()
    return build_candidate_funnel_from_frames(
        trade_day,
        state,
        history,
        events,
        ladder,
        prices,
    )
