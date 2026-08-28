"""Verify the QuantX single-day rich dashboard with standalone Playwright."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import ConsoleMessage, Page, Request, sync_playwright

OVERVIEW_PANELS = (
    "quantx-market-pulse",
    "quantx-theme-mainline",
    "quantx-decision-rail",
    "quantx-risk-signals",
    "quantx-emotion-calendar",
    "quantx-sector-breadth",
    "quantx-capital-ecosystem",
)

DEEP_SECTIONS = (
    "市场趋势",
    "题材行业",
    "情绪连板",
    "资金生态",
    "关注预案",
    "完整数据",
    "质量血缘",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify QuantX single-day charts and canonical metadata."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3011")
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:3018",
    )
    parser.add_argument(
        "--dates",
        nargs="+",
        default=["20260825", "20260826", "20260827"],
    )
    parser.add_argument("--minimum-canvas", type=int, default=10)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def _block_telemetry(route) -> None:
    url = route.request.url.lower()
    if any(marker in url for marker in ("rsms.me", "fonts.googleapis.com", "fonts.gstatic.com")):
        route.fulfill(status=204, content_type="text/css", body="")
        return
    if any(
        marker in url
        for marker in ("google-analytics", "googletagmanager", "sentry.io")
    ):
        route.abort()
    else:
        route.continue_()


def _verify_page(
    page: Page,
    *,
    base_url: str,
    api_url: str,
    trade_date: str,
    minimum_canvas: int,
    output_dir: Path,
) -> dict[str, object]:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    def on_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            console_errors.append(message.text)

    def on_page_error(error: Exception) -> None:
        page_errors.append(str(error))

    def on_request_failed(request: Request) -> None:
        if "/api/intraday/stream" in request.url and "ERR_ABORTED" in str(request.failure):
            return
        failed_requests.append(
            f"{request.method} {request.url}: {request.failure or 'failed'}"
        )

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)
    response = page.goto(
        f"{base_url.rstrip('/')}/quantx/{trade_date}",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    if response is None or not response.ok:
        raise AssertionError(f"page navigation failed for {trade_date}")

    dashboard = page.get_by_test_id("quantx-unified-dashboard")
    dashboard.wait_for(
        state="visible",
        timeout=60_000,
    )
    page.get_by_role("heading", name="QuantX 市场驾驶舱", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    for test_id in OVERVIEW_PANELS:
        if not page.get_by_test_id(test_id).is_visible():
            raise AssertionError(
                f"missing overview panel for {trade_date}: {test_id}"
            )
    if not page.get_by_test_id("quantx-metric-ribbon").is_visible():
        raise AssertionError(f"metric ribbon missing for {trade_date}")
    if not page.get_by_test_id("quantx-deep-workspace").is_visible():
        raise AssertionError(f"deep workspace missing for {trade_date}")
    deep_workspace = page.get_by_test_id("quantx-deep-workspace")
    for label in DEEP_SECTIONS:
        if not deep_workspace.get_by_role(
            "heading", name=label, exact=True
        ).is_visible():
            raise AssertionError(f"deep section missing for {trade_date}: {label}")
    if page.locator('[aria-label="多日窗口"]').count():
        raise AssertionError("obsolete global window switch is still rendered")
    if page.get_by_role("tab", name="全部展开", exact=True).count():
        raise AssertionError("obsolete compact/full switch is still rendered")
    if page.get_by_role("heading", name="情绪趋势", exact=True).count():
        raise AssertionError("duplicate emotion trend panel is still rendered")
    if page.get_by_role("heading", name="全A K线 + CCI5", exact=True).count():
        raise AssertionError("duplicate full-market K-line panel is still rendered")
    if page.get_by_role("heading", name="连板梯队网格", exact=True).count():
        raise AssertionError("removed ladder grid is still rendered")
    if page.get_by_test_id("quantx-watchlist").count():
        raise AssertionError("duplicate top-level watchlist is still rendered")

    date_picker = page.get_by_label("QuantX交易日", exact=True)
    if date_picker.evaluate("element => element.tagName") != "BUTTON":
        raise AssertionError("QuantX trade date must use the calendar date picker")
    risk_board = page.get_by_test_id("quantx-risk-signals")
    risk_board.get_by_text("参与度条件", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    if deep_workspace.get_by_role("heading", name="参与度条件", exact=True).count():
        raise AssertionError("participation conditions are duplicated in the themes section")

    lifecycle = page.get_by_test_id("theme-lifecycle-all")
    for label in ("当日结构", "跨日生灭", "连续性热力图"):
        lifecycle.get_by_role("heading", name=label, exact=True).wait_for(
            state="visible", timeout=30_000
        )
    for test_id in (
        "theme-lifecycle-current",
        "theme-lifecycle-events",
        "theme-lifecycle-heatmap",
    ):
        metrics = page.get_by_test_id(test_id).evaluate(
            "element => ({clientHeight: element.clientHeight, scrollHeight: element.scrollHeight, overflowY: getComputedStyle(element).overflowY})"
        )
        if metrics["overflowY"] in {"auto", "scroll"}:
            raise AssertionError(f"nested lifecycle scrolling detected: {test_id}")
    current_box = page.get_by_test_id("theme-lifecycle-current").bounding_box()
    events_box = page.get_by_test_id("theme-lifecycle-events").bounding_box()
    if not current_box or not events_box or events_box["y"] <= current_box["y"]:
        raise AssertionError("lifecycle events must use the full-width row below the summary")
    if page.locator('[data-testid^="lifecycle-group-"]').count() < 2:
        raise AssertionError("lifecycle events must be grouped by status")

    flow_industries = page.get_by_test_id("sector-flow-industries").bounding_box()
    flow_rules = page.get_by_test_id("sector-flow-rules").bounding_box()
    if not flow_industries or not flow_rules or abs(flow_industries["y"] - flow_rules["y"]) > 2 or flow_industries["x"] >= flow_rules["x"]:
        raise AssertionError("sector flow continuity tables must render side by side")
    for section in ("data", "quality"):
        disclosure = page.get_by_test_id(f"quantx-collapsible-{section}")
        if disclosure.get_attribute("aria-expanded") != "false":
            raise AssertionError(f"{section} must be collapsed by default")

    selected_date = page.get_by_label("QuantX交易日", exact=True).text_content()
    expected_picker_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    if selected_date != expected_picker_date:
        raise AssertionError(
            f"date picker mismatch: expected {expected_picker_date}, got {selected_date}"
        )
    canvas_count = page.locator("canvas").count()
    if canvas_count < minimum_canvas:
        raise AssertionError(
            f"chart regression for {trade_date}: {canvas_count} < {minimum_canvas}"
        )
    if not page.get_by_text("最高板", exact=True).first.is_visible():
        raise AssertionError(f"height summary missing for {trade_date}")
    page.get_by_role("tab", name="二级", exact=True).click()
    page.get_by_text("申万二级行业均线宽度", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    breadth_scroll = page.get_by_test_id("quantx-sector-breadth-scroll")
    dimensions = breadth_scroll.evaluate(
        "element => ({clientHeight: element.clientHeight, scrollHeight: element.scrollHeight})"
    )
    if dimensions["scrollHeight"] <= dimensions["clientHeight"]:
        raise AssertionError("level-2 breadth must expose its complete scrollable matrix")
    legend = page.get_by_test_id("quantx-sector-breadth-legend")
    for label in (
        "站上5日均线占比",
        "站上10日均线占比",
        "站上20日均线占比",
        "站上60日均线占比",
    ):
        if not legend.get_by_text(label, exact=True).is_visible():
            raise AssertionError(f"breadth semantics missing: {label}")
    capital_box = page.get_by_test_id("quantx-capital-ecosystem").bounding_box()
    breadth_box = page.get_by_test_id("quantx-sector-breadth").bounding_box()
    if not capital_box or not breadth_box or capital_box["width"] <= breadth_box["width"]:
        raise AssertionError("capital ecosystem must be wider than sector breadth")
    breadth_screenshot = output_dir / f"quantx-breadth-level2-{trade_date}.png"
    page.get_by_test_id("quantx-sector-breadth").screenshot(
        path=str(breadth_screenshot)
    )
    capital_breadth_screenshot = output_dir / f"quantx-capital-breadth-{trade_date}.png"
    page.get_by_test_id("quantx-capital-breadth-row").screenshot(
        path=str(capital_breadth_screenshot)
    )
    page.get_by_role("tab", name="一级", exact=True).click()

    risk_screenshot = output_dir / f"quantx-risk-signals-{trade_date}.png"
    page.get_by_test_id("quantx-risk-signals").screenshot(path=str(risk_screenshot))
    header_screenshot = output_dir / f"quantx-header-{trade_date}.png"
    page.get_by_test_id("quantx-dashboard-header").screenshot(path=str(header_screenshot))
    emotion_calendar_screenshot = output_dir / f"quantx-emotion-calendar-{trade_date}.png"
    page.get_by_test_id("quantx-emotion-calendar").screenshot(
        path=str(emotion_calendar_screenshot)
    )
    lifecycle_screenshot = output_dir / f"quantx-theme-lifecycle-{trade_date}.png"
    page.get_by_test_id("theme-lifecycle").screenshot(
        path=str(lifecycle_screenshot)
    )
    congestion = page.get_by_test_id("quantx-congestion-panel")
    congestion.get_by_text("近十日拥挤度历史", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    if deep_workspace.get_by_role("heading", name="拥挤度", exact=True).count():
        raise AssertionError("standalone congestion gauge is still rendered")
    if deep_workspace.get_by_role("heading", name="拥挤度历史", exact=True).count():
        raise AssertionError("standalone congestion history is still rendered")
    congestion_screenshot = output_dir / f"quantx-congestion-{trade_date}.png"
    congestion.screenshot(path=str(congestion_screenshot))

    page.get_by_text("交易日情绪分数", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    calendar_date = page.get_by_label(f"选择交易日 {trade_date}", exact=True)
    if not calendar_date.is_visible():
        raise AssertionError(f"selected date missing from emotion calendar: {trade_date}")
    if "ring-accent" not in (calendar_date.get_attribute("class") or ""):
        raise AssertionError(f"emotion calendar did not highlight {trade_date}")

    api_response = page.request.get(
        f"{api_url.rstrip('/')}/api/quantx/review/{trade_date}/data",
        timeout=60_000,
    )
    if not api_response.ok:
        raise AssertionError(
            f"review API failed for {trade_date}: {api_response.status}"
        )
    payload = api_response.json()
    foundation = payload.get("data_foundation") or {}
    if foundation.get("schema_version") != "quantx-review.v2":
        raise AssertionError(f"unexpected review schema for {trade_date}")
    if foundation.get("source_json_read") is not False:
        raise AssertionError(f"review JSON was read for {trade_date}")
    if foundation.get("fallback_fields"):
        raise AssertionError(
            f"canonical fallback detected for {trade_date}: "
            f"{foundation['fallback_fields']}"
        )
    if foundation.get("implicit_cache_fields"):
        raise AssertionError(
            f"implicit cache fields detected for {trade_date}: "
            f"{foundation['implicit_cache_fields']}"
        )
    if payload.get("emotion", {}).get("daily_summary") in (None, ""):
        raise AssertionError(f"daily summary missing for {trade_date}")
    new_high = ((payload.get("sections") or {}).get("s2") or {}).get("new_high")
    if not new_high or new_high.get("status") != "ok":
        raise AssertionError(f"100-day-high fact is unavailable for {trade_date}")

    page.get_by_test_id("quantx-collapsible-data").click()
    page.get_by_text("正在加载完整数据表", exact=True).wait_for(
        state="detached", timeout=60_000
    )
    page.get_by_test_id("quantx-collapsible-quality").click()
    page.get_by_text("数据来源", exact=True).wait_for(
        state="visible", timeout=60_000
    )
    quality_text = page.get_by_test_id("quantx-deep-quality").inner_text()
    if "[object Object]" in quality_text:
        raise AssertionError("quality tables contain unreadable nested object values")
    table_audit = page.get_by_test_id("quantx-adaptive-table").evaluate_all(
        "elements => elements.map((wrapper, index) => { const table = wrapper.querySelector('table'); return {index, wrapperWidth: wrapper.clientWidth, tableWidth: table ? table.getBoundingClientRect().width : 0}; })"
    )
    undersized_tables = [row for row in table_audit if row["tableWidth"] + 1 < row["wrapperWidth"]]
    if undersized_tables:
        raise AssertionError(f"tables do not fit their cards: {undersized_tables}")
    deep_table_screenshots: dict[str, str] = {}
    for tab in ("themes", "emotion", "flow", "watch", "quality"):
        target = output_dir / f"quantx-deep-{tab}-{trade_date}.png"
        page.get_by_test_id(f"quantx-deep-{tab}").screenshot(path=str(target))
        deep_table_screenshots[tab] = str(target)

    page.evaluate("window.scrollTo(0, 0)")
    screenshot = output_dir / f"quantx-dashboard-{trade_date}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    page.remove_listener("console", on_console)
    page.remove_listener("pageerror", on_page_error)
    page.remove_listener("requestfailed", on_request_failed)
    if console_errors:
        raise AssertionError(
            f"console errors for {trade_date}: {console_errors}; "
            f"failed requests: {failed_requests}"
        )
    if page_errors:
        raise AssertionError(f"page errors for {trade_date}: {page_errors}")
    if failed_requests:
        raise AssertionError(
            f"failed requests for {trade_date}: {failed_requests}"
        )
    return {
        "trade_date": trade_date,
        "canvas_count": canvas_count,
        "derived_field_count": len(foundation.get("derived_fields") or []),
        "implicit_cache_field_count": len(
            foundation.get("implicit_cache_fields") or []
        ),
        "new_high_count": len(new_high.get("stocks") or []),
        "screenshot": str(screenshot),
        "breadth_screenshot": str(breadth_screenshot),
        "capital_breadth_screenshot": str(capital_breadth_screenshot),
        "risk_screenshot": str(risk_screenshot),
        "header_screenshot": str(header_screenshot),
        "emotion_calendar_screenshot": str(emotion_calendar_screenshot),
        "lifecycle_screenshot": str(lifecycle_screenshot),
        "congestion_screenshot": str(congestion_screenshot),
        "adaptive_table_count": len(table_audit),
        "deep_table_screenshots": deep_table_screenshots,
    }


def _verify_related_pages(page: Page, base_url: str, output_dir: Path) -> list[dict[str, str]]:
    checks = (
        ("quantx", "/quantx", "QuantX 市场驾驶舱"),
        ("market-lab", "/market-lab", "市场实验室"),
        ("limit-ladder", "/limit-ladder", "连板梯队"),
        ("regime", "/regime", "市场环境"),
    )
    results: list[dict[str, str]] = []
    for name, route, heading in checks:
        console_errors: list[str] = []
        page_errors: list[str] = []
        failed_requests: list[str] = []

        def on_console(message) -> None:
            if message.type == "error":
                console_errors.append(message.text)

        def on_page_error(error: Exception) -> None:
            page_errors.append(str(error))

        def on_request_failed(request) -> None:
            if "/api/intraday/stream" in request.url and "ERR_ABORTED" in str(request.failure):
                return
            failed_requests.append(
                f"{request.method} {request.url}: {request.failure}"
            )

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("requestfailed", on_request_failed)
        page.goto(f"{base_url.rstrip('/')}{route}", wait_until="domcontentloaded")
        page.get_by_role("heading", name=heading, exact=True).wait_for(
            state="visible", timeout=60_000
        )
        if name == "regime":
            page.get_by_role("button", name="情绪周期", exact=True).click()
            page.get_by_text("情绪周期时间轴", exact=True).wait_for(
                state="visible", timeout=30_000
            )
        if page.get_by_text("Unexpected Application Error!", exact=True).count():
            raise AssertionError(f"application error boundary shown on {route}")
        screenshot = output_dir / f"related-{name}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_page_error)
        page.remove_listener("requestfailed", on_request_failed)
        if console_errors or page_errors or failed_requests:
            raise AssertionError(
                f"related page failed for {route}: console={console_errors}, "
                f"page={page_errors}, requests={failed_requests}"
            )
        results.append({"route": route, "screenshot": str(screenshot)})
    return results


def _verify_observability(page: Page, base_url: str, output_dir: Path) -> dict[str, str]:
    page.goto(f"{base_url.rstrip('/')}/data", wait_until="domcontentloaded")
    page.get_by_role("heading", name="数据", exact=True).wait_for(
        state="visible", timeout=60_000
    )
    panel = page.get_by_test_id("quantx-observability")
    panel.wait_for(state="visible", timeout=60_000)
    panel.get_by_text("QuantX 发布、质量与血缘", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    panel.get_by_text("13 类标准事实", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    screenshot = output_dir / "quantx-observability.png"
    panel.screenshot(path=str(screenshot))
    return {"route": "/data", "screenshot": str(screenshot)}


def _verify_date_switch(page: Page, base_url: str, start: str, target: str) -> None:
    page.goto(
        f"{base_url.rstrip('/')}/quantx/{start}",
        wait_until="domcontentloaded",
    )
    picker = page.get_by_label("QuantX交易日", exact=True)
    picker.click()
    picker_target = f"{target[:4]}-{target[4:6]}-{target[6:]}"
    page.get_by_label(f"选择日期 {picker_target}", exact=True).click()
    page.wait_for_url(f"**/quantx/{target}**", timeout=30_000)
    if page.get_by_label("QuantX交易日", exact=True).text_content() != picker_target:
        raise AssertionError(f"date switch did not render {target}")


def _verify_responsive(
    page: Page,
    base_url: str,
    trade_date: str,
    output_dir: Path,
) -> dict[str, object]:
    page.set_viewport_size({"width": 1024, "height": 900})
    page.goto(
        f"{base_url.rstrip('/')}/quantx/{trade_date}",
        wait_until="domcontentloaded",
    )
    page.get_by_test_id("quantx-unified-dashboard").wait_for(
        state="visible", timeout=60_000
    )
    dimensions = page.evaluate(
        "({ width: document.documentElement.clientWidth, "
        "scrollWidth: document.documentElement.scrollWidth })"
    )
    if dimensions["scrollWidth"] > dimensions["width"] + 1:
        raise AssertionError(f"responsive horizontal overflow: {dimensions}")
    screenshot = output_dir / f"quantx-dashboard-1024-{trade_date}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    return {"viewport": "1024x900", "screenshot": str(screenshot)}


def _verify_empty_and_error_states(
    page: Page,
    base_url: str,
    api_url: str,
    trade_date: str,
    output_dir: Path,
) -> list[str]:
    response = page.request.get(
        f"{api_url.rstrip('/')}/api/quantx/review/{trade_date}/data",
        timeout=60_000,
    )
    payload = response.json()
    payload["data_foundation"]["canonical_fields"] = []
    endpoint = f"**/api/quantx/review/{trade_date}/data"
    page.route(
        endpoint,
        lambda route: route.fulfill(status=200, json=payload),
    )
    page.goto(
        f"{base_url.rstrip('/')}/quantx/{trade_date}",
        wait_until="domcontentloaded",
    )
    page.get_by_test_id("quantx-dashboard-empty").wait_for(
        state="visible", timeout=30_000
    )
    empty_screenshot = output_dir / "quantx-review-empty.png"
    page.screenshot(path=str(empty_screenshot), full_page=True)
    page.unroute(endpoint)

    missing_date = "19000101"
    page.goto(
        f"{base_url.rstrip('/')}/quantx/{missing_date}",
        wait_until="domcontentloaded",
    )
    page.get_by_test_id("quantx-dashboard-error").get_by_text(
        f"无 {missing_date} 的单日标准事实", exact=True
    ).wait_for(state="visible", timeout=30_000)
    error_screenshot = output_dir / "quantx-review-error.png"
    page.screenshot(path=str(error_screenshot), full_page=True)
    return [str(empty_screenshot), str(error_screenshot)]


def main() -> int:
    args = _args()
    output_dir = args.output_dir or Path(
        tempfile.gettempdir(), "tickflow-quantx-ui-evidence"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(args.base_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("base URL must target the local TickFlow instance")

    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("**/*", _block_telemetry)
        try:
            page = context.new_page()
            for trade_date in args.dates:
                results.append(
                    _verify_page(
                        page,
                        base_url=args.base_url,
                        api_url=args.api_url,
                        trade_date=trade_date,
                        minimum_canvas=args.minimum_canvas,
                        output_dir=output_dir,
                    )
                )
            if len(args.dates) > 1:
                _verify_date_switch(
                    page,
                    args.base_url,
                    args.dates[0],
                    args.dates[1],
                )
            responsive_result = _verify_responsive(
                page,
                args.base_url,
                args.dates[-1],
                output_dir,
            )
            state_screenshots = _verify_empty_and_error_states(
                page,
                args.base_url,
                args.api_url,
                args.dates[0],
                output_dir,
            )
            related_results = _verify_related_pages(
                page,
                args.base_url,
                output_dir,
            )
            observability_result = _verify_observability(
                page,
                args.base_url,
                output_dir,
            )
        finally:
            context.close()
            browser.close()

    print(
        json.dumps(
            {
                "status": "ok",
                "browser": "msedge",
                "headless": True,
                "results": results,
                "related_results": related_results,
                "observability_result": observability_result,
                "responsive_result": responsive_result,
                "state_screenshots": state_screenshots,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
