"""Non-destructive migration of legacy QuantX source snapshots to facts."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.market_facts.adapters import (
    load_published_fact_evidence,
    load_tickflow_market_aggregate,
)
from app.market_facts.builders import FactValidationError, build_initial_fact_batches
from app.market_facts.registry import DatasetId
from app.market_facts.repository import MarketFactRepository
from app.market_facts.storage import FactPublication
from app.services.review_v4 import build_review_data

from .collectors import SOURCE_SPECS
from .io import read_json, write_json_atomic
from .repository import QuantXTableRepository

_DATASET_MIGRATION_VERSIONS = {
    dataset_id: 1 for dataset_id in DatasetId
}
_DATASET_MIGRATION_VERSIONS[DatasetId.SCREENING_CANDIDATE_DAILY] = 2


def _date_dirs(data_root: Path) -> list[Path]:
    quantx = data_root / "quantx"
    if not quantx.is_dir():
        return []
    return [
        path
        for path in sorted(quantx.iterdir())
        if path.is_dir() and len(path.name) == 8 and path.name.isdigit()
    ]


def _sources(data_root: Path, date_dir: Path) -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    for spec in SOURCE_SPECS:
        payload = read_json(date_dir / "normalized" / f"{spec.name}.json")
        if not isinstance(payload, dict):
            payload = read_json(date_dir / f"{spec.name}.json")
        if isinstance(payload, dict):
            payloads[spec.name] = payload
    aggregate = load_tickflow_market_aggregate(data_root, date_dir.name)
    if aggregate is not None:
        payloads["tickflow_enriched_aggregate"] = aggregate
    published = load_published_fact_evidence(data_root, date_dir.name)
    if published is not None:
        payloads["tickflow_published_fact"] = published
    return payloads


def _structured_tables(date_dir: Path) -> dict[str, dict]:
    names = (
        "_computed",
        "sentiment_state",
        "market_overview",
        "market_breadth",
        "market_liquidity",
        "limit_summary",
        "limit_ladder",
        "theme_stocks",
        "screening_candidates",
    )
    return {
        name: payload
        for name in names
        if isinstance(payload := read_json(date_dir / f"{name}.json"), dict)
    }


def migrate_quantx_history(
    data_root: Path,
    *,
    apply: bool = False,
    force: bool = False,
    datasets: tuple[DatasetId | str, ...] | None = None,
) -> dict:
    """Preflight or publish all migratable dates without changing legacy files."""
    data_root = Path(data_root)
    repo = MarketFactRepository(data_root)
    targeted = bool(datasets)
    dataset_ids = (
        tuple(dict.fromkeys(DatasetId(item) for item in datasets))
        if datasets
        else tuple(DatasetId)
    )
    result = {
        "dry_run": not apply,
        "eligible": [],
        "migrated": [],
        "skipped_existing": [],
        "skipped_incomplete": {},
        "failed": {},
    }
    for date_dir in _date_dirs(data_root):
        day = datetime.strptime(date_dir.name, "%Y%m%d").date()
        marker_path = date_dir / "_market_facts_migration.json"
        marker = read_json(marker_path)
        prior_versions = (
            marker.get("dataset_versions", {})
            if isinstance(marker, dict)
            and isinstance(marker.get("dataset_versions"), dict)
            else {}
        )
        missing_ids = {
            item for item in dataset_ids if not repo.has_partition(item, day)
        }
        stale_ids = (
            {
                item
                for item in dataset_ids
                if int(prior_versions.get(item.value, 0))
                < _DATASET_MIGRATION_VERSIONS[item]
            }
            if targeted
            else set()
        )
        selected_ids = set(dataset_ids) if force else missing_ids | stale_ids
        if not selected_ids:
            result["skipped_existing"].append(date_dir.name)
            continue
        run_id = f"migration-{date_dir.name}-{uuid4().hex[:12]}"
        try:
            batches = build_initial_fact_batches(
                date_dir.name,
                _sources(data_root, date_dir),
                run_id,
                structured_tables=_structured_tables(date_dir),
            )
            batches = [batch for batch in batches if batch.dataset_id in selected_ids]
        except FactValidationError as exc:
            result["skipped_incomplete"][date_dir.name] = str(exc)
            continue
        except (TypeError, ValueError) as exc:
            result["failed"][date_dir.name] = f"{type(exc).__name__}: {exc}"
            continue
        result["eligible"].append(date_dir.name)
        if not apply:
            continue

        publication = FactPublication(data_root, run_id)
        try:
            publication.stage(batches)
            artifacts = publication.manifest_artifacts()
            publication.commit()
            publication.finalize()
        except Exception as exc:
            publication.rollback()
            publication.abandon()
            result["failed"][date_dir.name] = f"{type(exc).__name__}: {exc}"
            continue

        write_json_atomic(
            date_dir / "review_data.json",
            build_review_data(date_dir),
        )
        dataset_versions = dict(prior_versions)
        dataset_versions.update(
            {
                item.value: _DATASET_MIGRATION_VERSIONS[item]
                for item in selected_ids
            }
        )
        write_json_atomic(
            marker_path,
            {
                "schema_version": 2,
                "trade_date": date_dir.name,
                "run_id": run_id,
                "migrated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "legacy_preserved": True,
                "migration_scope": sorted(item.value for item in selected_ids),
                "dataset_versions": dataset_versions,
                "fact_artifacts": artifacts,
                "reconciliation": QuantXTableRepository(
                    data_root / "quantx", repo
                ).load(date_dir.name)["data_foundation"]["reconciliation"],
            },
        )
        result["migrated"].append(date_dir.name)
    return result
