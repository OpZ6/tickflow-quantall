"""Canonical read model for the QuantX single-day rich dashboard."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from app.market_facts.registry import DatasetId, get_route
from app.market_facts.repository import MarketFactRepository

from .io import read_json


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


def _section(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    sections = snapshot.setdefault("sections", {})
    section = sections.setdefault(name, {})
    return section if isinstance(section, dict) else {}


class QuantXReviewRepository:
    """Overlay reusable facts onto the immutable rich-dashboard cache.

    ``review_data.json`` remains a presentation cache for fields that have no
    shared dataset yet. Reusable market values are always replaced from the
    canonical fact and TickFlow repositories before the API responds.
    """

    _PRESENTATION_CACHE_FIELDS = (
        "sections.s0.diagnosis_details",
        "sections.s0.risks",
        "sections.s1.kline_history.000985.CSI",
        "sections.s1.width_heat",
        "sections.s1.futures",
        "sections.s1.congestion",
        "sections.s3.ebb_signals",
        "sections.s3.crash_signals",
        "sections.s3.advance_history",
        "sections.s3.ladder_detail.supplemental_fields",
        "sections.s4.institution",
        "sections.s4.dx_strength",
        "sections.s6.position_and_scenarios",
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

    def load(self, trade_date: str) -> dict[str, Any] | None:
        cached = read_json(self.quantx_dir / trade_date / "review_data.json")
        if not isinstance(cached, dict):
            return None
        snapshot = deepcopy(cached)
        selected_day = _day(trade_date)
        canonical_fields: list[str] = []

        self._apply_market(snapshot, selected_day, canonical_fields)
        self._apply_history(snapshot, selected_day, canonical_fields)
        self._apply_margin(snapshot, selected_day, canonical_fields)
        self._apply_themes(snapshot, selected_day, canonical_fields)
        self._apply_ladder(snapshot, selected_day, canonical_fields)
        self._apply_sectors(snapshot, selected_day, canonical_fields)
        self._apply_new_high(snapshot, selected_day, canonical_fields)
        self._apply_candidates(snapshot, selected_day, canonical_fields)
        self._apply_indexes(snapshot, selected_day, canonical_fields)

        snapshot["data_foundation"] = {
            "read_mode": "canonical_facts_with_presentation_cache",
            "cache_artifact": "review_data.json",
            "source_json_read": False,
            "canonical_fields": sorted(set(canonical_fields)),
            "presentation_cache_fields": list(self._PRESENTATION_CACHE_FIELDS),
        }
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
        for name, score_key, zone_key in (
            ("market_heat", "market_heat_score", "market_heat_zone"),
            ("short_term_sentiment", "short_term_sentiment_score", None),
            ("trend_sentiment", "trend_sentiment_score", None),
        ):
            target = emotion.setdefault(name, {})
            target["score"] = row.get(score_key)
            if zone_key is not None:
                target["zone"] = row.get(zone_key)
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
            for row in _preferred(
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
                "turnover_pct": None,
                "amount_yi": None,
            }
            for row in ladder.to_dicts()
        ]
        fields.extend(["sections.s3.ladder_grid", "sections.s3.ladder_detail.core"])

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
        for code in (
            "000001.SH",
            "399001.SZ",
            "399006.SZ",
            "000688.SH",
            "000300.SH",
            "000016.SH",
            "399303.SZ",
            "399905.SZ",
        ):
            try:
                frame = self.indexes.get_index_daily(
                    code,
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
            previous = cached_by_code.get(code, {})
            updated.append(
                {
                    **previous,
                    "code": code,
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
