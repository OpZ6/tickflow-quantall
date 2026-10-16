"""Deterministic topic normalization shared by stock-pool logic and static views.

Rules only map explicit source text to display labels. They never change recall,
stage or ranking, and they keep the original evidence text untouched.
"""
from __future__ import annotations

import re

TOPIC_PATTERNS: tuple[tuple[str, str], ...] = (
    ("PCB／覆铜板", r"(?<![a-z])PCB(?![a-z])|(?<![a-z])HDI(?![a-z])|覆铜板|(?<![a-z])CCL(?![a-z])|电子布|铜箔"),
    ("液冷", r"液冷"),
    ("MLCC／被动元件", r"(?<![a-z])MLCC(?![a-z])|被动元件"),
    ("网络／AI安全", r"网络安全|AI安全|数据安全|网络可视化"),
    ("光互联", r"光通信|光模块|(?<![a-z])CPO(?![a-z])|光互联|光纤"),
    ("金刚石散热", r"金刚石散热"),
    ("培育钻石", r"培育钻石"),
    ("人形机器人", r"人形机器人"),
    ("机器人", r"机器人|减速器|丝杠"),
    ("脑机接口", r"脑机接口"),
    ("固态电池", r"固态电池"),
    ("半导体设备", r"半导体设备|光刻机"),
    ("先进封装", r"先进封装"),
    ("芯片／半导体材料", r"国产芯片|芯片设计|半导体材料|半导体钽材|半导体新材料"),
    ("智能电网", r"智能电网|配电|算电协同"),
    ("电力", r"热电联产|电力"),
    ("AI应用", r"AI应用|智能体|AI大模型"),
    ("算力／数据中心", r"AI算力|云计算数据中心|数据中心|服务器"),
    ("创新药／CRO", r"创新药|(?<![a-z])CRO(?![a-z])|(?<![a-z])mRNA(?![a-z])"),
    ("医疗／医药", r"医药|医疗"),
    ("零售", r"连锁零售|零售"),
    ("旅游", r"旅游|酒店|人工景点"),
    ("汽车零部件", r"汽车零部件|汽车电子|电子水泵"),
    ("新能源汽车", r"新能源汽车"),
    ("商业航天", r"商业航天|卫星"),
    ("玻纤", r"玻纤"),
    ("石英材料", r"石英"),
    ("房地产", r"房地产"),
    ("股权／重组事件", r"股权转让|控制权变更|资产重组|股权收购|完成收购"),
)

# A specific label already matched by another pattern suppresses the broader one.
SPECIFIC_OVERRIDES = {"机器人": "人形机器人", "电力": "智能电网", "医疗／医药": "创新药／CRO"}

# Presentation taxonomy for the static concept dimension. It reorders and groups
# existing memberships only; the raw concept list is never removed.
INDUSTRY_THEMES = {
    "人工智能", "AI", "中国AI", "机器人概念", "芯片概念", "新能源汽车", "军工",
    "军民融合", "新能源", "数字经济", "碳中和", "高端装备", "物联网",
    "消费电子概念", "光伏概念", "绿色电力", "文化传媒概念", "医疗器械概念",
    "旅游概念", "互联网金融", "5G", "6G", "6G概念",
}
BACKGROUND_THEME = re.compile(
    r"(?:大开发|振兴|一带一路|自贸|新区|一体化|大湾区|示范区|共同富裕|统一大市场|"
    r"特色小镇|海峡两岸|人民币贬值|俄乌冲突|参股|创投|独角兽|中字头|预增|摘帽|次新股|"
    r"土地流转|新型城镇化|新型工业化|超级品牌|大基金持股|出海50|新质50|果指数|"
    r"兵装重组|股权转让)"
)
BACKGROUND_EXACT = {
    "华为概念", "比亚迪概念", "阿里巴巴概念", "腾讯概念", "百度概念", "小米概念",
    "特斯拉概念", "苹果概念", "宁德时代概念", "富士康概念", "中芯国际概念",
    "长安汽车概念", "英伟达概念", "PC", "50",
}
INDUSTRY_DISPLAY_THEMES = {
    "元件": {"PCB", "MLCC", "PCB概念", "MLCC概念"},
    "半导体": {"存储芯片", "先进封装", "汽车芯片", "MCU芯片", "第三代半导体", "光刻胶", "光刻机"},
    "通信设备": {"共封装光学(CPO)", "光纤概念", "铜缆高速连接", "5G", "6G概念"},
    "电池": {"固态电池", "锂电池概念", "钠离子电池", "动力电池回收"},
    "军工装备": {"商业航天", "国产航母", "航空发动机", "军工信息化", "无人机", "大飞机"},
}

THEME_LEVEL_ORDER = {"theme": 0, "industry": 1, "background": 2}


def topic_labels(text: str, *, whole_term: bool = False) -> list[str]:
    """Return explicit topic labels mentioned by the text, preserving rule order."""
    if not text:
        return []
    # Dynamic clustering handles complete source tags, not free-form mentions.
    # A compound like 电力人工智能 keeps its own name instead of becoming 电力.
    target = re.sub(r"(概念|板块)$", "", text.strip()) if whole_term else text
    match = re.fullmatch if whole_term else re.search
    matched = [name for name, pattern in TOPIC_PATTERNS if match(pattern, target, re.I)]
    return [name for name in matched if SPECIFIC_OVERRIDES.get(name) not in matched]


def theme_level(label: str) -> str:
    name = label.strip()
    with_suffix = name if name.endswith("概念") else f"{name}概念"
    if name in BACKGROUND_EXACT or with_suffix in BACKGROUND_EXACT or BACKGROUND_THEME.search(name):
        return "background"
    return "industry" if name in INDUSTRY_THEMES or with_suffix in INDUSTRY_THEMES else "theme"
