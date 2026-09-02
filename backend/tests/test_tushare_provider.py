"""Tushare provider 单元测试。

用 mock 不实际调 Tushare(无需 TUSHARE_TOKEN)。验证标准化、分批、错误处理。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl

from app.plugins.tushare import bridge
from app.plugins.tushare.provider import TushareProvider, _normalize_financial, _preview


def _daily_df() -> pd.DataFrame:
    """模拟 Tushare pro.daily 返回的 pandas DataFrame。"""
    return pd.DataFrame({
        "ts_code": ["600519.SH", "000001.SZ"],
        "trade_date": ["20260821", "20260821"],
        "open": [1500.0, 10.0],
        "high": [1520.0, 10.2],
        "low": [1490.0, 9.8],
        "close": [1510.0, 10.1],
        "vol": [10000.0, 20000.0],
        "amount": [1.5e7, 2.0e6],
    })


def _adj_df() -> pd.DataFrame:
    """模拟 Tushare pro.adj_factor 返回。"""
    return pd.DataFrame({
        "ts_code": ["600519.SH", "600519.SH", "600519.SH"],
        "trade_date": ["20260819", "20260820", "20260821"],
        "adj_factor": [1.0, 1.0, 1.23],
    })


# ---- _normalize_adj ----

def test_normalize_adj_pandas():
    df = TushareProvider._normalize_adj(_adj_df())
    assert not df.is_empty()
    assert df.columns == ["symbol", "trade_date", "ex_factor"]
    assert df["symbol"].to_list() == ["600519.SH"]
    assert df["trade_date"].to_list() == [datetime(2026, 8, 21).date()]
    assert df["ex_factor"].to_list() == [1.23]


def test_normalize_adj_none():
    assert TushareProvider._normalize_adj(None).is_empty()


def test_normalize_adj_empty():
    assert TushareProvider._normalize_adj(pd.DataFrame()).is_empty()


# ---- get_daily ----

@patch("app.plugins.tushare.provider._get_pro")
def test_get_daily_by_date(mock_get_pro):
    """同日 start/end → trade_date 批量模式。"""
    mock_pro = MagicMock()
    mock_pro.daily.return_value = _daily_df()
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    df = provider.get_daily(["600519.SH"], datetime(2026, 8, 21), datetime(2026, 8, 21))

    assert not df.is_empty()
    assert "symbol" in df.columns
    assert "close" in df.columns
    assert df["symbol"].to_list() == ["600519.SH", "000001.SZ"]
    mock_pro.daily.assert_called_once_with(trade_date="20260821")


@patch("app.plugins.tushare.provider._get_pro")
def test_get_daily_history_chunked(mock_get_pro):
    """不同日 → 按标的分批历史模式。"""
    mock_pro = MagicMock()
    mock_pro.daily.return_value = _daily_df()
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    symbols = [f"{i:06d}.SZ" for i in range(200)]
    df = provider.get_daily(symbols, datetime(2026, 1, 1), datetime(2026, 8, 21))

    assert not df.is_empty()
    assert mock_pro.daily.call_count >= 2  # 200 symbols / 80 batch ≥ 3 calls


def test_get_daily_empty_symbols():
    provider = TushareProvider()
    assert provider.get_daily([], None, None).is_empty()


@patch("app.plugins.tushare.provider._get_pro", side_effect=RuntimeError("boom"))
def test_get_daily_error_returns_empty(mock_get_pro):
    provider = TushareProvider()
    df = provider.get_daily(["600519.SH"], datetime(2026, 8, 21), datetime(2026, 8, 21))
    assert df.is_empty()


# ---- get_adj_factors ----

@patch("app.plugins.tushare.provider._get_pro")
def test_get_adj_factors(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.adj_factor.return_value = _adj_df()
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    df = provider.get_adj_factors(["600519.SH"], datetime(2026, 1, 1), datetime(2026, 8, 21))

    assert not df.is_empty()
    assert df.columns == ["symbol", "trade_date", "ex_factor"]
    assert df["symbol"].to_list() == ["600519.SH"]
    mock_pro.adj_factor.assert_called_once()
    assert mock_pro.adj_factor.call_args.kwargs["start_date"] == "20251202"


def test_get_adj_factors_empty():
    provider = TushareProvider()
    assert provider.get_adj_factors([], None, None).is_empty()


# ---- get_instruments ----

@patch("app.plugins.tushare.provider._get_pro")
def test_get_instruments(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.stock_basic.return_value = pd.DataFrame({
        "ts_code": ["600519.SH", "000001.SZ"],
        "symbol": ["600519", "000001"],
        "name": ["贵州茅台", "平安银行"],
        "exchange": ["SSE", "SZSE"],
    })
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    rows = provider.get_instruments("stock")

    assert len(rows) == 2
    assert rows[0]["symbol"] == "600519.SH"
    assert rows[0]["name"] == "贵州茅台"
    mock_pro.stock_basic.assert_called_once()


def test_get_instruments_non_stock_returns_empty():
    provider = TushareProvider()
    assert provider.get_instruments("etf") == []


# ---- get_index_daily ----

@patch("app.plugins.tushare.provider._get_pro")
def test_get_index_daily(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.index_daily.return_value = _daily_df()
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    df = provider.get_index_daily(["000001.SH"], datetime(2026, 1, 1), datetime(2026, 8, 21))

    assert not df.is_empty()
    assert "symbol" in df.columns
    mock_pro.index_daily.assert_called_once_with(
        ts_code="000001.SH", start_date="20260101", end_date="20260821"
    )


# ---- bridge.availability ----

def test_availability_no_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    ok, _ = bridge.availability()
    assert ok is False


def test_availability_with_token(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    ok, msg = bridge.availability()
    # tushare 已装(测试依赖)时 ok=True; 否则 False 但原因含"未安装"
    if ok:
        assert msg == "ok"
    else:
        assert "tushare" in msg


# ---- config / datasets ----

def test_config_datasets():
    provider = TushareProvider()
    assert provider.name == "tushare"
    assert provider.builtin is True
    assert set(provider.config.datasets) == {"daily", "adj_factor", "index", "financial", "moneyflow"}


def test_preview():
    df = pl.DataFrame({"symbol": ["600519.SH"], "close": [1510.0]})
    p = _preview("daily", df)
    assert p["provider"] == "tushare"
    assert p["dataset"] == "daily"
    assert p["rows"] == 1
    assert len(p["preview"]) == 1


# ---- get_financials ----

@patch("app.plugins.tushare.provider._get_pro")
def test_get_financials_income(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.income.return_value = pd.DataFrame({
        "ts_code": ["600519.SH"],
        "ann_date": ["20260820"],
        "end_date": ["20260630"],
        "营业收入": [1.0e6],
        "净利润": [5.0e5],
    })
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    df = provider.get_financials("income", ["600519.SH"], latest_only=True)

    assert not df.is_empty()
    assert "symbol" in df.columns
    assert df["symbol"].to_list() == ["600519.SH"]
    assert df["period_end"].to_list()[0].isoformat() == "2026-06-30"
    assert df["announce_date"].to_list()[0].isoformat() == "2026-08-20"
    assert df["source"].to_list() == ["tushare"]
    mock_pro.income.assert_called_once()


@patch("app.plugins.tushare.provider._get_pro")
def test_get_financials_shares(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.daily_basic.return_value = pd.DataFrame({
        "ts_code": ["600519.SH"],
        "trade_date": ["20260821"],
        "close": [1510.0],
        "float_share": [1.0e8],
        "total_share": [1.25e8],
    })
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    df = provider.get_financials("shares", ["600519.SH"])

    assert not df.is_empty()
    assert "symbol" in df.columns
    assert df["total_shares"].to_list() == [1.25e12]
    assert df["float_shares"].to_list() == [1.0e12]
    mock_pro.daily_basic.assert_called_once()


@patch("app.plugins.tushare.provider._get_pro")
def test_financial_requests_each_symbol_separately(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.income.return_value = pd.DataFrame()
    mock_get_pro.return_value = mock_pro
    TushareProvider().get_financials("income", ["600519.SH", "000001.SZ"])
    assert [call.kwargs["ts_code"] for call in mock_pro.income.call_args_list] == ["600519.SH", "000001.SZ"]


def test_shares_are_converted_to_units_and_compressed_to_change_points():
    raw = pd.DataFrame({
        "ts_code": ["600519.SH"] * 3,
        "trade_date": ["20260101", "20260102", "20260103"],
        "total_share": [10.0, 10.0, 11.0], "float_share": [8.0, 8.0, 8.0],
    })
    df = _normalize_financial("shares", raw)
    assert df.height == 2
    assert df["total_shares"].to_list() == [100_000.0, 110_000.0]


def test_get_financials_unsupported_table():
    provider = TushareProvider()
    try:
        provider.get_financials("unknown", ["600519.SH"])
        raise AssertionError("should raise ValueError")
    except ValueError:
        pass


def test_get_financials_empty():
    provider = TushareProvider()
    assert provider.get_financials("income", []).is_empty()


# ---- get_moneyflow ----

@patch("app.plugins.tushare.provider._get_pro")
def test_get_moneyflow(mock_get_pro):
    mock_pro = MagicMock()
    mock_pro.moneyflow.return_value = pd.DataFrame({
        "ts_code": ["600519.SH"],
        "trade_date": ["20260821"],
        "net_amount": [1.0e6],
        "buy_sm_amount": [5.0e5],
    })
    mock_get_pro.return_value = mock_pro

    provider = TushareProvider()
    df = provider.get_moneyflow(["600519.SH"], datetime(2026, 8, 1), datetime(2026, 8, 21))

    assert not df.is_empty()
    assert "symbol" in df.columns
    assert df["symbol"].to_list() == ["600519.SH"]
    mock_pro.moneyflow.assert_called_once_with(
        ts_code="600519.SH", start_date="20260801", end_date="20260821"
    )


def test_get_moneyflow_empty():
    provider = TushareProvider()
    assert provider.get_moneyflow([], None, None).is_empty()


# ---- _to_polars_with_symbol ----

def test_to_polars_none():
    assert TushareProvider._to_polars_with_symbol(None).is_empty()


def test_to_polars_no_tscode():
    df = pl.DataFrame({"name": ["test"]})
    result = TushareProvider._to_polars_with_symbol(df)
    assert "name" in result.columns
    assert "symbol" not in result.columns
