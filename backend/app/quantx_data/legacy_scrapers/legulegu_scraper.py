"""LeGuLeGu Playwright scraper: 创新高/新低, 大盘拥挤度(成交量前5%占比), 市场宽度(站上均线比例).

Uses API interception to capture data from legulegu.com's internal APIs.
"""
import json
import os
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

OUTPUT_DIR = None
TRADE_DATE = None
BASE_URL = "https://legulegu.com"


def _fmt_date(d) -> str:
    """Format date from either string 'YYYY-MM-DD' or list ['YYYY','M','D']."""
    if isinstance(d, str):
        return d
    return f"{d[0]}-{int(d[1]):02d}-{int(d[2]):02d}"


def _extract_tables(page, prefix: str, max_rows: int = 30, max_tables: int = 5) -> dict:
    """Extract all visible tables from current page."""
    result = {}
    for i, table in enumerate(page.locator("table").all()):
        if i >= max_tables:
            break
        try:
            rows = table.locator("tr").all()
            if len(rows) < 2:
                continue
            hdrs = [h.text_content().strip() for h in rows[0].locator("th,td").all()]
            data = []
            for row in rows[1:max_rows + 1]:
                cells = [c.text_content().strip() for c in row.locator("td").all()]
                if cells and any(c for c in cells):
                    data.append(cells)
            if data and len(hdrs) > 1:  # Skip description-only tables
                result[f"{prefix}_table_{i}"] = {"headers": hdrs, "rows": data}
        except Exception:
            pass
    return result


