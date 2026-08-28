from __future__ import annotations

import pandas as pd

from app.quantx_data.legacy_scrapers import pywencai_scraper, tushare_scraper


def test_new_high_fallback_initializes_tushare_client_lazily(monkeypatch) -> None:
    class EmptyCalendarClient:
        def __init__(self) -> None:
            self.trade_calendar_calls = 0

        def trade_cal(self, **_kwargs) -> pd.DataFrame:
            self.trade_calendar_calls += 1
            return pd.DataFrame()

    client = EmptyCalendarClient()
    monkeypatch.setattr(tushare_scraper, "pro", None)
    monkeypatch.setattr(tushare_scraper, "_client", lambda: client)
    monkeypatch.setattr(pywencai_scraper, "TRADE_DATE", "20260828")

    result = pywencai_scraper._compute_new_high_from_tushare()

    assert client.trade_calendar_calls == 1
    assert result["status"] == "unavailable"
    assert result["error"] == "tushare trade calendar empty"
