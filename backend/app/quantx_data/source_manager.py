"""Unified registry and execution boundary for QuantX fact sources."""
from __future__ import annotations

import importlib
import importlib.util
import logging
import multiprocessing
import os
import queue
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .io import read_json
from .schemas import SourceResult, SourceSpec

logger = logging.getLogger(__name__)

SourceCollector = Callable[[str, Path], dict[str, Any]]
DependencyCheck = Callable[[], tuple[bool, str]]


def count_records(payload: dict[str, Any]) -> int:
    """Return the largest meaningful row collection in a source payload."""
    counts: list[int] = []
    for key in (
        "stocks",
        "sectors",
        "records",
        "rows",
        "data",
        "daily",
        "indexes",
        "daily_basic",
    ):
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
            count = count_records(value)
            if count:
                return count
    return 0


def payload_status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "ok").lower()
    if status in {"ok", "complete", "partial", "degraded"}:
        return "ok" if status == "complete" else status
    if status in {"unavailable", "error", "failed"}:
        return "error"
    return "ok" if count_records(payload) else "empty"


def classify_source_error(exc: BaseException) -> str:
    """Map source failures to stable operational categories."""
    message = str(exc).lower()
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "dependency"
    if "401" in message or "403" in message or "token" in message or "auth" in message:
        return "authentication"
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return "rate_limit"
    if isinstance(exc, TimeoutError) or "timeout" in message or "timed out" in message:
        return "timeout"
    if isinstance(exc, (ConnectionError, OSError)) or any(
        marker in message
        for marker in ("connection", "dns", "network", "proxy", "ssl")
    ):
        return "network"
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return "parse"
    return "unknown"


def dependency_modules_check(modules: tuple[str, ...]) -> DependencyCheck:
    def check() -> tuple[bool, str]:
        missing = [name for name in modules if importlib.util.find_spec(name) is None]
        if missing:
            return False, f"missing dependency: {', '.join(missing)}"
        return True, "ok"

    return check


def collect_from_descriptor(
    collector_ref: str,
    source_id: str,
    trade_date: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Execute a serializable collector descriptor in an isolated process."""
    if collector_ref == "tushare":
        module_name = "app.quantx_data.legacy_scrapers.tushare_scraper"
    elif collector_ref.startswith("legacy:"):
        module_name = f"app.quantx_data.legacy_scrapers.{collector_ref.split(':', 1)[1]}"
    elif collector_ref.startswith("module:"):
        module_name = collector_ref.split(":", 1)[1]
    else:
        raise ValueError(f"collector {collector_ref!r} is not process-isolatable")

    module = importlib.import_module(module_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = module.run(trade_date, str(output_dir))
    payload = result if isinstance(result, dict) else read_json(Path(result), {})
    if not isinstance(payload, dict):
        raise RuntimeError(f"{source_id} returned a non-object payload")
    return payload


def _collector_process(
    result_queue: multiprocessing.Queue,
    collector_ref: str,
    source_id: str,
    trade_date: str,
    output_dir: str,
) -> None:
    try:
        result_queue.put(
            ("ok", collect_from_descriptor(collector_ref, source_id, trade_date, Path(output_dir)))
        )
    except BaseException as exc:  # child boundary must serialize every source failure
        result_queue.put(("error", type(exc).__name__, str(exc)))


def _collect_with_timeout(
    spec: SourceSpec,
    trade_date: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Run one production collector with a cancellable wall-clock deadline."""
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_collector_process,
        args=(result_queue, spec.collector, spec.name, trade_date, str(output_dir)),
        daemon=False,
    )
    process.start()
    try:
        try:
            message = result_queue.get(timeout=spec.timeout_seconds)
        except queue.Empty as exc:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            raise TimeoutError(
                f"{spec.name} exceeded wall-clock timeout of {spec.timeout_seconds:g}s"
            ) from exc
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if not message or message[0] != "ok":
            error_type = message[1] if len(message) > 1 else "RuntimeError"
            error_message = message[2] if len(message) > 2 else "collector process failed"
            if error_type == "TimeoutError":
                raise TimeoutError(error_message)
            raise RuntimeError(f"{error_type}: {error_message}")
        return message[1]
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        result_queue.close()
        result_queue.join_thread()


