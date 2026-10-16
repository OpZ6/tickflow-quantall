import importlib.util
from datetime import date
from pathlib import Path

import polars as pl
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "repair_historical_turnover_rate.py"
SPEC = importlib.util.spec_from_file_location("repair_historical_turnover_rate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _legacy_frame(day: date, turnover_rate: float = 250.0) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": ["600000.SH"],
        "date": [day],
        "turnover_rate": [turnover_rate],
        "close": [10.0],
    })


@pytest.mark.parametrize("day", [date(2015, 1, 5), date(2024, 1, 2)])
def test_transform_partition_repairs_legacy_turnover(day: date) -> None:
    result = MODULE._transform_partition(_legacy_frame(day), day)

    assert result["turnover_rate"].item() == pytest.approx(2.5)
    assert result["close"].item() == 10.0


def test_transform_partition_rejects_current_turnover() -> None:
    day = date(2025, 8, 25)

    with pytest.raises(RuntimeError, match="not evidenced 100x turnover data"):
        MODULE._transform_partition(_legacy_frame(day, 2.5), day)


def test_targets_stay_inside_enriched_dataset(tmp_path: Path) -> None:
    day = date(2024, 1, 2)
    target = tmp_path / "kline_daily_enriched" / f"date={day}" / "part.parquet"
    target.parent.mkdir(parents=True)
    _legacy_frame(day).write_parquet(target)

    assert MODULE._targets(tmp_path, day, day) == [target.resolve()]


def test_cli_accepts_explicit_2015_repair(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["repair", "--start", "2015-01-01", "--end", "2015-12-31"])
    monkeypatch.setattr(MODULE, "_preflight", lambda *args: ({}, []))
    assert MODULE.main() == 0
