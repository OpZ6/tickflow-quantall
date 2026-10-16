"""Standalone Edge regression for QuantX promotion and window semantics."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


RESULTS = Path(__file__).resolve().parent / "results"


def assert_balanced_pair(page, left_test_id: str, right_test_id: str) -> None:
    """Ensure a desktop card pair fills one grid row without an orphan gap."""
    left = page.get_by_test_id(left_test_id)
    right = page.get_by_test_id(right_test_id)
    left_box = left.bounding_box()
    right_box = right.bounding_box()
    grid_box = left.locator("xpath=..").bounding_box()
    assert left_box and right_box and grid_box
    assert abs(left_box["y"] - right_box["y"]) <= 3
    assert abs(left_box["height"] - right_box["height"]) <= 3
    assert abs(left_box["x"] - grid_box["x"]) <= 3
    assert abs(
        right_box["x"] + right_box["width"] - grid_box["x"] - grid_box["width"]
    ) <= 3
    gap = right_box["x"] - left_box["x"] - left_box["width"]
    assert 0 <= gap <= 12


def assert_full_width_card(page, test_id: str) -> None:
    """Ensure a standalone desktop chart consumes its entire analysis row."""
    card = page.get_by_test_id(test_id)
    card_box = card.bounding_box()
    grid_box = card.locator("xpath=..").bounding_box()
    assert card_box and grid_box
    assert abs(card_box["x"] - grid_box["x"]) <= 3
    assert abs(card_box["width"] - grid_box["width"]) <= 3


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
        opportunity = page.get_by_test_id("opportunity-radar")
        assert opportunity.count() == 1
        assert page.get_by_test_id("sector-flow-continuity").count() == 0
        assert page.get_by_role("heading", name="连续规则候选", exact=True).count() == 0
        opportunity.get_by_role("button", name="20日", exact=True).click()
        opportunity.get_by_role("tab", name="行业", exact=True).click()
        opportunity.get_by_role("columnheader", name="累计净流入(亿)").wait_for()
        opportunity.get_by_role("tab", name="个股", exact=True).click()
        opportunity.get_by_role("columnheader", name="层级", exact=True).wait_for()
        assert page.get_by_role("heading", name="连板详细记录", exact=True).count() == 0
        assert page.get_by_test_id("quantx-advanced-risk_transmission").count() == 0
        assert page.get_by_role("heading", name="同花顺热点题材覆盖", exact=True).count() == 1
        assert page.get_by_role("heading", name="高级图谱数据覆盖", exact=True).count() == 0
        theme_scores = [
            float(page.get_by_test_id("quantx-theme-mainline-row").nth(index).get_attribute("data-score") or 0)
            for index in range(page.get_by_test_id("quantx-theme-mainline-row").count())
        ]
        assert len(theme_scores) == 8
        assert theme_scores == sorted(theme_scores, reverse=True)
        expected_domains = [
            "quantx-domain-conclusion",
            "quantx-domain-market",
            "quantx-domain-industry",
            "quantx-domain-themes",
            "quantx-domain-limit-board",
            "quantx-domain-liquidity",
            "quantx-domain-decision",
            "quantx-domain-data",
        ]
        rendered_domains = page.locator('[data-testid^="quantx-domain-"]')
        assert rendered_domains.count() == len(expected_domains)
        assert [
            rendered_domains.nth(index).get_attribute("data-testid")
            for index in range(rendered_domains.count())
        ] == expected_domains
        page.get_by_test_id("quantx-advanced-workspace").wait_for(timeout=30_000)
        for key in cards:
            assert page.get_by_test_id(f"quantx-advanced-{key}").count() == 1
        for left_key, right_key in (
            ("sentiment_phase", "state_transition"),
            ("anomaly_calendar", "advance_decline"),
            ("theme_river", "mainline_waterfall"),
            ("promotion_funnel", "theme_ladder_sunburst"),
            ("liquidity_participation", "return_distribution"),
            ("turnover_return_density", "turnover_lorenz"),
        ):
            assert_balanced_pair(
                page,
                f"quantx-advanced-{left_key}",
                f"quantx-advanced-{right_key}",
            )
        for key in (
            "sector_diffusion",
            "industry_correlation",
            "rps_rotation_clock",
        ):
            assert_full_width_card(page, f"quantx-advanced-{key}")
        assert page.get_by_test_id("quantx-domain-industry").get_by_test_id(
            "quantx-capital-workspace"
        ).count() == 1
        assert page.get_by_test_id("quantx-domain-limit-board").get_by_test_id(
            "quantx-advanced-promotion_funnel"
        ).count() == 1
        assert page.get_by_test_id("quantx-domain-liquidity").get_by_test_id(
            "quantx-congestion-panel"
        ).count() == 1
        market_domain = page.get_by_test_id("quantx-domain-market")
        market_overview_box = market_domain.get_by_test_id("quantx-deep-market").bounding_box()
        emotion_calendar_box = market_domain.get_by_test_id("quantx-emotion-calendar").bounding_box()
        advanced_market_box = market_domain.get_by_test_id("quantx-advanced-workspace").bounding_box()
        assert market_overview_box and emotion_calendar_box and advanced_market_box
        assert market_overview_box["y"] < emotion_calendar_box["y"] < advanced_market_box["y"]
        assert "两套分值与状态不可直接互换" in page.get_by_test_id(
            "quantx-state-transition-guide"
        ).inner_text()
        emotion_calendar = page.get_by_test_id("quantx-emotion-calendar")
        calendar_grid = emotion_calendar.get_by_test_id("quantx-emotion-calendar-grid")
        assert calendar_grid.locator('button[aria-label^="选择交易日"]').count() == 0
        selected_emotion_day = calendar_grid.get_by_test_id(
            f"quantx-emotion-day-{args.date}"
        )
        selected_calendar_row = next(
            row for row in multiday["calendar"] if row["trade_date"] == args.date
        )

        def rendered_score(key: str) -> str:
            value = selected_calendar_row[key]
            return str(int(value)) if float(value).is_integer() else str(value)

        dashboard_url = page.url
        selected_emotion_day.click()
        assert page.url == dashboard_url
        assert selected_emotion_day.get_attribute("data-score-key") == "market_heat_score"
        assert rendered_score("market_heat_score") in selected_emotion_day.inner_text()
        emotion_calendar.get_by_role("tab", name="波段情绪", exact=True).click()
        assert selected_emotion_day.get_attribute("data-score-key") == "trend_sentiment_score"
        assert rendered_score("trend_sentiment_score") in selected_emotion_day.inner_text()
        emotion_calendar.get_by_role("tab", name="短线情绪", exact=True).click()
        assert selected_emotion_day.get_attribute("data-score-key") == "short_term_sentiment_score"
        assert rendered_score("short_term_sentiment_score") in selected_emotion_day.inner_text()
        breadth_scroll = page.get_by_test_id("quantx-sector-breadth-scroll")
        breadth_metrics = breadth_scroll.evaluate(
            "element => ({clientHeight: element.clientHeight, scrollHeight: element.scrollHeight})"
        )
        assert breadth_metrics["scrollHeight"] <= breadth_metrics["clientHeight"] + 1, (
            breadth_metrics
        )
        for key in ("industry_correlation", "rps_rotation_clock", "mainline_waterfall"):
            assert "不是历史时点成分" in page.get_by_test_id(
                f"quantx-advanced-caveat-{key}"
            ).inner_text()
        page.get_by_test_id("quantx-correlation-dimension-industry_level2").click()
        correlation_rankings = page.get_by_test_id(
            "quantx-correlation-pair-rankings"
        )
        correlation_rankings.wait_for()
        highest_pairs = page.get_by_test_id("quantx-correlation-pair-highest")
        lowest_pairs = page.get_by_test_id("quantx-correlation-pair-lowest")
        assert highest_pairs.count() == 10
        assert lowest_pairs.count() == 10
        industry_select = page.get_by_test_id("quantx-correlation-industry-select")
        focused_industry = correlation["industries"][0]
        industry_select.select_option(focused_industry)
        ranking_context = page.get_by_test_id("quantx-correlation-ranking-context")
        assert focused_industry in ranking_context.inner_text()
        assert all(
            focused_industry in highest_pairs.nth(index).inner_text()
            for index in range(highest_pairs.count())
        )
        assert all(
            focused_industry in lowest_pairs.nth(index).inner_text()
            for index in range(lowest_pairs.count())
        )
        page.get_by_test_id("quantx-correlation-clear-industry").click()
        assert "全部行业组合总排名" in ranking_context.inner_text()
        clickable_industry = highest_pairs.first.locator("button[data-industry]").last
        clicked_industry = clickable_industry.get_attribute("data-industry")
        clickable_industry.click()
        assert clicked_industry in ranking_context.inner_text()
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
        for width, height in ((1440, 1000), (768, 900), (375, 812)):
            page.set_viewport_size({"width": width, "height": height})
            main_scroller = page.locator("main").first
            main_scroller.evaluate("element => { element.scrollTop = 0 }")
            dimensions = page.evaluate(
                "() => ({ clientWidth: document.documentElement.clientWidth, "
                "scrollWidth: document.documentElement.scrollWidth })"
            )
            assert dimensions["scrollWidth"] <= dimensions["clientWidth"] + 1, (
                width,
                dimensions,
            )
            main_dimensions = main_scroller.evaluate(
                "element => ({ clientWidth: element.clientWidth, "
                "scrollWidth: element.scrollWidth })"
            )
            assert main_dimensions["scrollWidth"] <= main_dimensions["clientWidth"] + 1, (
                width,
                main_dimensions,
            )
            page.screenshot(
                path=str(RESULTS / f"quantx-responsive-{width}.png")
            )
        assert not errors, errors
        assert not failed_responses, failed_responses
        browser.close()


if __name__ == "__main__":
    main()
