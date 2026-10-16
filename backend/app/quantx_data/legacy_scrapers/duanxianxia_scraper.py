"""Duanxianxia Playwright scraper: sentiment, sector strength, ladder data."""
import json
import os
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

from app.quantx_data.browser_runtime import launch_chromium

OUTPUT_DIR = None
TRADE_DATE = None
BASE_URLS = ["https://duanxianxia.com", "https://www.duanxianxia.com"]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

QXLIVE_LABELS = [
    "情绪指标",
    "涨停家数",
    "跌停家数",
    "亏钱效应",
    "主力流入",
    "连板高度",
    "上涨家数",
    "下跌家数",
    "今日封板率",
    "昨涨停表现",
    "昨连板表现",
]


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _goto_first_working(page, path: str) -> tuple[str, str]:
    last_error = None
    for base_url in BASE_URLS:
        url = f"{base_url}{path}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(5000)
            text = page.locator("body").inner_text(timeout=15000)
            if text and len(text) > 100:
                return base_url, text
        except Exception as exc:
            last_error = exc
            print(f"  [duanxianxia] {url} failed: {exc}")
    raise RuntimeError(f"all duanxianxia urls failed for {path}: {last_error}")


def _extract_tables(page, max_tables: int = 20, max_rows: int = 80) -> dict:
    result = {}
    for i, table in enumerate(page.locator("table").all()):
        if i >= max_tables:
            break
        try:
            rows = table.locator("tr").all()
            if len(rows) < 2:
                continue
            headers = [h.inner_text().strip() for h in rows[0].locator("th,td").all()]
            data_rows = []
            for row in rows[1 : max_rows + 1]:
                cells = [c.inner_text().strip() for c in row.locator("td").all()]
                if cells and any(cells):
                    data_rows.append(cells)
            if data_rows:
                result[f"table_{i}"] = {"headers": headers, "data": data_rows}
        except Exception:
            pass
    return result


def _parse_pool_stats(text: str) -> dict:
    stats = {}
    compact = _compact(text)
    for label in ["涨停", "连板", "封板率", "炸板", "跌停"]:
        m = re.search(rf"{label}\s+([0-9.]+%?)\s+今日\s+([0-9.]+%?)\s+昨日", compact)
        if m:
            stats[label] = {"today": m.group(1), "yesterday": m.group(2)}
    return stats


def _parse_qxlive_fields(text: str) -> dict:
    fields = {}
    compact = _compact(text)
    for label in QXLIVE_LABELS:
        m = re.search(rf"{label}[：:]\s*([-+]?[0-9.]+(?:%|亿)?)", compact)
        if m:
            fields[label] = m.group(1)
    return fields


def _parse_sector_strength(text: str) -> list[dict]:
    sectors = []
    seen = set()
    compact = _compact(text)
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{2,16})\((-?[0-9.]+)\)\s+([0-9]+)涨停", compact):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        sectors.append({"name": name, "score": m.group(2), "limit_up_count": int(m.group(3))})
        if len(sectors) >= 80:
            break
    return sectors


def scrape() -> dict:
    result = {
        "status": "unknown",
        "working_base_url": "",
        "sentiment": {},
        "sentiment_fields": {},
        "sector_strength": [],
        "sectors": [],
        "pool_stats": {},
        "tables": {},
    }

    with sync_playwright() as p:
        browser = launch_chromium(
            p,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1440, "height": 1200},
            ignore_https_errors=True,
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            print("  [duanxianxia] Loading /web/pool ...")
            base_url, pool_text = _goto_first_working(page, "/web/pool")
            result["working_base_url"] = base_url
            result["pool_stats"] = _parse_pool_stats(pool_text)
            result["tables"].update({f"pool_{k}": v for k, v in _extract_tables(page).items()})

            # Preserve table_N keys so downstream deterministic consumers can
            # inspect the same structured table rows.
            for k, v in _extract_tables(page, max_tables=10, max_rows=8).items():
                result[k] = v

            print("  [duanxianxia] Loading /web/qxlive ...")
            _, qxlive_text = _goto_first_working(page, "/web/qxlive")
            result["sentiment_fields"] = _parse_qxlive_fields(qxlive_text)
            result["sentiment"] = result["sentiment_fields"]
            result["sector_strength"] = _parse_sector_strength(qxlive_text)

            qx_tables = _extract_tables(page, max_tables=20, max_rows=120)
            result["tables"].update({f"qxlive_{k}": v for k, v in qx_tables.items()})
            for table in qx_tables.values():
                rows = table.get("data", [])
                if rows and len(rows[0]) >= 3:
                    result["sectors"] = rows[:40]
                    break

            result["status"] = "ok"
            print(
                f"  [duanxianxia] Scraping complete via {base_url}: "
                f"pool={bool(result['pool_stats'])}, qx={bool(result['sentiment_fields'])}, "
                f"sectors={len(result['sector_strength'])}"
            )
        except Exception as e:
            print(f"  [duanxianxia] Error: {e}")
            result["status"] = "error"
            result["error"] = str(e)
        finally:
            browser.close()

    return result


def run(trade_date: str = TRADE_DATE, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[duanxianxia] Scraping {trade_date}...")

    result = {
        "trade_date": trade_date,
        "scraped_at": datetime.now().isoformat(),
        "source": "duanxianxia.com",
        **scrape(),
    }

    path = os.path.join(output_dir, "duanxianxia.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[duanxianxia] Saved -> {path}")
    return path


if __name__ == "__main__":
    run()
