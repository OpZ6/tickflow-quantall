"""ZenChart 官方分析适配器 (openclarr 官方 API 直连)。

free  端点 /api/zen/analyze: 全量图层, bsp 恒为空。
pro   端点 /api/zq/analyze : 含服务端买卖点引擎结果, 需要用户自己的
      Bearer token —— 通过环境变量 TICKFLOW_ZENCHART_TOKEN 提供,
      绝不入库不入 Git。未配置时自动降级 free。

仅调用公开只读接口, 带浏览器身份头, 不登录、不采集任何用户数据。
"""
from __future__ import annotations

import os
from typing import Any

import httpx

ZENAPI = "https://openclarr.com/api/zen/analyze"
ZAPI = "https://openclarr.com/api/zq/analyze"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://openclarr.com/coin/",
    "Accept": "application/json, text/plain, */*",
}


class ZenError(RuntimeError):
    """ZenChart 接口不可用或响应异常。"""


def _token() -> str | None:
    return os.getenv("TICKFLOW_ZENCHART_TOKEN", "").strip() or None


def fetch_official(
    symbol: str,
    level: str = "D1",
    limit: int = 300,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """拉取官方全量分析图层。

    返回 {source, official}: source 为 'pro'|'free';
    official 含 candles/bi/segments/zhongshu/zhongshu_seg/macd/bsp。
    失败抛 ZenError, 由路由层转成 available=False 的稳定响应。
    """
    tok = _token()
    headers = dict(BROWSER_HEADERS)
    params: dict[str, Any] = {
        "symbol": symbol, "level": level, "mini": 0, "limit": limit,
    }
    if tok:
        url = ZAPI
        headers["Authorization"] = f"Bearer {tok}"
    else:
        url = ZENAPI

    try:
        resp = httpx.get(url, params=params, headers=headers,
                         timeout=timeout, trust_env=False)
    except httpx.HTTPError as exc:
        raise ZenError(f"网络错误: {type(exc).__name__}") from exc

    if resp.status_code == 401:
        raise ZenError("token 无效或已过期 (401)")
    if resp.status_code == 402:
        raise ZenError("该接口需要 Pro 订阅 (402)")
    if resp.status_code == 403:
        raise ZenError("接口拒绝访问 (403)")
    if resp.status_code != 200:
        raise ZenError(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ZenError("响应不是有效 JSON") from exc

    layers = payload.get("analyze") if isinstance(payload.get("analyze"), dict) else payload
    official = {
        "candles": layers.get("candles", []),
        "merged_klines": layers.get("merged_klines", []),
        "fenxing": layers.get("fenxing", []),
        "bi": layers.get("bi", []),
        "segments": layers.get("segments", []),
        "zhongshu": layers.get("zhongshu", []),
        "zhongshu_seg": layers.get("zhongshu_seg", []),
        "macd": layers.get("macd", []),
        "bsp": layers.get("bsp", []),
    }
    return {
        "source": "pro" if tok else "free",
        "name": payload.get("name") or layers.get("name"),
        "official": official,
    }
