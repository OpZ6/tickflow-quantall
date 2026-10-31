"""交互式抓取 QuickTiny 登录态 (Playwright storage state)。

QuickTiny 的行情页需要登录, 抓取器靠 `data/quicktiny_login_state.json` 复用
浏览器会话。会话被服务端作废后 (表现为 /api/auth/me 返回 401), 就得重新登录
一次并更新该文件 —— 这个脚本负责把「人工登录」和「落盘」串起来。

用法:
    cd backend
    .venv\\Scripts\\python.exe scripts\\quicktiny_login.py

脚本会打开一个有头浏览器窗口: 请在里面完成登录 (账号密码 / 扫码 / 短信都行),
登录成功后它会自动轮询到 /api/auth/me 返回 200, 把 storage state 写到
data/quicktiny_login_state.json, 并打印账号类型与 token 过期时间。
"""
from __future__ import annotations

import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from app.quantx_data.browser_runtime import launch_chromium  # noqa: E402

REPO_ROOT = BACKEND_ROOT.parent
BASE_URL = "https://stock.quicktiny.cn"
TARGET = REPO_ROOT / "data" / "quicktiny_login_state.json"
POLL_INTERVAL_SECONDS = 2.0
TIMEOUT_SECONDS = 15 * 60
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PROBE_AUTH = """async () => {
  try {
    const r = await fetch('/api/auth/me', {credentials: 'include'});
    return r.status;
  } catch (e) {
    return 0;
  }
}"""


def _log(message: str) -> None:
    print(message, flush=True)


def _jwt_exp(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        exp = data.get("exp")
        return datetime.fromtimestamp(exp).isoformat(timespec="seconds") if exp else None
    except Exception:
        return None


def _local_storage_map(state: dict) -> dict[str, str]:
    origin = next(
        (item for item in state.get("origins", []) if item.get("origin") == BASE_URL),
        None,
    )
    return {item["name"]: item["value"] for item in (origin or {}).get("localStorage", [])}


def _summarize(state: dict) -> str:
    values = _local_storage_map(state)
    token = values.get("token")
    if not token:
        token = next((c.get("value") for c in state.get("cookies", []) if c.get("name") == "token"), None)
    user = {}
    if values.get("user"):
        try:
            user = json.loads(values["user"])
        except Exception:
            user = {}
    return (
        f"账号类型={user.get('userType') or '未知'}, role={user.get('role') or '未知'}, "
        f"token 过期={_jwt_exp(token) or '未知'}, localStorage 键数={len(values)}"
    )


def main() -> int:
    _log("=" * 62)
    _log("QuickTiny 登录态抓取")
    _log("  1) 浏览器窗口打开后, 请手动登录 stock.quicktiny.cn")
    _log("  2) 登录成功后脚本会自动检测并在 1-2 秒内落盘")
    _log(f"  3) 目标文件: {TARGET}")
    _log("  4) 窗口请勿提前关闭 (最多等 15 分钟)")
    _log("=" * 62)

    with sync_playwright() as p:
        # 有头模式: 必须让用户看到窗口并交互
        browser = launch_chromium(
            p,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        page = context.new_page()
        page.set_default_timeout(30000)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

        deadline = time.monotonic() + TIMEOUT_SECONDS
        authenticated = False
        last_status = None
        while time.monotonic() < deadline:
            try:
                status = page.evaluate(_PROBE_AUTH)
            except Exception as exc:  # 窗口被关掉 / 页面跳转中
                if "closed" in str(exc).lower():
                    _log("[中止] 浏览器窗口已关闭, 未写入登录态")
                    return 2
                status = 0
            if status != last_status:
                _log(f"  /api/auth/me -> {status}" + ("  (等待登录…)" if status != 200 else "  (已登录)"))
                last_status = status
            if status == 200:
                authenticated = True
                break
            time.sleep(POLL_INTERVAL_SECONDS)

        if not authenticated:
            _log("[超时] 15 分钟内未检测到登录成功, 未写入登录态 (旧文件保持不变)")
            browser.close()
            return 1

        # 登录后 SPA 可能还在写 localStorage/token, 稍等一下再取状态
        page.wait_for_timeout(1500)
        state = context.storage_state()
        browser.close()

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    tmp = TARGET.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TARGET)

    _log("-" * 62)
    _log(f"[完成] 已写入 {TARGET}")
    _log(f"       {_summarize(state)}")
    _log("       下一步: 让后端重抓该源 ->")
    _log('       curl -X POST "http://127.0.0.1:3018/api/quantx-data/runs/<日期>/sources/quicktiny/retry"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
