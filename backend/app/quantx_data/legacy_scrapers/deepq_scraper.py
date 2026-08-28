"""DeepQ Playwright scraper: sector rotation stages via API interception."""
import json
import os
from datetime import datetime

from playwright.sync_api import sync_playwright

from app.quantx_data.browser_runtime import launch_chromium

OUTPUT_DIR = None
TRADE_DATE = None
BASE_URL = "https://sq.deepq.tech"


def scrape() -> dict:
    result = {"updateTime": "", "sector_rotation": [], "latest_day": {}}

    with sync_playwright() as p:
        browser = launch_chromium(p, headless=True)
        api_data = {}

        def capture_sector_rotation(response):
            if "sector-rotation" in response.url:
                try:
                    api_data["sector_rotation"] = response.json()
                    print(f"  [deepq] Captured sector-rotation API")
                except Exception:
                    pass

        page = browser.new_page()
        page.on("response", capture_sector_rotation)

        try:
            print("  [deepq] Loading /ticai/ ...")
            page.goto(f"{BASE_URL}/ticai/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(10000)

            if api_data.get("sector_rotation"):
                rot = api_data["sector_rotation"]
                result["updateTime"] = rot.get("updateTime", "")
                data = rot.get("data", [])
                result["sector_rotation"] = data

                if data:
                    latest = data[-1]
                    result["latest_day"] = {
                        "date": latest.get("date", ""),
                        "sectors": latest.get("sectors", []),
                    }
                    print(f"  [deepq] {len(data)} days, latest: {latest.get('date')}, "
                          f"{len(latest.get('sectors', []))} sectors")
            else:
                print("  [deepq] WARNING: sector-rotation API not captured")

            print("  [deepq] Scraping complete")
        except Exception as e:
            print(f"  [deepq] Error: {e}")
            result["error"] = str(e)
        finally:
            browser.close()

    return result


def run(trade_date: str = TRADE_DATE, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[deepq] Scraping {trade_date}...")

    result = {
        "trade_date": trade_date, "scraped_at": datetime.now().isoformat(),
        "source": "sq.deepq.tech",
        **scrape(),
    }

    path = os.path.join(output_dir, "deepq.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[deepq] Saved -> {path}")
    return path


if __name__ == "__main__":
    run()
