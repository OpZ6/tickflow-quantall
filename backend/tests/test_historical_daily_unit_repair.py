import importlib.util
from datetime import date
from pathlib import Path

import polars as pl
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_historical_daily_units.py"
SPEC = importlib.util.spec_from_file_location("repair_historical_daily_units", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _legacy_frame(day: date) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["600519.SH"],
        "date": [day],
        "open": [1680.0],
        "high": [1700.0],
        "low": [1670.0],
        "close": [1685.0],
        "volume": [3_215_644.0],
        "amount": [5_440_082.548],
    })


def test_transform_partition_maps_legacy_units() -> None:
    day = date(2024, 1, 2)
    result = MODULE._transform_partition(_legacy_frame(day), day)

    assert result["volume"].item() == 32_156.44
    assert result["amount"].item() == 5_440_082_548.0


def test_transform_partition_rejects_current_units() -> None:
    day = date(2025, 8, 25)
    current = _legacy_frame(day).with_columns(
        (pl.col("volume") / 100).alias("volume"),
        (pl.col("amount") * 1000).alias("amount"),
    )

    with pytest.raises(RuntimeError, match="not uniformly legacy-unit"):
        MODULE._transform_partition(current, day)


def test_preflight_requires_matching_raw_and_enriched_dates(tmp_path: Path) -> None:
    day = date(2024, 1, 2)
    raw = tmp_path / "kline_daily" / f"date={day}"
    raw.mkdir(parents=True)
    _legacy_frame(day).write_parquet(raw / "part.parquet")
    (tmp_path / "kline_daily_enriched").mkdir()

    with pytest.raises(RuntimeError, match="no kline_daily_enriched partitions"):
        MODULE._preflight(tmp_path, day, day)
