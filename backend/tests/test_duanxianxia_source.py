"""短线侠采集器回归测试：旧版域名路由 + 失败原因可诊断。

不联网；用假 page 复现 2026-11-06 主站改版后 /web/* 返回 nginx 404 的情形。
"""
from __future__ import annotations

import pytest

from app.quantx_data.legacy_scrapers import duanxianxia_scraper as dx


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status


class _Locator:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self, timeout=None) -> str:
        return self._text


class _FakePage:
    """按 URL 顺序返回 (http_status, body_text)。"""

    def __init__(self, results: list[tuple[int, str]]) -> None:
        self._results = list(results)
        self._current = ""
        self.urls: list[str] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.urls.append(url)
        status, self._current = self._results.pop(0)
        return _Response(status)

    def wait_for_timeout(self, ms) -> None:
        return None

    def locator(self, selector):
        return _Locator(self._current)


def test_legacy_domain_is_first_candidate() -> None:
    assert dx.BASE_URLS[0] == "https://v.duanxianxia.com"
    assert "https://duanxianxia.com" in dx.BASE_URLS


def test_target_markers_reject_spa_homepage() -> None:
    homepage = "竞价 板块轮动 数据复盘 榜单数据 登录 注册 " * 200
    assert not dx._matches_target("/web/pool", homepage)
    assert not dx._matches_target("/web/qxlive", homepage)
    assert dx._matches_target("/web/pool", "涨停 32 今日 83 封板率 71% 连板 11")
    assert dx._matches_target("/web/qxlive", "情绪指标：34 涨停家数：32 跌停家数：15")


def test_goto_skips_404_and_returns_first_valid_page() -> None:
    page = _FakePage([
        (404, "404 Not Found | nginx"),
        (200, "涨停 32 今日 83 昨日 封板率 71% 连板 11 " * 20),
    ])
    base, text = dx._goto_first_working(page, "/web/pool")
    assert base == dx.BASE_URLS[1]
    assert "封板率" in text
    assert len(page.urls) == 2


def test_goto_error_lists_every_failure_reason() -> None:
    page = _FakePage([(404, "404 Not Found | nginx") for _ in dx.BASE_URLS])
    with pytest.raises(RuntimeError) as exc:
        dx._goto_first_working(page, "/web/pool")
    message = str(exc.value)
    assert "HTTP 404" in message
    assert all(url in message for url in dx.BASE_URLS)
    # 旧实现在这里只会给出 "all urls failed ...: None"，无法定位。
    assert ": None" not in message
