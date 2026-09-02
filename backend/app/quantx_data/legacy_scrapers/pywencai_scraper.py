"""Limit-up / MA scraper (uses akshare em APIs, fallback to pywencai)."""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import requests

try:
    import akshare as ak
    HAS_AK = True
except ImportError:
    HAS_AK = False

try:
    import pywencai as _pywencai
    HAS_PYWENCAI = True
except ImportError:
    HAS_PYWENCAI = False

OUTPUT_DIR = None
TRADE_DATE = None
TOTAL_A_STOCKS = 5300
NEW_HIGH_SCHEMA_VERSION = 2
MARKET_METRIC_SEMANTICS_VERSION = 2

_IWENCAI_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

# D8 degraded fallback: eastmoney F10 concept rows that are style/index/trading
# attributes rather than investable themes. Kept alongside _is_attribute_theme
# in new_high_cluster so fallback concepts stay comparable to iwencai output.
_FALLBACK_ATTRIBUTE_TAGS = frozenset(
    {
        "深成500", "中证500", "上证380", "上证50", "沪深300", "中证1000", "创业板综",
        "融资融券", "转融券标的", "沪股通", "深股通", "富时罗素", "标准普尔", "MSCI中国",
        "百元股", "低价股", "中盘股", "小盘股", "大盘股", "中盘成长", "小盘成长", "大盘成长",
        "高市净率", "高市盈率", "低市盈率", "AH股", "含H股", "股权激励", "员工持股",
        "昨日涨停", "昨日连板", "昨日涨停_含一字", "昨日连板_含一字",
        "最近多板", "昨日打板", "首板", "连板", "强势股", "活跃股",
        "次新股", "新股与次新股", "题材股", "宁组合", "茅指数",
        "北上资金", "北向资金", "回购", "增持", "民企", "中字头",
    }
)
_FALLBACK_ATTRIBUTE_RE = re.compile(
    r"(?:\d{4}(?:中报|年报|一季报|三季报)?预增|预增$|质押|解禁|减持|重仓|做市|近期新高)"
)


