"""Deterministic, evidence-first risk summary for the QuantX daily view."""

from __future__ import annotations

from datetime import date
from typing import Any


SENTIMENT_INDICES = (
    ("880699.SH", "龙头情绪", 4.7, -4.0),
    ("880880.SH", "题材效应", 8.3, -5.9),
    ("880823.SH", "资金情绪", 3.9, -4.0),
    ("880003.SH", "赚钱效应", 4.7, -4.0),
)
MARKET_INDICES = (
    "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
    "000300.SH", "000016.SH", "399303.SZ", "399905.SZ",
)
ALL_A_INDEX = "000985.SH"


def index_ma10(rows: list[dict[str, Any]], day: date) -> dict[str, float | None] | None:
    """Use ten completed trading bars ending exactly on the requested day."""
    history = sorted(
        (row for row in rows if row.get("date") is not None and row["date"] <= day),
        key=lambda row: row["date"],
    )
    if len(history) < 10 or history[-1]["date"] != day:
        return None
    closes = [row.get("close") for row in history[-10:]]
    if any(value is None or float(value) <= 0 for value in closes):
        return None
    close = float(closes[-1])
    ma10 = sum(float(value) for value in closes) / 10
    previous = history[-2].get("close")
    return {
        "close": round(close, 4),
        "ma10": round(ma10, 4),
        "deviation_pct": round((close / ma10 - 1) * 100, 2),
        "change_pct": round((close / float(previous) - 1) * 100, 2)
        if previous else None,
    }


