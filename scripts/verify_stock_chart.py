"""Standalone Playwright acceptance check for the unified stock chart."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:3011"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "stock-chart"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    failed_requests: list[str] = []
    chart_requests: list[str] = []

    with urlopen("http://127.0.0.1:3018/api/strategies", timeout=30) as response:
        strategy_catalog = json.load(response)
    required_strategy_ids = {
        "vcp_breakout",
        "cup_handle_breakout",
        "high_tight_flag_breakout",
        "launch_pullback_support",
    }
    registered_strategy_ids = {
        item["id"] for item in strategy_catalog.get("strategies", [])
    }
    missing_strategies = required_strategy_ids - registered_strategy_ids
    if missing_strategies or strategy_catalog.get("load_errors"):
        raise SystemExit(
            "price-structure strategy registry failed: "
            + json.dumps(
                {
                    "missing": sorted(missing_strategies),
                    "load_errors": strategy_catalog.get("load_errors", []),
                },
                ensure_ascii=False,
            )
        )

    with urlopen(
        "http://127.0.0.1:3018/api/kline/chart?symbol=600000.SH&asset_type=stock"
        "&interval=1d&adjustment=qfq&range=1y&layers=pattern",
        timeout=60,
    ) as response:
        pattern_chart = json.load(response)
    pattern_layer_ids = {
        layer["id"] for layer in pattern_chart.get("annotation_layers", [])
    }
    if pattern_layer_ids != {"pattern.classic"}:
        raise SystemExit(
            "price-structure layers must be registered strategies, not patterns: "
            + json.dumps(sorted(pattern_layer_ids), ensure_ascii=False)
        )

    run_request = Request(
        "http://127.0.0.1:3018/api/screener/run_preset",
        data=json.dumps({"strategy_id": "trend_breakout", "asset_type": "stock", "timeframe": "1d"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(run_request, timeout=120) as response:  # noqa: S310 - fixed localhost acceptance target
        strategy_result = json.load(response)
    if not strategy_result.get("rows"):
        raise SystemExit("trend_breakout returned no rows; cannot verify the real strategy deep-link chain")
    target_symbol = strategy_result["rows"][0]["symbol"]
    strategy_id = strategy_result.get("strategy") or strategy_result.get("strategy_id")
    as_of = strategy_result["as_of"]
    source_run_id = strategy_result["source_run_id"]
    params_fingerprint = strategy_result["params_fingerprint"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        context.route(
            "**/*",
            lambda route: route.abort()
            if any(host in route.request.url for host in ("google-analytics", "googletagmanager", "sentry.io"))
            else route.continue_(),
        )
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        def record_failed_request(request) -> None:
            detail = f"{request.method} {request.url}: {request.failure}"
            # React Query 在 reload 时会主动取消上一页的 SSE；这不是网络故障。
            if "/api/intraday/stream" in request.url and "ERR_ABORTED" in str(request.failure):
                return
            failed_requests.append(detail)

        page.on("requestfailed", record_failed_request)
        page.on("request", lambda request: chart_requests.append(request.url) if "/api/kline/chart" in request.url else None)

        page.goto(f"{BASE_URL}/stock-analysis?symbol=600000.SH&name=浦发银行", wait_until="domcontentloaded")
        chart = page.get_by_test_id("unified-stock-chart")
        chart.wait_for(state="visible", timeout=30_000)
        page.get_by_test_id("unified-stock-chart-instance").wait_for(state="visible", timeout=30_000)
        page.wait_for_function("document.querySelectorAll('[data-testid=unified-stock-chart-instance] canvas').length === 1")

        initial_request_count = len(chart_requests)
        page.get_by_role("button", name="指标管理").click()
        drawer = page.get_by_role("complementary", name="指标管理器")
        drawer.wait_for(state="visible")
        drawer.locator("button").filter(has_text="RSI").first.click()
        drawer.get_by_role("button", name="关闭指标管理器").click()
        page.get_by_text("RSI", exact=True).first.wait_for(state="visible")
        page.wait_for_timeout(300)
        assert len(chart_requests) == initial_request_count, "切换指标不应重新请求 K 线"

        # 关键结构图层与同一个 canvas 同时存在。
        page.get_by_text("支撑阻力", exact=True).wait_for(state="visible")

        page.get_by_role("button", name="图层管理").click()
        manager = page.get_by_test_id("chart-layer-manager")
        for tab in ("技术指标", "缠论", "形态", "策略", "事件", "画线"):
            manager.get_by_role("button", name=tab, exact=True).wait_for(state="visible")
        manager.get_by_role("button", name="策略", exact=True).click()
        manager.get_by_text("策略信号", exact=True).wait_for(state="visible")
        page.get_by_role("button", name="关闭图层管理").click()

        chart.get_by_role("button", name="缠论", exact=True).first.click()
        page.get_by_text("默认本地算法", exact=False).wait_for(state="visible")
        page.get_by_text("包含处理", exact=True).wait_for(state="visible")
        page.get_by_text("分型", exact=True).wait_for(state="visible")
        assert page.locator("[data-testid=unified-stock-chart-instance]").count() == 1
        assert page.locator("[data-testid=unified-stock-chart-instance] canvas").count() == 1

        # 回放只截断当前内存序列，不重新请求行情。
        requests_before_replay = len(chart_requests)
        chart.get_by_role("button", name="回放", exact=True).click()
        page.get_by_role("slider", name="逐根回放").wait_for(state="visible")
        page.get_by_role("button", name="下一根", exact=True).click()
        assert len(chart_requests) == requests_before_replay
        page.get_by_role("button", name="退出", exact=True).click()

        # 周期变化才应产生新行情请求，并仍保留唯一图表实例。
        chart.get_by_role("combobox", name="周期").select_option("1w")
        page.wait_for_function("document.querySelectorAll('[data-testid=unified-stock-chart-instance] canvas').length === 1")
        assert len(chart_requests) > requests_before_replay
        chart.get_by_role("combobox", name="周期").select_option("1d")

        # 双击主图建立水平线，验证按股票/周期持久化以及单项删除入口。
        canvas = page.locator("[data-testid=unified-stock-chart-instance] canvas")
        box = canvas.bounding_box()
        assert box is not None
        canvas.dblclick(position={"x": box["width"] * 0.55, "y": box["height"] * 0.25})
        page.get_by_text("画线：", exact=True).wait_for(state="visible")
        page.get_by_role("button", name="删除画线 1").wait_for(state="visible")

        page.screenshot(path=OUTPUT_DIR / "desktop.png", full_page=True)
        chart.screenshot(path=OUTPUT_DIR / "chart.png")

        page.reload(wait_until="domcontentloaded")
        chart.wait_for(state="visible", timeout=30_000)
        page.get_by_text("RSI", exact=True).first.wait_for(state="visible")
        page.get_by_text("画线：", exact=True).wait_for(state="visible")
        assert page.locator("[data-testid=unified-stock-chart-instance]").count() == 1
        assert chart.get_by_role("combobox", name="周期").input_value() == "1d"

        # 使用真实策略结果验证策略页 → K 线深链、批次恢复和刷新恢复。
        page.evaluate("strategyId => localStorage.setItem('strategy-pool', JSON.stringify([strategyId]))", strategy_id)
        page.goto(
            f"{BASE_URL}/screener?strategyId={strategy_id}&asOf={as_of}",
            wait_until="domcontentloaded",
        )
        signal_link = page.get_by_test_id(f"strategy-signal-{target_symbol}")
        signal_link.wait_for(state="visible", timeout=30_000)
        signal_link.click()
        page.get_by_test_id("strategy-chart-context").wait_for(state="visible", timeout=30_000)
        page.wait_for_url("**/stock-analysis?**")
        assert f"strategyId={strategy_id}" in page.url
        assert f"sourceRunId={source_run_id}" in page.url
        assert f"paramsFingerprint={params_fingerprint}" in page.url
        page.reload(wait_until="domcontentloaded")
        page.get_by_test_id("strategy-chart-context").wait_for(state="visible", timeout=30_000)
        assert page.get_by_text("策略信号层已自动激活", exact=True).is_visible()
        assert page.locator("[data-testid=unified-stock-chart-instance] canvas").count() == 1
        page.get_by_role("button", name="图层管理").click()
        manager = page.get_by_test_id("chart-layer-manager")
        manager.get_by_role("button", name="策略", exact=True).click()
        manager.get_by_test_id("strategy-scope-all").click()
        page.wait_for_timeout(500)
        manager.get_by_test_id("annotation-density-detailed").click()
        manager.get_by_test_id("annotation-density-auto").click()
        manager.get_by_test_id("strategy-scope-source").click()
        page.wait_for_timeout(500)
        assert page.locator("[data-testid=unified-stock-chart-instance] canvas").count() == 1

        overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        result = {
            "chart_requests": len(chart_requests),
            "console_errors": console_errors,
            "failed_requests": failed_requests,
            "single_chart_instance": True,
            "indicator_persisted": True,
            "strategy_deep_link": True,
            "strategy_context_persisted": True,
            "layer_manager_tabs": 6,
            "strategy_scope_switch": True,
            "annotation_density_switch": True,
            "registered_price_structure_strategies": sorted(required_strategy_ids),
            "pattern_layer_ids": sorted(pattern_layer_ids),
            "horizontal_overflow": overflow,
        }
        (OUTPUT_DIR / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()

    if console_errors or failed_requests or overflow:
        raise SystemExit(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
