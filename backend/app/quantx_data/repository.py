"""Compatibility read model backed by canonical market facts.

The legacy QuantX JSON tables still carry presentation-only detail.  This
module overlays their core measurements with canonical facts and exposes a
small reconciliation report while the remaining datasets are migrated.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.market_facts.registry import DatasetId, get_route
from app.market_facts.repository import MarketFactRepository

from .catalog import load_tables


def _date(value: str):
    return datetime.strptime(value, "%Y%m%d").date()


def _differences(canonical: dict[str, Any], legacy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"canonical": value, "legacy": legacy.get(key)}
        for key, value in canonical.items()
        if legacy.get(key) != value
    }


def _status(differences: dict[str, Any]) -> str:
    return "mismatch" if differences else "match"


def _preferred_source(frame: pl.DataFrame, dataset_id: DatasetId) -> pl.DataFrame:
    if frame.is_empty() or "source" not in frame.columns:
        return frame
    for source in get_route(dataset_id).sources:
        rows = frame.filter(pl.col("source") == source)
        if not rows.is_empty():
            return rows
    return frame.head(0)


class QuantXTableRepository:
    """Return the stable QuantX table contract through the shared fact layer."""

    def __init__(self, quantx_dir: Path, facts: MarketFactRepository) -> None:
        self.quantx_dir = Path(quantx_dir)
        self.facts = facts

    def load(self, trade_date: str) -> dict[str, Any]:
        tables = deepcopy(load_tables(self.quantx_dir, trade_date))
        day = _date(trade_date)
        reconciliation: dict[str, Any] = {}
        canonical: list[str] = []
        fallback: list[str] = []

        for dataset_id, apply in (
            (DatasetId.MARKET_BREADTH_DAILY, self._apply_breadth),
            (DatasetId.MARKET_LIQUIDITY_DAILY, self._apply_liquidity),
            (DatasetId.LIMIT_EVENT_DAILY, self._apply_limits),
            (DatasetId.THEME_OBSERVATION_DAILY, self._apply_themes),
            (DatasetId.SECTOR_FLOW_DAILY, self._apply_sector_flows),
        ):
            if not self.facts.has_partition(dataset_id, day):
                fallback.append(dataset_id.value)
                reconciliation[dataset_id.value] = {"status": "legacy_fallback"}
                continue
            canonical.append(dataset_id.value)
            reconciliation[dataset_id.value] = apply(tables, day)

        tables["data_foundation"] = {
            "read_mode": "canonical_with_legacy_enrichment",
            "canonical_datasets": canonical,
            "legacy_fallback_datasets": fallback,
            "reconciliation": reconciliation,
        }
        return tables

    def _apply_breadth(self, tables: dict[str, Any], day) -> dict[str, Any]:
        frame = _preferred_source(
            self.facts.get_market_breadth(day), DatasetId.MARKET_BREADTH_DAILY
        )
        if frame.is_empty():
            canonical: dict[str, Any] = {}
        else:
            row = frame.row(0, named=True)
            canonical = {
                "up_count": row["up_count"],
                "down_count": row["down_count"],
                "flat_count": row["flat_count"],
                "total_count": row["total_count"],
                "up_ratio": row["up_ratio_pct"],
                "advance_decline": row["advance_decline"],
            }
        legacy = tables.get("market_breadth") or {}
        differences = _differences(canonical, legacy)
        tables["market_breadth"] = {**legacy, **canonical}
        overview = tables.get("market_overview")
        if isinstance(overview, dict):
            overview["breadth"] = {**(overview.get("breadth") or {}), **canonical}
        return {"status": _status(differences), "differences": differences}

    def _apply_liquidity(self, tables: dict[str, Any], day) -> dict[str, Any]:
        frame = _preferred_source(
            self.facts.get_market_liquidity(day),
            DatasetId.MARKET_LIQUIDITY_DAILY,
        )
        if frame.is_empty():
            canonical: dict[str, Any] = {}
        else:
            row = frame.row(0, named=True)
            canonical = {
                "total_amount_yi": row["total_amount_yi"],
                "top5_amount_yi": row["top5_amount_yi"],
                "top5pct_amount_yi": row.get("top5pct_amount_yi"),
                "top5pct_amount_ratio_pct": row.get(
                    "top5pct_amount_ratio_pct"
                ),
                "top20_amount_ratio_pct": row.get("top20_amount_ratio_pct"),
            }
        legacy = tables.get("market_liquidity") or {}
        differences = _differences(canonical, legacy)
        tables["market_liquidity"] = {**legacy, **canonical}
        overview = tables.get("market_overview")
        if isinstance(overview, dict) and canonical.get("total_amount_yi") is not None:
            overview["total_amount_yi"] = canonical["total_amount_yi"]
        return {"status": _status(differences), "differences": differences}

    def _apply_limits(self, tables: dict[str, Any], day) -> dict[str, Any]:
        frame = self.facts.get_limit_events(day)
        counts = {
            name: frame.filter(pl.col("event_type") == event).height
            for name, event in (
                ("limit_up_count", "limit_up"),
                ("broken_board_count", "broken_board"),
                ("limit_down_count", "limit_down"),
            )
        }
        legacy = tables.get("limit_summary") or {}
        differences = _differences(counts, legacy)
        tables["limit_summary"] = {**legacy, **counts}

        old_stocks = (tables.get("limit_stocks") or {}).get("stocks") or []
        old_by_code = {str(row.get("code") or row.get("symbol") or ""): row for row in old_stocks}
        limit_rows = []
        for row in frame.filter(pl.col("event_type") == "limit_up").to_dicts():
            code = row["symbol"]
            detail = dict(old_by_code.get(code, {}))
            detail.update(
                {
                    "code": code,
                    "name": row.get("name") or detail.get("name", ""),
                    "limit_times": row.get("board_height") or detail.get("limit_times") or 1,
                }
            )
            limit_rows.append(detail)
        container = tables.get("limit_stocks") or {}
        tables["limit_stocks"] = {**container, "stocks": limit_rows}
        return {"status": _status(differences), "differences": differences}

    def _apply_themes(self, tables: dict[str, Any], day) -> dict[str, Any]:
        frame = self.facts.get_theme_observations(day).filter(
            pl.col("source").is_in(["ths_hot", "pywencai"])
        )
        grouped = (
            frame.group_by("theme_name")
            .agg(pl.col("strength").fill_null(0).sum().alias("count"))
            .sort(["count", "theme_name"], descending=[True, False])
            if not frame.is_empty()
            else pl.DataFrame(schema={"theme_name": pl.String, "count": pl.Float64})
        )
        rankings = [
            {"name": row["theme_name"], "count": row["count"], "rank": rank}
            for rank, row in enumerate(grouped.to_dicts(), start=1)
        ]
        legacy_rows = (tables.get("theme_rankings") or {}).get("themes") or []
        legacy_counts = {str(row.get("name")): row.get("count") for row in legacy_rows}
        canonical_counts = {row["name"]: row["count"] for row in rankings}
        differences = _differences(canonical_counts, legacy_counts)
        snapshot = tables.get("theme_snapshot") or {}
        ranking_table = tables.get("theme_rankings") or {}
        tables["theme_snapshot"] = {**snapshot, "themes": rankings[:20]}
        tables["theme_rankings"] = {**ranking_table, "themes": rankings}
        return {"status": _status(differences), "differences": differences}

    def _apply_sector_flows(self, tables: dict[str, Any], day) -> dict[str, Any]:
        frame = _preferred_source(
            self.facts.get_sector_flows(day), DatasetId.SECTOR_FLOW_DAILY
        ).sort("net_inflow_yi", descending=True)
        sectors = [
            {
                "name": row["sector_name"],
                "pct_chg": row.get("pct_chg"),
                "net_inflow_yi": row.get("net_inflow_yi"),
                "amount_yi": row.get("amount_yi"),
            }
            for row in frame.to_dicts()
        ]
        legacy_rows = (tables.get("sector_fund_flow") or {}).get("sectors") or []
        legacy_values = {str(row.get("name")): row.get("net_inflow_yi") for row in legacy_rows}
        canonical_values = {row["name"]: row["net_inflow_yi"] for row in sectors}
        differences = _differences(canonical_values, legacy_values)
        flow = tables.get("sector_fund_flow") or {}
        rotation = tables.get("sector_rotation") or {}
        tables["sector_fund_flow"] = {**flow, "sectors": sectors}
        tables["sector_rotation"] = {
            **rotation,
            "top_in": sectors[:20],
            "top_out": list(reversed(sectors[-20:])) if sectors else [],
        }
        return {"status": _status(differences), "differences": differences}