def _metric(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


def _dimension(
    key: str, title: str, tone: str | None, status: str,
    metrics: list[dict[str, str]], explanation: str, details: list[dict[str, str]],
    source: str,
) -> dict[str, Any]:
    return {
        "key": key, "title": title, "tone": tone, "status": status,
        "metrics": metrics[:3], "explanation": explanation,
        "details": details, "source": source,
    }


def build_risk_radar(
    day: date, *, breadth: dict[str, Any] | None,
    state: dict[str, Any] | None, liquidity: list[dict[str, Any]],
    ladder: list[dict[str, Any]], indices: dict[str, dict[str, float | None]],
) -> dict[str, Any]:
    """Classify current risk; prior-day change appears in text, never in color."""
    dimensions: list[dict[str, Any]] = []
    down_ratio = None
    limit_down = state.get("limit_down_count") if state else None
    if breadth and breadth.get("total_count"):
        down_ratio = 100 * breadth["down_count"] / breadth["total_count"]
    if down_ratio is None or limit_down is None:
        dimensions.append(_dimension("breadth", "广度与尾部", None, "数据待同步", [], "", [], "market_breadth_daily · market_state_daily"))
    else:
        tone = "red" if down_ratio >= 80 or limit_down >= 50 or (down_ratio >= 70 and limit_down >= 30) else "amber" if down_ratio >= 55 or limit_down >= 15 else "green"
        dimensions.append(_dimension(
            "breadth", "广度与尾部", tone,
            {"red": "普跌与尾部风险", "amber": "广度需关注", "green": "广度正常"}[tone],
            [_metric("下跌占比", f"{down_ratio:.1f}%"), _metric("跌停", f"{limit_down} 家")],
            f"下跌 {breadth['down_count']} 家、跌停 {limit_down} 家；以已发布广度事实为准。",
            [_metric("上涨／下跌／平盘", f"{breadth['up_count']} / {breadth['down_count']} / {breadth['flat_count']}")],
            "market_breadth_daily · market_state_daily",
        ))

    premium = state.get("premium_rate_pct") if state else None
    advance = state.get("advance_rate_pct") if state else None
    seal = state.get("seal_rate_pct") if state else None
    if premium is None or advance is None:
        dimensions.append(_dimension("relay", "接力与封板", None, "数据待同步", [], "", [], "market_state_daily"))
    else:
        tone = "red" if premium <= -1 and advance < 20 else "amber" if premium < 0 or advance < 25 or (seal is not None and seal < 75) else "green"
        dimensions.append(_dimension(
            "relay", "接力与封板", tone,
            {"red": "接力亏损", "amber": "接力需关注", "green": "接力正常"}[tone],
            [_metric("昨涨停溢价", f"{premium:+.2f}%"), _metric("晋级率", f"{advance:.1f}%"), *([_metric("封板率", f"{seal:.1f}%")] if seal is not None else [])],
            "昨日涨停池的后续收益与晋级结果共同判断接力，封板质量作为辅助证据。",
            [], "market_state_daily · pywencai",
        ))

    board_counts = {int(row["board_height"]): int(row["count"]) for row in ladder}
    if not ladder:
        dimensions.append(_dimension("ladder", "连板结构", None, "数据待同步", [], "", [], "limit_ladder_daily · limit_event_daily"))
    else:
        maximum = max(board_counts)
        first, second = board_counts.get(1, 0), board_counts.get(2, 0)
        gaps = [level for level in range(2, maximum) if board_counts.get(level, 0) == 0]
        tone = "red" if maximum <= 2 and second <= 1 else "amber" if second < 5 or gaps else "green"
        dimensions.append(_dimension(
            "ladder", "连板结构", tone,
            {"red": "梯队明显收缩", "amber": "梯队有缺口", "green": "梯队正常"}[tone],
            [_metric("最高板", f"{maximum} 板"), _metric("首板", f"{first} 家"), _metric("二板", f"{second} 家")],
            f"二板 {second} 家；" + (f"缺少 {', '.join(map(str, gaps))} 板梯队。" if gaps else "二板以上梯队连续。"),
            [_metric(f"{level} 板", f"{board_counts.get(level, 0)} 家") for level in range(1, maximum + 1)],
            "limit_ladder_daily · limit_event_daily",
        ))

    ordered_liquidity = sorted((row for row in liquidity if row.get("trade_date") and row.get("total_amount_yi") is not None), key=lambda row: row["trade_date"])
    current = next((row for row in ordered_liquidity if row["trade_date"] == day), None)
    previous = [row["total_amount_yi"] for row in ordered_liquidity if row["trade_date"] < day][-5:]
    ratio = 100 * current["total_amount_yi"] / (sum(previous) / len(previous)) if current and len(previous) == 5 and sum(previous) > 0 else None
    if ratio is None:
        dimensions.append(_dimension("liquidity", "量能与承接", None, "数据待同步", [], "", [], "market_liquidity_daily"))
    else:
        tone = "red" if ratio < 70 and down_ratio is not None and down_ratio >= 70 else "amber" if ratio < 90 or ratio > 140 else "green"
        concentration = current.get("top5pct_amount_ratio_pct")
        daily_change = (current["total_amount_yi"] / previous[-1] - 1) * 100 if previous[-1] > 0 else None
        metrics = [_metric("相对前 5 日", f"{ratio:.1f}%")]
        if daily_change is not None and abs(daily_change) >= 10:
            metrics.append(_metric("较前日", f"{daily_change:+.1f}%"))
        if concentration is not None:
            metrics.append(_metric("前 5% 成交占比", f"{concentration:.1f}%"))
        dimensions.append(_dimension(
            "liquidity", "量能与承接", tone,
            {"red": "缩量与普跌共振", "amber": "量能波动需关注", "green": "量能正常"}[tone],
            metrics,
            "成交额与此前五个已发布交易日的均额比较；成交集中度用于观察承接范围。",
            [_metric("当日成交", f"{current['total_amount_yi']:,.0f} 亿"), _metric("前 5 日均额", f"{sum(previous) / 5:,.0f} 亿")],
            "market_liquidity_daily",
        ))

    ordinary = [indices[code] for code in MARKET_INDICES if code in indices]
    sentiment = []
    for code, name, high, low in SENTIMENT_INDICES:
        row = indices.get(code)
        if row:
            deviation = row["deviation_pct"]
            zone = "高位" if deviation >= high else "低位" if deviation <= low else "站上 MA10" if deviation > 0 else "低于 MA10"
            sentiment.append({"code": code, "name": name, "deviation_pct": deviation, "zone": zone})
    all_a = indices.get(ALL_A_INDEX)
    if len(ordinary) < 4 or all_a is None:
        dimensions.append(_dimension("trend", "指数趋势与背离", None, "数据待同步", [], "", [], "kline_index_daily"))
    else:
        above = sum(row["deviation_pct"] > 0 for row in ordinary)
        change = all_a["change_pct"]
        tone = "red" if above == 0 and len(sentiment) == 4 and all(row["deviation_pct"] <= 0 for row in sentiment) and change is not None and change <= -3 else "amber" if above <= 2 or (len(sentiment) == 4 and sum(row["deviation_pct"] > 0 for row in sentiment) <= 1) else "green"
        dimensions.append(_dimension(
            "trend", "指数趋势与背离", tone,
            {"red": "趋势同步走弱", "amber": "趋势尚待修复", "green": "趋势正常"}[tone],
            [_metric("普通指数站上 MA10", f"{above} / {len(ordinary)}"), *([_metric("四情绪站上 MA10", f"{sum(row['deviation_pct'] > 0 for row in sentiment)} / 4")] if len(sentiment) == 4 else []), *([_metric("全 A 当日", f"{change:+.2f}%")] if change is not None else [])],
            "普通指数与通达信四情绪分别观察，不合成一个情绪分。" if len(sentiment) == 4 else "普通指数已计算；通达信四情绪日线尚待同步。",
            [_metric(row["name"], f"{row['deviation_pct']:+.2f}% · {row['zone']}") for row in sentiment],
            "kline_index_daily · 通达信四情绪 MA10",
        ))

    by_key = {row["key"]: row for row in dimensions}
    if by_key["breadth"]["tone"] == "red" and by_key["relay"]["tone"] == "red":
        headline = "普跌与接力亏损共振"
    elif by_key["breadth"]["tone"] == "green" and by_key["relay"]["tone"] == "green" and by_key["liquidity"]["tone"] == "amber":
        headline = "广度与接力正常，量能仍需观察"
    elif any(row["tone"] == "red" for row in dimensions):
        headline = "市场出现显著风险信号"
    elif any(row["tone"] == "amber" for row in dimensions):
        headline = "市场局部条件需要关注"
    else:
        headline = "五维风险信号正常"
    missing = [row["title"] for row in dimensions if row["tone"] is None]
    if len(sentiment) < len(SENTIMENT_INDICES) and "指数趋势与背离" not in missing:
        missing.append("通达信四情绪")
    if missing:
        headline = "风险画像数据待同步"
    return {
        "headline": headline,
        "summary": "；".join(f"{row['title']}：{row['status']}" for row in dimensions if row["tone"] != "green" and row["tone"] is not None) or "五个维度均未触发风险条件",
        "dimensions": dimensions,
        "missing": missing,
        "algorithm_version": "risk-radar-v1",
    }
