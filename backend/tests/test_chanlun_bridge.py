from __future__ import annotations

import httpx

from app.api.chanlun import chanlun_status
from app.services import chanlun_bridge


class _FakeClient:
    def __init__(self, response: httpx.Response | Exception):
        self.response = response

    def get(self, _url: str) -> httpx.Response:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_loopback_validation_rejects_remote_and_credentials():
    assert chanlun_bridge.is_loopback_url("http://127.0.0.1:3020")
    assert chanlun_bridge.is_loopback_url("http://localhost:3020")
    assert not chanlun_bridge.is_loopback_url("https://127.0.0.1:3020")
    assert not chanlun_bridge.is_loopback_url("http://user:pass@localhost:3020")
    assert not chanlun_bridge.is_loopback_url("http://example.com:3020")


def test_status_reports_available_for_expected_page(monkeypatch):
    monkeypatch.setenv("TICKFLOW_CHANLUN_URL", "http://127.0.0.1:3020")
    response = httpx.Response(
        200,
        text="<title>Chanlun Visualizer</title>",
        request=httpx.Request("GET", "http://127.0.0.1:3020"),
    )

    status = chanlun_bridge.get_status(client=_FakeClient(response))

    assert status["available"] is True
    assert status["viewer_url"] == "http://127.0.0.1:3020"
    assert status["capabilities"]["sub_indicators"] == 38


def test_status_fails_closed_for_invalid_config(monkeypatch):
    monkeypatch.setenv("TICKFLOW_CHANLUN_URL", "http://example.com")

    status = chanlun_bridge.get_status(client=_FakeClient(AssertionError("must not call")))

    assert status["available"] is False
    assert status["viewer_url"] is None


def test_status_reports_local_service_timeout(monkeypatch):
    monkeypatch.setenv("TICKFLOW_CHANLUN_URL", "http://127.0.0.1:3020")
    timeout = httpx.ConnectTimeout(
        "offline",
        request=httpx.Request("GET", "http://127.0.0.1:3020"),
    )

    status = chanlun_bridge.get_status(client=_FakeClient(timeout))

    assert status["available"] is False
    assert status["viewer_url"] == "http://127.0.0.1:3020"
    assert "ConnectTimeout" in status["detail"]


def test_api_uses_bridge_contract(monkeypatch):
    expected = {"available": False, "viewer_url": None, "detail": "offline", "capabilities": {}}
    monkeypatch.setattr("app.api.chanlun.get_status", lambda: expected)

    assert chanlun_status() == expected
