"""Zhangtingke scraper: limit-up height history and daily ladder.

The site renders the needed data into JavaScript variables, so this scraper
parses those structured objects instead of copying the external table HTML.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

import requests


BASE_URL = "https://zhangtingke.com"
HEIGHT_URL = f"{BASE_URL}/zt_lbgd_line"
LADDER_URL = f"{BASE_URL}/query_lbtd_his/?date={{date}}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0 Safari/537.36"
)


def _stock_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[1]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _market_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith(("sh", "sz", "bj")):
        return text[:2]
    return ""


def _fetch(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    response.raise_for_status()
    if response.encoding and response.encoding.lower() != "iso-8859-1":
        response.encoding = response.encoding
    else:
        # Server didn't declare charset — try utf-8, fall back to gbk for CN sites
        try:
            response.content.decode("utf-8")
            response.encoding = "utf-8"
        except UnicodeDecodeError:
            response.encoding = "gbk" if "zhangtingke" in url or "duanxianxia" in url else response.apparent_encoding
    return response.text


def _extract_js_object(text: str, var_name: str) -> dict[str, Any]:
    match = re.search(rf"\b(?:let|var|const)\s+{re.escape(var_name)}\s*=", text)
    if not match:
        return {}
    start = text.find("{", match.end())
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    quote = ""
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = text[start : index + 1]
                raw = re.sub(r"\bNaN\b", "null", raw)
                raw = re.sub(r"\bInfinity\b", "null", raw)
                return json.loads(raw)
    return {}


def _row_dict(headers: list[Any], row: list[Any]) -> dict[str, Any]:
    return {str(headers[i]): row[i] for i in range(min(len(headers), len(row)))}


def _height_row(item: dict[str, Any]) -> dict[str, Any]:
    raw_code = item.get("股票代码")
    amount_wan = item.get("成交额")
    return {
        "date": str(item.get("交易日期") or ""),
        "code": _stock_code(raw_code),
        "market": _market_code(raw_code),
        "name": item.get("股票名称") or "",
        "limit_times": item.get("连板天数"),
        "close": item.get("收盘价"),
        "pct_chg": item.get("涨跌幅"),
        "auction_pct": item.get("竞价涨幅"),
        "turnover_pct": item.get("换手率"),
        "amount_wan": amount_wan,
        "amount_yi": round(float(amount_wan or 0) / 10000, 2) if amount_wan is not None else None,
        "float_mcap_yi": item.get("流通市值"),
        "total_mcap_yi": item.get("总市值"),
        "one_word_count": item.get("连板期一字板数"),
        "closed_limit": item.get("收盘涨停"),
    }


def _ladder_row(item: dict[str, Any], trade_date: str) -> dict[str, Any]:
    raw_code = item.get("股票代码")
    amount = item.get("成交额")
    return {
        "date": trade_date,
        "code": _stock_code(raw_code),
        "market": _market_code(raw_code),
        "name": item.get("股票名称") or "",
        "limit_times": item.get("连板天数"),
        "close": item.get("收盘价"),
        "pct_chg": item.get("涨跌幅"),
        "auction_pct": item.get("竞价涨幅"),
        "turnover_pct": item.get("换手率"),
        "amount_yi": amount,
        "float_mcap_yi": item.get("流通市值"),
        "theme_name": item.get("题材名"),
        "theme_reason": item.get("题材理由"),
        "interpretation": item.get("解读"),
    }


def scrape(trade_date: str) -> dict[str, Any]:
    height_html = _fetch(HEIGHT_URL)
    ladder_html = _fetch(LADDER_URL.format(date=trade_date))
    height_raw = _extract_js_object(height_html, "lbgd_dict")
    ladder_raw = _extract_js_object(ladder_html, "dictData")

    height_headers = list(height_raw.get("lbgd_header") or [])
    height_rows = [
        _height_row(_row_dict(height_headers, row))
        for row in (height_raw.get("lbgd_lst") or [])
        if isinstance(row, list)
    ]
    height_rows = [row for row in height_rows if row.get("date")]

    ladder_headers = list(ladder_raw.get("lbtd_header") or [])
    ladder_date = str(ladder_raw.get("date") or trade_date)
    ladder_stocks = [
        _ladder_row(_row_dict(ladder_headers, row), ladder_date)
        for row in (ladder_raw.get("lbtd_lst") or [])
        if isinstance(row, list)
    ]

    ladder_by_height: dict[str, list[dict[str, Any]]] = {}
    for stock in ladder_stocks:
        height = str(stock.get("limit_times") or "")
        if height:
            ladder_by_height.setdefault(height, []).append(stock)

    latest_by_date = height_rows[:120]
    today_height = next((row for row in height_rows if row.get("date") == trade_date), {})
    return {
        "trade_date": trade_date,
        "available": bool(height_rows or ladder_stocks),
        "source_urls": {
            "height_history": HEIGHT_URL,
            "daily_ladder": LADDER_URL.format(date=trade_date),
        },
        "height_history": latest_by_date,
        "today_height": today_height,
        "ladder_stocks": ladder_stocks,
        "ladder_by_height": ladder_by_height,
        "raw_counts": {"height_rows": len(height_rows), "ladder_rows": len(ladder_stocks)},
    }


def run(trade_date: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[zhangtingke] Scraping {trade_date}...")
    result: dict[str, Any] = {"trade_date": trade_date, "scraped_at": datetime.now().isoformat()}
    try:
        result.update(scrape(trade_date))
        result["status"] = "ok" if result.get("available") else "empty"
        print(
            f"  [zhangtingke] height_rows={result.get('raw_counts', {}).get('height_rows', 0)}, "
            f"ladder_rows={result.get('raw_counts', {}).get('ladder_rows', 0)}"
        )
    except Exception as exc:
        result.update({"status": "error", "available": False, "error": str(exc), "source_urls": {"height_history": HEIGHT_URL, "daily_ladder": LADDER_URL.format(date=trade_date)}})
        print(f"  [zhangtingke] ERROR: {exc}")

    path = os.path.join(output_dir, "zhangtingke.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[zhangtingke] Saved -> {path}")
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Zhangtingke limit-up height and ladder scraper")
    parser.add_argument("--date", required=True, help="Trade date (YYYYMMDD)")
    parser.add_argument("--output-dir", default="output/data", help="Output directory")
    args = parser.parse_args()
    run(args.date, args.output_dir)