def _float_or_none(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _stock_code(value) -> str:
    text = str(value or "").strip().split(".", 1)[0]
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _find_column(columns, *, exact=(), contains=(), excludes=()):
    names = [str(column) for column in columns]
    for candidate in exact:
        if candidate in names:
            return candidate
    for name in names:
        if any(token in name for token in excludes):
            continue
        if any(token in name for token in contains):
            return name
    return None


def _split_concepts(value) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return list(
        dict.fromkeys(
            item.strip()
            for item in re.split(r"[;；,，、|｜\n\r]+", str(value))
            if item and item.strip() and item.strip().lower() != "nan"
        )
    )


def _new_high_query(trade_date: str) -> str:
    date_value = datetime.strptime(str(trade_date), "%Y%m%d")
    return f"{date_value.year}年{date_value.month}月{date_value.day}日百日新高 所属概念板块"


def fetch_limit_up_details() -> dict:
    print("  [pywencai] Querying limit-up via akshare...")
    for attempt in range(3):
        try:
            df = ak.stock_zt_pool_em(date=TRADE_DATE)
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
            break  # success, exit retry loop
        except Exception as e:
            print(f"  [pywencai] akshare limit-up attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                time.sleep([5, 15][attempt])
            else:
                print("  [pywencai] akshare limit-up failed after 3 attempts, returning empty")
                return {"count": 0, "stocks": [], "ladder": {}, "themes": []}

    ladder = {}
    for r in records:
        t = max(r["limit_times"], 1)
        ladder.setdefault(t, []).append(r["name"])

    themes = {}
    for r in records:
        if r["reason"] and r["reason"] != "nan":
            themes[r["reason"]] = themes.get(r["reason"], 0) + 1
    theme_list = sorted(themes.items(), key=lambda x: x[1], reverse=True)[:15]

    max_board = max(ladder.keys()) if ladder else 0
    print(f"  [pywencai] Limit-up: {len(records)} stocks, max {max_board}连板")
    return {
        "count": len(records), "stocks": records,
        "ladder": {str(k): v for k, v in sorted(ladder.items(), reverse=True)},
        "themes": [{"name": k, "count": v} for k, v in theme_list],
    }


def fetch_broken_board() -> dict:
    print("  [pywencai] Querying broken board via akshare...")
    for attempt in range(3):
        try:
            df = ak.stock_zt_pool_zbgc_em(date=TRADE_DATE)
            records = []
            for _, row in df.iterrows():
                records.append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                })
            break  # success
        except Exception as e:
            print(f"  [pywencai] akshare broken board attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                time.sleep([5, 15][attempt])
            else:
                print("  [pywencai] akshare broken board failed after 3 attempts, returning empty")
                return {"count": 0, "stocks": []}
    return {"count": len(records), "stocks": records}


def fetch_yesterday_limit_up_today() -> dict:
    print("  [pywencai] Querying yesterday limit-up via akshare...")
    last_error = ""
    for attempt in range(3):
        try:
            df = ak.stock_zt_pool_previous_em(date=TRADE_DATE)
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
                "metric_semantics_version": MARKET_METRIC_SEMANTICS_VERSION,
                "as_of": TRADE_DATE,
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
        except Exception as e:
            last_error = str(e)
            print(f"  [pywencai] akshare yesterday perf attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                time.sleep([5, 15][attempt])
    return {
        "schema_version": 2,
        "metric_semantics_version": MARKET_METRIC_SEMANTICS_VERSION,
        "as_of": TRADE_DATE,
        "status": "unavailable",
        "count": None,
        "advance_sample_count": 0,
        "premium_sample_count": 0,
        "continued_count": 0,
        "premium_rate": None,
        "advance_rate": None,
        "yesterday_lianban_premium": None,
        "stocks": [],
        "error": last_error,
    }


def fetch_limit_down_details() -> dict:
    print("  [pywencai] Querying limit-down via akshare...")
    last_error = ""
    for attempt in range(3):
        try:
            df = ak.stock_zt_pool_dtgc_em(date=TRADE_DATE)
            records = []
            for _, row in df.iterrows():
                records.append({
                    "code": _stock_code(row.get("代码")),
                    "name": str(row.get("名称") or "").strip(),
                    "pct_chg": _float_or_none(row.get("涨跌幅")),
                })
            return {
                "schema_version": 1,
                "as_of": TRADE_DATE,
                "status": "ok",
                "count": len(records),
                "stocks": records,
            }
        except Exception as e:
            last_error = str(e)
            print(f"  [pywencai] akshare limit-down attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                time.sleep([5, 15][attempt])
    return {
        "schema_version": 1,
        "as_of": TRADE_DATE,
        "status": "unavailable",
        "count": None,
        "stocks": [],
        "error": last_error,
    }


def fetch_ma_ratios() -> dict:
    """MA ratios skipped — too expensive via Tushare; expose an explicit gap."""
    print("  [pywencai] MA ratios skipped (expensive, use daily up_ratio as proxy)")
    return {"skipped": True, "note": "MA ratios not computed (requires 5300+ individual stock queries)"}


def fetch_new_high_100d() -> dict:
    """D8 百日新高 — query iwencai for stocks hitting 100-day highs.

    One full-market query returns both the stock set and every stock's concepts.
    A homepage warm-up session plus spaced retries mitigates iwencai's
    intermittent anti-bot gate (403/401 captcha). If every attempt is blocked,
    the pipeline falls back to the tushare kline computation below.
    """
    query = _new_high_query(TRADE_DATE)
    if not HAS_PYWENCAI:
        print("  [pywencai] 百日新高 skipped (pywencai not installed)")
        return {
            "schema_version": NEW_HIGH_SCHEMA_VERSION,
            "as_of": TRADE_DATE,
            "status": "unavailable",
            "query": query,
            "count": None,
            "stocks": [],
            "error": "pywencai package not installed",
        }
    print("  [pywencai] Querying 百日新高 via iwencai...")
    cookie = _warm_iwencai_session() if type(_pywencai).__module__.startswith("pywencai") else ""
    last_error = ""
    for attempt in range(3):
        try:
            kwargs = {"query": query, "loop": True}
            if cookie:
                kwargs["cookie"] = cookie
            df = _pywencai.get(**kwargs)
            if df is None:
                print(f"  [pywencai] 百日新高 attempt {attempt+1} returned None")
                if attempt < 2:
                    time.sleep([8, 25][attempt])
                    if type(_pywencai).__module__.startswith("pywencai"):
                        cookie = cookie or _warm_iwencai_session()
                    continue
                last_error = "pywencai returned None after 3 attempts"
                break
            code_col = _find_column(df.columns, exact=("股票代码", "code"), contains=("股票代码",))
            name_col = _find_column(df.columns, exact=("股票简称", "name"), contains=("股票简称",))
            pct_col = _find_column(df.columns, exact=("最新涨跌幅", "涨跌幅"), contains=("最新涨跌幅", "涨跌幅"))
            concept_col = _find_column(
                df.columns,
                exact=("所属概念", "所属概念板块"),
                contains=("所属概念", "概念板块"),
                excludes=("数量",),
            )
            missing_columns = [
                label
                for label, column in (("code", code_col), ("name", name_col), ("concepts", concept_col))
                if column is None
            ]
            if missing_columns:
                raise ValueError(f"new-high query missing columns: {', '.join(missing_columns)}")
            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    "code": _stock_code(row.get(code_col)) if code_col else "",
                    "name": str(row.get(name_col) or "").strip() if name_col else "",
                    "pct_chg": _float_or_none(row.get(pct_col)) if pct_col else None,
                    "concepts": _split_concepts(row.get(concept_col)) if concept_col else [],
                })
            print(f"  [pywencai] 百日新高: {len(stocks)} stocks (iwencai)")
            return {
                "schema_version": NEW_HIGH_SCHEMA_VERSION,
                "as_of": TRADE_DATE,
                "status": "ok",
                "query": query,
                "count": len(stocks),
                "stocks": stocks,
            }
        except Exception as e:
            last_error = str(e)
            print(f"  [pywencai] 百日新高 attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep([8, 25][attempt])
                if type(_pywencai).__module__.startswith("pywencai"):
                    cookie = cookie or _warm_iwencai_session()
                continue
    return {
        "schema_version": NEW_HIGH_SCHEMA_VERSION,
        "as_of": TRADE_DATE,
        "status": "unavailable",
        "query": query,
        "count": None,
        "stocks": [],
        "error": last_error,
    }


def _warm_iwencai_session() -> str:
    """Visit the iwencai homepage so the follow-up data call is treated as a browser session.

    Returns a cookie string (possibly empty) to pass into pywencai.get().
    """
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": _IWENCAI_UA})
        session.get("http://www.iwencai.com/", timeout=15)
        return "; ".join(f"{key}={value}" for key, value in session.cookies.items())
    except Exception as exc:
        print(f"  [pywencai] iwencai session warm-up failed: {exc}")
        return ""


def _f10_boardtype_concepts(code: str) -> list[str]:
    """Eastmoney F10 board-type concept rows for one stock.

    Returns only concept-type boards (BOARD_TYPE is null); industry and region
    boards are excluded so the fallback stays comparable to iwencai's
    所属概念板块 column.
    """
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": "1",
        "pageSize": "500",
        "sortTypes": "-1",
        "sortColumns": "BOARD_RANK",
        "source": "HSF10",
        "client": "PC",
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _IWENCAI_UA, "Referer": "https://emweb.securities.eastmoney.com/"},
            timeout=10,
        )
        rows = ((resp.json().get("result") or {}).get("data")) or []
    except Exception:
        return []
    concepts: list[str] = []
    for row in rows:
        board_type = row.get("BOARD_TYPE")
        if board_type not in (None, ""):
            continue
        name = str(row.get("BOARD_NAME") or "").strip()
        if not name or name in _FALLBACK_ATTRIBUTE_TAGS or _FALLBACK_ATTRIBUTE_RE.search(name):
            continue
        if name not in concepts:
            concepts.append(name)
    return concepts


