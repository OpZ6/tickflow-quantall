"""Build a self-contained data snapshot for the stock-pool HTML prototype."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import polars as pl


SOURCE_ORDER = ["突破", "涨停", "异动", "趋势", "分歧", "炸板修复", "趋势回踩", "股性活跃", "人气中温"]
NEW_SOURCES = {"突破", "涨停", "异动", "炸板修复", "趋势回踩"}
STAGE_PRIORITY = [
    ("涨停强化", "涨停"),
    ("高位分歧", "分歧"),
    ("异动加速", "异动"),
    ("突破启动", "突破"),
    ("企稳修复", "炸板修复"),
    ("回踩整理", "趋势回踩"),
    ("趋势延续", "趋势"),
    ("活跃观察", "股性活跃"),
    ("人气观察", "人气中温"),
]
SOURCE_EXPIRY = {
    "突破": "10日",
    "涨停": "当日",
    "异动": "3日",
    "趋势": "日更",
    "分歧": "3日",
    "炸板修复": "3日",
    "趋势回踩": "3日",
    "股性活跃": "动态",
    "人气中温": "日更",
}

# Presentation taxonomy only: preserve the original membership and recall rules.
INDUSTRY_THEMES = {"人工智能", "AI", "中国AI", "机器人概念", "芯片概念", "新能源汽车", "军工", "军民融合", "新能源", "数字经济", "碳中和", "高端装备", "物联网", "消费电子概念", "光伏概念", "绿色电力", "文化传媒概念", "医疗器械概念", "旅游概念", "互联网金融"}
BACKGROUND_THEME = re.compile(r"(?:大开发|振兴|一带一路|自贸|新区|一体化|大湾区|示范区|共同富裕|统一大市场|特色小镇|海峡两岸|人民币贬值|俄乌冲突|参股|创投|独角兽|中字头|预增|摘帽|次新股|土地流转|新型城镇化|新型工业化|超级品牌|大基金持股|出海50|新质50|果指数|兵装重组|股权转让)")
BACKGROUND_EXACT = {"华为概念", "比亚迪概念", "阿里巴巴概念", "腾讯概念", "百度概念", "小米概念", "特斯拉概念", "苹果概念", "宁德时代概念", "富士康概念", "中芯国际概念", "长安汽车概念", "英伟达概念", "PC", "50"}
THEME_PARENTS = {
    "PCB概念": "电子产业链", "共封装光学(CPO)": "算力基础设施", "液冷服务器": "算力基础设施", "铜缆高速连接": "算力基础设施", "数据中心(AIDC)": "算力基础设施", "东数西算(算力)": "算力基础设施", "算力租赁": "算力基础设施", "光纤概念": "算力基础设施",
    "存储芯片": "芯片概念", "先进封装": "芯片概念", "光刻机": "芯片概念", "光刻胶": "芯片概念", "汽车芯片": "芯片概念", "第三代半导体": "芯片概念", "MCU芯片": "芯片概念", "玻璃基板": "芯片概念",
    "人形机器人": "机器人概念", "减速器": "机器人概念", "机器视觉": "机器人概念", "传感器": "机器人概念", "工业母机": "高端装备",
    "固态电池": "电池产业链", "锂电池概念": "电池产业链", "钠离子电池": "电池产业链", "PET铜箔": "电池产业链", "盐湖提锂": "电池产业链", "动力电池回收": "电池产业链",
    "商业航天": "军工", "卫星导航": "军工", "航空发动机": "军工", "国产航母": "军工", "军工信息化": "军工", "无人机": "低空经济", "飞行汽车(eVTOL)": "低空经济",
    "AI眼镜": "消费电子概念", "AI手机": "消费电子概念", "AI智能体": "人工智能", "AI应用": "人工智能", "AI视频": "人工智能", "多模态AI": "人工智能", "DeepSeek概念": "人工智能", "智谱AI": "人工智能",
    "汽车电子": "新能源汽车", "汽车热管理": "新能源汽车", "智能座舱": "新能源汽车", "无人驾驶": "新能源汽车", "车联网(车路协同)": "新能源汽车",
    "BC电池": "光伏概念", "TOPCON电池": "光伏概念", "HJT电池": "光伏概念", "钙钛矿电池": "光伏概念", "POE胶膜": "光伏概念",
}
INDUSTRY_DISPLAY_THEMES = {
    "元件": {"PCB概念", "MLCC概念"},
    "半导体": {"存储芯片", "先进封装", "汽车芯片", "MCU芯片", "第三代半导体", "光刻胶", "光刻机"},
    "通信设备": {"共封装光学(CPO)", "光纤概念", "铜缆高速连接", "5G", "6G概念"},
    "电池": {"固态电池", "锂电池概念", "钠离子电池", "动力电池回收"},
    "军工装备": {"商业航天", "国产航母", "航空发动机", "军工信息化", "无人机", "大飞机"},
}


def theme_level(label: str) -> str:
    if label in BACKGROUND_EXACT or BACKGROUND_THEME.search(label):
        return "background"
    return "industry" if label in INDUSTRY_THEMES else "theme"


def compare_snapshots(current: dict, previous: dict | None, previous_date: str | None) -> dict:
    """Compare identical recall contracts; missing history never implies a new member."""
    result = {"status": "unavailable", "previous_date": previous_date, "changes": {}, "exits": [], "counts": {}}
    if previous is None:
        result["reason"] = "缺少上一交易日同口径候选快照，新增／来源变化／阶段变化／退出暂不可比较。"
        return result
    if previous.get("trade_date") != previous_date:
        raise ValueError("Previous snapshot must be from the immediately preceding cached trading date")
    if any(current.get(field) != previous.get(field) for field in ("base_filters", "recall_rule_version", "source_status")):
        result["reason"] = "前后召回规则、基础过滤或来源覆盖状态不一致，暂不判定成员变化。"
        return result
    for field in ("source", "max_rank", "recall_rank_min", "recall_rank_max", "sources"):
        if (current.get("popularity_coverage") or {}).get(field) != (previous.get("popularity_coverage") or {}).get(field):
            result["reason"] = "前后人气榜覆盖区间不同，暂不判定成员变化。"
            return result
    old = {row["code"]: row for row in previous["rows"]}
    now = {row["code"]: row for row in current["rows"]}
    if len(old) != len(previous["rows"]) or len(now) != len(current["rows"]):
        raise ValueError("Duplicate candidate codes in comparison snapshots")
    counts = {"new": 0, "sources": 0, "stage": 0, "changed": 0, "exit": 0}
    for code, row in now.items():
        before = old.get(code)
        tags = []
        if before is None:
            tags.append("new")
        else:
            if set(row["sources"]) != set(before["sources"]):
                tags.append("sources")
            if row["stage"] != before["stage"]:
                tags.append("stage")
        if tags:
            counts["changed"] += 1
            for tag in tags:
                counts[tag] += 1
            result["changes"][code] = {"tags": tags, "previous_stage": before["stage"] if before else None, "added_sources": sorted(set(row["sources"]) - set(before["sources"] if before else [])), "removed_sources": sorted(set(before["sources"] if before else []) - set(row["sources"]))}
    result["exits"] = [{"code": code, "name": row["name"], "previous_stage": row["stage"], "sources": row["sources"]} for code, row in old.items() if code not in now]
    counts["exit"] = len(result["exits"])
    result.update(status="complete", reason="同口径快照逐股比较；退出仅代表今日未入选，不推断失守或卖出信号。", counts=counts)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-09-11")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output")
    parser.add_argument("--popularity-file")
    parser.add_argument("--html", help="Refresh the embedded snapshot in an existing prototype HTML")
    parser.add_argument("--previous-snapshot", help="Prior trading date snapshot with identical recall rules and coverage")
    parser.add_argument("--ledger-dir", help="Single-date inputs reconstructed using the existing study definitions")
    parser.add_argument("--anomaly-file", help="Dated Fuyao anomaly-analysis snapshot for source-backed topic grouping")
    parser.add_argument("--smnc-research-dir", help="QuantX Research data root for targeted approved-SMNC retrieval")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    compact_date = args.date.replace("-", "")
    trade_date = dt.datetime.strptime(compact_date, "%Y%m%d").date()
    data_dir = Path(args.data_dir)
    research_dir = data_dir / "research" / "stock-pools"
    output = Path(args.output) if args.output else research_dir / f"prototype-{compact_date}.json"

    instruments = pl.read_parquet(data_dir / "instruments" / "instruments.parquet")
    names = {row["symbol"]: row["name"] for row in instruments.to_dicts()}
    shares = {row["symbol"]: row for row in instruments.to_dicts()}
    if set(instruments["as_of"].cast(pl.String).to_list()) != {trade_date.isoformat()}:
        raise ValueError("Instrument share snapshot must match the requested trading date")
    quantx_dir = data_dir / "quantx" / compact_date
    tushare = json.loads((quantx_dir / "tushare.json").read_text(encoding="utf-8-sig"))
    quotes = {
        row["ts_code"]: {
            "price": float(row["close"]),
            "pct": float(row["pct_chg"]),
            "amount_yi": float(row["amount"]) / 100000.0,
            "market_cap_yi": float(row["close"]) * float(shares[row["ts_code"]]["total_shares"]) / 1e8 if row["ts_code"] in shares and shares[row["ts_code"]]["total_shares"] else None,
            "turnover_pct": float(row["vol"]) * 10000 / float(shares[row["ts_code"]]["float_shares"]) if row["ts_code"] in shares and shares[row["ts_code"]]["float_shares"] else None,
        }
        for row in tushare["daily"]
    }
    eligible = {
        symbol
        for symbol in quotes
        if symbol in names and "ST" not in (names.get(symbol) or "")
        and quotes[symbol]["market_cap_yi"] is not None
        and 20 <= quotes[symbol]["market_cap_yi"] <= 3000
        and quotes[symbol]["amount_yi"] >= 1
        and quotes[symbol]["turnover_pct"] is not None
        and quotes[symbol]["turnover_pct"] >= 1
    }

    ladder = json.loads((quantx_dir / "limit_ladder.json").read_text(encoding="utf-8-sig"))["ladder_by_height"]
    limit_details: dict[str, dict] = {}
    for height, members in ladder.items():
        for item in members:
            suffix = "SH" if item.get("market") == "sh" else ("BJ" if item.get("market") == "bj" else "SZ")
            limit_details[f"{item['code']}.{suffix}"] = {
                "height": int(height),
                "open_times": int(item.get("open_times") or 0),
                "turnover": item.get("turnover_pct"),
                "first_time": item.get("first_time") or "",
                "last_time": item.get("last_time") or "",
            }
    limit_symbols = set(limit_details)
    source_records: dict[str, dict[str, dict]] = defaultdict(dict)

    def scan(relative: str) -> pl.LazyFrame:
        return pl.scan_parquet((Path(args.ledger_dir) if args.ledger_dir else research_dir) / relative).filter(pl.col("date") == trade_date)

    def add(
        source: str,
        symbol: str,
        evidence: str,
        *,
        event_date: object = None,
        age: int = 0,
        anchor: float | None = None,
        details: dict | None = None,
    ) -> None:
        if symbol not in eligible:
            return
        source_records[source][symbol] = {
            "source": source,
            "evidence": evidence,
            "event_date": str(event_date or trade_date),
            "age": int(age or 0),
            "anchor": anchor,
            "details": details or {},
        }

    # 突破启动：当日首次越过60/100/250日高点，强势方向要求成交额不少于1亿元。
    breakout_fields = [
        "age_high60", "age_high100", "age_high250",
        "age_close60", "age_close100", "age_close250",
    ]
    breakout = scan("breakthrough/v1/daily-ledger.parquet").filter(
        pl.any_horizontal([pl.col(field) == 0 for field in breakout_fields])
    ).collect()
    for row in breakout.to_dicts():
        if row["symbol"] not in eligible or quotes[row["symbol"]]["amount_yi"] < 1:
            continue
        windows: list[str] = []
        for window in (60, 100, 250):
            if row[f"age_close{window}"] == 0:
                windows.append(f"收盘{window}日")
            elif row[f"age_high{window}"] == 0:
                windows.append(f"盘中{window}日")
        levels = [row.get(f"level_close{window}") for window in (250, 100, 60)]
        anchor = next((float(value) for value in levels if value is not None), float(row["close"]))
        add("突破", row["symbol"], "、".join(windows) + f"新高 · 量比{row['volume_ratio']:.2f}", anchor=anchor)

    # 涨停梯队：使用当日真实涨停梯队事实。
    for symbol, detail in limit_details.items():
        height = detail["height"]
        board = "首板" if height == 1 else f"{height}板"
        open_text = "未开板" if detail["open_times"] == 0 else f"开板{detail['open_times']}次"
        add("涨停", symbol, f"{board} · {open_text}", details=detail)

    # 异动加速：研究账本中当日新产生的宽异动事件。
    abnormal = scan("abnormal-surge/v1/daily-ledger.parquet").filter(
        (pl.col("sample_kind") == "surge") & (pl.col("process_age") == 0)
    ).collect()
    for row in abnormal.to_dicts():
        if row["symbol"] not in eligible or quotes[row["symbol"]]["amount_yi"] < 1:
            continue
        add("异动", row["symbol"], f"10日{row['return10_past'] * 100:+.1f}% · 30日{row['return30_past'] * 100:+.1f}%")

    # 趋势延续：成交额前200且维持多头结构。
    trend = scan("liquidity-trend/v1/daily-ledger.parquet").filter(
        (pl.col("amount_rank") <= 200)
        & (pl.col("close") > pl.col("ma20"))
        & (pl.col("ma20") > pl.col("ma60"))
        & (pl.col("ma20") > pl.col("ma20_10ago"))
        & (pl.col("drawdown20") >= -0.15)
    ).collect()
    for row in trend.to_dicts():
        add("趋势", row["symbol"], f"成交额第{row['amount_rank']} · 距20日高{row['drawdown20'] * 100:.1f}%", age=max(int(row["age_top200"] or 0), 0))

    # 分歧承接：首/二板后1—3日，未破锚点且上部收盘。
    location = (pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low"))
    divergence = scan("divergence/v1/daily-ledger.parquet").filter(
        pl.col("event_age").is_between(1, 3)
        & pl.col("board_height").is_between(1, 2)
        & (~pl.col("current_relimit"))
        & pl.col("current_day_return").is_between(-0.05, 0.03)
        & (~pl.col("broke_event_low"))
        & (location >= 0.55)
    ).collect().sort("event_age").unique("symbol", keep="first")
    for row in divergence.to_dicts():
        if row["symbol"] not in eligible or quotes[row["symbol"]]["amount_yi"] < 0.5:
            continue
        board = "首板" if row["board_height"] == 1 else "二板"
        close_location = (row["close"] - row["low"]) / (row["high"] - row["low"])
        add("分歧", row["symbol"], f"{board}后{row['event_age']}日 · 收盘位置{close_location * 100:.0f}%", event_date=row["event_date"], age=row["event_age"], anchor=float(row["event_low"]))

    # 炸板修复：近1—3日炸板后的严格修复。
    repair = scan("failed-limit-repair/v1/daily-ledger.parquet").filter(
        pl.col("event_age").is_between(1, 3)
        & (~pl.col("broke_event_low"))
        & (pl.col("day_return") > 0)
        & (location >= 0.6)
        & (pl.col("volume_ratio") < 1)
    ).collect().sort("event_age").unique("symbol", keep="first")
    for row in repair.to_dicts():
        if row["symbol"] not in eligible or quotes[row["symbol"]]["amount_yi"] < 0.5:
            continue
        add("炸板修复", row["symbol"], f"炸板后{row['event_age']}日 · 量比{row['volume_ratio']:.2f} · 收涨{row['day_return'] * 100:.1f}%", event_date=row["event_date"], age=row["event_age"], anchor=float(row["event_low"]))

    # 趋势回踩：当日产生的MA10/20缩量回踩事件。
    pullback = scan("trend-pullback/v1/daily-ledger.parquet").filter(
        (pl.col("age") == 0)
        & pl.col("support").is_in([10, 20])
        & (pl.col("event_volume_ratio") < 1)
        & (pl.col("event_close") >= pl.col("event_support_ma"))
        & (pl.col("trend_context") != "nontrend")
        & pl.col("event_breakthrough_age").is_between(0, 20)
    ).collect().sort("support").unique("symbol", keep="first")
    for row in pullback.to_dicts():
        if row["symbol"] not in eligible or quotes[row["symbol"]]["amount_yi"] < 0.5:
            continue
        add("趋势回踩", row["symbol"], f"突破后回踩MA{row['support']} · 量比{row['event_volume_ratio']:.2f}", anchor=float(row["event_support_ma"]))

    # 股性活跃：近期涨停记忆仍在结构内，排除当日涨停避免重复表达当前阶段。
    active = scan("active-character/v1/daily-ledger.parquet").filter(
        (pl.col("sample_kind") == "active")
        & ((pl.col("limit_age") <= 10) | (pl.col("limit_count30") >= 2))
        & (pl.col("close") > pl.col("ma20"))
        & (pl.col("drawdown20") >= -0.15)
        & (pl.col("close") >= pl.col("last_limit_low"))
        & (~pl.col("symbol").is_in(list(limit_symbols)))
    ).collect().unique("symbol")
    for row in active.to_dicts():
        if row["symbol"] not in eligible or quotes[row["symbol"]]["amount_yi"] < 0.5:
            continue
        add("股性活跃", row["symbol"], f"距涨停{row['limit_age']}日 · 30日涨停{int(row['limit_count30'])}次", age=row["limit_age"], anchor=float(row["last_limit_low"]))

    popularity_status = "unavailable"
    popularity_coverage = None
    if args.popularity_file:
        popularity = json.loads(Path(args.popularity_file).read_text(encoding="utf-8"))
        if str(popularity.get("date") or popularity.get("trade_date")).replace("-", "") != compact_date:
            raise ValueError("Popularity ranking date mismatch")
        if "records" in popularity:
            labels = {"ths": "同花顺", "xueqiu": "雪球", "baidu": "百度", "eastmoney": "东财"}
            ranked = defaultdict(dict)
            coverage = {}
            for root, label in labels.items():
                items = [item for item in popularity["records"] if item.get("source_root") == root and item.get("list_type", "normal") == "normal" and not item.get("deprecated")]
                ranks = {int(item["rank"]) for item in items}
                status = popularity.get("source_status", {}).get(root, {})
                complete = status.get("status") == "ok" and set(range(1, 101)) <= ranks
                coverage[root] = {"label": label, "status": "complete" if complete else "partial" if items else "unavailable", "count": len(items), "max_rank": max(ranks, default=0), "adapter": status.get("adapter"), "observed_at": status.get("observed_at")}
                for item in items:
                    if str(item.get("trade_date", compact_date)).replace("-", "") != compact_date:
                        raise ValueError("Popularity source record date mismatch")
                    code = str(item["code"])
                    if len(code) != 6 or not code.isdigit():
                        raise ValueError("Invalid normalized ranking code")
                    rank = int(item["rank"])
                    if root in ranked[code]:
                        raise ValueError("Duplicate root/code ranking")
                    ranked[code][root] = {"source": label, "rank": rank, "rank_change": item.get("rank_change"), "observed_at": item.get("observed_at")}
            popularity_status = "complete" if all(value["status"] == "complete" for value in coverage.values()) else "partial"
            popularity_coverage = {"source": "多源热榜", "date": trade_date.isoformat(), "max_rank": max((value["max_rank"] for value in coverage.values()), default=0), "count": sum(value["count"] for value in coverage.values()), "recall_rank_min": 20, "recall_rank_max": 100, "sources": {root: {key: value[key] for key in ("status", "max_rank")} for root, value in coverage.items()}, "source_details": coverage, "note": "任一源20—100名召回；各源独立排名，不按合并榜重排。收盘后关注度快照，百度为小时榜。"}
            symbol_by_code = {symbol.split(".")[0]: symbol for symbol in names}
            for code, source_ranks in ranked.items():
                reasons = [value for value in source_ranks.values() if 20 <= value["rank"] <= 100]
                if reasons and code in symbol_by_code:
                    add("人气中温", symbol_by_code[code], " · ".join(f"{value['source']}第{value['rank']}名" for value in reasons), details={"rankings": list(source_ranks.values()), "recall_sources": [value["source"] for value in reasons], "independent_source_count": len(source_ranks)})
        else:
            items = popularity["item"]
            max_rank = max((int(item["rank"]) for item in items), default=0)
            popularity_status = "complete" if set(range(1, 101)) <= {int(item["rank"]) for item in items} else "partial"
            popularity_coverage = {"source": "Fuyao / 同花顺", "date": popularity["date"], "max_rank": max_rank, "count": len(items), "recall_rank_min": 20, "recall_rank_max": 100}
            for item in items:
                if 20 <= int(item["rank"]) <= 100:
                    add("人气中温", item["thscode"], f"同花顺人气第{item['rank']}名 · 历史榜仅覆盖前{max_rank}", details={"rank": int(item["rank"])})
    symbols = sorted({symbol for records in source_records.values() for symbol in records})
    source_counts = {source: len(source_records[source]) for source in SOURCE_ORDER}
    stage_rank = {name: index for index, (name, _) in enumerate(STAGE_PRIORITY)}
    tier_rank = {"core": 0, "focus": 1, "all": 2}
    rows: list[dict] = []

    for symbol in symbols:
        entries = [source_records[source][symbol] for source in SOURCE_ORDER if symbol in source_records[source]]
        sources = [entry["source"] for entry in entries]
        stage = next(stage for stage, source in STAGE_PRIORITY if source in sources)
        event_strength = len(set(sources) & {"突破", "涨停", "异动", "分歧", "炸板修复", "趋势回踩"})
        if len(sources) >= 3 or (len(sources) >= 2 and event_strength >= 1):
            tier = "core"
        elif event_strength >= 1 or len(sources) >= 2:
            tier = "focus"
        else:
            tier = "all"
        quote = quotes[symbol]
        evidence = " · ".join(entry["evidence"] for entry in entries[:2])
        if len(entries) > 2:
            evidence += f" · 另{len(entries) - 2}项"
        rows.append({
            "name": names[symbol],
            "code": symbol,
            "price": round(quote["price"], 2),
            "pct": round(quote["pct"], 2),
            "amount_yi": round(quote["amount_yi"], 2),
            "market_cap_yi": round(quote["market_cap_yi"], 2),
            "turnover_pct": round(quote["turnover_pct"], 2),
            "stage": stage,
            "sources": sources,
            "popularity": source_records["人气中温"].get(symbol, {}).get("details"),
            "evidence": evidence,
            "fresh": "当日事件" if any(source in NEW_SOURCES for source in sources) else ("多源延续" if len(sources) >= 2 else "延续观察"),
            "days": " / ".join(SOURCE_EXPIRY[source] for source in sources[:2]),
            "tier": tier,
            "symbol": (names[symbol] or symbol)[0],
            "facts": [f"成交额 {quote['amount_yi']:.1f}亿", f"来源 {len(sources)}项", entries[0]["evidence"].split(" · ")[0], f"阶段 {stage}"],
            "timeline": [
                {
                    "date": entry["event_date"][5:] if len(entry["event_date"]) >= 10 else entry["event_date"],
                    "title": entry["source"],
                    "copy": entry["evidence"],
                }
                for entry in entries
            ],
        })

    rows.sort(key=lambda row: (tier_rank[row["tier"]], -len(row["sources"]), stage_rank[row["stage"]], -row["amount_yi"], row["code"]))
    stage_counts: dict[str, int] = defaultdict(int)
    tier_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        stage_counts[row["stage"]] += 1
        tier_counts[row["tier"]] += 1

    # Reuse QuantX's ext-data classification; this snapshot has no historical validity intervals.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.quantx_data.new_high_clusters import _load_memberships

    memberships = _load_memberships(data_dir)
    dimensions = {"concept": "题材概念", "industry_level1": "一级行业", "industry_level2": "二级行业", "attribute": "属性标签"}
    clusters = []
    for dimension in dimensions:
        market_groups: dict[str, set[str]] = defaultdict(set)
        for symbol in quotes:
            for label in memberships[dimension].get(symbol.split(".")[0], set()):
                market_groups[label].add(symbol)
        for row in rows:
            row.setdefault("memberships", {})[dimension] = sorted(memberships[dimension].get(row["code"].split(".")[0], set()))
        for label, market_members in market_groups.items():
            candidates = [row for row in rows if label in row["memberships"][dimension]]
            if not candidates:
                continue
            counts: dict[str, int] = defaultdict(int)
            for row in candidates:
                counts[row["stage"]] += 1
            weighted_count = sum(1 / len(row["memberships"][dimension]) for row in candidates)
            clusters.append({
                "id": f"{dimension}:{label}", "dimension": dimension, "name": label,
                "theme_level": theme_level(label) if dimension == "concept" else dimension,
                "parent_theme": THEME_PARENTS.get(label),
                "count": len(candidates), "market_count": len(market_members),
                "coverage_pct": round(len(candidates) / len(market_members) * 100, 2),
                "weighted_count": round(weighted_count, 2),
                "market_up_pct": round(sum(quotes[symbol]["pct"] > 0 for symbol in market_members) / len(market_members) * 100, 2),
                "market_mean_pct": round(sum(quotes[symbol]["pct"] for symbol in market_members) / len(market_members), 2),
                "limit_count": len(market_members & limit_symbols),
                "candidate_limit_count": sum("涨停" in row["sources"] for row in candidates),
                "event_count": sum(any(source in NEW_SOURCES for source in row["sources"]) for row in candidates),
                "source_counts": {source: sum(source in row["sources"] for row in candidates) for source in SOURCE_ORDER},
                "stage_counts": dict(counts), "members": [row["code"] for row in candidates],
                "representatives": [row["code"] for row in candidates[:3]],
            })
    clusters.sort(key=lambda cluster: (-cluster["weighted_count"], -cluster["count"], cluster["name"]))
    concept_clusters = sorted((cluster for cluster in clusters if cluster["dimension"] == "concept"), key=lambda cluster: ({"theme": 0, "industry": 1, "background": 2}[cluster["theme_level"]], -cluster["candidate_limit_count"], -cluster["event_count"], -cluster["weighted_count"], cluster["name"]))
    concept_priority = {cluster["name"]: index for index, cluster in enumerate(concept_clusters)}
    for row in rows:
        industry_themes = set().union(*(INDUSTRY_DISPLAY_THEMES.get(industry, set()) for industry in row["memberships"]["industry_level2"]))
        row["memberships"]["concept"].sort(key=lambda label: (label not in industry_themes, concept_priority.get(label, len(clusters))))
        row["primary_concept"] = next(iter(row["memberships"]["concept"]), None)
        row["display_theme_basis"] = "industry_matched_display_rule" if row["primary_concept"] in industry_themes else "specific_theme_event_display_rule"
    snapshot_files = list((data_dir / "ext_data").glob("*/part.parquet"))
    membership_metadata = {
        "basis": "latest_ext_snapshot_proxy", "source": "本地同花顺ext_data，复用QuantX分类",
        "snapshot_updated_at": max((dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone(dt.timedelta(hours=8))).isoformat() for path in snapshot_files), default=None),
        "note": "最新成分快照代理，非历史时点归属；板块指标使用当日行情中有报价的映射成员，非板块指数收益。概念多重计数；加权数按一股1/N分配。主展示概念优先具体主题，再按候选涨停、当日事件与加权聚集排序，不代表当日上涨原因。主题分层为可调整的展示规则，不删除原始归属。",
        "concept_covered_count": sum(bool(row["memberships"]["concept"]) for row in rows),
        "industry_covered_count": sum(bool(row["memberships"]["industry_level1"]) for row in rows),
        "dimensions": dimensions,
    }

    payload = {
        "trade_date": trade_date.isoformat(),
        "market_count": len(quotes),
        "raw_hits": sum(source_counts.values()),
        "unique_count": len(rows),
        "overlap_count": sum(len(row["sources"]) >= 2 for row in rows),
        "event_count": sum(any(source in NEW_SOURCES for source in row["sources"]) for row in rows),
        "available_sources": 8 + (popularity_status != "unavailable"),
        "eligible_market_count": len(eligible),
        "base_filters": {"total_market_cap_yi": [20, 3000], "amount_yi_min": 1, "turnover_pct_min": 1, "exclude_st": True},
        "recall_rule_version": "stock-pool-demo-v1",
        "popularity_coverage": popularity_coverage,
        "source_counts": source_counts,
        "source_status": {source: (popularity_status if source == "人气中温" else "complete") for source in SOURCE_ORDER},
        "stage_counts": dict(stage_counts),
        "tier_counts": dict(tier_counts),
        "rows": rows,
        "clusters": clusters,
        "membership_metadata": membership_metadata,
        "definitions": {
            "data_note": "真实历史缓存；九池召回统一经过市值20—3000亿、成交额≥1亿、换手≥1%过滤；人气覆盖以popularity_coverage为准。",
            "price_note": f"收盘价和涨跌幅来自data/quantx/{compact_date}/tushare.json。",
        },
    }
    from stock_pool_logic import enrich

    enrich(payload, data_dir, Path(args.anomaly_file) if args.anomaly_file else None)
    if args.smnc_research_dir:
        from stock_pool_smnc import enrich as enrich_smnc

        enrich_smnc(payload, Path(args.smnc_research_dir))
    calendar_files = list((data_dir / "trading_calendar").rglob("*.parquet"))
    prior_dates = pl.scan_parquet(calendar_files).filter((pl.col("trade_date") == trade_date) & (pl.col("exchange") == "SSE") & pl.col("is_open")).select("previous_open_date").collect().drop_nulls().unique() if calendar_files else pl.DataFrame()
    previous_date = prior_dates.item().isoformat() if prior_dates.height == 1 else None
    previous_path = Path(args.previous_snapshot) if args.previous_snapshot else research_dir / f"prototype-{(previous_date or '').replace('-', '')}.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else None
    if args.previous_snapshot and previous is None:
        raise FileNotFoundError(previous_path)
    payload["daily_changes"] = compare_snapshots(payload, previous, previous_date)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.html:
        html_path = Path(args.html)
        html = html_path.read_text(encoding="utf-8")
        html, replacements = re.subn(r"    const prototype = .*?;\n", lambda _: "    const prototype = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", html, count=1)
        if replacements != 1:
            raise ValueError("Prototype HTML snapshot marker missing")
        html_path.write_text(html, encoding="utf-8")
    summary_keys = ["trade_date", "market_count", "raw_hits", "unique_count", "overlap_count", "event_count", "available_sources", "source_counts", "stage_counts", "tier_counts"]
    print(json.dumps({key: payload[key] for key in summary_keys}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
