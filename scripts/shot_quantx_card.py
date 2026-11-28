"""Screenshot a single QuantX advanced chart card for visual review."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3011")
    parser.add_argument("--date", default="20261127")
    parser.add_argument("--card", default="turnover_return_density")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1680)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--channel", default="chrome", help="playwright browser channel, empty for bundled chromium")
    parser.add_argument("--theme", default="dark", choices=("dark", "light"))
    args = parser.parse_args()

    with sync_playwright() as play:
        browser = play.chromium.launch(channel=args.channel or None)
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.add_init_script(f"try{{localStorage.setItem('tf-theme','{args.theme}')}}catch(e){{}}")
        page.goto(f"{args.base_url.rstrip('/')}/quantx/{args.date}", wait_until="domcontentloaded", timeout=90_000)
        page.get_by_test_id("quantx-advanced-workspace").wait_for(state="visible", timeout=120_000)
        card = page.get_by_test_id(f"quantx-advanced-{args.card}")
        card.wait_for(state="visible", timeout=120_000)
        # 主题偏好由后端回填, init script 里的 localStorage 会被 hydrateUiPrefs 覆盖,
        # 所以按当前 html.dark 状态点一次切换按钮来对齐目标主题。
        is_dark = page.locator("html.dark").count() > 0
        if is_dark != (args.theme == "dark"):
            page.get_by_title("切换到亮色模式" if is_dark else "切换到暗色模式").click()
            page.wait_for_timeout(1200)
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(2500)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        card.screenshot(path=str(args.out))
        print(f"saved {args.out}")
        print(f"console errors: {console_errors[:5] if console_errors else 'none'}")
        browser.close()


if __name__ == "__main__":
    main()