class SourceManager:
    """Own source discovery, metadata and isolated collection execution."""

    def __init__(self) -> None:
        self._specs: dict[str, SourceSpec] = {}
        self._collectors: dict[str, SourceCollector] = {}
        self._dependency_checks: dict[str, DependencyCheck] = {}

    def register(
        self,
        spec: SourceSpec,
        collector: SourceCollector,
        *,
        dependency_check: DependencyCheck | None = None,
    ) -> None:
        source_id = spec.name.strip().lower()
        if not source_id or source_id != spec.name:
            raise ValueError("source name must be a non-empty lowercase identifier")
        if source_id in self._specs:
            raise ValueError(f"duplicate QuantX source: {source_id}")
        self._specs[source_id] = spec
        self._collectors[source_id] = collector
        self._dependency_checks[source_id] = dependency_check or dependency_modules_check(
            spec.dependency_modules
        )

    @property
    def specs(self) -> tuple[SourceSpec, ...]:
        return tuple(self._specs.values())

    @property
    def spec_by_name(self):
        return MappingProxyType(self._specs)

    def select(self, names: Iterable[str] | None = None) -> list[SourceSpec]:
        if not names:
            return list(self.specs)
        requested = list(names)
        unknown = sorted(set(requested) - set(self._specs))
        if unknown:
            raise ValueError(f"unknown QuantX source(s): {', '.join(unknown)}")
        return [self._specs[name] for name in requested]

    def describe(self, source_id: str) -> dict[str, Any]:
        spec = self._specs[source_id]
        available, reason = self._dependency_checks[source_id]()
        credentials_configured = bool(os.environ.get(spec.credentials_ref)) if spec.credentials_ref else True
        return {
            "source_id": spec.name,
            "display_name": spec.display_name or spec.name,
            "collector_type": spec.collector_type,
            "collector": spec.collector,
            "credentials_ref": spec.credentials_ref,
            "credentials_configured": credentials_configured,
            "credential_readiness": "ready" if credentials_configured else "missing",
            "dependency_available": available,
            "dependency_status": reason,
            "dependency_readiness": "ready" if available else "missing",
            "manifest_health": "not_evaluated",
            "live_probe": "not_run",
            "max_retries": spec.max_retries,
            "timeout_seconds": spec.timeout_seconds,
            "rate_limit_rpm": spec.rate_limit_rpm,
            "freshness_required": spec.freshness_required,
        }

    def collect(
        self,
        source_id: str,
        trade_date: str,
        date_dir: Path,
        *,
        read_dir: Path | None = None,
        force: bool = False,
        allow_network: bool = True,
    ) -> SourceResult:
        spec = self._specs[source_id]
        existing = None if force else self._load_existing(read_dir or date_dir, spec.name)
        if existing is not None:
            return self._existing_result(spec, trade_date, date_dir, existing)
        if not allow_network:
            return SourceResult(
                name=spec.name,
                status="missing",
                error="no reusable snapshot; recompute is offline",
                error_kind="missing",
            )

        available, reason = self._dependency_checks[source_id]()
        if not available:
            return SourceResult(
                name=spec.name,
                status="error",
                error=reason,
                error_kind="dependency",
                attempts=0,
            )

        last_error: str | None = None
        last_error_kind: str | None = None
        for attempt in range(spec.max_retries + 1):
            try:
                if spec.collector == "tushare" or spec.collector.startswith(("legacy:", "module:")):
                    payload = _collect_with_timeout(spec, trade_date, date_dir / "raw")
                else:
                    payload = self._collectors[source_id](trade_date, date_dir / "raw")
                if not isinstance(payload, dict):
                    raise TypeError(f"{source_id} returned a non-object payload")
                status = payload_status(payload)
                if status == "error" and attempt < spec.max_retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                return SourceResult(
                    name=spec.name,
                    status=status,
                    payload=payload,
                    source=str(payload.get("source") or spec.name),
                    record_count=count_records(payload),
                    collected_at=str(
                        payload.get("scraped_at")
                        or datetime.now().isoformat(timespec="seconds")
                    ),
                    attempts=attempt + 1,
                )
            except Exception as exc:  # source isolation is required by the pipeline
                last_error = f"{type(exc).__name__}: {exc}"
                last_error_kind = classify_source_error(exc)
                logger.warning(
                    "QuantX source %s failed (attempt %d/%d, kind=%s): %s",
                    spec.name,
                    attempt + 1,
                    spec.max_retries + 1,
                    last_error_kind,
                    exc,
                )
                if attempt < spec.max_retries:
                    time.sleep(0.25 * (attempt + 1))
        return SourceResult(
            name=spec.name,
            status="error",
            error=last_error,
            error_kind=last_error_kind,
            attempts=spec.max_retries + 1,
        )

    @staticmethod
    def _load_existing(date_dir: Path, name: str) -> dict[str, Any] | None:
        candidates = (
            date_dir / "normalized" / f"{name}.json",
            date_dir / f"{name}.json",
        )
        for path in candidates:
            payload = read_json(path)
            if isinstance(payload, dict) and payload:
                return payload
        return None

    @staticmethod
    def _existing_result(
        spec: SourceSpec,
        trade_date: str,
        date_dir: Path,
        existing: dict[str, Any],
    ) -> SourceResult:
        observed_date = str(existing.get("trade_date") or existing.get("as_of") or "")
        if spec.freshness_required and observed_date != trade_date:
            return SourceResult(
                name=spec.name,
                status="stale",
                payload=existing,
                source=str(existing.get("source") or "tickflow_snapshot"),
                error=f"payload date {observed_date} != requested {trade_date}",
                error_kind="stale",
                record_count=count_records(existing),
                reused_snapshot=True,
                attempts=1,
            )
        return SourceResult(
            name=spec.name,
            status=payload_status(existing),
            payload=existing,
            source=str(existing.get("source") or "tickflow_snapshot"),
            record_count=count_records(existing),
            collected_at=str(
                existing.get("scraped_at") or existing.get("collected_at") or ""
            ),
            input_path=str(date_dir / f"{spec.name}.json"),
            reused_snapshot=True,
            attempts=1,
        )
