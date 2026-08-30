"""Export and verify a self-contained QuantX HTML snapshot with Edge."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Page, sync_playwright


LOCAL_REFERENCE = re.compile(
    r"(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)(?::\d+)?",
    re.IGNORECASE,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one QuantX date as a self-contained static HTML file."
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
    assert not LOCAL_REFERENCE.search(html), "static HTML retains a local URL"
    assert not re.search(r"<script(?:\s|>)", html, re.IGNORECASE)
    assert "Content-Security-Policy" in html

    context = browser.new_context(
        offline=True,
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    errors = _collect_page_errors(page)
    page.goto(output.resolve().as_uri(), wait_until="load", timeout=120_000)
    page.get_by_test_id("quantx-unified-dashboard").wait_for(state="visible")

    title = page.title()
    exported_canvas_count = page.locator("img[data-exported-canvas]").count()
    assert trade_date in title
    assert "静态导出" in title
    assert (
        page.locator('meta[name="quantx-trade-date"]').get_attribute("content")
        == trade_date
    )
    assert page.locator("script").count() == 0
    assert page.locator("canvas").count() == 0
    assert page.get_by_test_id("quantx-export-html").count() == 0
    assert page.locator("[data-static-export-remove]").count() == 0
    assert exported_canvas_count == source_canvas_count
    assert not errors, errors
    _assert_no_horizontal_overflow(page)

    mobile = context.new_page()
    mobile.set_viewport_size({"width": 390, "height": 844})
    mobile.goto(output.resolve().as_uri(), wait_until="load", timeout=120_000)
    mobile.get_by_test_id("quantx-unified-dashboard").wait_for(state="visible")
    _assert_no_horizontal_overflow(mobile)

    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=False)

    context.close()
    return {
        "title": title,
        "canvas_images": exported_canvas_count,
        "bytes": output.stat().st_size,
        "desktop_overflow": False,
        "mobile_overflow": False,
        "offline_errors": errors,
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
