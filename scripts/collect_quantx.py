#!/usr/bin/env python
"""QuantX 多源采集器: ths_hot / zhangtingke / pywencai / duanxianxia。

从 QuantX src/scrapers/ 移植,产出 JSON 到 data/quantx/YYYYMMDD/(兼容 QuantX 格式)。
盘后运行:
    cd backend
    uv run python ../scripts/collect_quantx.py --source ths_hot --date 20260821

数据源复杂度:
    ths_hot      — 简单 HTTP GET + JSON (零依赖)
    zhangtingke  — HTTP GET + JS 变量 regex 解析 (零依赖)
    pywencai     — akshare (4 fetchers) + pywencai SDK (百日新高)
    duanxianxia  — Playwright 浏览器 (情绪/封板率/连板高度)

产出路径: data/quantx/YYYYMMDD/{source}.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ============================================================
# 共享工具
# ============================================================


def _float_or_none(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _stock_code(value) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _market_code(value) -> str:
    text = str(value or "").strip().lower()
    if text.startswith(("sh", "sz", "bj")):
        return text[:2]
    return ""


def _find_column(columns, *, exact=(), contains=(), excludes=()):
    names = [str(c) for c in columns]
    for candidate in exact:
        if candidate in names:
            return candidate
    for name in names:
        if any(tok in name for tok in excludes):
            continue
        if any(tok in name for tok in contains):
            return name
    return None


def _split_concepts(value) -> list:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return list(
        dict.fromkeys(
            item.strip()
            for item in re.split(r"[;；,，、|｜\n\r]+", str(value))
            if item and item.strip() and item.strip().lower() != "nan"
        )
    )


def _write_json(data: dict, source: str, trade_date: str, tickflow_data: Path) -> Path:
    out_dir = tickflow_data / "quantx" / trade_date
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{source}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ============================================================
# ths_hot: 同花顺热点 (强势股 + 题材标签)
# ============================================================


def collect_ths_hot(trade_date: str) -> dict:
    api_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/date/{api_date}"
        f"/orderby/date/orderway/desc/charset/GBK/"
    )
    r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("errocode", 0) != 0:
        logger.warning("ths_hot errocode=%s: %s", data.get("errocode"), data.get("errormsg"))
        return {"trade_date": trade_date, "status": "error", "count": 0, "stocks": [], "reason_tags": []}

    rows = data.get("data") or []
    stocks = []
    for row in rows:
        stocks.append({
            "code": str(row.get("code", "")),
            "name": str(row.get("name", "")),
            "reason": str(row.get("reason", "")),
            "pct_chg": _float_or_none(row.get("zhangfu")),
            "turnover_pct": _float_or_none(row.get("huanshou")),
            "amount": _float_or_none(row.get("chengjiaoe")),
            "close": _float_or_none(row.get("close")),
            "change_amt": _float_or_none(row.get("zhangdie")),
            "dde_net": _float_or_none(row.get("ddejingliang")),
            "market": str(row.get("market", "")),
        })

    themes: dict[str, int] = {}
    for s in stocks:
        if s.get("reason") and s["reason"] != "nan":
            for tag in re.split(r"[+/]", s["reason"]):
                tag = tag.strip()
                if tag and len(tag) <= 40:
                    themes[tag] = themes.get(tag, 0) + 1
    reason_tags = sorted(themes.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        "trade_date": trade_date,
        "scraped_at": datetime.now().isoformat(),
        "status": "ok",
        "count": len(stocks),
        "stocks": stocks,
        "reason_tags": [{"tag": t, "count": c} for t, c in reason_tags],
    }


# ============================================================
# zhangtingke: 涨停客 (连板高度历史 + 当日梯队)
# ============================================================

ZTK_BASE = "https://zhangtingke.com"
ZTK_HEIGHT_URL = f"{ZTK_BASE}/zt_lbgd_line"
ZTK_LADDER_URL = ZTK_BASE + "/query_lbtd_his/?date={date}"


def _ztk_fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    resp.raise_for_status()
    try:
        resp.content.decode("utf-8")
        resp.encoding = "utf-8"
    except UnicodeDecodeError:
        resp.encoding = "gbk"
    return resp.text


def _extract_js_object(text: str, var_name: str) -> dict:
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
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {}
    return {}


def _ztk_row_dict(headers: list, row: list) -> dict:
    return {str(headers[i]): row[i] for i in range(min(len(headers), len(row)))}


def _ztk_height_row(item: dict) -> dict:
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


def _ztk_ladder_row(item: dict, trade_date: str) -> dict:
    raw_code = item.get("股票代码")
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
        "amount_yi": item.get("成交额"),
        "float_mcap_yi": item.get("流通市值"),
        "theme_name": item.get("题材名"),
        "theme_reason": item.get("题材理由"),
        "interpretation": item.get("解读"),
    }


def collect_zhangtingke(trade_date: str) -> dict:
    """涨停客: 连板高度历史 + 当日梯队。HTTP GET + JS 对象解析。"""
    result: dict = {
        "trade_date": trade_date,
        "scraped_at": datetime.now().isoformat(),
        "available": False,
        "source_urls": {
            "height_history": ZTK_HEIGHT_URL,
            "daily_ladder": ZTK_LADDER_URL.format(date=trade_date),
        },
    }
    try:
        height_html = _ztk_fetch(ZTK_HEIGHT_URL)
        ladder_html = _ztk_fetch(ZTK_LADDER_URL.format(date=trade_date))
        height_raw = _extract_js_object(height_html, "lbgd_dict")
        ladder_raw = _extract_js_object(ladder_html, "dictData")

        height_headers = list(height_raw.get("lbgd_header") or [])
        height_rows = [
            _ztk_height_row(_ztk_row_dict(height_headers, row))
            for row in (height_raw.get("lbgd_lst") or [])
            if isinstance(row, list)
        ]
        height_rows = [r for r in height_rows if r.get("date")]

        ladder_headers = list(ladder_raw.get("lbtd_header") or [])
        ladder_date = str(ladder_raw.get("date") or trade_date)
        ladder_stocks = [
            _ztk_ladder_row(_ztk_row_dict(ladder_headers, row), ladder_date)
            for row in (ladder_raw.get("lbtd_lst") or [])
            if isinstance(row, list)
        ]

        ladder_by_height: dict[str, list] = {}
        for s in ladder_stocks:
            h = str(s.get("limit_times") or "")
            if h:
                ladder_by_height.setdefault(h, []).append(s)

        result.update({
            "available": bool(height_rows or ladder_stocks),
            "height_history": height_rows[:120],
            "today_height": next((r for r in height_rows if r.get("date") == trade_date), {}),
            "ladder_stocks": ladder_stocks,
            "ladder_by_height": ladder_by_height,
            "raw_counts": {"height_rows": len(height_rows), "ladder_rows": len(ladder_stocks)},
            "status": "ok" if (height_rows or ladder_stocks) else "empty",
        })
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        logger.warning("zhangtingke 拉取失败: %s", exc)
    return result


# ============================================================
# pywencai: 问财 (涨停/连板/题材/百日新高) via akshare + pywencai
# ============================================================


def _ak_retry(fn, *args, attempts=3, backoff=(5, 15), label=""):
    last_error = ""
    for attempt in range(attempts):
        try:
            return fn(*args)
        except Exception as e:
            last_error = str(e)
            logger.warning("pywencai %s attempt %d/%d failed: %s", label, attempt + 1, attempts, e)
            if attempt < attempts - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
    return None


def _py_fetch_limit_up(trade_date: str) -> dict:
    try:
        import akshare as ak
    except ImportError:
        return {"count": 0, "stocks": [], "ladder": {}, "themes": []}

    def _fetch():
        df = ak.stock_zt_pool_em(date=trade_date)
        records = []
        for _, row in df.iterrows():
            records.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "limit_times": int(row.get("连板数", 1)) if "连板数" in row.index else 1,
                "reason": str(row.get("所属行业", "")),
                "seal_amount_yi": round(float(row.get("封板资金", 0)) / 1e8, 2),
                "first_time": str(row.get("首次封板时间", "")),
                "last_time": str(row.get("最后封板时间", "")),
                "open_times": int(row.get("炸板次数", 0)),
            })
        return records

    records = _ak_retry(_fetch, label="limit-up")
    if records is None:
        return {"count": 0, "stocks": [], "ladder": {}, "themes": []}

    ladder: dict[int, list] = {}
    for r in records:
        t = max(r["limit_times"], 1)
        ladder.setdefault(t, []).append(r["name"])
    themes: dict[str, int] = {}
    for r in records:
        if r["reason"] and r["reason"] != "nan":
            themes[r["reason"]] = themes.get(r["reason"], 0) + 1
    theme_list = sorted(themes.items(), key=lambda x: x[1], reverse=True)[:15]
    return {
        "count": len(records),
        "stocks": records,
        "ladder": {str(k): v for k, v in sorted(ladder.items(), reverse=True)},
        "themes": [{"name": k, "count": v} for k, v in theme_list],
    }


def _py_fetch_broken_board(trade_date: str) -> dict:
    try:
        import akshare as ak
    except ImportError:
        return {"count": 0, "stocks": []}

    def _fetch():
        df = ak.stock_zt_pool_zbgc_em(date=trade_date)
        return [{"code": str(row.get("代码", "")), "name": str(row.get("名称", ""))} for _, row in df.iterrows()]

    records = _ak_retry(_fetch, label="broken-board")
    if records is None:
        return {"count": 0, "stocks": []}
    return {"count": len(records), "stocks": records}


def _py_fetch_yesterday_perf(trade_date: str) -> dict:
    try:
        import akshare as ak
    except ImportError:
        return {"status": "unavailable", "stocks": [], "count": None}

    def _fetch():
        df = ak.stock_zt_pool_previous_em(date=trade_date)
        records = []
        pcts = []
        lianban_pcts = []
        advance_samples = 0
        continued_count = 0
        for _, row in df.iterrows():
            pct_chg = _float_or_none(row.get("涨跌幅"))
            latest_price = _float_or_none(row.get("最新价"))
            limit_price = _float_or_none(row.get("涨停价"))
            board_count = _float_or_none(row.get("昨日连板数"))
            continued = None
            if latest_price is not None and limit_price is not None:
                advance_samples += 1
                continued = latest_price >= limit_price - 0.005
                continued_count += int(continued)
            if pct_chg is not None:
                pcts.append(pct_chg)
                if board_count is not None and board_count >= 2:
                    lianban_pcts.append(pct_chg)
            records.append({
                "code": _stock_code(row.get("代码")),
                "name": str(row.get("名称") or "").strip(),
                "pct_chg": pct_chg,
                "latest_price": latest_price,
                "limit_price": limit_price,
                "yesterday_board_count": int(board_count) if board_count is not None else None,
                "continued": continued,
            })
        premium = round(sum(pcts) / len(pcts), 2) if pcts else None
        lianban_premium = round(sum(lianban_pcts) / len(lianban_pcts), 2) if lianban_pcts else None
        advance = round(continued_count / advance_samples * 100, 1) if advance_samples else None
        return {
            "schema_version": 2,
            "metric_semantics_version": 2,
            "as_of": trade_date,
            "status": "ok",
            "count": len(records),
            "advance_sample_count": advance_samples,
            "premium_sample_count": len(pcts),
            "continued_count": continued_count,
            "premium_rate": premium,
            "advance_rate": advance,
            "yesterday_lianban_premium": lianban_premium,
            "yesterday_zt_pct": premium,
            "yesterday_lb_pct": lianban_premium,
            "stocks": records,
        }

    result = _ak_retry(_fetch, label="yesterday-perf")
    if result is None:
        return {
            "schema_version": 2,
            "metric_semantics_version": 2,
            "as_of": trade_date,
            "status": "unavailable",
            "count": None,
            "advance_sample_count": 0,
            "premium_sample_count": 0,
            "continued_count": 0,
            "premium_rate": None,
            "advance_rate": None,
            "yesterday_lianban_premium": None,
            "stocks": [],
        }
    return result


def _py_fetch_limit_down(trade_date: str) -> dict:
    try:
        import akshare as ak
    except ImportError:
        return {"schema_version": 1, "as_of": trade_date, "status": "unavailable", "count": None, "stocks": []}

    def _fetch():
        df = ak.stock_zt_pool_dtgc_em(date=trade_date)
        records = [{"code": _stock_code(row.get("代码")), "name": str(row.get("名称") or "").strip(), "pct_chg": _float_or_none(row.get("涨跌幅"))} for _, row in df.iterrows()]
        return {"schema_version": 1, "as_of": trade_date, "status": "ok", "count": len(records), "stocks": records}

    result = _ak_retry(_fetch, label="limit-down")
    if result is None:
        return {"schema_version": 1, "as_of": trade_date, "status": "unavailable", "count": None, "stocks": []}
    return result


def _py_warm_iwencai() -> str:
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": UA})
        session.get("http://www.iwencai.com/", timeout=15)
        return "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    except Exception:
        return ""


def _py_new_high_query(trade_date: str) -> str:
    dt = datetime.strptime(str(trade_date), "%Y%m%d")
    return f"{dt.year}年{dt.month}月{dt.day}日百日新高 所属概念板块"


def _py_fetch_new_high_100d(trade_date: str) -> dict:
    query = _py_new_high_query(trade_date)
    try:
        import pywencai as _pw
    except ImportError:
        return {"schema_version": 2, "as_of": trade_date, "status": "unavailable", "query": query, "count": None, "stocks": [], "error": "pywencai not installed"}

    cookie = _py_warm_iwencai()
    last_error = ""
    for attempt in range(3):
        try:
            kwargs = {"query": query, "loop": True}
            if cookie:
                kwargs["cookie"] = cookie
            df = _pw.get(**kwargs)
            if df is None:
                if attempt < 2:
                    time.sleep([8, 25][attempt])
                    cookie = cookie or _py_warm_iwencai()
                    continue
                last_error = "pywencai returned None"
                break
            code_col = _find_column(df.columns, exact=("股票代码", "code"), contains=("股票代码",))
            name_col = _find_column(df.columns, exact=("股票简称", "name"), contains=("股票简称",))
            pct_col = _find_column(df.columns, exact=("最新涨跌幅", "涨跌幅"), contains=("最新涨跌幅", "涨跌幅"))
            concept_col = _find_column(df.columns, exact=("所属概念", "所属概念板块"), contains=("所属概念", "概念板块"), excludes=("数量",))
            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    "code": _stock_code(row.get(code_col)) if code_col else "",
                    "name": str(row.get(name_col) or "").strip() if name_col else "",
                    "pct_chg": _float_or_none(row.get(pct_col)) if pct_col else None,
                    "concepts": _split_concepts(row.get(concept_col)) if concept_col else [],
                })
            return {"schema_version": 2, "as_of": trade_date, "status": "ok", "query": query, "count": len(stocks), "stocks": stocks}
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep([8, 25][attempt])
                cookie = cookie or _py_warm_iwencai()
    return {"schema_version": 2, "as_of": trade_date, "status": "unavailable", "query": query, "count": None, "stocks": [], "error": last_error}


def collect_pywencai(trade_date: str) -> dict:
    """问财: 涨停/连板/题材/百日新高。akshare 4 fetchers + pywencai 1 fetcher。"""
    result = {
        "trade_date": trade_date,
        "scraped_at": datetime.now().isoformat(),
        "limit_up": _py_fetch_limit_up(trade_date),
        "broken_board": _py_fetch_broken_board(trade_date),
        "limit_down": _py_fetch_limit_down(trade_date),
        "yesterday_perf": _py_fetch_yesterday_perf(trade_date),
        "new_high_100d": _py_fetch_new_high_100d(trade_date),
        "ma_ratios": {"skipped": True, "note": "MA ratios not computed"},
    }
    zt = result["limit_up"]["count"]
    zb = result["broken_board"]["count"]
    total = zt + zb
    result["broken_rate"] = round(zb / total * 100, 1) if total > 0 else 0
    result["seal_rate"] = round(zt / total * 100, 1) if total > 0 else 100
    return result


# ============================================================
# duanxianxia: 短线侠 (情绪/封板率/连板高度) via Playwright
# ============================================================

DX_BASE_URLS = ["https://duanxianxia.com", "https://www.duanxianxia.com"]
DX_QXLIVE_LABELS = [
    "情绪指标", "涨停家数", "跌停家数", "亏钱效应", "主力流入",
    "连板高度", "上涨家数", "下跌家数", "今日封板率",
    "昨涨停表现", "昨连板表现",
]


def _dx_compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dx_goto_first_working(page, path: str):
    last_error = None
    for base_url in DX_BASE_URLS:
        url = f"{base_url}{path}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(5000)
            text = page.locator("body").inner_text(timeout=15000)
            if text and len(text) > 100:
                return base_url, text
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"all duanxianxia urls failed for {path}: {last_error}")


def _dx_extract_tables(page, max_tables=20, max_rows=80) -> dict:
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


def _dx_parse_pool_stats(text: str) -> dict:
    stats = {}
    compact = _dx_compact(text)
    for label in ["涨停", "连板", "封板率", "炸板", "跌停"]:
        m = re.search(rf"{label}\s+([0-9.]+%?)\s+今日\s+([0-9.]+%?)\s+昨日", compact)
        if m:
            stats[label] = {"today": m.group(1), "yesterday": m.group(2)}
    return stats


def _dx_parse_qxlive_fields(text: str) -> dict:
    fields = {}
    compact = _dx_compact(text)
    for label in DX_QXLIVE_LABELS:
        m = re.search(rf"{label}[：:]\s*([-+]?[0-9.]+(?:%|亿)?)", compact)
        if m:
            fields[label] = m.group(1)
    return fields


def _dx_parse_sector_strength(text: str) -> list:
    sectors = []
    seen = set()
    compact = _dx_compact(text)
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{2,16})\((-?[0-9.]+)\)\s+([0-9]+)涨停", compact):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        sectors.append({"name": name, "score": m.group(2), "limit_up_count": int(m.group(3))})
        if len(sectors) >= 80:
            break
    return sectors


def collect_duanxianxia(trade_date: str) -> dict:
    """短线侠: 情绪/封板率/连板高度。Playwright 浏览器采集。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"trade_date": trade_date, "status": "unavailable", "error": "playwright not installed"}

    result: dict = {
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
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            base_url, pool_text = _dx_goto_first_working(page, "/web/pool")
            result["working_base_url"] = base_url
            result["page_text_preview"] = pool_text[:6000]
            result["pool_stats"] = _dx_parse_pool_stats(pool_text)
            result["tables"].update({f"pool_{k}": v for k, v in _dx_extract_tables(page).items()})
            for k, v in _dx_extract_tables(page, max_tables=10, max_rows=8).items():
                result[k] = v

            _, qxlive_text = _dx_goto_first_working(page, "/web/qxlive")
            result["qxlive_text_preview"] = qxlive_text[:6000]
            result["sentiment_fields"] = _dx_parse_qxlive_fields(qxlive_text)
            result["sentiment"] = result["sentiment_fields"]
            result["sector_strength"] = _dx_parse_sector_strength(qxlive_text)

            qx_tables = _dx_extract_tables(page, max_tables=20, max_rows=120)
            result["tables"].update({f"qxlive_{k}": v for k, v in qx_tables.items()})
            for table in qx_tables.values():
                rows = table.get("data", [])
                if rows and len(rows[0]) >= 3:
                    result["sectors"] = rows[:40]
                    break
            result["status"] = "ok"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.warning("duanxianxia 采集失败: %s", e)
        finally:
            browser.close()

    result["trade_date"] = trade_date
    result["scraped_at"] = datetime.now().isoformat()
    result["source"] = "duanxianxia.com"
    return result


# ============================================================
# main
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantX 多源采集器")
    parser.add_argument(
        "--source", required=True,
        choices=["ths_hot", "zhangtingke", "pywencai", "duanxianxia"],
    )
    parser.add_argument("--date", required=True, help="交易日 YYYYMMDD")
    parser.add_argument("--tickflow-data", default="./data", help="TickFlow data/ 目录")
    args = parser.parse_args()

    tickflow_data = Path(args.tickflow_data)
    collectors = {
        "ths_hot": collect_ths_hot,
        "zhangtingke": collect_zhangtingke,
        "pywencai": collect_pywencai,
        "duanxianxia": collect_duanxianxia,
    }
    fn = collectors[args.source]
    try:
        result = fn(args.date)
    except Exception as e:
        logger.error("%s 采集跳过: %s", args.source, e)
        sys.exit(2)
    path = _write_json(result, args.source, args.date, tickflow_data)
    logger.info("[OK] %s → %s", args.source, path)


if __name__ == "__main__":
    main()
