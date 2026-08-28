"""Dabanke public-page scraper.

Currently only the public replay page /fpb.html is used. Member pages are
detected separately and should not be treated as empty data.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from app.quantx_data.browser_runtime import launch_chromium

OUTPUT_DIR = None
TRADE_DATE = None
BASE_URL = "https://dabanke.com"
ROOT = Path(__file__).resolve().parents[2]
STATE_CANDIDATES = [
    Path(os.getenv("DABANKE_LOGIN_STATE", "")) if os.getenv("DABANKE_LOGIN_STATE") else None,
    ROOT / "reports" / "dabanke_login_state.json",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

MEMBER_PAGES = {
    "lhb": "/lhb.html",
    "limit_up_times": "/limit-up-times.html",
    "zgtd": "/zgtd.html",
    "lhbfp": "/lhbfp.html",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_tables(page, max_tables: int = 12, max_rows: int = 120) -> list[dict[str, Any]]:
    tables = []
    for i, table in enumerate(page.locator("table").all()):
        if i >= max_tables:
            break
        try:
            rows = table.locator("tr").all()
            if len(rows) < 2:
                continue
            headers = [h.inner_text().strip() for h in rows[0].locator("th,td").all()]
            data = []
            for row in rows[1 : max_rows + 1]:
                cells = [c.inner_text().strip() for c in row.locator("td,th").all()]
                if cells and any(cells):
                    data.append(cells)
            if data:
                tables.append({"index": i, "headers": headers, "rows": data})
        except Exception:
            pass
    return tables


def _extract_update_time(text: str) -> str:
    compact = _compact(text)
    patterns = [
        r"最后更新时间[:：]\s*(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
        r"当前时间[:：]\s*(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
    ]
    for pattern in patterns:
        m = re.search(pattern, compact)
        if m:
            return m.group(1)
    return ""


def _dates(text: str) -> list[str]:
    return sorted(set(re.findall(r"20\d{2}-\d{2}-\d{2}", text or "")))


def _compact_trade_date(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", str(value))
    return "".join(match.groups()) if match else str(value)


def _extract_ladder_source_date_from_tables(tables: list[dict[str, Any]]) -> str:
    for table in tables or []:
        headers = " ".join(str(item) for item in table.get("headers") or [])
        match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})\s*涨停连板", headers)
        if match:
            return "".join(match.groups())
    return ""


def _classify_member_page(text: str, table_rows: int) -> str:
    compact = _compact(text)
    if "数据会员可访问内容" in compact or "会员服务价格" in compact:
        return "member_required"
    if table_rows > 0:
        return "public_data"
    return "reachable_no_structured_data"


def _find_state_path() -> Path | None:
    for path in STATE_CANDIDATES:
        if path and path.exists():
            return path
    return None


def scrape(trade_date: str | None = None) -> dict:
    result: dict[str, Any] = {
        "status": "unknown",
        "source": BASE_URL,
        "login_state": {"state_found": bool(_find_state_path())},
        "fpb": {},
        "member_pages": {},
    }
    with sync_playwright() as p:
        browser = launch_chromium(
            p,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"],
        )
        state_path = _find_state_path()
        context_kwargs = {
            "user_agent": UA,
            "locale": "zh-CN",
            "viewport": {"width": 1440, "height": 1200},
            "ignore_https_errors": True,
            "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        }
        if state_path:
            context_kwargs["storage_state"] = str(state_path)
            result["login_state"]["state_path"] = (
                str(state_path.relative_to(ROOT)) if state_path.is_relative_to(ROOT) else str(state_path)
            )
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            print("  [dabanke] Loading /fpb.html ...")
            page.goto(f"{BASE_URL}/fpb.html", wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(8000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            text = page.locator("body").inner_text(timeout=15000)
            tables = _extract_tables(page)
            row_count = sum(len(t["rows"]) for t in tables)
            ladder_source_date = _extract_ladder_source_date_from_tables(tables)
            result["fpb"] = {
                "url": f"{BASE_URL}/fpb.html",
                "title": page.title(),
                "update_time": _extract_update_time(text),
                "dates": _dates(text),
                "ladder_source_date": ladder_source_date,
                "table_count": len(tables),
                "table_row_count": row_count,
                "tables": tables[:8],
            }

            for name, path in MEMBER_PAGES.items():
                print(f"  [dabanke] Checking {path} ...")
                try:
                    page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
                    member_text = page.locator("body").inner_text(timeout=5000)
                    member_tables = _extract_tables(page, max_tables=4, max_rows=20)
                    member_rows = sum(len(t["rows"]) for t in member_tables)
                    result["member_pages"][name] = {
                        "url": f"{BASE_URL}{path}",
                        "title": page.title(),
                        "status": _classify_member_page(member_text, member_rows),
                        "dates": _dates(member_text),
                        "table_row_count": member_rows,
                    }
                except Exception as exc:
                    result["member_pages"][name] = {
                        "url": f"{BASE_URL}{path}",
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }

            expected_date = _compact_trade_date(trade_date)
            if row_count <= 0:
                result["status"] = "no_public_rows"
            elif expected_date and ladder_source_date and ladder_source_date != expected_date:
                result["status"] = "stale_public_rows"
                result["freshness_warning"] = (
                    f"fpb ladder source date {ladder_source_date} != requested trade_date {expected_date}"
                )
            else:
                result["status"] = "ok"
        except Exception as exc:
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            browser.close()
    return result


def run(trade_date: str = TRADE_DATE, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[dabanke] Scraping {trade_date}...")
    result = {"trade_date": trade_date, "scraped_at": datetime.now().isoformat(), **scrape(trade_date)}
    path = os.path.join(output_dir, "dabanke.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[dabanke] Saved -> {path} (status={result.get('status')})")
    return path


if __name__ == "__main__":
    run()
