"""Standalone Edge regression for the QuantX 100-day-high cluster card."""
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

        response = page.request.get(
            f"{base_url}/api/quantx/review/{args.date}/data"
        )
        assert response.ok
        new_high = response.json()["sections"]["s2"]["new_high"]
        assert new_high["status"] == "ok"
        assert new_high["total_stocks"] > 0
        assert set(new_high["windows"]) == {"1", "5", "10", "20"}
        assert all(
            new_high["coverage_pct"][dimension] > 0
            for dimension in ("concept", "industry_level1", "industry_level2")
        )
        assert all(
            new_high["windows"]["5"]["dimensions"][dimension]
            for dimension in ("concept", "industry_level1", "industry_level2")
        )

        page.goto(
            f"{base_url}/quantx/{args.date}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        card = page.get_by_test_id("quantx-new-high-clusters")
        card.wait_for(timeout=30_000)
        card.scroll_into_view_if_needed()
        assert page.get_by_role(
            "heading", name="百日新高扩散聚类", exact=True
        ).count() == 1
        ranking = card.get_by_test_id("new-high-cluster-ranking")
        ranking.wait_for()
        assert 3 <= card.get_by_test_id("new-high-cluster-row").count() <= 10

        dimension_results = []
        for label in ("题材概念", "申万一级", "申万二级"):
            card.get_by_role("tab", name=label, exact=True).click()
            dimension_results.append(
                card.get_by_test_id("new-high-cluster-row").first.inner_text()
            )
        assert len(set(dimension_results)) == 3

        window_results = []
        card.get_by_role("tab", name="题材概念", exact=True).click()
        for label in ("当日", "5日", "10日", "20日"):
            card.get_by_role("tab", name=label, exact=True).click()
            window_results.append(card.inner_text())
        assert len(set(window_results)) == 4

        card.get_by_role("tab", name="5日", exact=True).click()
        toggle_all = card.get_by_test_id("new-high-toggle-all")
        if toggle_all.count():
            collapsed_count = card.get_by_test_id("new-high-cluster-row").count()
            toggle_all.click()
            assert card.get_by_test_id("new-high-cluster-row").count() > collapsed_count
            toggle_all.click()
        first_cluster = card.get_by_test_id("new-high-cluster-row").first
        first_cluster.click()
        details = card.get_by_test_id("new-high-member-details")
        details.wait_for(timeout=10_000)
        details.get_by_test_id("new-high-member-row").first.wait_for(timeout=10_000)
        assert details.get_by_test_id("new-high-member-row").count() > 0
        assert "今日新高" in details.inner_text() or "窗口出现" in details.inner_text()
        assert first_cluster.get_attribute("aria-expanded") == "true"

        overflow = card.evaluate(
            "element => ({clientWidth: element.clientWidth, scrollWidth: element.scrollWidth})"
        )
        assert overflow["scrollWidth"] <= overflow["clientWidth"] + 1, overflow
        card.screenshot(path=str(RESULTS / "quantx-new-high-clusters.png"))
        assert not errors, errors
        assert not failed_responses, failed_responses
        browser.close()


if __name__ == "__main__":
    main()
