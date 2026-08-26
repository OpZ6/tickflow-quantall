"""migrate_from_quants.py 辅助函数测试。

不连 DuckDB;只测 _parse_yyyymmdd / _write_date_partitions / _write_symbol_partitions。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

# 脚本在 prototypes/tickflow/scripts/,不在 backend 包内;用 sys.path 加载
_scripts = Path(__file__).resolve().parents[1].parent / "scripts"
sys.path.insert(0, str(_scripts))

from migrate_from_quants import (  # noqa: E402
    _parse_yyyymmdd,
    _write_date_partitions,
    _write_symbol_partitions,
)

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
