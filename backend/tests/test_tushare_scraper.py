from __future__ import annotations

import threading
import time

import pandas as pd
import pytest

from app.quantx_data.legacy_scrapers import tushare_scraper


class _TrackingPro:
    """Records concurrent in-flight calls so serial fetches fail the test."""

    def __init__(self, *, empty_dates: set[str] | None = None) -> None:
        self.empty_dates = empty_dates or set()
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def _enter(self, key: str) -> None:
        with self._lock:
            self.calls.append(key)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._lock:
            self.active -= 1

    def daily(self, *, trade_date: str) -> pd.DataFrame:
        self._enter(trade_date)
        if trade_date in self.empty_dates:
            return pd.DataFrame()
        return pd.DataFrame({"pct_chg": [1.0, -1.0], "amount": [100.0, 200.0]})

    def index_daily(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self._enter(ts_code)
        return pd.DataFrame(
            {
                "trade_date": [end_date],
                "close": [100.0],
                "pct_chg": [1.0],
                "vol": [10.0],
                "amount": [20.0],
            }
        )


def test_ad_history_fetches_dates_concurrently(monkeypatch) -> None:
    fake = _TrackingPro()
    monkeypatch.setattr(tushare_scraper, "pro", fake)
    tushare_scraper._DAILY_FRAME_CACHE.clear()

    result = tushare_scraper._fetch_ad_history("20260910", days=6)

    assert len(result["history"]) == 6
    assert fake.max_active > 1
    assert result["history"][-1]["date"] == "20260910"
    assert result["history"][-1]["up"] == 1
    assert result["history"][-1]["down"] == 1
    assert result["history"][-1]["flat"] == 0


def test_ad_history_refills_batch_after_empty_days(monkeypatch) -> None:
    fake = _TrackingPro(empty_dates={"20260909"})
    monkeypatch.setattr(tushare_scraper, "pro", fake)
    tushare_scraper._DAILY_FRAME_CACHE.clear()

    result = tushare_scraper._fetch_ad_history("20260910", days=5)

    assert len(result["history"]) == 5
    assert "20260909" not in {row["date"] for row in result["history"]}
    assert result["history"][-1]["date"] == "20260910"


def test_indexes_fetch_concurrently(monkeypatch) -> None:
    fake = _TrackingPro()
    monkeypatch.setattr(tushare_scraper, "pro", fake)

    result = tushare_scraper._fetch_indexes("20260910")

    assert set(result) == set(tushare_scraper.INDEXES)
    assert fake.max_active > 1


class _MarginPro:
    """Fake margin API whose latest day only has one exchange published."""

    def __init__(self) -> None:
        self.rows = [
            # 11-25 / 11-26: 三所齐全
            {"trade_date": "20261125", "exchange_id": "SSE", "rzye": 1.109014e12},
            {"trade_date": "20261125", "exchange_id": "SZSE", "rzye": 1.005272e12},
            {"trade_date": "20261125", "exchange_id": "BSE", "rzye": 7.100690e9},
            {"trade_date": "20261126", "exchange_id": "SSE", "rzye": 1.101070e12},
            {"trade_date": "20261126", "exchange_id": "SZSE", "rzye": 9.975219e11},
            {"trade_date": "20261126", "exchange_id": "BSE", "rzye": 6.986638e9},
            # 11-27: 只有上交所披露(T+1), 深交所/北交所还没出
            {"trade_date": "20261127", "exchange_id": "SSE", "rzye": 1.106188e12},
        ]

    def margin(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def test_margin_drops_day_missing_exchanges(monkeypatch) -> None:
    monkeypatch.setattr(tushare_scraper, "pro", _MarginPro())

    result = tushare_scraper._fetch_margin("20261127")

    dates = [row["date"] for row in result["history"]]
    assert dates[-1] == "20261126"
    assert "20261127" not in dates
    # 余额必须是三所合计, 不是只有上交所的那一半
    assert result["latest"]["rzye_yi"] == 21055.79
    # 净买入来自两日合计的差, 用构造值算出来是 -158.08, 允许分位误差
    assert result["latest"]["rz_net_buy_yi"] == pytest.approx(-158.07, abs=0.02)
    assert result["skipped_dates"] == [
        {
            "date": "20261127",
            "reason": "incomplete_exchanges",
            "exchanges": ["SSE"],
            "expected": ["BSE", "SSE", "SZSE"],
        }
    ]


def test_margin_keeps_day_when_all_exchanges_present(monkeypatch) -> None:
    fake = _MarginPro()
    fake.rows = [row for row in fake.rows if row["trade_date"] != "20261127"]
    monkeypatch.setattr(tushare_scraper, "pro", fake)

    result = tushare_scraper._fetch_margin("20261126")

    assert [row["date"] for row in result["history"]] == ["20261125", "20261126"]
    assert "skipped_dates" not in result
    assert result["latest"]["rzye_yi"] == 21055.79