def _attach_f10_concepts(stocks: list[dict]) -> None:
    """Attach eastmoney F10 concept boards to fallback new-high stocks in place."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_f10_boardtype_concepts, str(item.get("code") or "")): item
            for item in stocks
        }
        for future, item in futures.items():
            try:
                item["concepts"] = future.result(timeout=15)
            except Exception:
                item["concepts"] = []


def _compute_new_high_from_tushare() -> dict:
    """D8 degraded fallback: compute 100-day highs from tushare daily klines.

    Runs only when the iwencai query is blocked. One `pro.daily(trade_date=...)`
    call returns the full market for a single day, so ~110 calls build a
    per-stock close series over the trailing window. A stock is a 100-day high
    when today's close >= the highest close of the previous 100 trading days
    (at least 21 bars of history). Concepts are attached per stock from the
    eastmoney F10 board-type API. Returns the same v2 payload shape as the
    iwencai path so deterministic theme clustering receives the same fields.
    """
    try:
        from . import tushare_scraper
        pro = tushare_scraper.pro or tushare_scraper._client()
    except Exception as exc:
        return {
            "status": "unavailable", "scope": "tushare_fallback",
            "stocks": [], "count": 0, "error": f"tushare fallback init failed: {exc}",
        }

    try:
        end = datetime.strptime(TRADE_DATE, "%Y%m%d")
        start = (end - timedelta(days=220)).strftime("%Y%m%d")
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=TRADE_DATE)
        if cal is None or cal.empty:
            return {"status": "unavailable", "scope": "tushare_fallback", "stocks": [], "count": 0, "error": "tushare trade calendar empty"}
        open_days = sorted(str(row.cal_date) for row in cal.itertuples(index=False) if int(row.is_open) == 1)
        days = open_days[-110:]

        closes: dict[str, list[float]] = {}
        pcts: dict[str, float] = {}
        for index, day in enumerate(days):
            frame = pro.daily(trade_date=day)
            if frame is None or frame.empty:
                continue
            for row in frame.itertuples(index=False):
                code = _stock_code(row.ts_code)
                if not code:
                    continue
                closes.setdefault(code, []).append(float(row.close))
                if index == len(days) - 1:
                    pcts[code] = _float_or_none(row.pct_chg)
            if index % 20 == 19:
                time.sleep(0.3)

        names: dict[str, str] = {}
        try:
            basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
            if basic is not None and not basic.empty:
                for row in basic.itertuples(index=False):
                    code = _stock_code(row.ts_code)
                    if code:
                        names[code] = str(row.name)
        except Exception:
            pass

        stocks: list[dict] = []
        for code, series in closes.items():
            if len(series) < 21:
                continue
            today_close = series[-1]
            prior = series[:-1][-100:]
            if today_close < max(prior):
                continue
            stocks.append({
                "code": code,
                "name": names.get(code, ""),
                "pct_chg": pcts.get(code),
                "concepts": [],
            })
        stocks.sort(key=lambda item: (-(item.get("pct_chg") or 0), item.get("code") or ""))

        if not stocks:
            return {
                "status": "unavailable", "scope": "tushare_fallback",
                "stocks": [], "count": 0,
                "error": "no 100-day-high stocks found in tushare window",
            }

        _attach_f10_concepts(stocks)
        print(f"  [pywencai] 百日新高 fallback: {len(stocks)} stocks (tushare klines + eastmoney F10)")
        return {
            "schema_version": NEW_HIGH_SCHEMA_VERSION,
            "as_of": TRADE_DATE,
            "status": "ok",
            "query": _new_high_query(TRADE_DATE),
            "source": "tushare_fallback",
            "count": len(stocks),
            "stocks": stocks,
        }
    except Exception as exc:
        return {
            "status": "unavailable", "scope": "tushare_fallback",
            "stocks": [], "count": 0, "error": f"{type(exc).__name__}: {exc}",
        }


def run(
    trade_date: str = TRADE_DATE,
    output_dir: str = OUTPUT_DIR,
    *,
    allow_slow_new_high_fallback: bool = False,
) -> str:
    global TRADE_DATE, OUTPUT_DIR
    TRADE_DATE = trade_date
    OUTPUT_DIR = output_dir
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[pywencai] Scraping {trade_date} (via akshare em APIs)...")

    result = {
        "trade_date": trade_date, "scraped_at": datetime.now().isoformat(),
        "limit_up": fetch_limit_up_details(),
        "broken_board": fetch_broken_board(),
        "limit_down": fetch_limit_down_details(),
        "yesterday_perf": fetch_yesterday_limit_up_today(),
        "new_high_100d": fetch_new_high_100d(),
        "ma_ratios": fetch_ma_ratios(),
    }

    # This network-heavy fallback is opt-in: running it in the critical source
    # process can discard yesterday_perf when the process timeout is exhausted.
    if (
        allow_slow_new_high_fallback
        and result["new_high_100d"].get("status") != "ok"
    ):
        print("  [pywencai] 百日新高 iwencai unavailable, trying tushare fallback...")
        fallback = _compute_new_high_from_tushare()
        if fallback.get("status") == "ok":
            result["new_high_100d"] = fallback
        else:
            result["new_high_100d"]["fallback_error"] = fallback.get("error")

    zt = result["limit_up"]["count"]
    zb = result["broken_board"]["count"]
    total_attempt = zt + zb
    result["broken_rate"] = round(zb / total_attempt * 100, 1) if total_attempt > 0 else 0
    result["seal_rate"] = round(zt / total_attempt * 100, 1) if total_attempt > 0 else 100

    path = os.path.join(output_dir, "pywencai.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[pywencai] Saved -> {path} (zt={zt}, zb={zb}, seal={result['seal_rate']}%)")
    return path


if __name__ == "__main__":
    run()
