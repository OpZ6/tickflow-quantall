"""Akshare scraper: futures, sector fund flow, industry rankings."""
import json
import os
from datetime import datetime

import akshare as ak
import pandas as pd
import requests

OUTPUT_DIR = None
TRADE_DATE = None


def _future_signal(pct: float | None, oi_delta: int) -> str:
    """Interpret price + position change into signal text."""
    if pct is None:
        return "-"
    up = pct > 0
    inc = oi_delta > 0
    if up and inc:
        return "多头增仓，看涨"
    elif up and not inc:
        return "多头减仓，谨慎看多"
    elif not up and inc:
        return "空头增仓，看空"
    elif not up and not inc:
        return "空头减仓，谨慎看空"
    return "震荡观望"


def fetch_futures() -> dict:
    symbols = {
        "IF0": "IF(沪深300)", "IC0": "IC(中证500)",
        "IH0": "IH(上证50)", "IM0": "IM(中证1000)",
    }
    result = {}
    for sym, name in symbols.items():
        try:
            df = ak.futures_main_sina(symbol=sym)
            if df is None or len(df) == 0:
                result[sym] = None
                continue
            row = df.iloc[-1]
            close = float(row["收盘价"])
            oi = int(row.get("持仓量", 0))
            prev_oi = int(df.iloc[-2]["持仓量"]) if len(df) >= 2 else oi
            oi_delta = oi - prev_oi
            pct = None
            if len(df) >= 2:
                prev_close = float(df.iloc[-2]["收盘价"])
                if prev_close > 0:
                    pct = round((close - prev_close) / prev_close * 100, 2)
            signal = _future_signal(pct, oi_delta)
            result[sym] = {
                "name": name, "close": close,
                "pct_chg": pct,
                "open_interest": oi,
                "oi_delta": oi_delta,
                "signal": signal,
            }
            print(f"  [akshare] {name}: {close} ({pct:+.2f}%) OI={oi} Δ={oi_delta:+d} → {signal}")
        except Exception as e:
            print(f"  [akshare] futures {sym}: {e}")
            result[sym] = None
    return result


def _fetch_s4_once() -> list:
    """Single attempt at Eastmoney s:4 API."""
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(_k, None)
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f62", "po": "0", "pz": "200", "pn": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "ut": "8dec03ba335b81bf4ebdf7b29ec27d15",
        "fs": "m:90+s:4",
        "fields": "f12,f14,f3,f6,f62,f184",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://data.eastmoney.com/bkzj/hy.html",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    r = s.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = data.get("data", {}).get("diff") or []
    records = []
    for item in items:
        name = str(item.get("f14") or "")
        pct = float(item.get("f3") or 0)
        net_yi = round((float(item.get("f62") or 0)) / 1e8, 2)
        records.append({
            "name": name,
            "pct_chg": pct,
            "net_inflow_yi": net_yi,
            "amount_yi": round((float(item.get("f6") or 0)) / 1e8, 2),
            "net_inflow_pct": float(item.get("f184") or 0),
            "code": str(item.get("f12") or ""),
        })
    records.sort(key=lambda r: r["net_inflow_yi"], reverse=True)
    return records


def fetch_sector_fund_flow() -> list:
    """Fetch sector fund flow from Eastmoney s:4 API (new Shenwan, ~128 industries).

    Retries up to 3 times with exponential backoff before falling back to the
    less accurate akshare t:2 endpoint.
    """
    import time as _time
    backoffs = [3, 10, 25]
    for attempt, wait_s in enumerate(backoffs, 1):
        try:
            if attempt > 1:
                print(f"  [akshare] s:4 retry {attempt}/{len(backoffs)+1} after {wait_s}s...")
                _time.sleep(wait_s)
            records = _fetch_s4_once()
            print(f"  [akshare] Fund flow: {len(records)} sectors (s:4)")
            return records
        except Exception as e:
            if attempt <= len(backoffs):
                print(f"  [akshare] s:4 attempt {attempt} failed: {e}")
            else:
                print(f"  [akshare] fund_flow s:4 failed after {len(backoffs)} retries: {e}, falling back to akshare t:2")
    # Fallback: akshare stock_fund_flow_industry (old t:2 endpoint)
    try:
        df = ak.stock_fund_flow_industry()
        if df is not None and len(df) > 0:
            records = []
            for _, row in df.iterrows():
                records.append({
                    "name": str(row.iloc[1]),
                    "pct_chg": float(row.iloc[3]),
                    "net_inflow_yi": float(row.iloc[6]),
                })
            records.sort(key=lambda r: r["net_inflow_yi"], reverse=True)
            print(f"  [akshare] Fund flow: {len(records)} sectors (t:2 fallback)")
            return records
    except Exception as e:
        print(f"  [akshare] fund_flow t:2 fallback: {e}")
    return []


def fetch_industry_boards() -> dict:
    try:
        df = ak.stock_board_industry_summary_ths()
        if df is None or len(df) == 0:
            return {"top": [], "bottom": []}
        df = df.sort_values("涨跌幅", ascending=False)
        records = []
        for _, row in df.head(20).iterrows():
            records.append({
                "name": str(row["板块"]), "pct_chg": float(row["涨跌幅"]),
                "total_mv": float(row.get("总市值", 0)) if "总市值" in row.index else 0,
                "up_count": int(row.get("上涨家数", 0)) if "上涨家数" in row.index else 0,
                "down_count": int(row.get("下跌家数", 0)) if "下跌家数" in row.index else 0,
            })
        bottom = []
        for _, row in df.tail(10).iloc[::-1].iterrows():
            bottom.append({
                "name": str(row["板块"]), "pct_chg": float(row["涨跌幅"]),
            })
        print(f"  [akshare] Industries: {len(df)} boards, top={records[0]['name'] if records else 'none'}")
        return {"top": records, "bottom": bottom}
    except Exception as e:
        print(f"  [akshare] industry_boards: {e}")
        return {"top": [], "bottom": []}


def run(trade_date: str = TRADE_DATE, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n{'='*50}\n[akshare] Scraping {trade_date}...")
    result = {
        "trade_date": trade_date, "scraped_at": datetime.now().isoformat(),
        "futures": fetch_futures(),
        "sector_fund_flow": fetch_sector_fund_flow(),
        "industry_boards": fetch_industry_boards(),
    }
    path = os.path.join(output_dir, "akshare.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[akshare] Saved -> {path}")
    return path


if __name__ == "__main__":
    run()
