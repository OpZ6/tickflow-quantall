#!/usr/bin/env python3
"""Generate a reviewable starter bundle for a canonical market-fact dataset."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def render_files(dataset_id: str, source_id: str, description: str) -> dict[str, str]:
    enum_name = dataset_id.upper()
    builder_name = f"build_{dataset_id}"
    return {
        "README.md": f"""# {dataset_id} fact scaffold

Status: generated proposal, not registered automatically.

Dataset: `{dataset_id}`

Primary source: `{source_id}`

Description: {description}

Integration checklist:

1. Add `{enum_name}` and the `DatasetSpec` from `registry_snippet.py` to `app.market_facts.registry`.
2. Add the source route and verify it is declared by the unified Source Manager.
3. Adapt `builder.py` to the real normalized payload without changing source-specific semantics downstream.
4. Wire the builder into `build_initial_fact_batches` and expose reads through `MarketFactRepository`.
5. Add API and frontend contracts only after the fact repository test passes.
6. Run registry validation, unit tests, historical reconciliation and `git diff --check`.

Never invent missing values, use future data, or persist credentials.
""",
        "registry_snippet.py": f'''# Review and merge these declarations into app.market_facts.registry.
{enum_name} = "{dataset_id}"

DATASET_SPEC = DatasetSpec(
    dataset_id=DatasetId.{enum_name},
    description={description!r},
    schema_version=1,
    primary_key=("trade_date", "entity_id"),
    partition_keys=("trade_date",),
    required_columns=("trade_date", "entity_id"),
    storage_schema=_schema({{
        "trade_date": pl.Date,
        "entity_id": pl.String,
        "value": pl.Float64,
    }}),
    field_units=MappingProxyType({{"value": "REPLACE_WITH_EXPLICIT_UNIT"}}),
)

SOURCE_ROUTE = SourceRoute(
    DatasetId.{enum_name},
    ({source_id!r},),
)
''',
        "builder.py": f'''"""Source adapter for the proposed {dataset_id} fact."""
from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from app.market_facts.builders import FactBatch
from app.market_facts.registry import DatasetId, get_dataset


def {builder_name}(
    trade_date: date,
    payload: dict[str, Any],
    run_id: str,
) -> FactBatch:
    """Normalize one source payload; replace placeholder mappings explicitly."""
    dataset_id = DatasetId.{enum_name}
    spec = get_dataset(dataset_id)
    rows: list[dict[str, Any]] = []
    for item in payload.get("rows", []):
        rows.append({{
            "trade_date": trade_date,
            "entity_id": str(item["entity_id"]),
            "value": float(item["value"]),
            "source": {source_id!r},
            "source_record_id": f"{source_id}:{{dataset_id.value}}:{{trade_date}}:{{item['entity_id']}}",
            "observed_at": str(payload.get("observed_at") or ""),
            "ingested_at": str(payload.get("ingested_at") or ""),
            "run_id": run_id,
            "schema_version": spec.schema_version,
            "quality_level": "primary",
            "is_fallback": False,
        }})
    frame = pl.DataFrame(rows, schema=spec.storage_schema, orient="row", strict=False)
    return FactBatch(dataset_id, trade_date, frame)
''',
        f"test_{dataset_id}.py": f'''from datetime import date

from app.market_facts.registry import DatasetId, get_dataset

from .builder import {builder_name}


def test_{builder_name}_matches_registered_contract() -> None:
    batch = {builder_name}(
        date(2026, 8, 28),
        {{"rows": [{{"entity_id": "demo", "value": 1.0}}]}},
        "test-run",
    )
    spec = get_dataset(DatasetId.{enum_name})

    assert batch.frame.columns == list(spec.storage_schema)
    assert batch.frame.select(spec.primary_key).is_duplicated().any() is False
    assert batch.frame["trade_date"].unique().to_list() == [date(2026, 8, 28)]
''',
    }


def write_scaffold(output_dir: Path, files: dict[str, str]) -> None:
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = output_dir / name
        target.write_text(content, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id", help="snake_case canonical dataset id")
    parser.add_argument("--source", required=True, help="registered source id")
    parser.add_argument("--description", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not _IDENTIFIER.fullmatch(args.dataset_id):
        parser.error("dataset_id must match [a-z][a-z0-9_]*")
    if not _IDENTIFIER.fullmatch(args.source):
        parser.error("source must match [a-z][a-z0-9_]*")
    try:
        write_scaffold(
            args.output,
            render_files(args.dataset_id, args.source, args.description.strip()),
        )
    except (OSError, ValueError) as exc:
        print(f"scaffold failed: {exc}", file=sys.stderr)
        return 1
    print(f"generated market-fact scaffold: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
