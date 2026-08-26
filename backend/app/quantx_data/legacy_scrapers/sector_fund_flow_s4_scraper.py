"""Scrape Eastmoney s:4 sector fund flow via Playwright browser.

push2.eastmoney.com requires a browser session cookie from
data.eastmoney.com first. Without a valid session, API requests
return ERR_EMPTY_RESPONSE. We visit the main page to establish
the session, then fetch two pages (API caps 100 per page) to
cover all ~128 new-Shenwan industries.
"""
import json
import os
import time


def _s4_records_from_data(data: dict) -> list:
    items = data.get("data", {}).get("diff") or []
    records = []
    for item in items:
        records.append({
            "name": str(item.get("f14") or ""),
            "pct_chg": float(item.get("f3") or 0),
            "net_inflow_yi": round((float(item.get("f62") or 0)) / 1e8, 2),
            "amount_yi": round((float(item.get("f6") or 0)) / 1e8, 2),
            "net_inflow_pct": float(item.get("f184") or 0),
            "code": str(item.get("f12") or ""),
        })
    return records


def _fetch_page(page, pn: int) -> tuple:
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        "?fid=f62&po=0&pz=100&pn=" + str(pn) + "&np=1&fltt=2&invt=2"
        "&ut=8dec03ba335b81bf4ebdf7b29ec27d15"
        "&fs=m:90+s:4&fields=f12,f14,f3,f6,f62,f184"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    body = page.locator("body").inner_text()
    data = json.loads(body.strip())
    total = data.get("data", {}).get("total", 0)
    return _s4_records_from_data(data), total


def run(trade_date: str = "20260702", output_dir: str = "output/data") -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[sector_fund_flow_s4] Fetching Eastmoney s:4 sector fund flow...")

    from playwright.sync_api import sync_playwright

    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(_k, None)

    records = []
    last_error = ""
    for attempt in range(3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    viewport={"width": 1440, "height": 900},
                )
                page = context.new_page()

                if attempt > 0:
                    wait_s = [5, 15][attempt - 1]
                    print(f"  [sector_fund_flow_s4] retry {attempt + 1}/3 after {wait_s}s...")
                    time.sleep(wait_s)

                # Establish session by visiting the main page.
                page.goto(
                    "https://data.eastmoney.com/bkzj/hy.html",
                    wait_until="domcontentloaded", timeout=30000,
                )
                page.wait_for_timeout(4000)

                # Fetch two pages to cover all ~128 industries.
                r1, total = _fetch_page(page, 1)
                records = r1
                print(f"  [sector_fund_flow_s4] page1: {len(r1)} sectors (total={total})")

                if total > 100:
                    r2, _ = _fetch_page(page, 2)
                    existing = {r["code"] for r in records}
                    for r in r2:
                        if r["code"] not in existing:
                            records.append(r)
                            existing.add(r["code"])
                    print(f"  [sector_fund_flow_s4] page2: {len(r2)} → merged {len(records)} unique")

                browser.close()
                records.sort(key=lambda r: r["net_inflow_yi"], reverse=True)
                print(f"  [sector_fund_flow_s4] {len(records)} sectors (s:4, new Shenwan)")

                path = os.path.join(output_dir, "sector_fund_flow_s4.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        {"trade_date": trade_date, "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "sectors": records, "source": "eastmoney_s4"},
                        f, ensure_ascii=False, indent=2,
                    )
                return path
        except Exception as e:
            last_error = str(e)
            print(f"  [sector_fund_flow_s4] attempt {attempt + 1} failed: {e}")

    print(f"  [sector_fund_flow_s4] all 3 attempts failed, writing empty fallback")
    path = os.path.join(output_dir, "sector_fund_flow_s4.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"trade_date": trade_date, "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "sectors": [], "source": "eastmoney_s4", "error": last_error},
            f, ensure_ascii=False, indent=2,
        )
    return path
