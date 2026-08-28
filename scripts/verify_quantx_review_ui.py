"""Verify the QuantX single-day rich dashboard with standalone Playwright."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import ConsoleMessage, Page, Request, sync_playwright

OVERVIEW_PANELS = (
    "quantx-market-pulse",
    "quantx-theme-mainline",
    "quantx-decision-rail",
    "quantx-emotion-cycle",
    "quantx-sector-breadth",
    "quantx-capital-ecosystem",
    "quantx-watchlist",
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
    for label in DEEP_SECTIONS:
        if not page.get_by_role("tab", name=label, exact=True).is_visible():
            raise AssertionError(f"deep tab missing for {trade_date}: {label}")

    selected_date = page.get_by_label("QuantX交易日", exact=True).input_value()
    if selected_date != trade_date:
        raise AssertionError(
            f"date selector mismatch: expected {trade_date}, got {selected_date}"
        )
    canvas_count = page.locator("canvas").count()
    if canvas_count < minimum_canvas:
        raise AssertionError(
            f"chart regression for {trade_date}: {canvas_count} < {minimum_canvas}"
        )
    if not page.get_by_text("最高板", exact=True).first.is_visible():
        raise AssertionError(f"height summary missing for {trade_date}")
    page.evaluate("window.scrollTo(0, 0)")
    compact_screenshot = output_dir / f"quantx-dashboard-compact-{trade_date}.png"
    page.screenshot(path=str(compact_screenshot), full_page=True)

    page.get_by_role("tab", name="二级", exact=True).click()
    page.get_by_text("申万二级行业均线宽度", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    page.get_by_role("tab", name="一级", exact=True).click()

    page.get_by_role("tab", name="全部展开", exact=True).click()
    deep_workspace = page.get_by_test_id("quantx-deep-workspace")
    for label in DEEP_SECTIONS:
        deep_workspace.get_by_role("heading", name=label, exact=True).wait_for(
            state="visible", timeout=30_000
        )
    page.get_by_text("交易日历", exact=True).wait_for(
        state="visible", timeout=30_000
    )
    full_canvas_count = page.locator("canvas").count()
    if full_canvas_count < canvas_count:
        raise AssertionError(
            f"full mode lost charts for {trade_date}: "
            f"{full_canvas_count} < {canvas_count}"
        )

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

    page.evaluate("window.scrollTo(0, 0)")
    screenshot = output_dir / f"quantx-dashboard-full-{trade_date}.png"
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
        "full_canvas_count": full_canvas_count,
        "derived_field_count": len(foundation.get("derived_fields") or []),
        "implicit_cache_field_count": len(
            foundation.get("implicit_cache_fields") or []
        ),
        "compact_screenshot": str(compact_screenshot),
        "full_screenshot": str(screenshot),
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
    page.get_by_label("QuantX交易日", exact=True).select_option(target)
    page.wait_for_url(f"**/quantx/{target}**", timeout=30_000)
    if page.get_by_label("QuantX交易日", exact=True).input_value() != target:
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
    return os.EX_OK


if __name__ == "__main__":
    raise SystemExit(main())
