"""migrate_from_quants.py 辅助函数测试。

不连 DuckDB;只测 _parse_yyyymmdd / _write_date_partitions / _write_symbol_partitions。
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

# 脚本在 prototypes/tickflow/scripts/,不在 backend 包内;用 sys.path 加载
_scripts = Path(__file__).resolve().parents[1].parent / "scripts"
sys.path.insert(0, str(_scripts))

from migrate_from_quants import (  # noqa: E402
    _normalize_daily_units,
    _parse_yyyymmdd,
    _write_date_partitions,
    _write_symbol_partitions,
    export_daily,
    export_enriched,
)


def test_normalize_daily_units_matches_2015_source_and_preserves_turnover():
    frame = pd.DataFrame({
        "source_daily_raw": ["quanti.stock_daily_raw", "tushare.pro.daily"],
        "volume": [286_043_643.0, 1000.0],
        "amount": [4_565_387.8464, 10.0],
        "turnover_rate": [2.9079, 0.1],
    })
    result = _normalize_daily_units(frame)
    assert result["volume"].tolist() == [2_860_436.43, 10.0]
    assert result["amount"].tolist() == pytest.approx([4_565_387_846.4, 10_000.0])
    assert result["turnover_rate"].tolist() == [2.9079, 0.1]
    assert "source_daily_raw" not in result.columns
    assert frame["volume"].iloc[0] == 286_043_643.0


@pytest.mark.parametrize("source", [None, "unknown", ""])
def test_normalize_daily_units_rejects_unverified_sources(source):
    with pytest.raises(ValueError, match="unverified daily source"):
        _normalize_daily_units(pd.DataFrame({"source_daily_raw": [source]}))


def test_normalize_daily_units_rejects_missing_source():
    with pytest.raises(ValueError, match="source is required"):
        _normalize_daily_units(pd.DataFrame({"amount": [1.0], "volume": [1.0]}))


@pytest.mark.parametrize("exporter,dataset", [
    (export_daily, "kline_daily"), (export_enriched, "kline_daily_enriched"),
])
def test_export_standard_units_across_old_year_boundary(tmp_path, exporter, dataset):
    import duckdb

    # In-memory source only; never connect to the production warehouse.
    bars = pd.DataFrame({
        "ts_code": ["600000.SH"] * 3,
        "trade_date": [date(2015, 1, 5), date(2016, 12, 30), date(2017, 1, 3)],
        **{f"{field}_raw": [10.0] * 3 for field in ("open", "high", "low", "close")},
        **{f"{field}_adj": [5.0] * 3 for field in ("open", "high", "low", "close")},
        "volume_raw": [1_000_000.0] * 3,
        "amount_raw": [10_000.0] * 3,
        "source_daily_raw": ["quanti.stock_daily_raw", "tushare.pro.daily", "tushare.pro.daily"],
    })
    basic = bars[["ts_code", "trade_date"]].assign(turnover_rate=2.5)
    with duckdb.connect(":memory:") as con:
        con.register("bars", bars)
        con.register("basic", basic)
        con.execute("CREATE TABLE dwd_daily_bar AS SELECT * FROM bars")
        con.execute("CREATE TABLE dwd_daily_basic AS SELECT * FROM basic")
        assert exporter(con, tmp_path, date(2015, 1, 1), date(2016, 12, 31)) == 2
    for day in ("2015-01-05", "2016-12-30"):
        row = pd.read_parquet(tmp_path / dataset / f"date={day}" / "part.parquet").iloc[0]
        assert row["volume"] == 10_000.0  # lots
        assert row["amount"] == 10_000_000.0  # yuan
        price = row["raw_close"] if dataset.endswith("enriched") else row["close"]
        assert row["amount"] / (row["volume"] * 100) == price
        if dataset.endswith("enriched"):
            assert row["turnover_rate"] == 2.5  # percentage points, no extra scaling
    assert not (tmp_path / dataset / "date=2017-01-03").exists()

# ---- _parse_yyyymmdd ----

def test_parse_yyyymmdd_string():
    assert _parse_yyyymmdd("20260821") == date(2026, 8, 21)


def test_parse_yyyymmdd_int():
    assert _parse_yyyymmdd(20260821) == date(2026, 8, 21)


def test_parse_yyyymmdd_none():
    assert _parse_yyyymmdd(None) is None


def test_parse_yyyymmdd_nan():
    assert _parse_yyyymmdd(float("nan")) is None


def test_parse_yyyymmdd_invalid():
    assert _parse_yyyymmdd("invalid") is None


def test_parse_yyyymmdd_duckdb_date():
    assert _parse_yyyymmdd(date(2026, 8, 21)) == date(2026, 8, 21)


def test_parse_yyyymmdd_iso_string_and_timestamp():
    expected = date(2026, 8, 21)
    assert _parse_yyyymmdd("2026-08-21") == expected
    assert _parse_yyyymmdd(datetime(2026, 8, 21, 15, 0)) == expected
    assert _parse_yyyymmdd(pd.Timestamp("2026-08-21")) == expected


# ---- _write_date_partitions ----

def test_write_date_partitions(tmp_path):
    df = pd.DataFrame({
        "symbol": ["600519.SH", "000001.SZ"],
        "date": [date(2026, 8, 21), date(2026, 8, 21)],
        "close": [1510.0, 10.1],
    })
    out = tmp_path / "kline_daily"
    n = _write_date_partitions(df, out)
    assert n == 1
    part = out / "date=2026-08-21" / "part.parquet"
    assert part.exists()


def test_write_date_partitions_multi_date(tmp_path):
    df = pd.DataFrame({
        "symbol": ["600519.SH", "000001.SZ"],
        "date": [date(2026, 8, 21), date(2026, 8, 22)],
        "close": [1510.0, 10.2],
    })
    n = _write_date_partitions(df, tmp_path / "kline_daily")
    assert n == 2


def test_write_date_partitions_empty(tmp_path):
    assert _write_date_partitions(pd.DataFrame(), tmp_path / "empty") == 0


# ---- _write_symbol_partitions ----

def test_write_symbol_partitions(tmp_path):
    df = pd.DataFrame({
        "symbol": ["600519.SH", "000001.SZ"],
        "trade_date": [date(2026, 8, 21), date(2026, 8, 21)],
        "ex_factor": [1.23, 1.0],
    })
    out = tmp_path / "adj_factor"
    n = _write_symbol_partitions(df, out)
    assert n == 2
    assert (out / "symbol=600519_SH" / "part.parquet").exists()
    assert (out / "symbol=000001_SZ" / "part.parquet").exists()


def test_write_symbol_partitions_empty(tmp_path):
    assert _write_symbol_partitions(pd.DataFrame(), tmp_path / "empty") == 0
