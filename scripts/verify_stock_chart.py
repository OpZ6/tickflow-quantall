"""Standalone Edge/Playwright acceptance check for the unified stock-chart workbench."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

FRONTEND_URL = "http://127.0.0.1:3011"
BACKEND_URL = "http://127.0.0.1:3018"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "stock-chart"


def read_json(url: str) -> dict:
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    catalog = read_json(f"{BACKEND_URL}/api/strategies")
    registered = {item["id"] for item in catalog.get("strategies", [])}
    required_strategies = {
        "vcp_breakout", "cup_handle_breakout", "high_tight_flag_breakout", "launch_pullback_support",
    }
    if missing := required_strategies - registered:
        raise SystemExit(f"正式策略缺失: {sorted(missing)}")

    query = urlencode({
        "symbol": "600000.SH", "asset_type": "stock", "interval": "1d",
        "adjustment": "qfq", "range": "3y", "warmup_bars": 500,
        "indicator_warmups": "macd:120,chanlun:500",
    })
    chart_probe = read_json(f"{BACKEND_URL}/api/kline/chart?{query}")
    if chart_probe["meta"]["required_warmup_bars"] != 500:
        raise SystemExit("参数化预热没有进入图表 API")
    if set(chart_probe["meta"]["indicator_readiness"]) != {"macd", "chanlun"}:
        raise SystemExit("逐指标预热状态缺失")
    if not chart_probe["meta"]["complete"] or not chart_probe["meta"]["warmup_complete"]:
        raise SystemExit(f"3 年样本覆盖或预热不完整: {chart_probe['meta']}")
    if len(chart_probe["rows"]) < 700 or len(chart_probe["analysis_rows"]) <= len(chart_probe["rows"]):
        raise SystemExit("3 年可见数据或隐藏预热数据量不足")

    console_errors: list[str] = []
    failed_requests: list[str] = []
    chart_requests: list[str] = []
    chart_responses: list[tuple[str, int]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        def route_request(route) -> None:
            url = route.request.url
            if any(host in url for host in ("fonts.googleapis.com", "rsms.me")):
                route.fulfill(status=200, content_type="text/css", body="")
            elif any(host in url for host in ("google-analytics", "googletagmanager", "sentry.io")):
                route.abort()
            else:
                route.continue_()

        context.route("**/*", route_request)
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

        def record_failure(request) -> None:
            failure = str(request.failure)
            if "ERR_ABORTED" in failure or "/api/intraday/stream" in request.url:
                return
            failed_requests.append(f"{request.method} {request.url}: {failure}")

        page.on("requestfailed", record_failure)
        page.on("request", lambda request: chart_requests.append(request.url) if "/api/kline/chart" in request.url else None)
        page.on("response", lambda response: chart_responses.append((response.url, response.status)) if "/api/kline/chart" in response.url else None)

        page.goto(f"{FRONTEND_URL}/stock-analysis?symbol=600000.SH&name=浦发银行", wait_until="domcontentloaded")
        page.evaluate("localStorage.removeItem('stock_chart_layout_v1')")
        page.reload(wait_until="domcontentloaded")
        chart = page.get_by_test_id("unified-stock-chart")
        chart.wait_for(state="visible", timeout=30_000)
        page.get_by_test_id("unified-stock-chart-instance").wait_for(state="visible", timeout=30_000)
        page.wait_for_function("document.querySelectorAll('[data-testid=unified-stock-chart-instance] canvas').length === 1")
        assert page.get_by_test_id("stock-chart-toolbar").count() == 1
        assert page.get_by_role("button", name="指标中心").count() == 1
        assert page.get_by_role("complementary", name="指标管理器").count() == 0

        page.get_by_role("button", name="指标中心").click()
        center = page.get_by_test_id("chart-indicator-center")
        center.wait_for(state="visible")
        for tab in ("技术指标", "结构指标", "形态", "策略", "事件", "模板", "画线"):
            center.get_by_role("button", name=tab, exact=True).wait_for(state="visible")

        rsi_section = center.locator("section").filter(has_text="RSI").first
        requests_before_rsi = len(chart_requests)
        rsi_section.get_by_role("checkbox").check()
        rsi_section.get_by_role("button").first.click()
        rsi_section.locator("span").filter(has_text="预热：").last.wait_for(state="visible")
        page.wait_for_timeout(500)
        assert len(chart_requests) > requests_before_rsi, "新增指标的预热契约应进入查询键"
        assert "indicator_warmups=" in chart_requests[-1]
        requests_before_style = len(chart_requests)
        rsi_section.locator('input[type="color"]').fill("#f97316")
        page.wait_for_timeout(300)
        assert len(chart_requests) == requests_before_style, "仅调整指标样式不应重新请求行情"

        rsi_section.get_by_role("button", name="下移 RSI").focus()
        page.keyboard.press("Enter")
        assert page.evaluate("JSON.parse(localStorage.getItem('stock_chart_layout_v1')).indicators.find(item => item.indicatorId === 'rsi').pane.order") > 0

        center.get_by_role("button", name="结构指标", exact=True).click()
        toolbar_box_before = page.get_by_test_id("stock-chart-toolbar").bounding_box()
        chanlun_toggle = center.locator("section").filter(has_text="缠论结构指标").first.get_by_role("checkbox").first
        with page.expect_response(lambda response: "/api/chanlun/analyze" in response.url and response.status == 200, timeout=60_000):
            chanlun_toggle.check()
        assert center.get_by_text("包含处理", exact=True).is_visible()
        assert center.get_by_text("买卖点", exact=True).is_visible()
        key_levels_section = center.locator("section").filter(has_text="关键价位指标").first
        assert key_levels_section.count() == 1
        key_levels_section.scroll_into_view_if_needed()
        assert key_levels_section.is_visible()
        toolbar_box_after = page.get_by_test_id("stock-chart-toolbar").bounding_box()
        assert toolbar_box_before and toolbar_box_after
        assert abs(toolbar_box_before["height"] - toolbar_box_after["height"]) < 2

        center.get_by_role("button", name="模板", exact=True).click()
        center.get_by_text("趋势", exact=True).click()
        center.get_by_text("当前工作区与所应用模板一致。", exact=True).wait_for(state="visible")
        page.once("dialog", lambda dialog: dialog.accept("Playwright 验收模板"))
        center.get_by_role("button", name="保存当前工作区为新模板", exact=True).click()
        center.get_by_text("Playwright 验收模板", exact=True).wait_for(state="visible")
        stored = page.evaluate("JSON.parse(localStorage.getItem('stock_chart_layout_v1'))")
        custom = next(item for item in stored["templates"] if item["name"] == "Playwright 验收模板")
        assert custom["system"] is False and custom["indicators"]
        assert all("params" in item and "style" in item and "pane" in item for item in custom["indicators"])

        center.get_by_role("button", name="关闭指标中心").click()
        with page.expect_response(lambda response: "/api/kline/chart" in response.url and "range=3y" in response.url and response.status == 200, timeout=60_000):
            chart.get_by_role("combobox", name="范围").select_option("3y")
        assert any("range=3y" in url for url in chart_requests)
        chart_instance = page.get_by_test_id("unified-stock-chart-instance")
        assert chart_instance.is_visible()
        page.wait_for_function(
            "(element) => Number(element.dataset.rowCount) >= 700 && element.dataset.visibleBars === element.dataset.rowCount",
            arg=chart_instance.element_handle(),
        )
        assert int(chart_instance.get_attribute("data-row-count")) >= 700
        assert int(chart_instance.get_attribute("data-visible-bars")) == int(chart_instance.get_attribute("data-row-count"))
        assert float(chart_instance.get_attribute("data-initial-zoom-start")) == 0

        chart.get_by_role("button", name="更多图表操作").click()
        chart.get_by_role("button", name="截图", exact=True).wait_for(state="visible")
        chart.get_by_role("button", name="全屏", exact=True).wait_for(state="visible")
        chart.get_by_role("button", name="更多图表操作").click()

        page.reload(wait_until="domcontentloaded")
        chart.wait_for(state="visible", timeout=30_000)
        page.get_by_role("button", name="指标中心").click()
        center = page.get_by_test_id("chart-indicator-center")
        center.get_by_role("button", name="模板", exact=True).click()
        center.get_by_text("Playwright 验收模板", exact=True).wait_for(state="visible")
        center.get_by_role("button", name="关闭指标中心").click()

        page.goto(
            f"{FRONTEND_URL}/stock-analysis?symbol=600000.SH&name=浦发银行"
            "&strategyId=trend_breakout&asOf=2026-08-31",
            wait_until="domcontentloaded",
        )
        page.get_by_test_id("strategy-chart-context").wait_for(state="visible", timeout=30_000)
        page.get_by_role("button", name="指标中心").click()
        center = page.get_by_test_id("chart-indicator-center")
        center.get_by_role("button", name="策略", exact=True).click()
        center.get_by_test_id("single-stock-strategy-preview").wait_for(state="visible")
        assert page.locator("[data-testid=unified-stock-chart-instance]").count() == 1

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        document_overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        page.screenshot(path=OUTPUT_DIR / "workbench-mobile.png", full_page=True)
        page.set_viewport_size({"width": 1600, "height": 1000})
        center.get_by_role("button", name="关闭指标中心").click()
        page.screenshot(path=OUTPUT_DIR / "workbench-desktop.png", full_page=True)

        result = {
            "single_chart_instance": True,
            "single_indicator_center": True,
            "toolbar_rows": 1,
            "indicator_tabs": 7,
            "template_persisted": True,
            "template_payload_complete": True,
            "three_year_request": True,
            "three_year_full_initial_view": True,
            "three_year_coverage_complete": True,
            "parameterized_warmup": True,
            "per_indicator_readiness": True,
            "style_change_without_market_refetch": True,
            "keyboard_indicator_reorder": True,
            "strategy_deep_link": True,
            "chart_requests": len(chart_requests),
            "failed_chart_responses": [item for item in chart_responses if item[1] >= 400],
            "console_errors": console_errors,
            "failed_requests": failed_requests,
            "document_overflow_mobile": document_overflow,
        }
        browser.close()

    (OUTPUT_DIR / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if console_errors or failed_requests or result["failed_chart_responses"] or document_overflow:
        raise SystemExit(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
