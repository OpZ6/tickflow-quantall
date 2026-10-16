from __future__ import annotations

import json

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


def test_run_does_not_block_core_payload_on_slow_new_high_fallback(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        pywencai_scraper,
        "fetch_limit_up_details",
        lambda: {"count": 1, "stocks": [{"code": "000001"}]},
    )
    monkeypatch.setattr(
        pywencai_scraper,
        "fetch_broken_board",
        lambda: {"count": 0, "stocks": []},
    )
    monkeypatch.setattr(
        pywencai_scraper,
        "fetch_limit_down_details",
        lambda: {"count": 0, "stocks": []},
    )
    monkeypatch.setattr(
        pywencai_scraper,
        "fetch_yesterday_limit_up_today",
        lambda: {"advance_rate": 42.5, "advance_sample_count": 40},
    )
    monkeypatch.setattr(
        pywencai_scraper,
        "fetch_new_high_100d",
        lambda: {"status": "unavailable", "stocks": [], "count": 0},
    )
    monkeypatch.setattr(pywencai_scraper, "fetch_ma_ratios", lambda: {})

    def fail_if_called() -> dict:
        raise AssertionError("slow Tushare fallback must not run in the core source process")

    monkeypatch.setattr(
        pywencai_scraper, "_compute_new_high_from_tushare", fail_if_called
    )

    output = pywencai_scraper.run("20260901", str(tmp_path))
    payload = json.loads((tmp_path / "pywencai.json").read_text(encoding="utf-8"))

    assert output == str(tmp_path / "pywencai.json")
    assert payload["yesterday_perf"]["advance_rate"] == 42.5
    assert payload["new_high_100d"]["status"] == "unavailable"
