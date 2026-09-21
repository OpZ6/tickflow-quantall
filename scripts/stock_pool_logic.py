"""Build dated, source-backed topic groups for the research prototype."""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

TOPICS = {
    "PCB／覆铜板": r"PCB|HDI|覆铜板|CCL|电子布|铜箔",
    "液冷": r"液冷", "MLCC／被动元件": r"MLCC|被动元件",
    "网络／AI安全": r"网络安全|AI安全|数据安全|网络可视化",
    "光互联": r"光通信|光模块|CPO|光互联|光纤",
    "金刚石散热": r"金刚石散热", "培育钻石": r"培育钻石",
    "人形机器人": r"人形机器人", "机器人": r"机器人|减速器|丝杠",
    "脑机接口": r"脑机接口", "固态电池": r"固态电池",
    "半导体设备": r"半导体设备|光刻机", "先进封装": r"先进封装",
    "芯片／半导体材料": r"国产芯片|芯片设计|半导体材料|半导体钽材|半导体新材料",
    "智能电网": r"智能电网|配电|算电协同", "电力": r"热电联产|电力",
    "AI应用": r"AI应用|智能体|AI大模型", "算力／数据中心": r"AI算力|云计算数据中心|数据中心|服务器",
    "创新药／CRO": r"创新药|CRO|mRNA", "医疗／医药": r"医药|医疗",
    "零售": r"连锁零售|零售", "旅游": r"旅游|酒店|人工景点",
    "汽车零部件": r"汽车零部件|汽车电子|电子水泵", "新能源汽车": r"新能源汽车",
    "商业航天": r"商业航天|卫星", "玻纤": r"玻纤",
    "石英材料": r"石英", "房地产": r"房地产",
    "股权／重组事件": r"股权转让|控制权变更|资产重组|股权收购|完成收购",
}
SPECIFIC = {"机器人": "人形机器人", "电力": "智能电网", "医疗／医药": "创新药／CRO"}


def topics(text: str) -> list[str]:
    result = [name for name, pattern in TOPICS.items() if re.search(pattern, text, re.I)]
    return [name for name in result if SPECIFIC.get(name) not in result]


def enrich(payload: dict, data_dir: Path, anomaly_file: Path | None) -> None:
    day = payload["trade_date"]
    compact = day.replace("-", "")
    root = data_dir / "quantx" / compact
    evidence = defaultdict(list)
    source_details = []

    def add(code: str, source: str, text: str, labels: list[str], observed: str, kind: str, catalyst: str = "") -> None:
        evidence[code.split(".")[0]].append({"source": source, "date": day, "observed_at": observed, "kind": kind, "text": text, "topics": labels, "catalyst": catalyst})

    ladder = json.loads((root / "limit_ladder.json").read_text(encoding="utf-8-sig"))
    if str(ladder["trade_date"]).replace("-", "") != compact:
        raise ValueError("Logic ladder date mismatch")
    for members in ladder["ladder_by_height"].values():
        for row in members:
            theme = row.get("theme_name", "")
            labels = topics(theme)
            if not labels and theme not in ("其他", "大消费", "", "独立逻辑"):
                labels = [theme]
            add(row["code"], "QuantX涨停梯队解读", row.get("interpretation") or theme, labels, day + "收盘采集", "涨停解读", row.get("theme_reason", ""))
    source_details.append({"source": "涨停梯队解读", "count": sum(len(rows) for rows in ladder["ladder_by_height"].values()), "date": day})
    hot = json.loads((root / "ths_hot.json").read_text(encoding="utf-8-sig"))
    if str(hot["trade_date"]).replace("-", "") != compact:
        raise ValueError("Logic hot list date mismatch")
    for row in hot.get("stocks", []):
        text = row.get("reason", "")
        if text:
            add(row["code"], "同花顺热点理由", text, topics(text), hot.get("scraped_at", ""), "热点标签")
    source_details.append({"source": "同花顺热点理由", "count": len(hot.get("stocks", [])), "date": day})
    if anomaly_file and anomaly_file.exists():
        anomaly = json.loads(anomaly_file.read_text(encoding="utf-8"))
        observed = dt.datetime.fromtimestamp(anomaly["timestamp"] / 1000, dt.timezone(dt.timedelta(hours=8)))
        if observed.date().isoformat() != day:
            raise ValueError("Current-only anomaly source does not match requested date")
        for row in anomaly["item"]:
            # Keyword tags can contain a negative development; preserve it verbatim.
            add(row["thscode"], "Fuyao／同花顺异动解读（上游AI摘要）", row.get("analysis_content", ""), topics("+".join(row.get("keyword_list", []))), observed.isoformat(), row.get("tag_name", "异动"))
        source_details.append({"source": "同花顺异动解读（上游AI摘要）", "count": len(anomaly["item"]), "observed_at": observed.isoformat()})

    groups = defaultdict(set)
    for code, entries in evidence.items():
        for entry in entries:
            for label in entry["topics"]:
                groups[label].add(code)
    rows = payload["rows"]
    for row in rows:
        entries = evidence.get(row["code"].split(".")[0], [])
        labels = sorted({label for entry in entries for label in entry["topics"]})
        row["logic_evidence"] = entries
        row["memberships"]["logic"] = labels
        row["logic_status"] = "当日题材标签" if labels else "有解读，题材待归类" if entries else "今日逻辑待确认"
    for label, codes in groups.items():
        members = [row for row in rows if label in row["memberships"]["logic"]]
        if not members:
            continue
        related = [row["code"] for row in rows if label not in row["memberships"]["logic"] and label in topics("+".join(row["memberships"]["concept"]))]
        catalysts = list(dict.fromkeys(entry["catalyst"] for row in members for entry in row["logic_evidence"] if label in entry["topics"] and entry["catalyst"]))
        payload["clusters"].append({
            "id": "logic:" + label, "dimension": "logic", "name": label, "theme_level": "logic", "parent_theme": None,
            "count": len(members), "market_count": len(codes), "coverage_pct": round(len(members) / len(codes) * 100, 2),
            "weighted_count": sum(1 / len(row["memberships"]["logic"]) for row in members),
            "market_up_pct": sum(row["pct"] > 0 for row in members) / len(members) * 100,
            "market_mean_pct": sum(row["pct"] for row in members) / len(members),
            "limit_count": sum(row["stage"] == "涨停强化" for row in members),
            "candidate_limit_count": sum(row["stage"] == "涨停强化" for row in members),
            "event_count": sum(row["fresh"] == "当日事件" for row in members),
            "source_counts": dict(Counter(source for row in members for source in row["sources"])),
            "stage_counts": dict(Counter(row["stage"] for row in members)), "members": [row["code"] for row in members],
            "representatives": [row["code"] for row in sorted(members, key=lambda row: (row["stage"] != "涨停强化", -row["pct"], -row["amount_yi"]))[:3]],
            "catalysts": catalysts, "related_members": related, "down_count": sum(row["pct"] < 0 for row in members),
        })
    payload["membership_metadata"]["dimensions"]["logic"] = "当日交易题材"
    payload["logic_metadata"] = {"sources": source_details, "evidence_count": sum(bool(row["logic_evidence"]) for row in rows), "topic_count": sum(bool(row["memberships"]["logic"]) for row in rows), "rule_version": "explicit-topic-tags-v1", "note": "按来源题材、热点理由及异动关键词归类；标签代表当日材料提及，不证明上涨因果。异动来源为上游AI摘要，包含下跌事件；当前没有连续历史，暂不判定升温、扩散或持续性。"}
