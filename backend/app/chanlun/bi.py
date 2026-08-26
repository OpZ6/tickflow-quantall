"""Bi (stroke) detection using czsc engine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from czsc import CZSC, Freq, RawBar


MIN_BI_LEN = 7


def _naive_utc(ts: float) -> datetime:
    """czsc 约定 dt 为 tz-naive 且按 UTC 语义存储。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def _epoch(dt: datetime) -> int:
    """把 naive-UTC datetime 还原为 unix 秒 (与 _naive_utc 严格互逆)。"""
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _to_czsc_bars(candles: list[dict[str, Any]], symbol: str = "tickflow"):
    bars = []
    for c in candles:
        dt = _naive_utc(c["time"])
        bar = RawBar(
            symbol=symbol,
            id=c["time"],
            dt=dt,
            freq=Freq.D,
            open=c["open"],
            close=c["close"],
            high=c["high"],
            low=c["low"],
            vol=c.get("volume", 0),
            amount=0,
        )
        bars.append(bar)
    return bars


def _extract_bi(candles: list[dict], min_bi_len: int = MIN_BI_LEN) -> tuple[list[dict], list[dict]]:
    bars = _to_czsc_bars(candles)
    czsc_obj = CZSC(bars, max_bi_num=10000, min_bi_len=min_bi_len)
    time_to_idx = {c["time"]: i for i, c in enumerate(candles)}
    strokes = []
    points = []
    for b in czsc_obj.bi_list:
        fx_a = b.fx_a
        is_up = b.direction.name == "Up"
        s_t = _epoch(fx_a.dt)
        e_t = _epoch(b.fx_b.dt)
        s_val = fx_a.low if is_up else fx_a.high
        e_val = b.fx_b.high if is_up else b.fx_b.low
        ptype = "bottom" if is_up else "top"
        val = fx_a.low if ptype == "bottom" else fx_a.high
        points.append({"time": s_t, "type": ptype, "value": val})
        strokes.append({
            "start_time": s_t, "start_price": s_val,
            "end_time": e_t, "end_price": e_val,
            "direction": "up" if is_up else "down",
            "start_index": time_to_idx.get(s_t),
            "end_index": time_to_idx.get(e_t),
            "is_sure": True, "confirm_index": time_to_idx.get(e_t),
        })
    if czsc_obj.bi_list:
        last_fx = czsc_obj.bi_list[-1].fx_b
        is_up = "up" in str(czsc_obj.bi_list[-1].direction).lower()
        ptype = "top" if is_up else "bottom"
        val = last_fx.high if ptype == "top" else last_fx.low
        t = _epoch(last_fx.dt)
        points.append({"time": t, "type": ptype, "value": val})
    if czsc_obj.ubi and czsc_obj.ubi.get("fx_a"):
        ubi = czsc_obj.ubi
        ubi_is_up = ubi["direction"].name == "Up"
        s_t = _epoch(ubi["fx_a"].dt)
        s_val = ubi["fx_a"].fx
        e_t = int(candles[-1]["time"])
        e_val = ubi["high"] if ubi_is_up else ubi["low"]
        strokes.append({
            "start_time": s_t, "start_price": s_val,
            "end_time": e_t, "end_price": e_val,
            "direction": "up" if ubi_is_up else "down",
            "start_index": time_to_idx.get(s_t),
            "end_index": time_to_idx.get(e_t),
            "is_sure": False, "confirm_index": None,
        })
    return strokes, points