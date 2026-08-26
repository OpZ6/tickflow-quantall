"""Dataset and source routing contracts for canonical market facts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

import polars as pl


class DatasetId(StrEnum):
    MARKET_BREADTH_DAILY = "market_breadth_daily"
    LIMIT_EVENT_DAILY = "limit_event_daily"
    THEME_OBSERVATION_DAILY = "theme_observation_daily"
    SECTOR_FLOW_DAILY = "sector_flow_daily"


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: DatasetId
    description: str
    schema_version: int
    primary_key: tuple[str, ...]
    partition_keys: tuple[str, ...]
    required_columns: tuple[str, ...]
    storage_schema: Mapping[str, pl.DataType]
    field_units: Mapping[str, str]
    freshness: str = "trade_date"


@dataclass(frozen=True)
class SourceRoute:
    dataset_id: DatasetId
    sources: tuple[str, ...]


_COMMON_SCHEMA: dict[str, pl.DataType] = {
    "source": pl.String,
    "source_record_id": pl.String,
    "observed_at": pl.String,
    "ingested_at": pl.String,
    "run_id": pl.String,
    "schema_version": pl.UInt32,
    "quality_level": pl.String,
    "is_fallback": pl.Boolean,
}


def _schema(fields: dict[str, pl.DataType]) -> Mapping[str, pl.DataType]:
    return MappingProxyType({**fields, **_COMMON_SCHEMA})


DATASETS: Mapping[DatasetId, DatasetSpec] = MappingProxyType(
    {
        DatasetId.MARKET_BREADTH_DAILY: DatasetSpec(
            dataset_id=DatasetId.MARKET_BREADTH_DAILY,
            description="A-share daily advancing, declining and flat counts",
            schema_version=1,
            primary_key=("trade_date", "market"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "market",
                "up_count",
                "down_count",
                "flat_count",
                "total_count",
                "up_ratio_pct",
                "advance_decline",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "market": pl.String,
                    "up_count": pl.Int64,
                    "down_count": pl.Int64,
                    "flat_count": pl.Int64,
                    "total_count": pl.Int64,
                    "up_ratio_pct": pl.Float64,
                    "advance_decline": pl.Int64,
                }
            ),
            field_units=MappingProxyType({"up_ratio_pct": "percent"}),
        ),
        DatasetId.LIMIT_EVENT_DAILY: DatasetSpec(
            dataset_id=DatasetId.LIMIT_EVENT_DAILY,
            description="Daily stock limit-up, limit-down and broken-board events",
            schema_version=1,
            primary_key=("trade_date", "symbol", "event_type"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "symbol",
                "exchange",
                "asset_type",
                "event_type",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "symbol": pl.String,
                    "exchange": pl.String,
                    "asset_type": pl.String,
                    "source_code": pl.String,
                    "name": pl.String,
                    "event_type": pl.String,
                    "board_height": pl.UInt32,
                }
            ),
            field_units=MappingProxyType({}),
        ),
        DatasetId.THEME_OBSERVATION_DAILY: DatasetSpec(
            dataset_id=DatasetId.THEME_OBSERVATION_DAILY,
            description="Source-level daily theme observations",
            schema_version=1,
            primary_key=("trade_date", "source", "theme_id"),
            partition_keys=("trade_date",),
            required_columns=("trade_date", "source", "theme_id", "theme_name"),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "theme_id": pl.String,
                    "theme_name": pl.String,
                    "rank": pl.UInt32,
                    "stock_count": pl.UInt32,
                    "strength": pl.Float64,
                }
            ),
            field_units=MappingProxyType({"strength": "score"}),
        ),
        DatasetId.SECTOR_FLOW_DAILY: DatasetSpec(
            dataset_id=DatasetId.SECTOR_FLOW_DAILY,
            description="Observed or explicitly labelled proxy sector fund flow",
            schema_version=1,
            primary_key=("trade_date", "source", "sector_id"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "source",
                "sector_id",
                "sector_name",
                "net_inflow_yi",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "sector_id": pl.String,
                    "sector_name": pl.String,
                    "dimension": pl.String,
                    "pct_chg": pl.Float64,
                    "net_inflow_yi": pl.Float64,
                    "amount_yi": pl.Float64,
                }
            ),
            field_units=MappingProxyType(
                {
                    "pct_chg": "percent",
                    "net_inflow_yi": "CNY_100M",
                    "amount_yi": "CNY_100M",
                }
            ),
        ),
    }
)


ROUTES: Mapping[DatasetId, SourceRoute] = MappingProxyType(
    {
        DatasetId.MARKET_BREADTH_DAILY: SourceRoute(
            DatasetId.MARKET_BREADTH_DAILY,
            ("tickflow_enriched_aggregate", "tushare", "pywencai"),
        ),
        DatasetId.LIMIT_EVENT_DAILY: SourceRoute(
            DatasetId.LIMIT_EVENT_DAILY,
            ("pywencai", "zhangtingke", "zhangtingjun", "duanxianxia", "quicktiny", "dabanke"),
        ),
        DatasetId.THEME_OBSERVATION_DAILY: SourceRoute(
            DatasetId.THEME_OBSERVATION_DAILY,
            ("ths_hot", "pywencai", "deepq"),
        ),
        DatasetId.SECTOR_FLOW_DAILY: SourceRoute(
            DatasetId.SECTOR_FLOW_DAILY,
            ("sector_fund_flow_s4", "akshare", "enriched_ohlcv_proxy"),
        ),
    }
)


def get_dataset(dataset_id: DatasetId | str) -> DatasetSpec:
    return DATASETS[DatasetId(dataset_id)]


def get_route(dataset_id: DatasetId | str) -> SourceRoute:
    return ROUTES[DatasetId(dataset_id)]


def datasets_for_source(source_id: str) -> tuple[DatasetId, ...]:
    return tuple(
        dataset_id
        for dataset_id, route in ROUTES.items()
        if source_id in route.sources
    )
