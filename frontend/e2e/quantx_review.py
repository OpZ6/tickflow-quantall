"""Standalone Playwright regression test for the QuantX rich daily review."""
from __future__ import annotations

import argparse

from playwright.sync_api import sync_playwright


EXPECTED_SECTIONS = [
    "一、顶部决断",
    "二、大盘环境",
    "三、主线题材",
    "四、连板情绪",
    "五、资金生态与趋势容量",
    "六、关注名单",
    "七、次日预案与复盘校验",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3011")
    parser.add_argument("--date", default="20260825")
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/quantx/{args.date}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.locator("h2").filter(has_text=EXPECTED_SECTIONS[-1]).wait_for(timeout=10_000)

        response = page.request.get(
            f"{args.base_url.rstrip('/')}/api/quantx/review/{args.date}/data"
        )
        assert response.ok
        payload = response.json()
        foundation = payload["data_foundation"]
        assert foundation["read_mode"] == "canonical_facts_with_presentation_cache"
        canonical = foundation["canonical_fields"]
        presentation_cache = foundation["presentation_cache_fields"]
        for field in (
            "sections.s1.congestion",
            "sections.s2.new_high",
            "sections.s2.participation",
            "sections.s2.ebb_risk",
            "sections.s3.advance_history",
            "sections.s3.ebb_signals",
            "sections.s3.crash_signals",
            "sections.s6.position",
            "sections.s6.scenes",
        ):
            assert field in canonical
            assert field not in presentation_cache
        assert len(payload["sections"]["s3"]["ebb_signals"]) == 4
        assert len(payload["sections"]["s3"]["crash_signals"]) == 3

        headings = page.locator("h2").all_inner_texts()
        missing = [title for title in EXPECTED_SECTIONS if title not in headings]
        assert not missing, f"missing QuantX review sections: {missing}"
        assert page.locator("canvas").count() == 11
        new_high = page.get_by_role("heading", name="百日新高")
        new_high.wait_for()
        assert new_high.locator("..").locator("span").count() == 29

        browser.close()


if __name__ == "__main__":
    main()
