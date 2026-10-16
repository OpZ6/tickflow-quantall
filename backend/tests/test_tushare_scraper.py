from __future__ import annotations

import threading
import time

import pandas as pd

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
