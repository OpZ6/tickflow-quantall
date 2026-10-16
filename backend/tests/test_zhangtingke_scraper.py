from __future__ import annotations

import json

from app.quantx_data.legacy_scrapers import zhangtingke_scraper

HEIGHT_HTML = (
    'var lbgd_dict = {"lbgd_header": ["交易日期", "股票代码", "连板天数"], '
    '"lbgd_lst": [["20260911", "sh.600519", 3]]};'
)
LADDER_HTML = (
    'var dictData = {"lbtd_header": ["股票代码", "连板天数", "题材名"], '
    '"lbtd_lst": [["sh.600519", 3, "大消费"]], "date": "20260911"};'
)
EMPTY_LADDER_HTML = (
    'var dictData = {"lbtd_header": ["股票代码", "连板天数"], '
    '"lbtd_lst": [], "date": "20260911"};'
)


def _silence_sleep(monkeypatch) -> None:
    monkeypatch.setattr(zhangtingke_scraper.time, "sleep", lambda _seconds: None)


def test_fetch_retries_transient_errors(monkeypatch) -> None:
    _silence_sleep(monkeypatch)
    calls: list[str] = []

    class Response:
        encoding = "utf-8"
        content = "ok".encode()
        text = "ok"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url, **_kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise ConnectionError("connection aborted")
        return Response()

    monkeypatch.setattr(zhangtingke_scraper.requests, "get", fake_get)

    assert zhangtingke_scraper._fetch("https://example.com") == "ok"
    assert len(calls) == 3


def test_fetch_raises_after_exhausting_retries(monkeypatch) -> None:
    _silence_sleep(monkeypatch)
    calls: list[str] = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        raise TimeoutError("timed out")

    monkeypatch.setattr(zhangtingke_scraper.requests, "get", fake_get)

    try:
        zhangtingke_scraper._fetch("https://example.com")
    except TimeoutError:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("_fetch must re-raise the last error")
    assert len(calls) == zhangtingke_scraper._FETCH_RETRIES


def test_scrape_retries_when_ladder_empty(monkeypatch) -> None:
    _silence_sleep(monkeypatch)
    payloads = [
        HEIGHT_HTML,
        EMPTY_LADDER_HTML,
        HEIGHT_HTML,
        EMPTY_LADDER_HTML,
        HEIGHT_HTML,
        LADDER_HTML,
    ]
    monkeypatch.setattr(zhangtingke_scraper, "_fetch", lambda _url: payloads.pop(0))

    result = zhangtingke_scraper.scrape("20260911")

    assert payloads == []
    assert len(result["ladder_stocks"]) == 1
    assert result["ladder_stocks"][0]["theme_name"] == "大消费"
    assert result["ladder_by_height"]["3"][0]["code"] == "600519"


def test_scrape_returns_empty_ladder_after_all_retries(monkeypatch) -> None:
    _silence_sleep(monkeypatch)
    payloads = [HEIGHT_HTML, EMPTY_LADDER_HTML] * zhangtingke_scraper._SCRAPE_RETRIES
    monkeypatch.setattr(zhangtingke_scraper, "_fetch", lambda _url: payloads.pop(0))

    result = zhangtingke_scraper.scrape("20260911")

    assert result["ladder_stocks"] == []
    assert result["ladder_by_height"] == {}
    assert result["height_history"]


def test_scrape_does_not_retry_when_ladder_present(monkeypatch) -> None:
    _silence_sleep(monkeypatch)
    calls: list[str] = []
    payloads = [HEIGHT_HTML, LADDER_HTML]

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return payloads.pop(0)

    monkeypatch.setattr(zhangtingke_scraper, "_fetch", fake_fetch)

    result = zhangtingke_scraper.scrape("20260911")

    assert len(calls) == 2
    assert result["ladder_stocks"][0]["name"] == ""


def test_run_marks_empty_when_no_data(monkeypatch, tmp_path) -> None:
    _silence_sleep(monkeypatch)
    monkeypatch.setattr(
        zhangtingke_scraper,
        "_fetch",
        lambda _url: 'var dictData = {"lbtd_header": [], "lbtd_lst": []};',
    )

    path = zhangtingke_scraper.run("20260911", str(tmp_path))
    payload = json.loads((tmp_path / "zhangtingke.json").read_text(encoding="utf-8"))

    assert path == str(tmp_path / "zhangtingke.json")
    assert payload["status"] == "empty"
    assert payload["available"] is False
