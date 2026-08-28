"""Canonical read model for the QuantX single-day rich dashboard."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from app.market_facts.registry import DatasetId, get_route
from app.market_facts.repository import MarketFactRepository
from app.services.index_sync import (
    QUANTX_ALL_A_DISPLAY_SYMBOL,
    QUANTX_ALL_A_STORAGE_SYMBOL,
)

from .io import read_json
from .review_contract import (
    DEPRECATION_SCHEDULE,
    REVIEW_SCHEMA_VERSION,
    audit_review_fields,
)
from .review_schema import REVIEW_V2_SCHEMA_VERSION, QuantXReviewResponseV2
from .review_view import (
    VIEW_ALGORITHM_VERSION,
    apply_deterministic_review_view,
    review_view_derivation_status,
)

INDEX_DISPLAY_NAMES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
    "000300.SH": "沪深300",
    "000016.SH": "上证50",
    "399303.SZ": "国证2000",
    "399905.SZ": "中证500",
    QUANTX_ALL_A_DISPLAY_SYMBOL: "中证全指",
}


class IndexRepository(Protocol):
    def get_index_daily(
        self,
        symbol: str,
        start: date,
        end: date,
        columns: list[str] | None = None,
    ) -> pl.DataFrame: ...


def _day(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _preferred(frame: pl.DataFrame, dataset_id: DatasetId) -> pl.DataFrame:
    if frame.is_empty() or "source" not in frame.columns:
        return frame
    for source in get_route(dataset_id).sources:
        selected = frame.filter(pl.col("source") == source)
        if not selected.is_empty():
            return selected
    return frame.head(0)


def _preferred_by_day(
    frame: pl.DataFrame,
    dataset_id: DatasetId,
) -> pl.DataFrame:
    if frame.is_empty() or "source" not in frame.columns:
        return frame
    ranks = {
        source: rank for rank, source in enumerate(get_route(dataset_id).sources)
    }
    return (
        frame.with_columns(
            pl.col("source")
            .replace_strict(ranks, default=len(ranks))
            .alias("_source_rank")
        )
        .sort(["trade_date", "_source_rank"])
        .unique(subset=["trade_date"], keep="first", maintain_order=True)
        .drop("_source_rank")
    )


def _preferred_rows_by_day(
    frame: pl.DataFrame,
    dataset_id: DatasetId,
) -> pl.DataFrame:
    """Select the preferred source per date while preserving all source rows."""
    if frame.is_empty() or "source" not in frame.columns:
        return frame
    selected = [
        _preferred(
            frame.filter(pl.col("trade_date") == trade_day),
            dataset_id,
        )
        for trade_day in frame["trade_date"].unique().sort().to_list()
    ]
    return pl.concat(selected) if selected else frame.head(0)


def _section(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    sections = snapshot.setdefault("sections", {})
    section = sections.setdefault(name, {})
    if isinstance(section, dict):
        return section
    replacement: dict[str, Any] = {}
    sections[name] = replacement
    return replacement


def _clear_canonical_cache_fields(snapshot: dict[str, Any]) -> None:
    """Prevent stale compatibility values from replacing missing facts."""
    strip = snapshot.setdefault("metric_strip", {})
    for key in (
        "indexes",
        "up_count",
        "down_count",
        "flat_count",
        "total_amount_yi",
        "advance_rate",
    ):
        strip.pop(key, None)

    emotion = snapshot.setdefault("emotion", {})
    for key in (
        "market_heat",
        "short_term_sentiment",
        "trend_sentiment",
        "loss_effect",
    ):
        emotion.pop(key, None)

    fields_by_section = {
        "s1": (
            "indexes",
            "kline_history",
            "up_count_history",
            "width_heat",
            "width_heat_level2",
            "margin",
            "margin_history",
            "congestion",
        ),
        "s2": (
            "participation",
            "ebb_risk",
            "themes_pywencai",
            "themes_ths",
            "new_high",
        ),
        "s3": (
            "emotion_scores",
            "advance",
            "advance_history",
            "ebb_signals",
            "crash_signals",
            "ladder_grid",
            "ladder_detail",
            "height_history",
        ),
        "s4": ("sector_flow", "sector_treemap"),
        "s5": ("candidates",),
        "s6": ("position", "scenes"),
    }
    for section_name, keys in fields_by_section.items():
        section = _section(snapshot, section_name)
        for key in keys:
            section.pop(key, None)


def _decoded(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class QuantXReviewRepository:
    """Build the single-day view from repositories with an explicit V1 fallback."""

    _PRESENTATION_CACHE_FIELDS = (
        "sections.s1.futures",
        "sections.s4.institution",
        "sections.s4.dx_strength",
    )

    def __init__(
        self,
        quantx_dir: Path,
        facts: MarketFactRepository,
        indexes: IndexRepository | None = None,
    ) -> None:
        self.quantx_dir = Path(quantx_dir)
        self.facts = facts
        self.indexes = indexes

    def load(
        self,
        trade_date: str,
        *,
        view_version: str = "v2",
    ) -> dict[str, Any] | None:
        if view_version == "v1":
            cached = read_json(self.quantx_dir / trade_date / "review_data.json")
            if not isinstance(cached, dict):
                return None
            snapshot = deepcopy(cached)
            _clear_canonical_cache_fields(snapshot)
            return self._populate(
                trade_date,
                snapshot,
                cache_backed=True,
            )
        if view_version != "v2":
            raise ValueError(f"unsupported QuantX review version: {view_version}")
        snapshot = QuantXReviewResponseV2.empty(trade_date).model_dump(
            exclude={"data_foundation"}
        )
        response = self._populate(
            trade_date,
            snapshot,
            cache_backed=False,
        )
        if response is None:  # pragma: no cover - defensive contract guard
            return None
        return QuantXReviewResponseV2.model_validate(response).model_dump()

    def _populate(
        self,
        trade_date: str,
        snapshot: dict[str, Any],
        *,
        cache_backed: bool,
    ) -> dict[str, Any]:
        selected_day = _day(trade_date)
        canonical_fields: list[str] = []

        self._apply_market(snapshot, selected_day, canonical_fields)
        self._apply_history(snapshot, selected_day, canonical_fields)
        self._apply_sector_breadth(snapshot, selected_day, canonical_fields)
        self._apply_congestion(snapshot, selected_day, canonical_fields)
        self._apply_advance_history(snapshot, selected_day, canonical_fields)
        self._apply_risk_signals(snapshot, selected_day, canonical_fields)
        self._apply_margin(snapshot, selected_day, canonical_fields)
        self._apply_themes(snapshot, selected_day, canonical_fields)
        self._apply_ladder(snapshot, selected_day, canonical_fields)
        self._apply_sectors(snapshot, selected_day, canonical_fields)
        self._apply_new_high(snapshot, selected_day, canonical_fields)
        self._apply_candidates(snapshot, selected_day, canonical_fields)
        self._apply_kline_history(snapshot, selected_day, canonical_fields)
        self._apply_indexes(snapshot, selected_day, canonical_fields)

        loss_effect = snapshot.get("emotion", {}).get("loss_effect", {})
        derived_fields = apply_deterministic_review_view(
            snapshot,
            loss_severity=str(loss_effect.get("severity") or ""),
        )
        audit = audit_review_fields(
            snapshot,
            canonical_fields=canonical_fields,
            derived_fields=derived_fields,
            cache_backed=cache_backed,
            schema_version=(
                REVIEW_SCHEMA_VERSION if cache_backed else REVIEW_V2_SCHEMA_VERSION
            ),
        )
        derivation_status = review_view_derivation_status(snapshot)

        snapshot["data_foundation"] = {
            "read_mode": (
                "canonical_facts_with_presentation_cache"
                if cache_backed
                else "canonical_view_v2"
            ),
            "cache_artifact": "review_data.json" if cache_backed else None,
            "source_json_read": cache_backed,
            "presentation_cache_read": cache_backed,
            "canonical_fields": sorted(set(canonical_fields)),
            "derived_fields": sorted(set(derived_fields)),
            "view_algorithm_version": VIEW_ALGORITHM_VERSION,
            "derived_field_status": derivation_status,
            "presentation_cache_fields": (
                list(self._PRESENTATION_CACHE_FIELDS) if cache_backed else []
            ),
            **audit,
        }
        if cache_backed:
            snapshot["data_foundation"]["deprecation_schedule"] = (
                DEPRECATION_SCHEDULE
            )
        return snapshot

    def _apply_market(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        strip = snapshot.setdefault("metric_strip", {})
        breadth = _preferred(
            self.facts.get_market_breadth(day), DatasetId.MARKET_BREADTH_DAILY
        )
        if not breadth.is_empty():
            row = breadth.row(0, named=True)
            strip.update(
                {
                    "up_count": row["up_count"],
                    "down_count": row["down_count"],
                    "flat_count": row["flat_count"],
                }
            )
            fields.append("metric_strip.market_breadth")

        liquidity = _preferred(
            self.facts.get_market_liquidity(day),
            DatasetId.MARKET_LIQUIDITY_DAILY,
        )
        if not liquidity.is_empty():
            strip["total_amount_yi"] = liquidity["total_amount_yi"].item()
            fields.append("metric_strip.total_amount_yi")

        state = self.facts.get_market_state(day)
        if state.is_empty():
            return
        row = state.row(0, named=True)
        strip["advance_rate"] = row.get("advance_rate_pct")
        emotion = snapshot.setdefault("emotion", {})
        for name, score_key in (
            ("market_heat", "market_heat_score"),
            ("short_term_sentiment", "short_term_sentiment_score"),
            ("trend_sentiment", "trend_sentiment_score"),
        ):
            emotion[name] = {"score": row.get(score_key)}
        emotion["loss_effect"] = {
            "severity": row.get("loss_severity") or "",
            "limit_down_count": row.get("limit_down_count"),
        }
        s3 = _section(snapshot, "s3")
        s3["emotion_scores"] = {
            "market_heat": row.get("market_heat_score"),
            "short_term": row.get("short_term_sentiment_score"),
            "trend": row.get("trend_sentiment_score"),
        }
        s3["advance"] = {
            "advance_rate": row.get("advance_rate_pct"),
            "premium_rate": row.get("premium_rate_pct"),
        }
        fields.extend(
            [
                "metric_strip.advance_rate",
                "emotion.scores",
                "emotion.loss_effect",
                "sections.s3.emotion_scores",
                "sections.s3.advance",
            ]
        )

    def _apply_history(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        start = day - timedelta(days=90)
        breadth = self.facts.get_range(
            DatasetId.MARKET_BREADTH_DAILY, start, day
        )
        if breadth.is_empty():
            return
        liquidity = self.facts.get_range(
            DatasetId.MARKET_LIQUIDITY_DAILY, start, day
        )
        amount_by_day = {
            row["trade_date"]: row.get("total_amount_yi")
            for row in _preferred_by_day(
                liquidity, DatasetId.MARKET_LIQUIDITY_DAILY
            ).to_dicts()
        }
        rows = [
            {
                "date": row["trade_date"].strftime("%Y%m%d"),
                "up_count": row["up_count"],
                "down_count": row["down_count"],
                "total_amount_yi": amount_by_day.get(row["trade_date"]),
            }
            for row in breadth.tail(30).to_dicts()
        ]
        _section(snapshot, "s1")["up_count_history"] = rows
        fields.append("sections.s1.up_count_history")

    def _apply_sector_breadth(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        breadth = _preferred(
            self.facts.get_sector_breadth(day),
            DatasetId.SECTOR_BREADTH_DAILY,
        )
        if breadth.is_empty():
            return
        def serialize(frame: pl.DataFrame) -> list[dict[str, Any]]:
            return [
                {
                    "code": row["sector_id"],
                    "name": row["sector_name"],
                    "ma5": row["above_ma5_pct"],
                    "ma10": row["above_ma10_pct"],
                    "ma20": row["above_ma20_pct"],
                    "ma60": row["above_ma60_pct"],
                }
                for row in frame.sort("sector_id").to_dicts()
            ]

        section = _section(snapshot, "s1")
        level1 = breadth.filter(pl.col("dimension") == "sw_level1")
        level2 = breadth.filter(pl.col("dimension") == "sw_level2")
        if not level1.is_empty():
            section["width_heat"] = serialize(level1)
            fields.append("sections.s1.width_heat")
        if not level2.is_empty():
            section["width_heat_level2"] = serialize(level2)
            fields.append("sections.s1.width_heat_level2")

    def _apply_congestion(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        liquidity = _preferred_by_day(
            self.facts.get_range(
                DatasetId.MARKET_LIQUIDITY_DAILY,
                day - timedelta(days=120),
                day,
            ),
            DatasetId.MARKET_LIQUIDITY_DAILY,
        ).tail(10)
        if liquidity.is_empty():
            return
        close_by_day: dict[date, float | None] = {}
        if self.indexes is not None and hasattr(self.indexes, "get_index_daily"):
            try:
                index = self.indexes.get_index_daily(
                    "000001.SH",
                    day - timedelta(days=120),
                    day,
                    ["symbol", "date", "close"],
                )
            except (OSError, RuntimeError, ValueError):
                index = pl.DataFrame()
            if not index.is_empty():
                close_by_day = {
                    row["date"]: row.get("close") for row in index.to_dicts()
                }
        amount_column = (
            "top5pct_amount_yi"
            if "top5pct_amount_yi" in liquidity.columns
            else "top5_amount_yi"
        )
        ratio_column = (
            "top5pct_amount_ratio_pct"
            if "top5pct_amount_ratio_pct" in liquidity.columns
            else "top5_amount_ratio_pct"
        )
        rows = []
        for row in liquidity.to_dicts():
            ratio = row.get(ratio_column)
            total = row.get("total_amount_yi")
            amount = row.get(amount_column)
            if amount is None and ratio is not None and total is not None:
                amount = round(total * ratio / 100, 2)
            rows.append(
                [
                    row["trade_date"].isoformat(),
                    close_by_day.get(row["trade_date"]),
                    amount,
                    total,
                    ratio,
                ]
            )
        latest = rows[-1]
        _section(snapshot, "s1")["congestion"] = {
            "latest": {
                "date": latest[0],
                "close": latest[1],
                "top5_amount": latest[2],
                "total_amount": latest[3],
                "congestion_pct": latest[4],
            },
            "table": rows,
        }
        fields.append("sections.s1.congestion")

    def _apply_advance_history(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        states = self.facts.get_range(
            DatasetId.MARKET_STATE_DAILY,
            day - timedelta(days=120),
            day,
        ).tail(20)
        if states.is_empty():
            return
        _section(snapshot, "s3")["advance_history"] = [
            {
                "date": row["trade_date"].strftime("%Y%m%d"),
                "advance_rate": row.get("advance_rate_pct"),
                "premium_rate": row.get("premium_rate_pct"),
                "limit_up_count": row.get("limit_up_count"),
                "max_board": row.get("max_board"),
                "seal_rate": row.get("seal_rate_pct"),
            }
            for row in states.to_dicts()
        ]
        fields.append("sections.s3.advance_history")

    def _apply_position(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        state = self.facts.get_market_state(day)
        if state.is_empty():
            return
        score = state["market_heat_score"].item()
        if score is None:
            return
        if score >= 70:
            position = {
                "band": "高仓位(70-90%)",
                "action": "积极参与主线,关注退潮信号",
            }
        elif score >= 50:
            position = {
                "band": "中等仓位(40-60%)",
                "action": "脉冲处理,关注主线确认",
            }
        elif score >= 30:
            position = {
                "band": "低仓位(10-30%)",
                "action": "谨慎参与,等待情绪修复",
            }
        else:
            position = {
                "band": "空仓或极低仓位(0-10%)",
                "action": "规避风险,等待冰点反转",
            }
        section = _section(snapshot, "s6")
        section["position"] = position
        section["scenes"] = [
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
        fields.extend(["sections.s6.position", "sections.s6.scenes"])

    def _apply_risk_signals(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        signals = self.facts.get_market_signals(day)
        if signals.is_empty():
            return
        participation = signals.filter(
            pl.col("signal_group") == "participation"
        ).sort("signal_id")
        ebb = signals.filter(pl.col("signal_group") == "ebb").sort("signal_id")
        crash = signals.filter(pl.col("signal_group") == "crash").sort(
            "signal_id"
        )
        section2 = _section(snapshot, "s2")
        section3 = _section(snapshot, "s3")
        if not participation.is_empty():
            rows = participation.to_dicts()
            section2["participation"] = {
                "conditions": [
                    {
                        "name": row["signal_name"],
                        "value": _decoded(row.get("value_json")),
                        "ok": row.get("ok"),
                        "available": row.get("available"),
                    }
                    for row in rows
                ],
                "verdict": rows[0].get("group_verdict") or "",
                "satisfied": sum(row.get("ok") is True for row in rows),
                "total": len(rows),
            }
            fields.append("sections.s2.participation")
        if not ebb.is_empty():
            rows = ebb.to_dicts()
            section2["ebb_risk"] = {
                "verdict": rows[0].get("group_verdict") or "",
                "signal_count": sum(
                    row.get("triggered") is True for row in rows
                ),
            }
            section3["ebb_signals"] = [
                {
                    "name": row["signal_name"],
                    "triggered": row.get("triggered"),
                    "available": row.get("available"),
                    "value": _decoded(row.get("value_json")),
                    "baseline": _decoded(row.get("baseline_json")),
                }
                for row in rows
            ]
            fields.extend(["sections.s2.ebb_risk", "sections.s3.ebb_signals"])
        if not crash.is_empty():
            section3["crash_signals"] = [
                {
                    "name": row["signal_name"],
                    "triggered": row.get("triggered"),
                    "status": row.get("status") or "",
                    "evidence": row.get("evidence") or "",
                }
                for row in crash.to_dicts()
            ]
            fields.append("sections.s3.crash_signals")

    def _apply_margin(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        margin = self.facts.get_margin_history(
            day - timedelta(days=120), day, as_of=day
        ).tail(30)
        if margin.is_empty():
            return
        rows = [
            {
                "date": row["trade_date"].strftime("%Y%m%d"),
                "rzye_yi": row["financing_balance_yi"],
                "rz_net_buy_yi": row["financing_net_buy_yi"],
            }
            for row in margin.to_dicts()
        ]
        section = _section(snapshot, "s1")
        section["margin_history"] = rows
        section["margin"] = rows[-1]
        fields.extend(["sections.s1.margin", "sections.s1.margin_history"])

    def _apply_themes(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        observations = self.facts.get_theme_observations(day)
        if observations.is_empty():
            return
        section = _section(snapshot, "s2")
        pywencai = observations.filter(pl.col("source") == "pywencai").sort(
            "rank", nulls_last=True
        )
        ths = observations.filter(pl.col("source") == "ths_hot").sort(
            "rank", nulls_last=True
        )
        if not pywencai.is_empty():
            section["themes_pywencai"] = [
                {
                    "name": row["theme_name"],
                    "count": row.get("stock_count") or row.get("strength"),
                    "rank": row.get("rank"),
                }
                for row in pywencai.head(8).to_dicts()
            ]
            fields.append("sections.s2.themes_pywencai")
        if not ths.is_empty():
            section["themes_ths"] = [
                {
                    "tag": row["theme_name"],
                    "count": row.get("stock_count") or row.get("strength"),
                    "rank": row.get("rank"),
                }
                for row in ths.head(8).to_dicts()
            ]
            fields.append("sections.s2.themes_ths")

    def _apply_ladder(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        ladder = _preferred(
            self.facts.get_limit_ladder(day), DatasetId.LIMIT_LADDER_DAILY
        )
        if ladder.is_empty():
            return
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in ladder.to_dicts():
            grouped.setdefault(int(row["board_height"]), []).append(row)
        section = _section(snapshot, "s3")
        section["ladder_grid"] = [
            {
                "level": str(level),
                "count": len(rows),
                "names": [row.get("name") or "" for row in rows[:8]],
            }
            for level, rows in sorted(grouped.items(), reverse=True)
        ]
        section["ladder_detail"] = [
            {
                "code": row["symbol"],
                "name": row.get("name") or "",
                "limit_times": row["board_height"],
                "theme_name": row.get("theme_name") or "",
                "turnover_pct": row.get("turnover_pct"),
                "amount_yi": row.get("amount_yi"),
            }
            for row in ladder.to_dicts()
        ]
        history = _preferred_rows_by_day(
            self.facts.get_range(
                DatasetId.LIMIT_LADDER_DAILY,
                day - timedelta(days=180),
                day,
            ),
            DatasetId.LIMIT_LADDER_DAILY,
        )
        if not history.is_empty():
            height_history: list[dict[str, Any]] = []
            for trade_day in sorted(history["trade_date"].unique().to_list()):
                daily = history.filter(pl.col("trade_date") == trade_day).sort(
                    ["board_height", "symbol"], descending=[True, False]
                )
                heights = sorted(
                    {int(value) for value in daily["board_height"].to_list()},
                    reverse=True,
                )
                if not heights:
                    continue
                highest = daily.filter(pl.col("board_height") == heights[0])
                leader = highest.row(0, named=True)
                second_height = heights[1] if len(heights) > 1 else 0
                second_names = (
                    daily.filter(pl.col("board_height") == second_height)["name"]
                    .drop_nulls()
                    .head(5)
                    .to_list()
                    if second_height
                    else []
                )
                height_history.append(
                    {
                        "date": trade_day.strftime("%Y%m%d"),
                        "height": heights[0],
                        "name": leader.get("name") or "",
                        "names": highest["name"].drop_nulls().head(5).to_list(),
                        "second_height": second_height,
                        "second_names": second_names,
                        "turnover_pct": leader.get("turnover_pct"),
                        "amount_yi": leader.get("amount_yi"),
                    }
                )
            section["height_history"] = height_history[-60:]
        fields.extend(
            [
                "sections.s3.ladder_grid",
                "sections.s3.ladder_detail",
                "sections.s3.height_history",
            ]
        )

    def _apply_sectors(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        frame = _preferred(
            self.facts.get_sector_flows(day), DatasetId.SECTOR_FLOW_DAILY
        )
        if frame.is_empty():
            return
        rows = [
            {
                "name": row["sector_name"],
                "pct_chg": row.get("pct_chg"),
                "net_inflow_yi": row.get("net_inflow_yi"),
                "amount_yi": row.get("amount_yi"),
            }
            for row in frame.to_dicts()
        ]
        top_in = sorted(
            rows, key=lambda row: row.get("net_inflow_yi") or 0, reverse=True
        )[:5]
        top_out = sorted(rows, key=lambda row: row.get("net_inflow_yi") or 0)[:5]
        treemap = [
            {
                "name": row["name"],
                "value": row.get("net_inflow_yi"),
                "pct_chg": row.get("pct_chg"),
            }
            for row in sorted(
                rows,
                key=lambda row: abs(row.get("net_inflow_yi") or 0),
                reverse=True,
            )[:60]
        ]
        section = _section(snapshot, "s4")
        section["sector_flow"] = {"top_in": top_in, "top_out": top_out}
        section["sector_treemap"] = treemap
        fields.extend(["sections.s4.sector_flow", "sections.s4.sector_treemap"])

    def _apply_candidates(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        frame = self.facts.get_screening_candidates(day).filter(
            pl.col("included")
            & (pl.col("candidate_type") != "new_high_100d")
        )
        if frame.is_empty():
            return
        frame = frame.sort(
            ["priority", "score", "symbol"],
            descending=[False, True, False],
            nulls_last=True,
        )
        _section(snapshot, "s5")["candidates"] = [
            {
                "code": row["symbol"],
                "name": row.get("name") or "",
                "limit_times": None,
                "reason": ", ".join(row.get("rules_matched") or []),
                "score": row.get("score"),
                "priority": row.get("priority"),
            }
            for row in frame.head(6).to_dicts()
        ]
        fields.append("sections.s5.candidates")

    def _apply_new_high(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        frame = self.facts.get_screening_candidates(day).filter(
            pl.col("included")
            & (pl.col("candidate_type") == "new_high_100d")
        )
        if frame.is_empty():
            return
        _section(snapshot, "s2")["new_high"] = {
            "status": "ok",
            "stocks": [
                {
                    "code": row["symbol"],
                    "name": row.get("name") or "",
                    "pct_chg": row.get("pct_chg"),
                }
                for row in frame.sort("symbol").to_dicts()
            ],
        }
        fields.append("sections.s2.new_high")

    def _apply_indexes(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        if self.indexes is None or not hasattr(self.indexes, "get_index_daily"):
            return
        section = _section(snapshot, "s1")
        cached_rows = section.get("indexes") or []
        cached_by_code = {
            str(row.get("code") or ""): row
            for row in cached_rows
            if isinstance(row, dict)
        }
        updated = []
        for display_code, storage_code in (
            ("000001.SH", "000001.SH"),
            ("399001.SZ", "399001.SZ"),
            ("399006.SZ", "399006.SZ"),
            ("000688.SH", "000688.SH"),
            ("000300.SH", "000300.SH"),
            ("000016.SH", "000016.SH"),
            ("399303.SZ", "399303.SZ"),
            ("399905.SZ", "399905.SZ"),
            (QUANTX_ALL_A_DISPLAY_SYMBOL, QUANTX_ALL_A_STORAGE_SYMBOL),
        ):
            try:
                frame = self.indexes.get_index_daily(
                    storage_code,
                    day - timedelta(days=10),
                    day,
                    ["symbol", "date", "close"],
                )
            except (OSError, RuntimeError, ValueError):
                continue
            if frame.is_empty():
                continue
            frame = frame.sort("date")
            row = frame.row(-1, named=True)
            previous_close = (
                frame["close"][-2] if frame.height > 1 else None
            )
            pct_chg = (
                round((row["close"] / previous_close - 1) * 100, 2)
                if previous_close not in (None, 0) and row.get("close") is not None
                else None
            )
            previous = cached_by_code.get(display_code, {})
            updated.append(
                {
                    **previous,
                    "code": display_code,
                    "name": previous.get("name") or INDEX_DISPLAY_NAMES[display_code],
                    "close": row.get("close"),
                    "pct_chg": pct_chg,
                }
            )
        if updated:
            section["indexes"] = updated
            strip = snapshot.setdefault("metric_strip", {})
            strip_rows = {
                str(row.get("code") or ""): row
                for row in strip.get("indexes") or []
                if isinstance(row, dict)
            }
            strip["indexes"] = [
                {**strip_rows.get(row["code"], {}), **row} for row in updated[:4]
            ]
            fields.extend(["metric_strip.indexes", "sections.s1.indexes"])

    def _apply_kline_history(
        self,
        snapshot: dict[str, Any],
        day: date,
        fields: list[str],
    ) -> None:
        if self.indexes is None or not hasattr(self.indexes, "get_index_daily"):
            return
        try:
            frame = self.indexes.get_index_daily(
                QUANTX_ALL_A_STORAGE_SYMBOL,
                day - timedelta(days=240),
                day,
                ["symbol", "date", "open", "high", "low", "close", "volume"],
            )
        except (OSError, RuntimeError, ValueError):
            return
        required = {"date", "open", "high", "low", "close"}
        if frame.is_empty() or not required.issubset(frame.columns):
            return
        frame = frame.sort("date")
        typical_price = (
            pl.col("high") + pl.col("low") + pl.col("close")
        ) / 3
        frame = (
            frame.with_columns(typical_price.alias("_typical_price"))
            .with_columns(
                pl.col("close").rolling_mean(5).alias("ma5"),
                pl.col("close").rolling_mean(10).alias("ma10"),
                pl.col("close").rolling_mean(20).alias("ma20"),
                pl.col("_typical_price").rolling_mean(5).alias("_typical_ma5"),
                pl.col("_typical_price")
                .rolling_map(
                    lambda values: (values - values.mean()).abs().mean(),
                    window_size=5,
                )
                .alias("_mean_deviation5"),
            )
            .with_columns(
                pl.when(pl.col("_mean_deviation5") > 0)
                .then(
                    (pl.col("_typical_price") - pl.col("_typical_ma5"))
                    / (0.015 * pl.col("_mean_deviation5"))
                )
                .otherwise(None)
                .alias("cci5")
            )
            .tail(130)
        )
        rows = []
        for row in frame.to_dicts():
            rows.append(
                {
                    "date": row["date"].strftime("%Y%m%d"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "vol": row.get("volume"),
                    "ma5": round(row["ma5"], 2) if row.get("ma5") is not None else None,
                    "ma10": round(row["ma10"], 2) if row.get("ma10") is not None else None,
                    "ma20": round(row["ma20"], 2) if row.get("ma20") is not None else None,
                    "cci5": round(row["cci5"], 1) if row.get("cci5") is not None else None,
                }
            )
        _section(snapshot, "s1")["kline_history"] = rows
        fields.append("sections.s1.kline_history")
