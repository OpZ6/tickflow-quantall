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


@pytest.mark.parametrize("day", [date(2015, 1, 5), date(2024, 1, 2)])
def test_transform_partition_maps_legacy_units(day: date) -> None:
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


def test_2015_negotiated_bar_uses_raw_price_range_for_unit_check() -> None:
    day = date(2015, 3, 19)
    frame = pl.DataFrame({
        "symbol": ["430139.BJ"], "date": [day],
        "open": [15.38], "high": [15.38], "low": [0.01], "close": [0.01],
        "volume": [28000.0], "amount": [113.58],
    })
    result = MODULE._transform_partition(frame, day)
    assert result["amount"].item() == 113580.0
    assert result["volume"].item() == 280.0
    with pytest.raises(RuntimeError, match="outside evidenced bounds"):
        MODULE._transform_partition(frame.with_columns(pl.lit(3.0).alias("high")), day)


def test_preflight_requires_matching_raw_and_enriched_dates(tmp_path: Path) -> None:
    day = date(2024, 1, 2)
    raw = tmp_path / "kline_daily" / f"date={day}"
    raw.mkdir(parents=True)
    _legacy_frame(day).write_parquet(raw / "part.parquet")
    (tmp_path / "kline_daily_enriched").mkdir()

    with pytest.raises(RuntimeError, match="no kline_daily_enriched partitions"):
        MODULE._preflight(tmp_path, day, day)


def test_cli_accepts_explicit_2015_repair(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["repair", "--start", "2015-01-01", "--end", "2015-12-31"])
    monkeypatch.setattr(MODULE, "_preflight", lambda *args: ({}, {}))
    assert MODULE.main() == 0
