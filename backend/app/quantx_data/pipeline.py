from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.market_facts.adapters import load_tickflow_market_aggregate
from app.market_facts.builders import (
    build_initial_fact_batches,
    build_sector_breadth_history_batches,
)
from app.market_facts.registry import datasets_for_source
from app.market_facts.snapshots import SourceSnapshotStore
from app.market_facts.storage import FactPublication

from .calculators import build_daily_tables
from .collectors import collect_source, source_specs
from .io import read_json, sha256_file, validate_trade_date, write_json_atomic
from .manifest import write_manifest
from .normalizers import normalize_source
from .quality import validate_artifacts, validate_fact_batches, validate_sources
from .schemas import PipelineResult, RunStatus, SourceResult

logger = logging.getLogger(__name__)

_DATE_LOCKS: dict[str, threading.Lock] = {}
_DATE_LOCKS_GUARD = threading.Lock()


class PipelineError(RuntimeError):
    pass


def _date_lock(trade_date: str) -> threading.Lock:
    with _DATE_LOCKS_GUARD:
        return _DATE_LOCKS.setdefault(trade_date, threading.Lock())


def _copy_tree_replace(source: Path, target: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _publish(
    run_dir: Path,
    final_dir: Path,
    quantx_dir: Path,
    result: PipelineResult,
) -> None:
    """Swap a validated date snapshot without exposing a half-copied tree."""
    staging = quantx_dir / f".{result.trade_date}.{result.run_id}.staging"
    backup = quantx_dir / f".{result.trade_date}.{result.run_id}.backup"
    swapped = False
    try:
        # Keep unmanaged legacy files (if a user already has them) while all
        # managed outputs below are replaced by this run.
        if final_dir.is_dir():
            _copy_tree_replace(final_dir, staging)
        _copy_tree_replace(run_dir, staging)
        result.stages.append("published")
        _write_status(staging / "_pipeline_status.json", result)

        if final_dir.exists():
            os.replace(final_dir, backup)
        try:
            os.replace(staging, final_dir)
        except Exception:
            if backup.exists() and not final_dir.exists():
                os.replace(backup, final_dir)
            raise
        swapped = True
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if swapped:
            shutil.rmtree(backup, ignore_errors=True)


def _status_payload(result: PipelineResult) -> dict[str, Any]:
    payload = result.to_dict()
    payload["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload["llm"] = False
    return payload


def _write_status(path: Path, result: PipelineResult) -> None:
    write_json_atomic(path, _status_payload(result))


def _source_payloads(results) -> dict[str, dict[str, Any]]:
    return {name: result.payload for name, result in results.items() if result.payload}


def run_pipeline(
    data_root: Path,
    trade_date: str,
    *,
    selected_sources: list[str] | None = None,
    retry_sources: list[str] | None = None,
    force: bool = False,
    recompute: bool = False,
) -> dict[str, Any]:
    """Run one idempotent date snapshot and publish only after quality checks.

    ``data_root`` is Tickflow's own writable data directory.  No path outside
    it is consulted.  Existing source files in the target date are reusable
    snapshots; ``force``/``retry_sources`` explicitly bypass them.
    """
    validate_trade_date(trade_date)
    data_root = Path(data_root).resolve()
    quantx_dir = data_root / "quantx"
    final_dir = quantx_dir / trade_date
    specs = source_specs()
    selected_set = set(selected_sources or [])
    retry_set = set(retry_sources or [])
    unknown = (selected_set | retry_set) - {spec.name for spec in specs}
    if unknown:
        raise ValueError(f"unknown QuantX source(s): {', '.join(sorted(unknown))}")
    force_set = set(spec.name for spec in specs) if force and not selected_set else selected_set
    force_set.update(retry_set)
    quantx_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{trade_date}-{uuid.uuid4().hex[:12]}"
    lock = _date_lock(trade_date)
    if not lock.acquire(blocking=False):
        raise PipelineError(f"QuantX data run already active for {trade_date}")

    run_dir = quantx_dir / ".runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    # Always evaluate the complete source contract.  A selected/retried source
    # is refreshed while all other sources are reused from the date snapshot;
    # this prevents a single-source retry from publishing a partial dataset.
    results = {}
    stages = ["pending", "collecting"]
    errors: list[str] = []
    warnings: list[str] = []
    fact_publication: FactPublication | None = None
    snapshot_store = SourceSnapshotStore(data_root)
    try:
        for spec in specs:
            result = collect_source(
                spec,
                trade_date,
                run_dir,
                read_dir=final_dir,
                force=not recompute and spec.name in force_set,
                allow_network=not recompute,
            )
            if result.payload:
                raw_payload = result.payload
                write_json_atomic(run_dir / "raw" / f"{spec.name}.json", raw_payload)
                result.raw_sha256 = sha256_file(run_dir / "raw" / f"{spec.name}.json")
                dataset_ids = datasets_for_source(spec.name)
                if not result.reused_snapshot and dataset_ids:
                    snapshot = snapshot_store.record(
                        source_id=spec.name,
                        dataset_ids=dataset_ids,
                        trade_date=trade_date,
                        run_id=run_id,
                        payload=raw_payload,
                    )
                    result.snapshot_refs = tuple(
                        path.relative_to(data_root).as_posix()
                        for path in snapshot.metadata_paths
                    )
                normalized = normalize_source(spec.name, trade_date, raw_payload)
                result.payload = normalized
                write_json_atomic(run_dir / f"{spec.name}.json", normalized)
                write_json_atomic(run_dir / "normalized" / f"{spec.name}.json", normalized)
                result.normalized_sha256 = sha256_file(run_dir / "normalized" / f"{spec.name}.json")
                result.input_path = f"{trade_date}/{spec.name}.json"
            results[spec.name] = result

        stages.append("normalized")
        aggregate = load_tickflow_market_aggregate(data_root, trade_date)
        if aggregate is not None:
            results["tickflow_enriched_aggregate"] = SourceResult(
                name="tickflow_enriched_aggregate",
                status="ok",
                payload=aggregate,
                source="tickflow_enriched_aggregate",
                record_count=len(aggregate["daily"]),
                collected_at=aggregate["scraped_at"],
                input_path=f"{aggregate['input_table']}/date={trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",
                attempts=1,
            )
        source_payloads = _source_payloads(results)
        if recompute and not source_payloads:
            raise PipelineError(f"no reusable source payloads for {trade_date}")

        py_limit = source_payloads.get("pywencai", {}).get("limit_up", {})
        ztk_stocks = source_payloads.get("zhangtingke", {}).get("ladder_stocks", [])
        if isinstance(py_limit, dict) and not py_limit.get("stocks") and ztk_stocks:
            if "pywencai" in results:
                results["pywencai"].used_fallback = True
            warnings.append("pywencai limit-up table filled from zhangtingke ladder")
        if not source_payloads.get("sector_fund_flow_s4", {}).get("sectors") and source_payloads.get("akshare", {}).get("sector_fund_flow"):
            if "sector_fund_flow_s4" in results:
                results["sector_fund_flow_s4"].used_fallback = True
            warnings.append("sector fund flow filled from akshare fallback")

        stages.append("computed")
        tables = build_daily_tables(trade_date, run_dir, quantx_dir, source_payloads)
        for name, payload in tables.items():
            write_json_atomic(run_dir / f"{name}.json", payload)
        from app.services.review_v4 import build_review_data

        write_json_atomic(run_dir / "review_data.json", build_review_data(run_dir))
        stages.extend(["trends", "structured"])

        fact_batches = build_initial_fact_batches(
            trade_date,
            source_payloads,
            run_id,
            structured_tables=tables,
        )
        status, source_errors, source_warnings = validate_sources(specs, results)
        errors.extend(source_errors)
        warnings.extend(source_warnings)
        dataset_status, dataset_errors, dataset_warnings = validate_fact_batches(
            fact_batches, source_payloads
        )
        errors.extend(dataset_errors)
        warnings.extend(dataset_warnings)
        sector_history = build_sector_breadth_history_batches(
            trade_date, source_payloads, run_id
        )
        current_fact_date = datetime.strptime(trade_date, "%Y%m%d").date()
        fact_batches.extend(
            batch for batch in sector_history if batch.trade_date != current_fact_date
        )
        if dataset_status == RunStatus.FAILED:
            status = RunStatus.FAILED
        elif dataset_status == RunStatus.DEGRADED and status == RunStatus.COMPLETE:
            status = RunStatus.DEGRADED
        artifact_errors = validate_artifacts(run_dir)
        if artifact_errors:
            status = RunStatus.FAILED
            errors.extend(f"missing artifact: {name}" for name in artifact_errors)
        stages.append("quality")
        provisional = PipelineResult(trade_date, status, run_id, stages, results, {}, errors, warnings)
        fact_artifacts: list[dict[str, object]] = []
        if status in {RunStatus.COMPLETE, RunStatus.DEGRADED}:
            fact_publication = FactPublication(data_root, run_id)
            fact_publication.stage(fact_batches)
            fact_artifacts = fact_publication.manifest_artifacts()
        manifest = write_manifest(
            run_dir,
            trade_date,
            run_id,
            status,
            results,
            errors=errors,
            warnings=warnings,
            fact_artifacts=fact_artifacts,
        )
        provisional.artifacts = {item["path"]: item["sha256"] for item in manifest.get("artifacts", [])}

        if status in {RunStatus.COMPLETE, RunStatus.DEGRADED}:
            provisional.stages = stages
            assert fact_publication is not None
            fact_publication.commit()
            try:
                _publish(run_dir, final_dir, quantx_dir, provisional)
            except Exception:
                fact_publication.rollback()
                raise
            fact_publication.finalize()
            fact_publication = None
            try:
                from .catalog import build_and_save_catalog
                from .multiday import build_multiday_snapshot

                write_json_atomic(final_dir / "multiday_snapshot.json", build_multiday_snapshot(quantx_dir, trade_date))
                build_and_save_catalog(quantx_dir)
            except Exception:
                logger.exception("QuantX multiday refresh failed for %s", trade_date)
            return provisional.to_dict()

        stages.append("failed")
        provisional.stages = stages
        final_dir.mkdir(parents=True, exist_ok=True)
        _write_status(final_dir / "_pipeline_status.json", provisional)
        return provisional.to_dict()
    except Exception as exc:
        logger.exception("QuantX data pipeline failed for %s", trade_date)
        errors.append(f"{type(exc).__name__}: {exc}")
        failed = PipelineResult(trade_date, RunStatus.FAILED, run_id, [*stages, "failed"], results, {}, errors, warnings)
        final_dir.mkdir(parents=True, exist_ok=True)
        _write_status(final_dir / "_pipeline_status.json", failed)
        return failed.to_dict()
    finally:
        if fact_publication is not None:
            fact_publication.abandon()
        shutil.rmtree(run_dir, ignore_errors=True)
        lock.release()


def get_status(data_root: Path, trade_date: str) -> dict[str, Any] | None:
    validate_trade_date(trade_date)
    return read_json(Path(data_root) / "quantx" / trade_date / "_pipeline_status.json")
