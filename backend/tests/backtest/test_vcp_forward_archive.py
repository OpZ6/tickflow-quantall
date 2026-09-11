from __future__ import annotations

import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _module():
    path = Path(__file__).resolve().parents[3] / "scripts/archive_vcp_forward_baseline.py"
    spec = importlib.util.spec_from_file_location("archive_vcp_forward_baseline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_snapshot_rejects_undersized_partition(tmp_path) -> None:
    module = _module()
    module.ROOT = tmp_path
    for dataset, rows in (("raw", 2), ("enriched", 1)):
        path = tmp_path / "data" / dataset / "date=2026-09-08" / "part.parquet"
        path.parent.mkdir(parents=True)
        pq.write_table(pa.table({"symbol": [str(i) for i in range(rows)]}), path)

    selection = {
        "completed_through": "2026-09-08",
        "dated_datasets": ["raw", "enriched"],
        "aligned_date_datasets": ["raw", "enriched"],
        "minimum_rows_by_dataset": {"enriched": 2},
        "files": [],
    }

    with pytest.raises(RuntimeError, match="archive partition below minimum rows"):
        module._load_selected_snapshot(selection)
