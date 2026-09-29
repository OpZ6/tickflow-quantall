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
MARKET_INDEX_NAMES = {
    "000001.SH": "上证指数", "399001.SZ": "深证成指",
    "399006.SZ": "创业板指", "000688.SH": "科创50",
    "000300.SH": "沪深300", "000016.SH": "上证50",
    "399303.SZ": "国证2000", "399905.SZ": "中证500",
}


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


def _metric(
    label: str, value: str, tone: str | None = None, judgement: str | None = None,
) -> dict[str, str | None]:
    return {"label": label, "value": value, "tone": tone, "judgement": judgement}


def _dimension(
    key: str, title: str, tone: str | None, status: str,
    metrics: list[dict[str, str | None]], explanation: str,
    details: list[dict[str, str | None]], source: str,
    series: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key, "title": title, "tone": tone, "status": status,
        "metrics": metrics, "explanation": explanation,
        "details": details, "source": source, "series": series or [],
    }


def build_risk_radar(
    day: date, *, breadth: dict[str, Any] | None,
    state: dict[str, Any] | None, liquidity: list[dict[str, Any]],
    ladder: list[dict[str, Any]], indices: dict[str, dict[str, float | None]],
    state_history: list[dict[str, Any]] | None = None,
    broken_board_count: int | None = None,
) -> dict[str, Any]:
    """Classify current risk; prior-day change appears in text, never in color."""
    dimensions: list[dict[str, Any]] = []
    down_ratio = None
    limit_down = state.get("limit_down_count") if state else None
    tail_ratio = breadth.get("down_gt7_ratio_pct") if breadth else None
    if breadth and breadth.get("total_count"):
        down_ratio = 100 * breadth["down_count"] / breadth["total_count"]
    if down_ratio is None or limit_down is None:
        dimensions.append(_dimension("breadth", "广度与尾部", None, "数据待同步", [], "", [], "market_breadth_daily · market_state_daily"))
    else:
        tone = "red" if down_ratio >= 80 or limit_down >= 50 or (down_ratio >= 70 and limit_down >= 30) or (tail_ratio is not None and tail_ratio >= 5) else "amber" if down_ratio >= 55 or limit_down >= 15 or (tail_ratio is not None and tail_ratio >= 2) else "green"
        dimensions.append(_dimension(
            "breadth", "广度与尾部", tone,
            {"red": "普跌与尾部风险", "amber": "广度需关注", "green": "广度正常"}[tone],
            [
                _metric("上涨", f"{breadth['up_count']} 家"),
                _metric("下跌", f"{breadth['down_count']} 家"),
                _metric(
                    "下跌占比", f"{down_ratio:.1f}%",
                    "red" if down_ratio >= 80 else "amber" if down_ratio >= 55 else None,
                    f"下跌占比 {down_ratio:.1f}% 达到 80%" if down_ratio >= 80 else
                    f"下跌占比 {down_ratio:.1f}% 达到 55%" if down_ratio >= 55 else None,
                ),
                _metric(
                    "跌停", f"{limit_down} 家",
                    "red" if limit_down >= 50 else "amber" if limit_down >= 15 else None,
                    f"跌停 {limit_down} 家达到 50 家" if limit_down >= 50 else
                    f"跌停 {limit_down} 家达到 15 家" if limit_down >= 15 else None,
                ),
                *([_metric("平均涨幅", f"{breadth['mean_up_pct']:+.2f}%")] if breadth.get("mean_up_pct") is not None else []),
                *([_metric("平均跌幅", f"{breadth['mean_down_pct']:+.2f}%")] if breadth.get("mean_down_pct") is not None else []),
                *([_metric(
                    "跌超 7% 占比", f"{tail_ratio:.2f}%",
                    "red" if tail_ratio >= 5 else "amber" if tail_ratio >= 2 else None,
                    f"跌幅超过 7% 的个股占 {tail_ratio:.2f}%，达到 5%" if tail_ratio >= 5 else
                    f"跌幅超过 7% 的个股占 {tail_ratio:.2f}%，达到 2%" if tail_ratio >= 2 else None,
                )] if tail_ratio is not None else []),
            ],
            f"下跌 {breadth['down_count']} 家、跌停 {limit_down} 家；以已发布广度事实为准。",
            [_metric("样本总数", f"{breadth['total_count']} 家")],
            "market_breadth_daily · market_state_daily",
        ))

    board_counts = {int(row["board_height"]): int(row["count"]) for row in ladder}
    maximum = max(board_counts) if board_counts else None
    missing_levels = [level for level in (3, 4) if maximum is not None and maximum >= 4 and board_counts.get(level, 0) == 0]
    premium = state.get("premium_rate_pct") if state else None
    advance = state.get("advance_rate_pct") if state else None
    seal = state.get("seal_rate_pct") if state else None
    previous_state = sorted(
        (row for row in state_history or [] if row.get("trade_date") and row["trade_date"] < day),
        key=lambda row: row["trade_date"],
    )[-5:]
    premium_baseline = [row["premium_rate_pct"] for row in previous_state if row.get("premium_rate_pct") is not None]
    advance_baseline = [row["advance_rate_pct"] for row in previous_state if row.get("advance_rate_pct") is not None]
    if premium is None or advance is None or maximum is None:
        dimensions.append(_dimension("relay", "接力与封板", None, "数据待同步", [], "", [], "market_state_daily"))
    else:
        tone = "red" if premium <= -1 and advance < 20 else "amber" if premium < 0 or advance < 25 or (seal is not None and seal < 75) or maximum < 4 or missing_levels else "green"
        dimensions.append(_dimension(
            "relay", "接力与封板", tone,
            {"red": "接力亏损", "amber": "接力或连板需关注", "green": "接力正常"}[tone],
            [
                _metric(
                    "昨涨停溢价", f"{premium:+.2f}%",
                    "red" if premium <= -1 else "amber" if premium < 0 else "green",
                    f"昨涨停溢价 {premium:+.2f}% 不高于 -1%" if premium <= -1 else
                    f"昨涨停溢价 {premium:+.2f}% 为负" if premium < 0 else None,
                ),
                _metric(
                    "晋级率", f"{advance:.1f}%",
                    "red" if advance < 20 else "amber" if advance < 25 else "green",
                    f"晋级率 {advance:.1f}% 低于 20%" if advance < 20 else
                    f"晋级率 {advance:.1f}% 低于 25%" if advance < 25 else None,
                ),
                *([_metric(
                    "封板率", f"{seal:.1f}%",
                    "red" if seal < 65 else "amber" if seal < 75 else "green",
                    f"封板率 {seal:.1f}% 低于 65%" if seal < 65 else
                    f"封板率 {seal:.1f}% 低于 75%" if seal < 75 else None,
                )] if seal is not None else []),
                *([_metric("涨停", f"{state['limit_up_count']} 家")] if state.get("limit_up_count") is not None else []),
                *([_metric("炸板", f"{broken_board_count} 家")] if broken_board_count is not None else []),
                _metric(
                    "最高板", f"{maximum} 板", "amber" if maximum < 4 else "green",
                    f"最高板 {maximum} 板，未达到 4 板" if maximum < 4 else None,
                ),
                *[_metric(
                    f"{level} 板", f"{board_counts.get(level, 0)} 家",
                    "amber" if level in missing_levels else None,
                    f"{level} 板缺档" if level in missing_levels else None,
                ) for level in (3, 4)],
            ],
            "昨日涨停池收益、晋级、封板，以及最高板是否达到 4 板和 3/4 板是否缺档共同判断。",
            [
                *([_metric("前 5 日溢价均值", f"{sum(premium_baseline) / 5:+.2f}%")] if len(premium_baseline) == 5 else []),
                *([_metric("前 5 日晋级率均值", f"{sum(advance_baseline) / 5:.1f}%")] if len(advance_baseline) == 5 else []),
            ], "market_state_daily · limit_ladder_daily · limit_event_daily · pywencai",
        ))

    ordered_liquidity = sorted((row for row in liquidity if row.get("trade_date") and row.get("total_amount_yi") is not None), key=lambda row: row["trade_date"])
    current = next((row for row in ordered_liquidity if row["trade_date"] == day), None)
    previous = [row["total_amount_yi"] for row in ordered_liquidity if row["trade_date"] < day][-5:]
    previous20 = [row["total_amount_yi"] for row in ordered_liquidity if row["trade_date"] < day][-20:]
    ratio = 100 * current["total_amount_yi"] / (sum(previous) / len(previous)) if current and len(previous) == 5 and sum(previous) > 0 else None
    daily_change = None
    if ratio is None:
        dimensions.append(_dimension("liquidity", "量能与承接", None, "数据待同步", [], "", [], "market_liquidity_daily"))
    else:
        tone = "red" if ratio < 70 and down_ratio is not None and down_ratio >= 70 else "amber" if ratio < 90 or ratio > 140 else "green"
        concentration = current.get("top5pct_amount_ratio_pct")
        daily_change = (current["total_amount_yi"] / previous[-1] - 1) * 100 if previous[-1] > 0 else None
        ratio_tone = "red" if ratio < 80 or ratio > 150 else "amber" if ratio < 90 or ratio > 140 else "green"
        metrics = [
            _metric("当日成交", f"{current['total_amount_yi']:,.0f} 亿"),
            _metric(
                "相对前 5 日", f"{ratio:.1f}%", ratio_tone,
                f"成交额为前 5 日均额的 {ratio:.1f}%，低于 80%" if ratio < 80 else
                f"成交额为前 5 日均额的 {ratio:.1f}%，高于 150%" if ratio > 150 else
                f"成交额为前 5 日均额的 {ratio:.1f}%，低于 90%" if ratio < 90 else
                f"成交额为前 5 日均额的 {ratio:.1f}%，高于 140%" if ratio > 140 else None,
            ),
            _metric("前 5 日均额", f"{sum(previous) / 5:,.0f} 亿"),
        ]
        if daily_change is not None:
            metrics.append(_metric(
                "较前日", f"{daily_change:+.1f}%",
                "red" if abs(daily_change) >= 15 else "amber" if abs(daily_change) >= 10 else "green",
                f"成交额较前日 {daily_change:+.1f}%，波动达到 15%" if abs(daily_change) >= 15 else
                f"成交额较前日 {daily_change:+.1f}%，波动达到 10%" if abs(daily_change) >= 10 else None,
            ))
        if concentration is not None:
            metrics.append(_metric("前 5% 成交占比", f"{concentration:.1f}%"))
        if current.get("top20_amount_ratio_pct") is not None:
            metrics.append(_metric("前 20 名成交占比", f"{current['top20_amount_ratio_pct']:.1f}%"))
        if len(previous20) == 20 and sum(previous20) > 0:
            metrics.append(_metric("相对前 20 日", f"{100 * current['total_amount_yi'] / (sum(previous20) / 20):.1f}%"))
        dimensions.append(_dimension(
            "liquidity", "量能与承接", tone,
            {"red": "缩量与普跌共振", "amber": "量能波动需关注", "green": "量能正常"}[tone],
            metrics,
            "成交额与此前五个已发布交易日的均额比较；成交集中度用于观察承接范围。",
            [*([_metric("前 20 日均额", f"{sum(previous20) / 20:,.0f} 亿")] if len(previous20) == 20 else [])],
            "market_liquidity_daily",
        ))

    ordinary = [indices[code] for code in MARKET_INDICES if code in indices]
    series = []
    for code in MARKET_INDICES:
        row = indices.get(code)
        if row:
            deviation = row["deviation_pct"]
            series.append({
                "kind": "ordinary", "code": code, "name": MARKET_INDEX_NAMES[code],
                "deviation_pct": deviation, "change_pct": row.get("change_pct"),
                "close": row.get("close"), "ma10": row.get("ma10"),
                "zone": "站上 MA10" if deviation > 0 else "低于 MA10",
                "tone": "green" if deviation > 0 else "amber",
            })
    sentiment = []
    for code, name, high, low in SENTIMENT_INDICES:
        row = indices.get(code)
        if row:
            deviation = row["deviation_pct"]
            zone = "高位" if deviation >= high else "低位" if deviation <= low else "站上 MA10" if deviation > 0 else "低于 MA10"
            sentiment.append({
                "kind": "sentiment", "code": code, "name": name,
                "deviation_pct": deviation, "change_pct": row.get("change_pct"),
                "close": row.get("close"), "ma10": row.get("ma10"),
                "zone": zone, "tone": "red" if deviation >= high or deviation <= low else "green" if deviation > 0 else "amber",
                "judgement": f"{name}偏离 MA10 {deviation:+.2f}%，达到高位阈值 {high:+.1f}%" if deviation >= high else
                f"{name}偏离 MA10 {deviation:+.2f}%，达到低位阈值 {low:.1f}%" if deviation <= low else
                f"{name}偏离 MA10 {deviation:+.2f}%，仍在均线下方" if deviation <= 0 else None,
            })
    all_a = indices.get(ALL_A_INDEX)
    above = None
    sentiment_above = sum(row["deviation_pct"] > 0 for row in sentiment)
    if len(ordinary) < 4 or all_a is None:
        dimensions.append(_dimension("trend", "指数与趋势", None, "数据待同步", [], "", [], "kline_index_daily"))
    else:
        above = sum(row["deviation_pct"] > 0 for row in ordinary)
        change = all_a["change_pct"]
        tone = "red" if above == 0 and len(sentiment) == 4 and sentiment_above == 0 and change is not None and change <= -3 else "amber" if above <= 2 or (len(sentiment) == 4 and sentiment_above <= 1) else "green"
        dimensions.append(_dimension(
            "trend", "指数与趋势", tone,
            {"red": "趋势同步走弱", "amber": "趋势尚待修复", "green": "趋势正常"}[tone],
            [
                _metric(
                    "普通指数站上 MA10", f"{above} / {len(ordinary)}",
                    "red" if above == 0 else "amber" if above <= 2 else "green",
                    f"普通指数 {above}/{len(ordinary)} 站上 MA10，全部低于均线" if above == 0 else
                    f"普通指数仅 {above}/{len(ordinary)} 站上 MA10" if above <= 2 else None,
                ),
                *([_metric(
                    "四情绪站上 MA10", f"{sentiment_above} / 4",
                    "red" if sentiment_above == 0 else "amber" if sentiment_above == 1 else "green",
                    f"四情绪 {sentiment_above}/4 站上 MA10，全部低于均线" if sentiment_above == 0 else
                    "四情绪仅 1/4 站上 MA10" if sentiment_above == 1 else None,
                )] if len(sentiment) == 4 else []),
                *([_metric(
                    "全 A 当日", f"{change:+.2f}%",
                    "red" if change <= -3 else "amber" if change < 0 else "green",
                    f"全 A 当日 {change:+.2f}%，跌幅达到 3%" if change <= -3 else
                    f"全 A 当日 {change:+.2f}%，收跌" if change < 0 else None,
                )] if change is not None else []),
                *[_metric(row["name"], f"{row['deviation_pct']:+.2f}%", row["tone"], row["judgement"]) for row in sentiment],
            ],
            "普通指数与通达信四情绪分别观察，不合成一个情绪分。" if len(sentiment) == 4 else "普通指数已计算；通达信四情绪日线尚待同步。",
            [
                _metric("四情绪高位信号", f"{sum(row['zone'] == '高位' for row in sentiment)} 条"),
                _metric("四情绪低位信号", f"{sum(row['zone'] == '低位' for row in sentiment)} 条"),
            ] if len(sentiment) == 4 else [],
            "kline_index_daily · 通达信四情绪 MA10",
            series=series + sentiment,
        ))

    for row in dimensions:
        warnings = [item for item in row["metrics"] if item["tone"] in ("amber", "red")]
        if row["tone"] != "amber" or len(warnings) != 1 or warnings[0]["tone"] != "amber":
            continue
        mild = (
            row["key"] == "breadth" and down_ratio < 70 and limit_down < 20
            and (tail_ratio is None or tail_ratio < 3)
        ) or (
            row["key"] == "relay" and maximum >= 4 and not missing_levels
            and premium >= -0.5 and advance >= 22 and (seal is None or seal >= 70)
        ) or (
            row["key"] == "liquidity" and 85 <= ratio <= 145
        )
        if mild:
            row["tone"] = "green"
            row["status"] = "基本正常"

    by_key = {row["key"]: row for row in dimensions}
    if by_key["breadth"]["tone"] == "red" and by_key["relay"]["tone"] == "red":
        headline = "普跌与接力亏损共振"
    elif by_key["breadth"]["tone"] == "green" and by_key["relay"]["tone"] == "green" and by_key["liquidity"]["tone"] == "amber":
        prior = previous_state[-1] if previous_state else {}
        improved_breadth = prior.get("up_ratio_pct") is not None and breadth is not None and prior["up_ratio_pct"] < 100 * breadth["up_count"] / breadth["total_count"]
        improved_relay = prior.get("premium_rate_pct") is not None and prior["premium_rate_pct"] < 0 <= premium
        headline = "广度与接力修复，量能继续收缩" if improved_breadth and improved_relay and daily_change is not None and daily_change <= -10 else "广度与接力正常，量能仍需观察"
    elif any(row["tone"] == "red" for row in dimensions):
        headline = "市场出现显著风险信号"
    elif any(row["tone"] == "amber" for row in dimensions):
        headline = "市场局部条件需要关注"
    elif any(metric["tone"] in ("red", "amber") for row in dimensions for metric in row["metrics"]):
        headline = "四维整体正常，局部信号需留意"
    else:
        headline = "四维风险信号正常"
    missing = [row["title"] for row in dimensions if row["tone"] is None]
    if len(sentiment) < len(SENTIMENT_INDICES) and "指数与趋势" not in missing:
        missing.append("通达信四情绪")
    if missing:
        headline = "风险画像数据待同步"
    issue_groups = [
        f"{row['title']}：" + "、".join(
            metric["judgement"] for metric in row["metrics"]
            if metric["tone"] in ("red", "amber") and metric["judgement"]
        )
        for row in dimensions
        if any(metric["tone"] in ("red", "amber") for metric in row["metrics"])
    ]
    if by_key["breadth"]["tone"] == "red" and by_key["relay"]["tone"] == "red":
        counter_evidence = f"最高连板仍有 {max(board_counts) if board_counts else 0} 板" + (f"、封板率 {seal:.1f}%" if seal is not None else "") + "；局部强势尚未覆盖普跌与接力亏损。"
    elif by_key["breadth"]["tone"] == "green" and by_key["relay"]["tone"] == "green" and any(row["tone"] == "amber" for row in dimensions):
        prior = previous_state[-1] if previous_state else {}
        if prior.get("advance_rate_pct") is not None and prior.get("premium_rate_pct") is not None:
            counter_evidence = f"晋级率由前日 {prior['advance_rate_pct']:.1f}% 升至 {advance:.1f}%，溢价由 {prior['premium_rate_pct']:+.2f}% 转为 {premium:+.2f}%；短线改善仍需量能和趋势确认。"
        else:
            counter_evidence = "广度与接力处于正常区间；量能和指数趋势仍需分别核对。"
    elif any(row["tone"] == "red" for row in dimensions):
        counter_evidence = "其他维度的正常信号说明风险范围仍有差异，需按各维证据判断。"
    elif any(row["tone"] == "amber" for row in dimensions):
        normal = [row["title"] for row in dimensions if row["tone"] == "green"]
        counter_evidence = "、".join(normal) + "仍在正常区间；其他维度的关注信号需按各自证据核对。" if normal else ""
    else:
        counter_evidence = ""
    return {
        "headline": headline,
        "summary": "风险判断：" + "；".join(issue_groups) + "。" if issue_groups else "四维条件未触发风险阈值。" if not missing else "已发布市场事实不足，暂无法生成完整风险总览。",
        "counter_evidence": counter_evidence,
        "coverage": {"complete": max(0, len(dimensions) - len(missing)), "total": len(dimensions)},
        "dimensions": dimensions,
        "missing": missing,
        "algorithm_version": "risk-radar-v3",
    }
