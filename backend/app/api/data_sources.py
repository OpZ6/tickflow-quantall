"""Read-only discovery and health API for the shared data foundation."""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from app.market_facts.registry import DATASETS, ROUTES, DatasetId, datasets_for_source
from app.market_facts.repository import MarketFactRepository
from app.market_facts.snapshots import SnapshotRetentionPolicy, SourceSnapshotStore
from app.quantx_data.collectors import SOURCE_SPECS

router = APIRouter(prefix="/api/data-sources", tags=["data-sources"])


def _data_root(request: Request) -> Path:
    return Path(request.app.state.repo.store.data_dir)


def _latest_manifest(data_root: Path) -> tuple[str | None, dict[str, Any]]:
    quantx_dir = data_root / "quantx"
    if not quantx_dir.is_dir():
        return None, {}
    for date_dir in sorted(quantx_dir.iterdir(), reverse=True):
        if not date_dir.is_dir() or len(date_dir.name) != 8 or not date_dir.name.isdigit():
            continue
        path = date_dir / "_data_manifest.json"
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            return date_dir.name, payload if isinstance(payload, dict) else {}
    return None, {}


@router.get("/datasets")
def datasets() -> dict[str, Any]:
    return {
        "datasets": [
            {
                "dataset_id": spec.dataset_id.value,
                "description": spec.description,
                "schema_version": spec.schema_version,
                "primary_key": list(spec.primary_key),
                "partition_keys": list(spec.partition_keys),
                "required_columns": list(spec.required_columns),
                "field_units": dict(spec.field_units),
                "freshness": spec.freshness,
            }
            for spec in DATASETS.values()
        ]
    }


@router.get("/sources")
def sources() -> dict[str, Any]:
    rows = [
        {
            "source_id": "tickflow_enriched_aggregate",
            "display_name": "TickFlow enriched aggregate",
            "supported_datasets": ["trading_calendar", "market_breadth_daily"],
            "collector_type": "provider",
            "collector": "market_fact_adapter",
            "credentials_ref": None,
            "credentials_configured": True,
            "dependency_available": True,
            "max_retries": 0,
            "freshness_required": True,
        },
        {
            "source_id": "enriched_ohlcv_proxy",
            "display_name": "TickFlow OHLCV proxy",
            "supported_datasets": ["sector_flow_daily"],
            "collector_type": "provider",
            "collector": "market_fact_adapter",
            "credentials_ref": None,
            "credentials_configured": True,
            "dependency_available": True,
            "max_retries": 0,
            "freshness_required": True,
        },
        {
            "source_id": "tickflow_published_fact",
            "display_name": "TickFlow published canonical fact",
            "supported_datasets": ["trading_calendar"],
            "collector_type": "provider",
            "collector": "market_fact_adapter",
            "credentials_ref": None,
            "credentials_configured": True,
            "dependency_available": True,
            "max_retries": 0,
            "freshness_required": True,
        },
        {
            "source_id": "quantx_deterministic_v1",
            "display_name": "QuantX deterministic state derivation",
            "supported_datasets": ["market_state_daily"],
            "collector_type": "provider",
            "collector": "deterministic_derivation",
            "credentials_ref": None,
            "credentials_configured": True,
            "dependency_available": True,
            "max_retries": 0,
            "freshness_required": True,
        },
        {
            "source_id": "quantx_rule_screen_v1",
            "display_name": "QuantX deterministic rule screen",
            "supported_datasets": ["screening_candidate_daily"],
            "collector_type": "provider",
            "collector": "deterministic_derivation",
            "credentials_ref": None,
            "credentials_configured": True,
            "dependency_available": True,
            "max_retries": 0,
            "freshness_required": True,
        },
    ]
    for spec in SOURCE_SPECS:
        package = "tushare" if spec.collector == "tushare" else None
        rows.append(
            {
                "source_id": spec.name,
                "display_name": spec.name,
                "supported_datasets": [item.value for item in datasets_for_source(spec.name)],
                "collector_type": "provider" if spec.collector == "tushare" else "python",
                "collector": spec.collector,
                "credentials_ref": "TUSHARE_TOKEN" if spec.name == "tushare" else None,
                "credentials_configured": bool(os.environ.get("TUSHARE_TOKEN")) if spec.name == "tushare" else True,
                "dependency_available": importlib.util.find_spec(package) is not None if package else True,
                "max_retries": spec.max_retries,
                "freshness_required": spec.freshness_required,
            }
        )
    return {"sources": rows}


@router.get("/routes")
def routes() -> dict[str, Any]:
    return {
        "routes": [
            {"dataset_id": dataset_id.value, "sources": list(route.sources)}
            for dataset_id, route in ROUTES.items()
        ]
    }


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    data_root = _data_root(request)
    trade_date, manifest = _latest_manifest(data_root)
    source_states = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else {}
    fact_repo = MarketFactRepository(data_root)
    try:
        retention_policy = SnapshotRetentionPolicy.from_environment()
        retention_plan = SourceSnapshotStore(data_root).plan_retention(retention_policy)
        retention = {
            "dry_run": True,
            "retention_days": retention_plan.retention_days,
            "cutoff_date": retention_plan.cutoff_date.isoformat(),
            "metadata_count": retention_plan.metadata_count,
            "blob_count": retention_plan.blob_count,
            "bytes_reclaimable": retention_plan.bytes_reclaimable,
        }
    except ValueError as exc:
        retention = {"status": "invalid_configuration", "error": str(exc)}
    return {
        "latest_trade_date": trade_date,
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status") or ("never_run" if trade_date is None else "unknown"),
        "sources": [
            {
                "source_id": spec.name,
                **(
                    source_states.get(spec.name)
                    if isinstance(source_states.get(spec.name), dict)
                    else {"status": "unknown"}
                ),
            }
            for spec in SOURCE_SPECS
        ],
        "datasets": [
            {
                "dataset_id": dataset_id.value,
                "partition_count": len(available := fact_repo.available_dates(dataset_id)),
                "latest_partition": available[-1].isoformat() if available else None,
            }
            for dataset_id in DatasetId
        ],
        "snapshot_retention": retention,
    }


@router.get("/calendar")
def calendar(request: Request, start: date, end: date, exchange: str = "SSE") -> dict[str, Any]:
    frame = MarketFactRepository(_data_root(request)).get_trading_calendar(
        start,
        end,
        exchange=exchange.upper(),
    )
    return {
        "exchange": exchange.upper(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "calendar": frame.to_dicts(),
    }
