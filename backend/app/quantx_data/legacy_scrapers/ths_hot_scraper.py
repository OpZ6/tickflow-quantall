"""同花顺热点 scraper: 当日强势股 + 题材归因 reason tags.

零鉴权 HTTP API, ~73ms 响应。提供每只强势股的逐股涨停原因标签，
比 pywencai 的"行业名"精准得多，是主线拆解和候选池的核心输入。

Usage:
    from scrapers import ths_hot_scraper
    path = ths_hot_scraper.run("20260522", "output/data/20260522")
"""
import json
import os
from datetime import datetime

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "Chrome/117.0.0.0 Safari/537.36"
)
API_URL = "http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"


def _trade_date_to_api(date_str: str) -> str:
    """YYYYMMDD -> YYYY-MM-DD."""
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"


def scrape(trade_date: str) -> dict:
    """Fetch 同花顺热点 data for a trade date. Returns raw structured dict."""
    api_date = _trade_date_to_api(trade_date)
    url = API_URL.format(date=api_date)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        return {"error": str(e), "trade_date": trade_date}

    data = r.json()
    if data.get("errocode", 0) != 0:
        return {
            "error": data.get("errormsg", "unknown error"),
            "errocode": data.get("errocode"),
            "trade_date": trade_date,
        }

    rows = data.get("data") or []
    stocks = []
    for row in rows:
        stocks.append({
            "code": row.get("code", ""),
            "name": row.get("name", ""),
            "reason": row.get("reason", ""),
            "pct_chg": _float(row.get("zhangfu")),
            "turnover_pct": _float(row.get("huanshou")),
            "amount": _float(row.get("chengjiaoe")),
            "close": _float(row.get("close")),
            "change_amt": _float(row.get("zhangdie")),
            "dde_net": _float(row.get("ddejingliang")),
            "market": row.get("market", ""),
        })

    # Extract all unique reason tags for theme analysis
    all_tags = []
    for s in stocks:
        if s["reason"]:
            tags = [t.strip() for t in s["reason"].split("+") if t.strip()]
            all_tags.extend(tags)

    # Count tag frequency
    tag_counts = {}
    for t in all_tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1

    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:20]

    return {
        "trade_date": trade_date,
        "count": len(stocks),
        "stocks": stocks,
        "reason_tags": [{"tag": t, "count": c} for t, c in top_tags],
    }


def _float(v) -> float | None:
    """Safe float conversion, returns None on empty/missing."""
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def run(trade_date: str, output_dir: str) -> str:
    """Main entry: fetch 同花顺热点 data and save to output_dir/ths_hot.json."""
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[ths_hot] Scraping {trade_date} (同花顺热点 reason tags)...")

    result = {"trade_date": trade_date, "scraped_at": datetime.now().isoformat()}
    data = scrape(trade_date)

    if "error" in data and "errocode" not in data:
        # Network-level error
        result["status"] = "error"
        result["error"] = data["error"]
        print(f"  [ths_hot] ERROR: {data['error']}")
    elif "error" in data:
        # API-level error (e.g. no data for date)
        result["status"] = "api_error"
        result["error"] = data["error"]
        print(f"  [ths_hot] API error (errocode={data.get('errocode')}): {data['error']}")
    else:
        result["status"] = "ok"
        result.update(data)
        top3 = data.get("reason_tags", [])[:3]
        tag_str = ", ".join(f"{t['tag']}({t['count']})" for t in top3)
        print(f"  [ths_hot] {data['count']} stocks, top tags: {tag_str}")

    path = os.path.join(output_dir, "ths_hot.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[ths_hot] Saved -> {path}")
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="同花顺热点 reason tag scraper")
    parser.add_argument("--date", required=True, help="Trade date (YYYYMMDD)")
    parser.add_argument(
        "--output-dir", default="output/data", help="Output directory"
    )
    args = parser.parse_args()
    run(args.date, args.output_dir)
