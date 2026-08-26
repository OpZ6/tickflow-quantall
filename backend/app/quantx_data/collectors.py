"""Data-source adapters used by the independent TickFlow pipeline.

Adapters are isolated from the deterministic calculation layer. Their output
is persisted as source data and never interpreted as editorial or LLM text.
"""
from __future__ import annotations

import importlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .io import read_json
from .schemas import SourceResult, SourceSpec

logger = logging.getLogger(__name__)

SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec("tushare", True, "tushare", "market", min_records=1),
    SourceSpec("akshare", False, "legacy:akshare_scraper", "market"),
    SourceSpec("ths_hot", False, "legacy:ths_hot_scraper", "theme"),
    SourceSpec("zhangtingke", False, "legacy:zhangtingke_scraper", "limit"),
    SourceSpec("zhangtingjun", False, "legacy:zhangtingjun_scraper", "limit"),
    SourceSpec("pywencai", True, "legacy:pywencai_scraper", "limit", min_records=1),
    SourceSpec("duanxianxia", False, "legacy:duanxianxia_scraper", "limit"),
    SourceSpec("deepq", False, "legacy:deepq_scraper", "theme"),
    SourceSpec("legulegu", False, "legacy:legulegu_scraper", "market"),
    SourceSpec("quicktiny", False, "legacy:quicktiny_scraper", "limit"),
    SourceSpec("dabanke", False, "legacy:dabanke_scraper", "limit"),
    SourceSpec("sector_fund_flow_s4", False, "legacy:sector_fund_flow_s4_scraper", "fund_flow"),
)

SPEC_BY_NAME = {item.name: item for item in SOURCE_SPECS}


def _count_records(payload: dict[str, Any]) -> int:
    counts: list[int] = []
    for key in ("stocks", "sectors", "records", "rows", "data", "daily", "indexes", "daily_basic"):
        value = payload.get(key)
        if isinstance(value, list):
            counts.append(len(value))
        elif isinstance(value, dict):
            list_count = sum(len(item) for item in value.values() if isinstance(item, list))
            if list_count:
                counts.append(list_count)
            elif value and all(isinstance(item, dict) for item in value.values()):
                counts.append(len(value))
    if counts:
        return max(counts)
    for value in payload.values():
        if isinstance(value, dict):
            count = _count_records(value)
            if count:
                return count
    return 0


def _payload_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "ok").lower()
    if status in {"ok", "complete", "partial", "degraded"}:
        return "ok" if status == "complete" else status
    if status in {"unavailable", "error", "failed"}:
        return "error"
    return "ok" if _count_records(payload) else "empty"


def _load_existing(date_dir: Path, name: str) -> dict[str, Any] | None:
    candidates = (date_dir / "normalized" / f"{name}.json", date_dir / f"{name}.json")
    for path in candidates:
        payload = read_json(path)
        if isinstance(payload, dict) and payload:
            return payload
    return None


def _collect_tushare(trade_date: str, output_dir: Path | None = None) -> dict[str, Any]:
    """Fetch Tushare market, breadth, calendar and liquidity facts."""
    module = importlib.import_module("app.quantx_data.legacy_scrapers.tushare_scraper")
    path = module.run(trade_date, str(output_dir or Path(".")))
    payload = read_json(Path(path), {})
    if not isinstance(payload, dict):
        raise RuntimeError("tushare returned a non-object payload")
    return payload


def _collect_legacy(module_name: str, trade_date: str, output_dir: Path, source: str) -> dict[str, Any]:
    module = importlib.import_module(f"app.quantx_data.legacy_scrapers.{module_name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = module.run(trade_date, str(output_dir))
    payload = read_json(Path(path), {})
    if not isinstance(payload, dict):
        raise RuntimeError(f"{source} returned a non-object payload")
    return payload


def collect_source(
    spec: SourceSpec,
    trade_date: str,
    date_dir: Path,
    *,
    read_dir: Path | None = None,
    force: bool = False,
    allow_network: bool = True,
) -> SourceResult:
    existing = None if force else _load_existing(read_dir or date_dir, spec.name)
    if existing is not None:
        observed_date = str(existing.get("trade_date") or existing.get("as_of") or "")
        if spec.freshness_required and observed_date != trade_date:
            return SourceResult(
                name=spec.name,
                status="stale",
                payload=existing,
                source=str(existing.get("source") or "tickflow_snapshot"),
                error=f"payload date {observed_date} != requested {trade_date}",
                record_count=_count_records(existing),
                reused_snapshot=True,
                attempts=1,
            )
        status = _payload_status(existing)
        return SourceResult(
            name=spec.name,
            status=status,
            payload=existing,
            source=str(existing.get("source") or "tickflow_snapshot"),
            record_count=_count_records(existing),
            collected_at=str(existing.get("scraped_at") or existing.get("collected_at") or ""),
            input_path=str(date_dir / f"{spec.name}.json"),
            reused_snapshot=True,
            attempts=1,
        )

    if not allow_network:
        return SourceResult(name=spec.name, status="missing", error="no reusable snapshot; recompute is offline")

    last_error: str | None = None
    for attempt in range(spec.max_retries + 1):
        try:
            if spec.collector == "tushare":
                payload = _collect_tushare(trade_date, date_dir / "raw")
            else:
                module_name = spec.collector.split(":", 1)[1]
                payload = _collect_legacy(module_name, trade_date, date_dir / "raw", spec.name)
            status = _payload_status(payload)
            if status == "error" and attempt < spec.max_retries:
                time.sleep(0.25 * (attempt + 1))
                continue
            return SourceResult(
                name=spec.name,
                status=status,
                payload=payload,
                source=str(payload.get("source") or spec.name),
                record_count=_count_records(payload),
                collected_at=str(payload.get("scraped_at") or datetime.now().isoformat(timespec="seconds")),
                attempts=attempt + 1,
            )
        except Exception as exc:  # source isolation is intentional; quality decides final status
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("QuantX source %s failed (attempt %d/%d): %s", spec.name, attempt + 1, spec.max_retries + 1, exc)
            if attempt < spec.max_retries:
                time.sleep(0.25 * (attempt + 1))
                continue
            break
    return SourceResult(name=spec.name, status="error", error=last_error, attempts=spec.max_retries + 1)


def source_specs(names: list[str] | None = None) -> list[SourceSpec]:
    if not names:
        return list(SOURCE_SPECS)
    unknown = sorted(set(names) - set(SPEC_BY_NAME))
    if unknown:
        raise ValueError(f"unknown QuantX source(s): {', '.join(unknown)}")
    return [SPEC_BY_NAME[name] for name in names]
