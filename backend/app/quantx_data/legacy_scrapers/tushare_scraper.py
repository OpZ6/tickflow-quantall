"""Deterministic Tushare adapter for TickFlow's data-only pipeline.

This module contains only numeric market collection. It keeps the client lazy
so importing optional adapters never fails when a token is not configured.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

pro = None
_DAILY_FRAME_CACHE: dict[str, pd.DataFrame] = {}

INDEXES = {
    "000985.CSI": "鍏ˋ鎸囨暟", "000001.SH": "涓婅瘉鎸囨暟", "000300.SH": "娌繁300",
    "000016.SH": "涓婅瘉50", "000905.SH": "涓瘉500", "000852.SH": "涓瘉1000",
    "399006.SZ": "鍒涗笟鏉挎寚", "000688.SH": "绉戝垱50",
}


def _client():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured")
    import tushare as ts

    return ts.pro_api(token, timeout=30)


def _frame_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _daily_frame(trade_date: str) -> pd.DataFrame:
    cached = _DAILY_FRAME_CACHE.get(trade_date)
    if cached is not None:
        return cached.copy()
    frame = pro.daily(trade_date=trade_date)  # type: ignore[union-attr]
    cached = frame if frame is not None else pd.DataFrame()
    _DAILY_FRAME_CACHE[trade_date] = cached.copy()
    return cached.copy()


def _classify_board(code: str) -> str:
    code = str(code).split(".", 1)[0].zfill(6)
    if code.startswith("688"):
        return "科创板"
    if code.startswith("30"):
        return "创业板"
    if code[0] in {"0", "6"}:
        return "主板"
    return "北交所"


def _fetch_indexes(trade_date: str) -> dict[str, dict[str, Any]]:
    end = datetime.strptime(trade_date, "%Y%m%d")
    start = (end - timedelta(days=120)).strftime("%Y%m%d")
    result: dict[str, dict[str, Any]] = {}
    for code, name in INDEXES.items():
        try:
            frame = pro.index_daily(ts_code=code, start_date=start, end_date=trade_date)  # type: ignore[union-attr]
        except Exception:
            continue
        if frame is None or frame.empty:
            continue
        frame = frame.sort_values("trade_date").reset_index(drop=True)
        close = pd.to_numeric(frame["close"], errors="coerce")
        result[code] = {
            "name": name,
            "close": float(close.iloc[-1]),
            "pct_chg": float(frame.get("pct_chg", pd.Series([0])).iloc[-1] or 0),
            "vol": int(float(frame.get("vol", pd.Series([0])).iloc[-1] or 0)),
            "amount": float(frame.get("amount", pd.Series([0])).iloc[-1] or 0),
            "ma5": round(float(close.tail(5).mean()), 2),
            "ma10": round(float(close.tail(10).mean()), 2),
            "ma20": round(float(close.tail(20).mean()), 2),
        }
    return result


def _fetch_daily_market(trade_date: str, frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    pct = pd.to_numeric(frame.get("pct_chg"), errors="coerce").fillna(0)
    amount = pd.to_numeric(frame.get("amount"), errors="coerce").fillna(0)
    volume = pd.to_numeric(frame.get("vol"), errors="coerce").fillna(0)
    total = len(frame)
    up = int((pct > 0).sum())
    down = int((pct < 0).sum())
    sorted_amount = amount.sort_values(ascending=False)
    amount_sum = float(amount.sum())
    board_stats: dict[str, dict[str, int]] = {}
    if "ts_code" in frame.columns:
        boards = frame["ts_code"].map(_classify_board)
        for board in ("主板", "创业板", "科创板", "北交所"):
            mask = boards == board
            if int(mask.sum()):
                board_stats[board] = {
                    "up": int((pct[mask] > 0).sum()),
                    "down": int((pct[mask] < 0).sum()),
                    "total": int(mask.sum()),
                }
    return {
        "trade_date": trade_date,
        "total_stocks": total,
        "up_count": up,
        "down_count": down,
        "flat_count": total - up - down,
        "up_ratio": round(up / total * 100, 1) if total else 0,
        "red_avg_pct": round(float(pct[pct > 0].mean()) if up else 0, 2),
        "green_avg_pct": round(float(pct[pct < 0].mean()) if down else 0, 2),
        "total_amount_yi": round(amount_sum / 100000, 2),
        "total_vol": int(volume.sum()),
        "top20_amount_ratio": round(float(sorted_amount.head(20).sum()) / amount_sum * 100, 2) if amount_sum else 0,
        "top5_amount_ratio": round(float(sorted_amount.head(max(1, int(total * 0.05))).sum()) / amount_sum * 100, 2) if amount_sum else 0,
        "board_stats": board_stats,
    }


def _fetch_ad_history(trade_date: str, days: int = 60) -> dict[str, Any]:
    end = datetime.strptime(trade_date, "%Y%m%d")
    records: list[dict[str, Any]] = []
    cursor = end
    while len(records) < days:
        if cursor.weekday() < 5:
            date = cursor.strftime("%Y%m%d")
            try:
                frame = _daily_frame(date)
            except Exception:
                frame = pd.DataFrame()
            if not frame.empty:
                pct = pd.to_numeric(frame.get("pct_chg"), errors="coerce").fillna(0)
                amount = pd.to_numeric(frame.get("amount"), errors="coerce").fillna(0)
                records.append({
                    "date": date,
                    "up": int((pct > 0).sum()),
                    "down": int((pct < 0).sum()),
                    "flat": int((pct == 0).sum()),
                    "total_amount_yi": float(amount.sum()) / 100000,
                })
        cursor -= timedelta(days=1)
        if (end - cursor).days > days * 5:
            break
    records.sort(key=lambda row: row["date"])
    records = records[-days:]
    running = 0
    for index, row in enumerate(records):
        row["up_minus_down"] = row["up"] - row["down"]
        running += row["up_minus_down"]
        row["ad_line"] = running
        window = records[max(0, index - 4):index + 1]
        row["ma5_up"] = round(sum(item["up"] for item in window) / len(window), 1)
        row["ma5_down"] = round(sum(item["down"] for item in window) / len(window), 1)
    return {"history": records, "latest": records[-1] if records else {}}


def _fetch_margin(trade_date: str, days: int = 30) -> dict[str, Any]:
    end = datetime.strptime(trade_date, "%Y%m%d")
    start = (end - timedelta(days=90)).strftime("%Y%m%d")
    try:
        frame = pro.margin(start_date=start, end_date=trade_date)  # type: ignore[union-attr]
    except Exception:
        return {}
    if frame is None or frame.empty or "rzye" not in frame.columns:
        return {}
    frame["rzye_f"] = pd.to_numeric(frame["rzye"], errors="coerce").fillna(0) / 1e8
    grouped = frame.groupby("trade_date", as_index=False)["rzye_f"].sum().sort_values("trade_date").tail(days)
    records = []
    previous = None
    for row in grouped.to_dict(orient="records"):
        value = float(row["rzye_f"])
        records.append({
            "date": str(row["trade_date"]),
            "rzye_yi": round(value, 2),
            "rz_net_buy_yi": round(value - previous, 2) if previous is not None else 0.0,
        })
        previous = value
    return {"history": records, "latest": records[-1] if records else {}}


def _fetch_kline(trade_date: str, days: int = 60) -> list[dict[str, Any]]:
    end = datetime.strptime(trade_date, "%Y%m%d")
    start = (end - timedelta(days=days + 60)).strftime("%Y%m%d")
    try:
        frame = pro.index_daily(ts_code="000985.CSI", start_date=start, end_date=trade_date)  # type: ignore[union-attr]
    except Exception:
        return []
    if frame is None or frame.empty:
        return []
    frame = frame.sort_values("trade_date").tail(days).copy()
    close = pd.to_numeric(frame["close"], errors="coerce")
    records = []
    for index, (_, row) in enumerate(frame.iterrows()):
        records.append({
            "date": str(row.get("trade_date", "")),
            "open": float(row.get("open") or 0), "high": float(row.get("high") or 0),
            "low": float(row.get("low") or 0), "close": float(row.get("close") or 0),
            "vol": float(row.get("vol") or 0), "amount": float(row.get("amount") or 0),
            "ma5": float(close.iloc[max(0, index - 4):index + 1].mean()),
            "ma10": float(close.iloc[max(0, index - 9):index + 1].mean()),
            "ma20": float(close.iloc[max(0, index - 19):index + 1].mean()),
        })
    return records


def _fetch_calendar(trade_date: str) -> dict[str, Any]:
    base = datetime.strptime(trade_date, "%Y%m%d")
    try:
        frame = pro.trade_cal(  # type: ignore[union-attr]
            exchange="", start_date=(base - timedelta(days=7)).strftime("%Y%m%d"),
            end_date=(base + timedelta(days=30)).strftime("%Y%m%d"),
        )
    except Exception:
        return {}
    records = _frame_records(frame)
    current = next((row for row in records if str(row.get("cal_date")) == trade_date), {})
    future = [row for row in records if str(row.get("cal_date", "")) > trade_date and int(row.get("is_open") or 0) == 1]
    return {"current": current, "next_open": future[0] if future else {}, "records": records}


def _fetch_suspended(trade_date: str) -> dict[str, Any]:
    try:
        frame = pro.suspend_d(trade_date=trade_date, suspend_type="S")  # type: ignore[union-attr]
    except Exception:
        return {"count": 0, "stocks": []}
    stocks = []
    for row in _frame_records(frame):
        code = str(row.get("ts_code") or "").split(".", 1)[0]
        stocks.append({
            "code": code,
            "name": "",
            "suspend_type": row.get("suspend_type", ""),
            "suspend_timing": row.get("suspend_timing", ""),
        })
    return {"count": len(stocks), "stocks": stocks}


def run(trade_date: str, output_dir: str) -> str:
    global pro
    pro = _client()
    _DAILY_FRAME_CACHE.clear()
    frame = _daily_frame(trade_date)
    payload = {
        "trade_date": trade_date,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
        "status": "ok" if not frame.empty else "empty",
        "source": "tushare_pro",
        "indexes": _fetch_indexes(trade_date),
        "daily_market": _fetch_daily_market(trade_date, frame),
        "daily": _frame_records(frame),
        "advance_decline": _fetch_ad_history(trade_date),
        "margin": _fetch_margin(trade_date),
        "kline_history": _fetch_kline(trade_date),
        "trade_calendar": _fetch_calendar(trade_date),
        "suspended_stocks": _fetch_suspended(trade_date),
    }
    path = Path(output_dir) / "tushare.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
