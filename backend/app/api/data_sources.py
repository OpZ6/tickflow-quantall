"""Read-only discovery and health API for the shared data foundation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from app.market_facts.registry import DATASETS, ROUTES, datasets_for_source
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
            "supported_datasets": ["market_breadth_daily"],
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
    trade_date, manifest = _latest_manifest(_data_root(request))
    source_states = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else {}
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
    }
