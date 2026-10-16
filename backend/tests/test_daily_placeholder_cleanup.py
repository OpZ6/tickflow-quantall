import importlib.util
from datetime import date
from pathlib import Path

import polars as pl
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "remove_invalid_daily_placeholders.py"
SPEC = importlib.util.spec_from_file_location("remove_invalid_daily_placeholders", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_preflight = MODULE._preflight


def _daily_rows(include_placeholder: bool = True) -> pl.DataFrame:
    rows = [{
        "symbol": "000001.SZ",
        "date": date(2026, 9, 1),
        "open": 10.0,
        "high": 10.2,
        "low": 9.9,
        "close": 10.1,
        "volume": 100.0,
        "amount": 1000.0,
    }]
    if include_placeholder:
        rows.append({
            "symbol": "000002.SZ",
            "date": date(2026, 9, 1),
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": 0.0,
            "amount": 0.0,
        })
    return pl.DataFrame(rows)


def _write_partition(root: Path, table: str, frame: pl.DataFrame) -> None:
    target = root / table / "date=2026-09-01"
    target.mkdir(parents=True)
    frame.write_parquet(target / "part.parquet")


def test_placeholder_preflight_removes_only_audited_key(tmp_path) -> None:
    _write_partition(tmp_path, "kline_daily", _daily_rows())
    _write_partition(tmp_path, "kline_daily_enriched", _daily_rows(False))

    plan, replacements = _preflight(
        tmp_path, [{"symbol": "000002.SZ", "date": "2026-09-01"}]
    )

    assert plan["removed_rows"] == 1
    assert plan["affected_partitions"] == 1
    replacement = next(iter(replacements.values()))
    assert replacement["symbol"].to_list() == ["000001.SZ"]
    assert pl.read_parquet(
        tmp_path / "kline_daily" / "date=2026-09-01" / "part.parquet"
    ).height == 2


def test_placeholder_preflight_rejects_key_present_in_enriched(tmp_path) -> None:
    frame = _daily_rows()
    _write_partition(tmp_path, "kline_daily", frame)
    _write_partition(tmp_path, "kline_daily_enriched", frame)

    with pytest.raises(RuntimeError, match="unexpectedly exist"):
        _preflight(
            tmp_path, [{"symbol": "000002.SZ", "date": "2026-09-01"}]
        )
