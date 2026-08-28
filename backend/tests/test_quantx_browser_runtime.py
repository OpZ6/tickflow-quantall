from __future__ import annotations

from app.quantx_data import browser_runtime


class _Chromium:
    def __init__(self) -> None:
        self.kwargs = None

    def launch(self, **kwargs):
        self.kwargs = kwargs
        return object()


class _Playwright:
    def __init__(self) -> None:
        self.chromium = _Chromium()


def test_windows_browser_runtime_uses_installed_edge(monkeypatch) -> None:
    monkeypatch.setattr(browser_runtime.sys, "platform", "win32")
    playwright = _Playwright()

    browser_runtime.launch_chromium(playwright, headless=True)

    assert playwright.chromium.kwargs == {"headless": True, "channel": "msedge"}


def test_non_windows_browser_runtime_uses_playwright_chromium(monkeypatch) -> None:
    monkeypatch.setattr(browser_runtime.sys, "platform", "linux")
    playwright = _Playwright()

    browser_runtime.launch_chromium(playwright, headless=True)

    assert playwright.chromium.kwargs == {"headless": True}
