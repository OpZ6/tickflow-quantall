"""Quicktiny Playwright scraper.

The site requires login for usable data. This scraper reuses a saved
Playwright/localStorage state and never writes raw tokens to output JSON.
"""
import base64
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

OUTPUT_DIR = None
TRADE_DATE = None
BASE_URL = "https://stock.quicktiny.cn"
ROOT = Path(__file__).resolve().parents[2]
STATE_CANDIDATES = [
    Path(os.getenv("QUICKTINY_LOGIN_STATE", "")) if os.getenv("QUICKTINY_LOGIN_STATE") else None,
    ROOT / "reports" / "quicktiny_login_state.json",
    ROOT / "archive" / "test_files" / "quicktiny_login_state.json",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DATA_WORDS = ["涨停", "连板", "首板", "龙虎榜", "情绪", "题材", "主线", "龙头"]
LOGIN_WORDS = ["登录开启", "立即注册", "欢迎回来"]


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _find_state_path() -> Path | None:
    for path in STATE_CANDIDATES:
        if path and path.exists():
            return path
    return None


def _decode_jwt_meta(token: str | None) -> dict[str, Any]:
    if not token or "." not in token:
        return {"has_token": bool(token)}
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        exp = data.get("exp")
        iat = data.get("iat")
        return {
            "has_token": True,
            "iat": datetime.fromtimestamp(iat).isoformat(timespec="seconds") if iat else None,
            "exp": datetime.fromtimestamp(exp).isoformat(timespec="seconds") if exp else None,
            "expired": bool(exp and exp < time.time()),
        }
    except Exception as exc:
        return {"has_token": True, "decode_error": f"{type(exc).__name__}: {exc}"}


def _state_meta(state: dict[str, Any]) -> dict[str, Any]:
    local_storage = state.get("localStorage", {})
    token = local_storage.get("token")
    if not token:
        for cookie in state.get("cookies", []):
            if cookie.get("name") == "token":
                token = cookie.get("value")
                break
    meta = _decode_jwt_meta(token)
    user_raw = local_storage.get("user")
    if user_raw:
        try:
            user = json.loads(user_raw)
            meta.update(
                {
                    "user_type": user.get("userType"),
                    "role": user.get("role"),
                    "pro_expiry_date": user.get("proExpiryDate"),
                    "agent_membership_level": user.get("agentMembershipLevel"),
                    "last_login": user.get("lastLogin"),
                }
            )
        except Exception:
            meta["user_parse_error"] = True
    return meta


def _sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    filtered = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in {"token", "mobiletoken", "authorization"}:
            filtered.append((key, "***"))
        else:
            filtered.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def _extract_theme_counts(text: str) -> list[dict[str, Any]]:
    compact = _compact(text)
    if "更多" in compact:
        compact = compact.split("更多", 1)[1]
    stop = {"单日", "多日", "列表", "行情", "分享", "收起", "涨停", "连板天梯"}
    out = []
    seen = set()
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-zA-Z0-9+\-]{2,16})\s+([1-9][0-9]?)\b", compact):
        name = m.group(1)
        count = int(m.group(2))
        if name in stop or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "count": count})
        if len(out) >= 30:
            break
    return out


def _probe_page(page, url: str, wait_ms: int = 18000) -> dict[str, Any]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
    except Exception as exc:
        # Quicktiny is a SPA and may abort document navigation while client-side
        # routing takes over. If that happens, the page can still render data.
        if "ERR_ABORTED" not in str(exc):
            raise
    page.wait_for_timeout(wait_ms)
    for selector in [".ant-modal-close", ".ant-drawer-close"]:
        try:
            page.locator(selector).first.click(timeout=1000)
        except Exception:
            pass
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    text = page.locator("body").inner_text(timeout=15000)
    compact = _compact(text)
    return {
        "url": url,
        "title": page.title(),
        "text_len": len(text),
        "data_hits": [w for w in DATA_WORDS if w in compact],
        "login_hits": [w for w in LOGIN_WORDS if w in compact],
        "theme_counts": _extract_theme_counts(text),
        "row_like_count": page.locator("[class*=row], [class*=card], [class*=item]").count(),
    }


def scrape() -> dict:
    state_path = _find_state_path()
    result: dict[str, Any] = {
        "status": "needs_login_state",
        "source": BASE_URL,
        "state_path": "",
        "login_state": {"state_found": bool(state_path)},
        "pages": {},
        "captured": [],
    }
    if not state_path:
        result["error"] = "quicktiny login state not found"
        return result

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["status"] = "login_state_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    meta = _state_meta(state)
    result["state_path"] = str(state_path.relative_to(ROOT)) if state_path.is_relative_to(ROOT) else str(state_path)
    result["login_state"] = {
        "state_found": True,
        "token_meta": meta,
        "local_storage_keys": sorted(state.get("localStorage", {}).keys()),
        "cookie_names": [c.get("name") for c in state.get("cookies", [])],
    }
    if meta.get("expired"):
        result["status"] = "login_state_expired"
        return result

    with sync_playwright() as p:
        browser = p.chromium.launch(
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
        if state.get("cookies"):
            context.add_cookies(state["cookies"])
        page = context.new_page()
        page.set_default_timeout(30000)

        def on_response(response):
            if any(key in response.url for key in ["api", "stock", "ladder", "replay", "theme", "limit"]):
                item = {"url": _sanitize_url(response.url), "status": response.status}
                try:
                    ct = response.headers.get("content-type", "")
                    if "application/json" in ct:
                        data = response.json()
                        item["json_type"] = type(data).__name__
                        item["json_keys"] = list(data.keys())[:20] if isinstance(data, dict) else []
                except Exception:
                    pass
                result["captured"].append(item)

        page.on("response", on_response)
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=40000)
            if state.get("localStorage"):
                page.evaluate(
                    """items => {
                        for (const [key, value] of Object.entries(items)) {
                            localStorage.setItem(key, value);
                        }
                    }""",
                    state["localStorage"],
                )

            result["pages"]["stock_ladder"] = _probe_page(page, f"{BASE_URL}/stock-ladder")
            result["pages"]["daily_replay"] = _probe_page(page, f"{BASE_URL}/daily-replay")
            result["captured"] = result["captured"][:80]

            logged_pages = [v for v in result["pages"].values() if v.get("data_hits") and not v.get("login_hits")]
            result["status"] = "ok" if len(logged_pages) >= 2 else "partial"
        except Exception as exc:
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            browser.close()
    return result


def run(trade_date: str = TRADE_DATE, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[quicktiny] Scraping {trade_date}...")
    result = {"trade_date": trade_date, "scraped_at": datetime.now().isoformat(), **scrape()}
    path = os.path.join(output_dir, "quicktiny.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[quicktiny] Saved -> {path} (status={result.get('status')})")
    return path


if __name__ == "__main__":
    run()
