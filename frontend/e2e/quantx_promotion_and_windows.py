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
        assert len(cards) == 15
        assert "risk_transmission" not in cards
        for key in ("industry_correlation", "rps_rotation_clock", "mainline_waterfall"):
            assert "不是历史时点成分" in cards[key]["note"]
        correlation = cards["industry_correlation"]["data"]["views"]["industry_level2"]
        assert len(correlation["industries"]) > 50
        assert len(correlation["matrix"]) == len(correlation["industries"])
        assert all(
            len(row) == len(correlation["industries"])
            for row in correlation["matrix"]
        )
        assert len(correlation["pair_rankings"]["highest"]) == 8
        assert len(correlation["pair_rankings"]["lowest"]) == 8
        mainlines = cards["mainline_waterfall"]["data"]["mainlines"]
        assert len(mainlines) > 1
        assert mainlines[0]["focus"] != mainlines[1]["focus"]
        assert all(len(row["components"]) == 4 for row in mainlines)
        promotion = cards["promotion_funnel"]["data"]
        stages = promotion["stages"]
        assert promotion["default_view"] == "current"
        assert set(promotion["views"]) == {"current", "5", "20"}
        assert promotion["baseline"]["stages"] == stages
        assert promotion["baseline"]["sample_days"] >= promotion["views"]["20"]["sample_days"]
        assert promotion["views"]["current"]["sample_days"] == 1
        assert stages[0]["name"] == "0→1 首板封板"
        assert stages[0]["basis"] == "same_day_seal"
        assert stages[0]["pool"] == stages[0]["promoted"] + stages[0]["failed"]
        assert any(
            row["name"] == f"{promotion['max_observed_board'] - 1}→{promotion['max_observed_board']}"
            for row in stages
        )
        assert cards["theme_river"]["data"]["source"]

        multiday_response = page.request.get(
            f"{base_url}/api/quantx-data/multiday/{args.date}"
        )
        assert multiday_response.ok
        multiday = multiday_response.json()
        assert multiday["schema_version"] == "tickflow-quantx-multiday-v3"
        assert "institution_continuity" not in multiday
        assert "institution_days" not in multiday["data_coverage"]
        assert "core_stocks" not in multiday["sector_flow_continuity"]
        assert all(
            "institution" not in multiday["window_signals"][str(window)]
            for window in (5, 10, 20)
        )
        mainline_names = {
            tuple(
                row["name"]
                for row in multiday["window_signals"][str(window)]["themes"]["mainline"]
            )
            for window in (5, 10, 20)
        }
        assert len(mainline_names) > 1

        page.goto(
            f"{base_url}/quantx/{args.date}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        matrix = page.get_by_test_id("window-signal-matrix")
        matrix.wait_for(timeout=30_000)
        assert page.locator('[data-testid^="window-statistics-"]').count() == 3
        assert page.locator('[data-testid="window-statistics"]').count() == 0
        assert page.get_by_role("heading", name="核心个股", exact=True).count() == 0
        assert page.get_by_role("heading", name="连续规则候选", exact=True).count() == 1
        assert page.get_by_test_id("quantx-advanced-risk_transmission").count() == 0
        assert page.get_by_role("heading", name="同花顺热点题材覆盖", exact=True).count() == 1
        assert "15 张真实数据卡片" in page.get_by_test_id(
            "quantx-advanced-workspace"
        ).locator("header").first.inner_text()
        assert "两套分值与状态不可直接互换" in page.get_by_test_id(
            "quantx-state-transition-guide"
        ).inner_text()
        for key in ("industry_correlation", "rps_rotation_clock", "mainline_waterfall"):
            assert "不是历史时点成分" in page.get_by_test_id(
                f"quantx-advanced-caveat-{key}"
            ).inner_text()
        page.get_by_test_id("quantx-correlation-dimension-industry_level2").click()
        correlation_rankings = page.get_by_test_id(
            "quantx-correlation-pair-rankings"
        )
        correlation_rankings.wait_for()
        assert page.get_by_test_id("quantx-correlation-pair-highest").count() == 8
        assert page.get_by_test_id("quantx-correlation-pair-lowest").count() == 8
        mainline_selector = page.get_by_test_id("quantx-mainline-selector")
        mainline_selector.wait_for()
        assert mainline_selector.get_by_role("button").count() == len(mainlines)
        first_mainline = page.get_by_test_id("quantx-mainline-option-0")
        second_mainline = page.get_by_test_id("quantx-mainline-option-1")
        assert first_mainline.get_attribute("aria-pressed") == "true"
        second_mainline.click()
        assert second_mainline.get_attribute("aria-pressed") == "true"
        assert first_mainline.get_attribute("aria-pressed") == "false"

        rendered_theme_structures = []
        for window in (5, 10, 20):
            page.get_by_test_id(f"window-statistics-{window}").click()
            rendered_theme_structures.append(
                page.get_by_test_id("window-theme-structure").inner_text()
            )
        assert len(set(rendered_theme_structures)) > 1

        promotion_card = page.get_by_test_id("quantx-advanced-promotion_funnel")
        promotion_card.locator("canvas").wait_for(timeout=30_000)
        page.get_by_test_id("quantx-promotion-guide").wait_for()
        promotion_controls = page.get_by_test_id("quantx-promotion-window-controls")
        promotion_controls.wait_for()
        current_window = page.get_by_test_id("quantx-promotion-window-current")
        five_day_window = page.get_by_test_id("quantx-promotion-window-5")
        twenty_day_window = page.get_by_test_id("quantx-promotion-window-20")
        assert current_window.get_attribute("aria-pressed") == "true"
        five_day_window.click()
        assert five_day_window.get_attribute("aria-pressed") == "true"
        twenty_day_window.click()
        assert twenty_day_window.get_attribute("aria-pressed") == "true"
        assert "全样本基线" in page.get_by_test_id(
            "quantx-promotion-baseline-label"
        ).inner_text()
        assert "ths_hot" in page.get_by_test_id(
            "quantx-advanced-theme_river"
        ).locator("header").inner_text()

        matrix.screenshot(path=str(RESULTS / "quantx-window-merged.png"))
        promotion_card.screenshot(path=str(RESULTS / "quantx-promotion-ladder.png"))
        page.get_by_test_id("quantx-advanced-industry_correlation").screenshot(
            path=str(RESULTS / "quantx-industry-correlation.png")
        )
        assert not errors, errors
        assert not failed_responses, failed_responses
        browser.close()


if __name__ == "__main__":
    main()
