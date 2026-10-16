"""Export and verify a self-contained interactive QuantX HTML with Edge."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Page, sync_playwright


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one QuantX date as a self-contained interactive HTML file."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3011")
    parser.add_argument("--date", default="20260828")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-screenshot", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--minimum-canvas", type=int, default=20)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow replacing an existing output file.",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"\d{8}", args.date):
        parser.error("--date must use YYYYMMDD")
    return args


def _block_telemetry(route) -> None:
    url = route.request.url.lower()
    if any(
        marker in url
        for marker in (
            "google-analytics",
            "googletagmanager",
            "sentry.io",
        )
    ):
        route.abort()
        return
    route.continue_()


def _collect_page_errors(page: Page) -> list[str]:
    errors: list[str] = []

    def on_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(f"console:{message.text}")

    page.on("console", on_console)
    page.on("pageerror", lambda error: errors.append(f"pageerror:{error}"))
    return errors


def _wait_for_report(page: Page, minimum_canvas: int) -> int:
    report = page.get_by_test_id("quantx-unified-dashboard")
    report.wait_for(state="visible", timeout=120_000)
    page.get_by_test_id("quantx-advanced-industry").wait_for(
        state="visible", timeout=120_000
    )
    page.get_by_test_id("quantx-advanced-liquidity").wait_for(
        state="visible", timeout=120_000
    )
    page.wait_for_function(
        """minimum => {
          const root = document.querySelector('[data-testid="quantx-unified-dashboard"]');
          const canvases = root ? [...root.querySelectorAll('canvas')] : [];
          return canvases.length >= minimum
            && canvases.every(canvas => canvas.width > 0 && canvas.height > 0);
        }""",
        arg=minimum_canvas,
        timeout=120_000,
    )
    page.locator("main").evaluate(
        "element => { element.scrollTop = element.scrollHeight; element.scrollTop = 0; }"
    )
    return report.locator("canvas").count()


def _assert_no_horizontal_overflow(page: Page) -> None:
    dimensions = page.evaluate(
        """() => ({
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
        })"""
    )
    assert dimensions["scrollWidth"] <= dimensions["clientWidth"] + 1, dimensions


def _verify_offline(
    browser,
    *,
    output: Path,
    trade_date: str,
    source_canvas_count: int,
    screenshot: Path | None,
) -> dict[str, object]:
    html = output.read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html
    assert 'name="quantx-export-mode" content="interactive"' in html

    context = browser.new_context(
        offline=True,
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    errors = _collect_page_errors(page)
    external_requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            external_requests.append(request.url)
            if request.url.startswith(("http://", "https://"))
            else None
        ),
    )
    page.goto(output.resolve().as_uri(), wait_until="load", timeout=120_000)
    page.get_by_test_id("quantx-unified-dashboard").wait_for(state="visible")
    page.get_by_test_id("quantx-advanced-industry").wait_for(state="visible")
    page.wait_for_function(
        """expected => document.querySelectorAll(
          '[data-testid="quantx-unified-dashboard"] canvas'
        ).length >= expected""",
        arg=source_canvas_count,
        timeout=120_000,
    )

    title = page.title()
    exported_canvas_count = (
        page.get_by_test_id("quantx-unified-dashboard").locator("canvas").count()
    )
    assert trade_date in title
    assert "交互导出" in title
    assert (
        page.locator('meta[name="quantx-trade-date"]').get_attribute("content")
        == trade_date
    )
    assert page.locator("script").count() >= 1
    assert page.locator("img[data-exported-canvas]").count() == 0
    assert exported_canvas_count >= source_canvas_count
    assert not page.get_by_test_id("quantx-export-html").is_visible()
    local_resources = page.locator("[src], [href]").evaluate_all(
        """elements => elements.flatMap(element => ['src', 'href'].flatMap(name => {
          const raw = element.getAttribute(name);
          if (!raw) return [];
          try {
            const host = new URL(raw, document.baseURI).hostname;
            return host === 'localhost' || host === '::1' || /^127[.]/.test(host)
              ? [`${name}=${raw}`]
              : [];
          } catch {
            return [];
          }
        }))"""
    )
    assert not local_resources, local_resources
    assert not external_requests, external_requests

    state_canvas = page.get_by_test_id("quantx-advanced-state_transition").locator(
        "canvas"
    )
    state_canvas.scroll_into_view_if_needed()
    state_canvas.hover(position={"x": 120, "y": 40})
    page.wait_for_function(
        """() => [...document.querySelectorAll('div')].some(element => {
          const style = getComputedStyle(element);
          return style.position === 'absolute'
            && style.display !== 'none'
            && element.innerText.includes('概率：')
            && element.innerText.includes('样本：');
        })""",
        timeout=10_000,
    )

    window_structure = page.get_by_test_id("window-theme-structure")
    original_window_text = window_structure.inner_text()
    page.get_by_test_id("window-statistics-5").click()
    assert (
        page.get_by_test_id("window-statistics-5").get_attribute("aria-pressed")
        == "true"
    )
    assert window_structure.inner_text() != original_window_text

    page.get_by_test_id("quantx-correlation-dimension-industry_level2").click()
    industry_select = page.get_by_test_id("quantx-correlation-industry-select")
    industry_value = industry_select.locator("option").nth(1).get_attribute("value")
    assert industry_value
    industry_select.select_option(industry_value)
    assert (
        industry_value
        in page.get_by_test_id("quantx-correlation-ranking-context").inner_text()
    )

    page.get_by_test_id("quantx-promotion-window-5").click()
    assert (
        page.get_by_test_id("quantx-promotion-window-5").get_attribute("aria-pressed")
        == "true"
    )

    data_panel = page.get_by_test_id("quantx-collapsible-data")
    data_panel.click()
    assert (
        page.get_by_test_id("quantx-collapsible-data").get_attribute("aria-expanded")
        == "true"
    )
    data_panel.locator("xpath=..").locator("table").first.wait_for(
        state="visible", timeout=30_000
    )
    quality_panel = page.get_by_test_id("quantx-collapsible-quality")
    quality_panel.click()
    assert (
        page.get_by_test_id("quantx-collapsible-quality").get_attribute("aria-expanded")
        == "true"
    )
    quality_panel.locator("xpath=..").locator("table").first.wait_for(
        state="visible", timeout=30_000
    )

    new_high = page.get_by_test_id("quantx-new-high-clusters")
    new_high.get_by_test_id("new-high-cluster-row").first.click()
    new_high.get_by_test_id("new-high-member-details").wait_for(timeout=30_000)
    assert new_high.get_by_test_id("new-high-member-row").count() > 0
    assert not errors, errors
    _assert_no_horizontal_overflow(page)

    mobile = context.new_page()
    mobile.set_viewport_size({"width": 390, "height": 844})
    mobile.goto(output.resolve().as_uri(), wait_until="load", timeout=120_000)
    mobile.get_by_test_id("quantx-unified-dashboard").wait_for(state="visible")
    _assert_no_horizontal_overflow(mobile)

    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshot), full_page=False)

    context.close()
    return {
        "title": title,
        "interactive_canvas": exported_canvas_count,
        "bytes": output.stat().st_size,
        "desktop_overflow": False,
        "mobile_overflow": False,
        "offline_errors": errors,
        "external_requests": external_requests,
    }


def main() -> None:
    args = _args()
    output = (args.output or Path.cwd() / f"quantx-{args.date}.html").resolve()
    if output.exists() and not args.force:
        raise FileExistsError(
            f"Refusing to replace existing file: {output}. Pass --force to replace it."
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(
            "window.EventSource = class { close(){} addEventListener(){} }"
        )
        page.route("**/*", _block_telemetry)
        online_errors = _collect_page_errors(page)
        url = f"{args.base_url.rstrip('/')}/quantx/{args.date}"
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        source_canvas_count = _wait_for_report(page, args.minimum_canvas)

        export_button = page.get_by_test_id("quantx-export-html")
        export_button.wait_for(state="visible")
        if args.source_screenshot:
            args.source_screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.get_by_test_id("quantx-dashboard-header").screenshot(
                path=str(args.source_screenshot)
            )
        with page.expect_download(timeout=120_000) as download_info:
            export_button.click()
        download_info.value.save_as(str(output))
        assert not online_errors, online_errors

        offline = _verify_offline(
            browser,
            output=output,
            trade_date=args.date,
            source_canvas_count=source_canvas_count,
            screenshot=args.screenshot,
        )
        browser.close()

    print(
        json.dumps(
            {
                "url": url,
                "output": str(output),
                "source_canvas": source_canvas_count,
                **offline,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
