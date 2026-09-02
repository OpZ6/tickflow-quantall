"""Standalone Edge regression for the unified QuantX data foundation."""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3011")
    parser.add_argument("--date", default="20260825")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    errors: list[str] = []
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

        tables_response = page.request.get(
            f"{base_url}/api/quantx-data/{args.date}/tables"
        )
        assert tables_response.ok
        tables = tables_response.json()
        foundation = tables["data_foundation"]
        assert foundation["read_mode"] == "canonical_with_legacy_enrichment"
        assert len(foundation["canonical_datasets"]) == 5
        assert not foundation["legacy_fallback_datasets"]

        for endpoint in ("datasets", "sources", "routes", "health"):
            response = page.request.get(f"{base_url}/api/data-sources/{endpoint}")
            assert response.ok, f"data source endpoint failed: {endpoint}"
        datasets_response = page.request.get(f"{base_url}/api/data-sources/datasets").json()
        assert len(datasets_response["datasets"]) == 14
        assert "kline_index_daily" in {
            item["dataset_id"] for item in datasets_response["datasets"]
        }
        assert "sector_breadth_daily" in {
            item["dataset_id"] for item in datasets_response["datasets"]
        }
        calendar_response = page.request.get(
            f"{base_url}/api/data-sources/calendar?start=2026-08-25&end=2026-08-26"
        )
        assert calendar_response.ok
        assert calendar_response.json()["calendar"]

        page.goto(
            f"{base_url}/quantx/{args.date}",
            wait_until="networkidle",
            timeout=30_000,
        )
        page.wait_for_function("document.querySelectorAll('h2').length >= 7")
        page.get_by_test_id("sector-breadth-heatmap").locator("canvas").wait_for()
        assert page.locator("canvas").count() == 12
        page.screenshot(
            path=str(RESULTS / "quantx-data-foundation-daily.png"), full_page=True
        )

        page.goto(f"{base_url}/quantx", wait_until="networkidle", timeout=30_000)
        page.get_by_test_id("quantx-data-coverage").wait_for()
        opportunity = page.get_by_test_id("opportunity-radar")
        opportunity.wait_for()
        assert page.get_by_test_id("sector-flow-continuity").count() == 0
        page.get_by_text("行业资金覆盖", exact=True).wait_for()
        page.get_by_text("题材 / 行业 / 个股多日机会与连续性", exact=True).wait_for()
        opportunity.get_by_role("button", name="20日", exact=True).click()
        opportunity.get_by_role("tab", name="行业", exact=True).click()
        opportunity.get_by_role("columnheader", name="累计净流入(亿)").wait_for()
        page.screenshot(
            path=str(RESULTS / "quantx-data-foundation-multiday.png"), full_page=True
        )

        flow = page.request.get(f"{base_url}/api/market-lab/sector-flow").json()
        radar = page.request.get(f"{base_url}/api/market-lab/sector-radar").json()
        assert flow["quality"] == "observed"
        assert radar["quality"] == "observed"
        assert flow["basis"] == radar["basis"] == "sector_flow_daily.net_inflow_yi"

        page.goto(f"{base_url}/market-lab", wait_until="networkidle", timeout=30_000)
        page.get_by_role("button", name="板块资金").click()
        page.get_by_text("真实资金流", exact=True).wait_for()
        page.get_by_test_id("sector-flow-trend-chart").locator("canvas").wait_for()
        page.screenshot(
            path=str(RESULTS / "quantx-data-foundation-market-lab.png"), full_page=True
        )

        page.goto(f"{base_url}/data", wait_until="networkidle", timeout=30_000)
        page.get_by_test_id("data-source-foundation").wait_for()
        page.get_by_text("统一市场数据底座", exact=True).wait_for()
        page.get_by_text("行业资金流", exact=True).wait_for()
        page.get_by_text("交易日历", exact=True).wait_for()
        page.screenshot(
            path=str(RESULTS / "quantx-data-foundation-sources.png"), full_page=True
        )

        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    main()
