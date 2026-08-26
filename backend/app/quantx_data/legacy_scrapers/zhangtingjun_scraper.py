"""涨停君 (zhangtingjun.com) public API scraper.

Free-tier HTTP API, no auth required.  Provides market sentiment cycle
(fundamentally different "three-line" model vs 短线侠/DeepQ), selected limit-up
stock scoring, sector cycle map, and index snapshots.

Source docs (reverse-engineered from the SPA bundle + live probes, 2026-08-22):

    Base:        https://api.zhangtingjun.com
    Free tier:   GET /api/public/v1/*
    Paid tier:   GET /api/app/v1/*   (lianban detail / youzi seats / post-market
                 detail-v2) — NOT scraped here.

Endpoints scraped:
    /api/public/v1/dashboard/overview            市场概览（温度/情绪分/炸板率/指数）
    /api/public/v1/homepage?trade_date=          首页 Hero/行业标签/情绪指标
    /api/public/v1/emotion/history?days=&signal_limit=&date=   情绪周期历史+板块周期图
    /api/public/v1/index/list?trade_date=&points_limit=30       指数快照
    /api/public/v1/index/sse?days=30                             上证指数历史

Design: 每个端点独立 try/except，单端点失败只降级对应分片，不中断整体采集；
与 pipeline 其余采集器一样在 pipeline 中由 run_scraper 兜底，永不崩溃主流程。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

import requests

BASE_URL = "https://api.zhangtingjun.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0 Safari/537.36"
)
TIMEOUT = 25
MAX_RETRY = 3
RETRY_SLEEP = 3.0

# 各片段的相对路径（作为 source urls 记录）
PATH_OVERVIEW = "/api/public/v1/dashboard/overview"
PATH_HOMEPAGE = "/api/public/v1/homepage"
PATH_EMOTION_HISTORY = "/api/public/v1/emotion/history"
PATH_INDEX_LIST = "/api/public/v1/index/list"
PATH_INDEX_SSE = "/api/public/v1/index/sse"


class ZTJError(Exception):
    """Wraps a non-200 response from the zhangtingjun public API."""


def _fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """GET a JSON endpoint with retry; raises ZTJError on final failure."""
    last: Exception | None = None
    for attempt in range(MAX_RETRY):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            last = ZTJError(f"http_{resp.status_code}: {resp.text[:200]}")
        except Exception as e:  # noqa: BLE001 — network/SSL/timeout retries
            last = e
        if attempt + 1 < MAX_RETRY:
            time.sleep(RETRY_SLEEP * (attempt + 1))
    raise ZTJError(str(last))


def _safe_section(key: str, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch one section; on failure return {'status': 'error', 'error': ...}."""
    try:
        payload = _fetch_json(url, params)
        return {"status": "ok", **payload} if isinstance(payload, dict) else {"status": "ok", "payload": payload}
    except Exception as e:  # noqa: BLE001 — section isolation, never crash pipeline
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def scrape(trade_date: str) -> dict[str, Any]:
    """Fetch all free-tier zhangtingjun sections for ``trade_date`` (YYYYMMDD).

    Returns a flat dict with deterministic keys; each value is a dict that
    carries ``status`` ("ok"/"error").  ``available`` is True when at least one
    section succeeded.
    """
    homepage_base = BASE_URL + PATH_HOMEPAGE
    result: dict[str, Any] = {
        "trade_date": trade_date,
        "scraped_at": datetime.now().isoformat(),
        "source_urls": {
            "overview": BASE_URL + PATH_OVERVIEW,
            "homepage": homepage_base,
            "emotion_history": BASE_URL + PATH_EMOTION_HISTORY,
            "index_list": BASE_URL + PATH_INDEX_LIST,
            "index_sse": BASE_URL + PATH_INDEX_SSE,
        },
        "overview": _safe_section("overview", BASE_URL + PATH_OVERVIEW),
        "homepage_latest": _safe_section("homepage_latest", homepage_base + f"?trade_date=latest"),
        "homepage_date": _safe_section("homepage_date", homepage_base + f"?trade_date={trade_date}"),
        "emotion_history_latest": _safe_section(
            "emotion_history_latest",
            BASE_URL + PATH_EMOTION_HISTORY,
            {"days": "10", "signal_limit": "5"},
        ),
        "emotion_history_date": _safe_section(
            "emotion_history_date",
            BASE_URL + PATH_EMOTION_HISTORY,
            {"days": "10", "signal_limit": "5", "date": trade_date},
        ),
        "index_list": _safe_section(
            "index_list",
            BASE_URL + PATH_INDEX_LIST,
            {"trade_date": trade_date, "points_limit": "30"},
        ),
        "index_sse": _safe_section("index_sse", BASE_URL + PATH_INDEX_SSE, {"days": "30"}),
    }

    ok_count = sum(1 for v in result.values() if isinstance(v, dict) and v.get("status") == "ok")
    result["available"] = ok_count >= 2
    result["available_sections"] = [
        k for k, v in result.items() if isinstance(v, dict) and v.get("status") == "ok"
    ]
    return result


def run(trade_date: str, output_dir: str) -> str:
    """Main entry: fetch 涨停君 free public data and save to output_dir/zhangtingjun.json."""
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[zhangtingjun] Scraping {trade_date}...")

    result = scrape(trade_date)
    ok_sections = result.get("available_sections") or []
    if result.get("available"):
        result["status"] = "ok"
        print(f"  [zhangtingjun] ok, sections: {len(ok_sections)} -> {', '.join(ok_sections)}")
    else:
        result["status"] = "error"
        errors = {
            k: (v.get("error") if isinstance(v, dict) else None) for k, v in result.items()
            if isinstance(v, dict) and v.get("status") == "error"
        }
        result["errors"] = errors
        print(f"  [zhangtingjun] ERROR: {len(errors)} sections failed: {json.dumps(errors, ensure_ascii=False)}")

    path = os.path.join(output_dir, "zhangtingjun.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[zhangtingjun] Saved -> {path}")
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="涨停君 public API scraper")
    parser.add_argument("--date", required=True, help="Trade date (YYYYMMDD)")
    parser.add_argument("--output-dir", default="output/data", help="Output directory")
    args = parser.parse_args()
    run(args.date, args.output_dir)
