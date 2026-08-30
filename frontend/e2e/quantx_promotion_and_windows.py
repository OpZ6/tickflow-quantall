"""Standalone Edge regression for QuantX promotion and window semantics."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3011")
    parser.add_argument("--date", default="20260828")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    errors: list[str] = []
    failed_responses: list[str] = []
    RESULTS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(
            "window.EventSource = class { close(){} addEventListener(){} }"
        )
        page.on(
            "console",
            lambda message: errors.append(f"console:{message.text}")
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: errors.append(f"pageerror:{error}"))
        page.on(
            "response",
            lambda response: failed_responses.append(
                f"{response.status}:{response.url}"
            )
            if response.status >= 400
            else None,
        )

        advanced_response = page.request.get(
            f"{base_url}/api/quantx-data/advanced/{args.date}"
        )
        assert advanced_response.ok
        cards = advanced_response.json()["cards"]
        promotion = cards["promotion_funnel"]["data"]
        stages = promotion["stages"]
        assert stages[0]["name"] == "0→1 首板封板"
        assert stages[0]["basis"] == "same_day_seal"
        assert stages[0]["pool"] == stages[0]["promoted"] + stages[0]["failed"]
        assert any(
            row["name"] == f"{promotion['max_observed_board'] - 1}→{promotion['max_observed_board']}"
            for row in stages
        )
        assert cards["theme_river"]["data"]["source"]

        page.goto(
            f"{base_url}/quantx/{args.date}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        matrix = page.get_by_test_id("window-signal-matrix")
        matrix.wait_for(timeout=30_000)
        assert page.locator('[data-testid^="window-statistics-"]').count() == 3
        assert page.locator('[data-testid="window-statistics"]').count() == 0

        promotion_card = page.get_by_test_id("quantx-advanced-promotion_funnel")
        promotion_card.locator("canvas").wait_for(timeout=30_000)
        page.get_by_test_id("quantx-promotion-guide").wait_for()
        assert "ths_hot" in page.get_by_test_id(
            "quantx-advanced-theme_river"
        ).locator("header").inner_text()

        matrix.screenshot(path=str(RESULTS / "quantx-window-merged.png"))
        promotion_card.screenshot(path=str(RESULTS / "quantx-promotion-ladder.png"))
        assert not errors, errors
        assert not failed_responses, failed_responses
        browser.close()


if __name__ == "__main__":
    main()