def scrape() -> dict:
    result = {
        "scraped_at": datetime.now().isoformat(),
        "source": "legulegu.com",
        "source_urls": [
            f"{BASE_URL}/stockdata/high-low-statistics",
            f"{BASE_URL}/stockdata/sw-market-width",
            f"{BASE_URL}/stockdata/sw-market-width/sec-level",
            f"{BASE_URL}/stockdata/ashares-congestion",
        ],
        "width_source_urls": [
            f"{BASE_URL}/stockdata/sw-market-width",
            f"{BASE_URL}/stockdata/sw-market-width/sec-level",
        ],
        "market_width_ad_wait_seconds": 22,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ========== HIGH-LOW STATISTICS (API interception) ==========
        print("  [legulegu] Scraping high-low-statistics...")
        api_highlow = {}

        def capture_highlow(response):
            if "get-high-low-statistics" in response.url:
                try:
                    key = response.url.split("/")[-1].split("?")[0]
                    api_highlow[key] = response.json()
                    print(f"    Captured API: {key}")
                except:
                    pass

        page1 = browser.new_page()
        page1.on("response", capture_highlow)
        try:
            page1.goto(f"{BASE_URL}/stockdata/high-low-statistics", wait_until="domcontentloaded", timeout=60000)
            page1.wait_for_timeout(8000)
        except Exception as e:
            print(f"    Error: {e}")
        page1.close()

        if api_highlow:
            result["high_low_api"] = api_highlow
            latest_by_index = {}
            for idx_name, idx_data in api_highlow.items():
                entries = idx_data.get("data", [])
                if entries:
                    last = entries[-1]
                    latest_by_index[idx_name] = {
                        "date": _fmt_date(last['date']),
                        "close": last.get("close", 0),
                    }
            result["high_low_latest"] = latest_by_index
            print(f"    Latest high-low: {latest_by_index}")

        # ========== MARKET WIDTH (API interception + DOM fallback) ==========
        print("  [legulegu] Scraping sw-market-width (with 22s ad wait)...")
        api_width = {}
        width_scope = {"name": "primary"}

        def capture_width(response):
            url = response.url
            # Catch all JSON API responses for market width
            if any(kw in url for kw in ["market-width", "ma-market", "sw-market", "marketWidth"]):
                try:
                    data = response.json()
                    raw_key = (url.split("/")[-1].split("?")[0] or "market_width").replace("-", "_")
                    key = raw_key
                    if raw_key == "ma_market_width":
                        key = f"ma_market_width_{width_scope['name']}"
                    api_width[key] = data
                    print(f"    Captured API: {key} <- {url[-60:]}")
                except:
                    pass

        page2 = browser.new_page()
        page2.on("response", capture_width)
        try:
            page2.goto(f"{BASE_URL}/stockdata/sw-market-width", wait_until="domcontentloaded", timeout=60000)
            page2.wait_for_timeout(22000)  # 20s ad + buffer
        except Exception as e:
            print(f"    Error: {e}")

        # DOM fallback: try extracting from page if no API caught
        if not api_width:
            print("    No API captured, trying DOM extraction...")
            try:
                dom_data = page2.evaluate("""() => {
                    // Try to find market width data in page variables or tables
                    const tables = document.querySelectorAll('table');
                    const result = {headers: [], rows: []};
                    for (const t of tables) {
                        const headers = Array.from(t.querySelectorAll('th')).map(h => h.textContent.trim());
                        if (headers.some(h => h.includes('MA') || h.includes('均线') || h.includes('站上'))) {
                            result.headers = headers;
                            const trs = t.querySelectorAll('tbody tr');
                            for (const tr of trs) {
                                result.rows.push(Array.from(tr.querySelectorAll('td')).map(d => d.textContent.trim()));
                            }
                            break;
                        }
                    }
                    return result;
                }""")
                if dom_data and dom_data.get("rows"):
                    api_width["dom_extracted"] = dom_data
                    print(f"    DOM extracted: {len(dom_data['rows'])} rows")
            except Exception as e2:
                print(f"    DOM extraction failed: {e2}")

        # Also try sec-level sub-page
        try:
            print("    Trying sec-level sub-page...")
            width_scope["name"] = "sec_level"
            page2.goto(f"{BASE_URL}/stockdata/sw-market-width/sec-level", wait_until="domcontentloaded", timeout=30000)
            page2.wait_for_timeout(22000)  # same 20s ad gate as primary page
        except Exception:
            pass

        page2.close()

        if api_width:
            if "ma_market_width" not in api_width:
                api_width["ma_market_width"] = (
                    api_width.get("ma_market_width_primary")
                    or api_width.get("ma_market_width_sec_level")
                    or next(iter(api_width.values()))
                )
            result["width_api"] = api_width
            # Try to extract from any captured API
            for key, width_data in api_width.items():
                if isinstance(width_data, dict) and (width_data.get("dates") or width_data.get("data")):
                    if width_data.get("dates") and width_data.get("data"):
                        latest_idx = len(width_data["dates"]) - 1
                        result["width_latest"] = {"date": width_data["dates"][latest_idx]}
                        for k, vals in width_data.get("data", {}).items():
                            if vals and len(vals) > latest_idx:
                                result["width_latest"][k] = vals[latest_idx]
                    elif width_data.get("rows"):
                        result["width_latest"] = {"rows": width_data["rows"][:10]}
                    print(f"    Width extracted from '{key}': {result.get('width_latest', {})}")
                    break

        # ========== CONGESTION (table extraction) ==========
        print("  [legulegu] Scraping ashares-congestion...")
        page3 = browser.new_page()
        page3.set_default_timeout(60000)
        try:
            page3.goto(f"{BASE_URL}/stockdata/ashares-congestion", wait_until="domcontentloaded", timeout=60000)
            page3.wait_for_selector("table", timeout=15000)
            page3.wait_for_timeout(3000)
            result.update(_extract_tables(page3, "congestion"))
            # Extract latest congestion value
            for k, v in result.items():
                if k.startswith("congestion_table") and v.get("rows"):
                    first_row = v["rows"][0]
                    if len(first_row) >= 5:
                        result["congestion_latest"] = {
                            "date": first_row[0],
                            "close": float(first_row[1]),
                            "top5_amount": float(first_row[2]),
                            "total_amount": float(first_row[3]),
                            "congestion_pct": float(first_row[4])
                        }
                        print(f"    Latest congestion: {result['congestion_latest']}")
                        break
        except Exception as e:
            print(f"    Error: {e}")
        page3.close()

        browser.close()

    # Summary
    items = sum(1 for k in result if "api" in k or "table" in k or "latest" in k)
    print(f"  [legulegu] Done: {items} data items captured")
    return result


def run(trade_date: str = TRADE_DATE, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[legulegu] Scraping {trade_date}...")

    result = {"trade_date": trade_date, **scrape()}

    path = os.path.join(output_dir, "legulegu.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[legulegu] Saved -> {path}")
    return path


if __name__ == "__main__":
    run()
