"""Dataset and source routing contracts for canonical market facts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

import polars as pl


class DatasetId(StrEnum):
    TRADING_CALENDAR = "trading_calendar"
    MARKET_BREADTH_DAILY = "market_breadth_daily"
    MARKET_LIQUIDITY_DAILY = "market_liquidity_daily"
    MARGIN_DAILY = "margin_daily"
    LIMIT_EVENT_DAILY = "limit_event_daily"
    LIMIT_LADDER_DAILY = "limit_ladder_daily"
    THEME_OBSERVATION_DAILY = "theme_observation_daily"
    THEME_MEMBER_DAILY = "theme_member_daily"
    SECTOR_FLOW_DAILY = "sector_flow_daily"
    MARKET_STATE_DAILY = "market_state_daily"
    MARKET_SIGNAL_DAILY = "market_signal_daily"
    SCREENING_CANDIDATE_DAILY = "screening_candidate_daily"


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
        DatasetId.TRADING_CALENDAR: DatasetSpec(
            dataset_id=DatasetId.TRADING_CALENDAR,
            description="Point-in-time exchange trading calendar",
            schema_version=1,
            primary_key=("exchange", "trade_date"),
            partition_keys=("as_of_date",),
            required_columns=(
                "trade_date",
                "as_of_date",
                "exchange",
                "is_open",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "as_of_date": pl.Date,
                    "exchange": pl.String,
                    "is_open": pl.Boolean,
                    "previous_open_date": pl.Date,
                }
            ),
            field_units=MappingProxyType({}),
        ),
        DatasetId.MARKET_BREADTH_DAILY: DatasetSpec(
            dataset_id=DatasetId.MARKET_BREADTH_DAILY,
            description="A-share daily advancing, declining and flat counts",
            schema_version=2,
            primary_key=("trade_date", "market"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "market",
                "up_count",
                "down_count",
                "flat_count",
                "unknown_count",
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
                    "unknown_count": pl.Int64,
                    "total_count": pl.Int64,
                    "up_ratio_pct": pl.Float64,
                    "advance_decline": pl.Int64,
                }
            ),
            field_units=MappingProxyType({"up_ratio_pct": "percent"}),
        ),
        DatasetId.MARKET_LIQUIDITY_DAILY: DatasetSpec(
            dataset_id=DatasetId.MARKET_LIQUIDITY_DAILY,
            description="A-share daily turnover and concentration metrics",
            schema_version=3,
            primary_key=("trade_date", "market"),
            partition_keys=("trade_date",),
            required_columns=("trade_date", "market", "total_amount_yi"),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "market": pl.String,
                    "total_amount_yi": pl.Float64,
                    "top5_amount_yi": pl.Float64,
                    "top5pct_amount_yi": pl.Float64,
                    "top5_amount_ratio_pct": pl.Float64,
                    "top5pct_amount_ratio_pct": pl.Float64,
                    "top20_amount_ratio_pct": pl.Float64,
                    "volume_ratio_pct": pl.Float64,
                }
            ),
            field_units=MappingProxyType(
                {
                    "total_amount_yi": "CNY_100M",
                    "top5_amount_yi": "CNY_100M",
                    "top5pct_amount_yi": "CNY_100M",
                    "top5_amount_ratio_pct": "percent",
                    "top5pct_amount_ratio_pct": "percent",
                    "top20_amount_ratio_pct": "percent",
                    "volume_ratio_pct": "percent",
                }
            ),
        ),
        DatasetId.MARGIN_DAILY: DatasetSpec(
            dataset_id=DatasetId.MARGIN_DAILY,
            description="Point-in-time A-share margin financing history",
            schema_version=1,
            primary_key=("scope", "trade_date"),
            partition_keys=("as_of_date",),
            required_columns=(
                "trade_date",
                "as_of_date",
                "scope",
                "financing_balance_yi",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "as_of_date": pl.Date,
                    "scope": pl.String,
                    "financing_balance_yi": pl.Float64,
                    "financing_net_buy_yi": pl.Float64,
                }
            ),
            field_units=MappingProxyType(
                {
                    "financing_balance_yi": "CNY_100M",
                    "financing_net_buy_yi": "CNY_100M",
                }
            ),
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
        DatasetId.LIMIT_LADDER_DAILY: DatasetSpec(
            dataset_id=DatasetId.LIMIT_LADDER_DAILY,
            description="Daily consecutive limit-up ladder membership",
            schema_version=1,
            primary_key=("trade_date", "board_height", "symbol"),
            partition_keys=("trade_date",),
            required_columns=("trade_date", "board_height", "symbol", "exchange"),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "board_height": pl.UInt32,
                    "symbol": pl.String,
                    "exchange": pl.String,
                    "asset_type": pl.String,
                    "source_code": pl.String,
                    "name": pl.String,
                    "theme_name": pl.String,
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
        DatasetId.THEME_MEMBER_DAILY: DatasetSpec(
            dataset_id=DatasetId.THEME_MEMBER_DAILY,
            description="Point-in-time stock membership observed for a theme",
            schema_version=1,
            primary_key=("trade_date", "source", "theme_id", "symbol"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "source",
                "theme_id",
                "theme_name",
                "symbol",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "theme_id": pl.String,
                    "theme_name": pl.String,
                    "symbol": pl.String,
                    "exchange": pl.String,
                    "asset_type": pl.String,
                    "name": pl.String,
                    "role": pl.String,
                }
            ),
            field_units=MappingProxyType({}),
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
        DatasetId.MARKET_STATE_DAILY: DatasetSpec(
            dataset_id=DatasetId.MARKET_STATE_DAILY,
            description="Deterministic daily QuantX market and sentiment state",
            schema_version=1,
            primary_key=("trade_date", "market"),
            partition_keys=("trade_date",),
            required_columns=("trade_date", "market", "algorithm_version"),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "market": pl.String,
                    "market_heat_score": pl.Float64,
                    "market_heat_zone": pl.String,
                    "short_term_sentiment_score": pl.Float64,
                    "trend_sentiment_score": pl.Float64,
                    "sentiment_semantics_version": pl.UInt32,
                    "up_ratio_pct": pl.Float64,
                    "up_count": pl.Int64,
                    "down_count": pl.Int64,
                    "limit_up_count": pl.Int64,
                    "limit_down_count": pl.Int64,
                    "seal_rate_pct": pl.Float64,
                    "max_board": pl.UInt32,
                    "advance_rate_pct": pl.Float64,
                    "premium_rate_pct": pl.Float64,
                    "loss_severity": pl.String,
                    "ebb_signal_count": pl.UInt32,
                    "crash_triggered": pl.Boolean,
                    "participation_verdict": pl.String,
                    "total_amount_yi": pl.Float64,
                    "algorithm_version": pl.String,
                    "input_generation": pl.String,
                }
            ),
            field_units=MappingProxyType(
                {
                    "market_heat_score": "score",
                    "short_term_sentiment_score": "score",
                    "trend_sentiment_score": "score",
                    "up_ratio_pct": "percent",
                    "seal_rate_pct": "percent",
                    "advance_rate_pct": "percent",
                    "premium_rate_pct": "percent",
                    "total_amount_yi": "CNY_100M",
                }
            ),
        ),
        DatasetId.MARKET_SIGNAL_DAILY: DatasetSpec(
            dataset_id=DatasetId.MARKET_SIGNAL_DAILY,
            description="Deterministic participation, ebb and crash signals",
            schema_version=1,
            primary_key=("trade_date", "market", "signal_group", "signal_id"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "market",
                "signal_group",
                "signal_id",
                "algorithm_version",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "market": pl.String,
                    "signal_group": pl.String,
                    "signal_id": pl.String,
                    "signal_name": pl.String,
                    "ok": pl.Boolean,
                    "triggered": pl.Boolean,
                    "available": pl.Boolean,
                    "status": pl.String,
                    "group_verdict": pl.String,
                    "value_json": pl.String,
                    "baseline_json": pl.String,
                    "evidence": pl.String,
                    "algorithm_version": pl.String,
                    "input_generation": pl.String,
                }
            ),
            field_units=MappingProxyType({}),
        ),
        DatasetId.SCREENING_CANDIDATE_DAILY: DatasetSpec(
            dataset_id=DatasetId.SCREENING_CANDIDATE_DAILY,
            description="Daily rule-screen and observed signal candidates",
            schema_version=1,
            primary_key=("trade_date", "candidate_type", "symbol"),
            partition_keys=("trade_date",),
            required_columns=(
                "trade_date",
                "candidate_type",
                "symbol",
                "algorithm_version",
            ),
            storage_schema=_schema(
                {
                    "trade_date": pl.Date,
                    "symbol": pl.String,
                    "exchange": pl.String,
                    "asset_type": pl.String,
                    "name": pl.String,
                    "candidate_type": pl.String,
                    "priority": pl.String,
                    "score": pl.Float64,
                    "pct_chg": pl.Float64,
                    "net_mf_yi": pl.Float64,
                    "industry": pl.String,
                    "rules_matched": pl.List(pl.String),
                    "included": pl.Boolean,
                    "algorithm_version": pl.String,
                    "input_generation": pl.String,
                }
            ),
            field_units=MappingProxyType(
                {
                    "score": "score",
                    "pct_chg": "percent",
                    "net_mf_yi": "CNY_100M",
                }
            ),
        ),
    }
)


ROUTES: Mapping[DatasetId, SourceRoute] = MappingProxyType(
    {
        DatasetId.TRADING_CALENDAR: SourceRoute(
            DatasetId.TRADING_CALENDAR,
            ("tushare", "tickflow_enriched_aggregate", "tickflow_published_fact"),
        ),
        DatasetId.MARKET_BREADTH_DAILY: SourceRoute(
            DatasetId.MARKET_BREADTH_DAILY,
            ("tickflow_enriched_aggregate", "tushare", "pywencai"),
        ),
        DatasetId.MARKET_LIQUIDITY_DAILY: SourceRoute(
            DatasetId.MARKET_LIQUIDITY_DAILY,
            ("tickflow_enriched_aggregate", "tushare"),
        ),
        DatasetId.MARGIN_DAILY: SourceRoute(
            DatasetId.MARGIN_DAILY,
            ("tushare",),
        ),
        DatasetId.LIMIT_EVENT_DAILY: SourceRoute(
            DatasetId.LIMIT_EVENT_DAILY,
            ("pywencai", "zhangtingke", "zhangtingjun", "duanxianxia", "quicktiny", "dabanke"),
        ),
        DatasetId.LIMIT_LADDER_DAILY: SourceRoute(
            DatasetId.LIMIT_LADDER_DAILY,
            ("zhangtingke", "pywencai"),
        ),
        DatasetId.THEME_OBSERVATION_DAILY: SourceRoute(
            DatasetId.THEME_OBSERVATION_DAILY,
            ("ths_hot", "pywencai", "deepq"),
        ),
        DatasetId.THEME_MEMBER_DAILY: SourceRoute(
            DatasetId.THEME_MEMBER_DAILY,
            ("pywencai", "ths_hot"),
        ),
        DatasetId.SECTOR_FLOW_DAILY: SourceRoute(
            DatasetId.SECTOR_FLOW_DAILY,
            ("sector_fund_flow_s4", "akshare", "enriched_ohlcv_proxy"),
        ),
        DatasetId.MARKET_STATE_DAILY: SourceRoute(
            DatasetId.MARKET_STATE_DAILY,
            ("quantx_deterministic_v1",),
        ),
        DatasetId.MARKET_SIGNAL_DAILY: SourceRoute(
            DatasetId.MARKET_SIGNAL_DAILY,
            ("quantx_deterministic_v1",),
        ),
        DatasetId.SCREENING_CANDIDATE_DAILY: SourceRoute(
            DatasetId.SCREENING_CANDIDATE_DAILY,
            ("quantx_rule_screen_v1", "pywencai"),
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
