"""Review V4 七区复盘报告。

从 QuantX report_builder.py 移植精简版,替换 market_recap。
两阶段:Python 生成 draft HTML(带 7 个 CLAUDE_ANALYSIS marker),LLM 填充。

七区结构:
  s0 顶部决断 | s1 大盘环境 | s2 主线题材
  s3 连板情绪 | s4 资金生态 | s5 关注名单 | s6 次日预案

数据来源: data/quantx/YYYYMMDD/_computed.json + 原始 JSON
输出: data/quantx/YYYYMMDD/review.html (draft)
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from app.services.emotion_state import _load_json

logger = logging.getLogger(__name__)

BLOCK_ORDER = [
    "decision_summary",
    "combined_environment_analysis",
    "theme_deep_dive",
    "sentiment_deep_dive",
    "trend_institution_analysis",
    "watchlist_final",
    "summary_lessons",
]

BLOCK_TITLES = {
    "decision_summary": "顶部决断",
    "combined_environment_analysis": "大盘环境综合分析",
    "theme_deep_dive": "主线10日演变与生命周期",
    "sentiment_deep_dive": "情绪周期深度定位",
    "trend_institution_analysis": "机构趋势深度分析",
    "watchlist_final": "最终关注名单",
    "summary_lessons": "总结与沉淀",
}

SECTION_TITLES = {
    "s0": "一、顶部决断",
    "s1": "二、大盘环境",
    "s2": "三、主线题材",
    "s3": "四、连板情绪",
    "s4": "五、资金生态与趋势容量",
    "s5": "六、关注名单",
    "s6": "七、次日预案与复盘校验",
}

BLOCK_SECTION_MAP = {
    "decision_summary": "s0",
    "combined_environment_analysis": "s1",
    "theme_deep_dive": "s2",
    "sentiment_deep_dive": "s3",
    "trend_institution_analysis": "s4",
    "watchlist_final": "s5",
    "summary_lessons": "s6",
}


def _claude_analysis_marker(block_id: str) -> str:
    title = BLOCK_TITLES.get(block_id, block_id)
    return f"""<!-- CLAUDE_ANALYSIS_START:{block_id} -->
<div class="analysis-block" data-claude-analysis="{block_id}">
  <div class="data-block-title">待 Claude 嵌入：{title}</div>
  <p class="footnote">此处由 LLM 编辑器填充结构化分析内容。</p>
</div>
<!-- CLAUDE_ANALYSIS_END:{block_id} -->"""


def _build_metric_strip(computed: dict, tu: dict) -> str:
    sh = (tu.get("indexes") or {}).get("000001.SH", {})
    cy = (tu.get("indexes") or {}).get("399006.SZ", {})
    kc = (tu.get("indexes") or {}).get("000688.SH", {})
    dm = tu.get("daily_market", {})
    ad_latest = (tu.get("advance_decline") or {})
    up_count = dm.get("up_count", 0)
    down_count = dm.get("down_count", 0)
    flat_count = dm.get("flat_count", 0)
    total_amount = dm.get("total_amount_yi", 0)
    advance = computed.get("advance_stats", {})

    cards = [
        ("上证指数", f"{sh.get('pct_chg', 0):+.2f}%", _zone_color(sh.get("pct_chg", 0))),
        ("创业板指", f"{cy.get('pct_chg', 0):+.2f}%", _zone_color(cy.get("pct_chg", 0))),
        ("科创50", f"{kc.get('pct_chg', 0):+.2f}%", _zone_color(kc.get("pct_chg", 0))),
        ("涨跌平", f"{up_count}/{down_count}/{flat_count}", "neutral"),
        ("成交额", f"{total_amount:.0f}亿", "neutral"),
        ("晋级率", f"{advance.get('advance_rate', '--')}%", "neutral"),
    ]
    items = "".join(
        f'<div class="metric-card {_cls}"><span class="metric-label">{label}</span><span class="metric-value">{val}</span></div>'
        for label, val, _cls in cards
    )
    return f'<div class="metric-strip">{items}</div>'


def _zone_color(pct) -> str:
    try:
        v = float(pct)
    except (TypeError, ValueError):
        return "neutral"
    return "positive" if v > 0 else "negative" if v < 0 else "neutral"


def _build_multi_dim_diagnosis(computed: dict) -> str:
    st = computed.get("short_term_sentiment", {})
    tr = computed.get("trend_sentiment", {})
    mh = computed.get("market_heat", {})
    ebb = computed.get("ebb_risk_check", {})
    part = computed.get("participation_check", {})
    crash = computed.get("crash_signals", {})
    loss = computed.get("loss_effect", {})

    advance_rate = computed.get("advance_stats", {}).get("advance_rate")
    dims = [
        ("市场热度", str(mh.get("score", 0)), mh.get("zone", "")),
        ("短线情绪", str(st.get("score", 0)), st.get("zone", "")),
        ("趋势情绪", str(tr.get("score", 0)), tr.get("zone", "")),
        ("参与度", "", part.get("verdict", "")),
        ("退潮风险", str(ebb.get("signal_count", 0)), ebb.get("verdict", "")),
        ("崩塌信号", "", "已触发" if crash.get("any_triggered") else "未触发"),
        ("亏钱效应", "", loss.get("severity", "")),
        ("晋级率", f"{advance_rate}%" if advance_rate is not None else "--", ""),
    ]
    rows = "".join(
        f'<tr><td>{name}</td><td>{val}</td><td>{zone}</td></tr>'
        for name, val, zone in dims
    )
    return f'<table class="dim-diagnosis"><thead><tr><th>维度</th><th>值</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>'


def _build_risk_checklist(computed: dict) -> str:
    ebb = computed.get("ebb_risk_check", {})
    crash = computed.get("crash_signals", {})
    loss = computed.get("loss_effect", {})
    signals = ebb.get("signals", {})
    items = []
    for name, sig in signals.items():
        if isinstance(sig, dict):
            triggered = sig.get("triggered", False)
            items.append(f'<li class="{"risk-triggered" if triggered else ""}">{name}: {"触发" if triggered else "未触发"}</li>')
    for s in crash.get("signals", []):
        triggered = s.get("triggered", False)
        items.append(f'<li class="{"risk-triggered" if triggered else ""}">{s.get("name", "")}: {s.get("status", "")}</li>')
    items.append(f'<li>亏钱效应: {loss.get("severity", "未知")}</li>')
    return f'<ul class="risk-checklist">{"".join(items)}</ul>'


def _build_index_table(tu: dict) -> str:
    indexes = tu.get("indexes", {})
    codes = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH", "000016.SH", "399303.SZ", "399905.SZ"]
    rows = ""
    for code in codes:
        idx = indexes.get(code, {})
        if not idx:
            continue
        rows += f'<tr><td>{code}</td><td>{idx.get("name", "")}</td><td>{idx.get("close", 0):.2f}</td><td class="{_zone_color(idx.get("pct_chg", 0))}">{idx.get("pct_chg", 0):+.2f}%</td></tr>'
    return f'<table class="index-table"><thead><tr><th>代码</th><th>名称</th><th>收盘</th><th>涨跌幅</th></tr></thead><tbody>{rows}</tbody></table>'


def _build_ebb_tide_table(computed: dict) -> str:
    part = computed.get("participation_check", {})
    ebb = computed.get("ebb_risk_check", {})
    conditions = part.get("conditions", {})
    rows = ""
    for name, cond in conditions.items():
        if isinstance(cond, dict):
            ok = cond.get("ok")
            status = "满足" if ok is True else "不满足" if ok is False else "数据不足"
            rows += f'<tr><td>{name}</td><td>{cond.get("value", "")}</td><td>{status}</td></tr>'
    rows += f'<tr class="summary-row"><td colspan="2">参与度判定</td><td>{part.get("verdict", "")}</td></tr>'
    rows += f'<tr class="summary-row"><td colspan="2">退潮风险</td><td>{ebb.get("verdict", "")}</td></tr>'
    return f'<table class="ebb-tide"><thead><tr><th>条件</th><th>值</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>'


def _build_ladder_grid(computed: dict, py: dict) -> str:
    ladder_data = computed.get("limit_ladder", {})
    ladder = ladder_data.get("ladder_by_height", {}) or {}
    if not ladder:
        lu = py.get("limit_up", {})
        ladder = lu.get("ladder", {})
    cards = ""
    for level in sorted(ladder.keys(), key=lambda x: int(x) if str(x).isdigit() else 0, reverse=True):
        stocks = ladder.get(level, [])
        names = ", ".join(s if isinstance(s, str) else s.get("name", "") for s in stocks[:8])
        cards += f'<div class="ladder-card"><div class="ladder-level">{level}板</div><div class="ladder-count">{len(stocks)}只</div><div class="ladder-names">{names}</div></div>'
    return f'<div class="ladder-grid">{cards}</div>' if cards else '<p class="no-data">无连板数据</p>'


def _build_sentiment_combined(computed: dict) -> str:
    mh = computed.get("market_heat", {})
    st = computed.get("short_term_sentiment", {})
    tr = computed.get("trend_sentiment", {})
    scores = [
        ("市场热度", mh.get("score", 0), mh.get("zone", "")),
        ("短线情绪", st.get("score", 0), st.get("zone", "")),
        ("趋势情绪", tr.get("score", 0), tr.get("zone", "")),
    ]
    bars = ""
    for name, score, zone in scores:
        color = _score_color(score)
        bars += f'<div class="sentiment-bar"><span class="sentiment-label">{name}</span><div class="sentiment-track"><div class="sentiment-fill" style="width:{score}%;background:{color}"></div></div><span class="sentiment-score">{score}</span><span class="sentiment-zone">{zone}</span></div>'
    return f'<div class="sentiment-combined">{bars}</div>'


def _score_color(score: int) -> str:
    if score >= 70: return "#ef4444"
    elif score >= 60: return "#f97316"
    elif score >= 40: return "#3b82f6"
    elif score >= 30: return "#6b7280"
    else: return "#1e40af"


def _build_sector_flow(ak: dict) -> str:
    sectors = ak.get("sector_fund_flow", [])
    if not sectors:
        return '<p class="no-data">无行业资金流数据</p>'
    top_in = sorted(sectors, key=lambda x: float(x.get("net_inflow_yi", 0)), reverse=True)[:5]
    top_out = sorted(sectors, key=lambda x: float(x.get("net_inflow_yi", 0)))[:5]
    rows_in = "".join(f'<tr><td>{s.get("name", "")}</td><td class="positive">{s.get("net_inflow_yi", 0):+.2f}亿</td></tr>' for s in top_in)
    rows_out = "".join(f'<tr><td>{s.get("name", "")}</td><td class="negative">{s.get("net_inflow_yi", 0):+.2f}亿</td></tr>' for s in top_out)
    return f'<div class="sector-flow"><div class="sector-col"><h4>主力净流入Top5</h4><table><tbody>{rows_in}</tbody></table></div><div class="sector-col"><h4>主力净流出Top5</h4><table><tbody>{rows_out}</tbody></table></div></div>'


def _build_next_day_plan(computed: dict, py: dict, tu: dict) -> str:
    mh = computed.get("market_heat", {})
    zone = mh.get("zone", "正常")
    score = mh.get("score", 50)
    if score >= 70:
        position = "高仓位(70-90%)"
        action = "积极参与主线,关注退潮信号"
    elif score >= 50:
        position = "中等仓位(40-60%)"
        action = "脉冲处理,关注主线确认"
    elif score >= 30:
        position = "低仓位(10-30%)"
        action = "谨慎参与,等待情绪修复"
    else:
        position = "空仓或极低仓位(0-10%)"
        action = "规避风险,等待冰点反转"
    return f"""<!-- REVIEW_DECISION_PLAN_START -->
<div class="decision-plan">
  <div class="position-analysis">
    <h4>仓位建议</h4>
    <p class="position-band">{position}</p>
    <p class="action-suggestion">{action}</p>
  </div>
  <div class="scene-grid">
    <div class="scene-card scene-up"><h5>走强情景</h5><p>热度>70 + 参与度判定=参与 + 退潮未触发</p></div>
    <div class="scene-card scene-flat"><h5>震荡情景</h5><p>热度40-70 + 参与度=脉冲处理</p></div>
    <div class="scene-card scene-down"><h5>走弱情景</h5><p>热度<40 或 退潮确认 或 崩塌触发</p></div>
  </div>
</div>
<!-- REVIEW_DECISION_PLAN_END -->"""


def _build_themes_table(py: dict, th: dict) -> str:
    lu = py.get("limit_up", {})
    themes = lu.get("themes", [])[:8]
    ths_tags = (th.get("reason_tags") or [])[:8]
    py_rows = "".join(f'<tr><td>{t.get("name", "")}</td><td>{t.get("count", 0)}</td></tr>' for t in themes)
    ths_rows = "".join(f'<tr><td>{t.get("tag", "")}</td><td>{t.get("count", 0)}</td></tr>' for t in ths_tags)
    return f"""<div class="themes-section">
  <div class="themes-col"><h4>问财题材</h4><table><thead><tr><th>题材</th><th>涨停数</th></tr></thead><tbody>{py_rows}</tbody></table></div>
  <div class="themes-col"><h4>同花顺热点</h4><table><thead><tr><th>标签</th><th>数量</th></tr></thead><tbody>{ths_rows}</tbody></table></div>
</div>"""


def _build_new_high_block(py: dict) -> str:
    nh = py.get("new_high_100d", {})
    if nh.get("status") != "ok":
        return '<p class="no-data">百日新高数据不可用</p>'
    stocks = nh.get("stocks", [])[:10]
    rows = "".join(f'<tr><td>{s.get("code", "")}</td><td>{s.get("name", "")}</td><td>{s.get("pct_chg", 0):+.2f}%</td><td>{", ".join(s.get("concepts", [])[:3])}</td></tr>' for s in stocks)
    return f'<table class="new-high"><thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>概念</th></tr></thead><tbody>{rows}</tbody></table>'


def _build_height_chart(computed: dict) -> str:
    zh = computed.get("zhangtingke_height", {})
    if not zh.get("available"):
        return '<p class="no-data">无连板高度历史</p>'
    days = zh.get("days", [])
    if not days:
        return '<p class="no-data">无连板高度历史</p>'
    rows = "".join(
        f'<tr><td>{d.get("date", "")}</td><td>{d.get("name", "")}</td><td>{d.get("limit_times", "")}</td><td>{d.get("pct_chg", 0):+.2f}%</td></tr>'
        for d in days[:10]
    )
    return f'<table class="height-history"><thead><tr><th>日期</th><th>名称</th><th>连板</th><th>涨跌幅</th></tr></thead><tbody>{rows}</tbody></table>'


def _build_watchlist(computed: dict, py: dict) -> str:
    lu = py.get("limit_up", {})
    stocks = lu.get("stocks", [])
    if not stocks:
        return '<p class="no-data">无关注名单数据</p>'
    top_stocks = sorted(stocks, key=lambda x: int(x.get("limit_times", 1)), reverse=True)[:6]
    cards = ""
    for s in top_stocks:
        cards += f"""<div class="watchlist-card">
          <div class="card-header"><span class="card-name">{s.get("name", "")}</span><span class="card-code">{s.get("code", "")}</span><span class="card-height">{s.get("limit_times", 1)}板</span></div>
          <div class="card-notes"><p>入选依据：{s.get("reason", "")}</p><p>横向比较：待分析</p><p>确认条件：待分析</p><p>止损：待设定</p><p>止盈压力：待设定</p></div>
        </div>"""
    return f'<div class="watchlist-grid">{cards}</div>'


REVIEW_CSS = """
:root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9; --muted: #8b949e; --positive: #3fb950; --negative: #f85149; --accent: #58a6ff; }
[data-theme="light"] { --bg: #fff; --card: #f6f8fa; --border: #d0d7de; --text: #1f2328; --muted: #656d76; --positive: #1a7f37; --negative: #cf222e; --accent: #0969da; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; padding: 20px; }
h1 { font-size: 1.6em; } h1 span { font-size: 0.5em; color: var(--accent); margin-left: 8px; }
.subtitle { color: var(--muted); font-size: 0.85em; margin-bottom: 16px; }
.metric-strip { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.metric-card { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 8px 14px; display: flex; flex-direction: column; min-width: 80px; }
.metric-label { font-size: 0.7em; color: var(--muted); } .metric-value { font-size: 1.1em; font-weight: 600; }
.metric-card.positive .metric-value { color: var(--positive); } .metric-card.negative .metric-value { color: var(--negative); }
nav.toc { display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }
nav.toc a { color: var(--accent); text-decoration: none; font-size: 0.85em; }
h2 { border-bottom: 2px solid var(--border); padding-bottom: 6px; margin-top: 32px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.85em; }
th, td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
th { background: var(--card); font-weight: 600; }
td.positive, .positive { color: var(--positive); } td.negative, .negative { color: var(--negative); }
.dim-diagnosis th { background: var(--card); }
.risk-checklist { list-style: none; padding: 0; }
.risk-checklist li { padding: 4px 0; border-bottom: 1px dashed var(--border); }
.risk-checklist .risk-triggered { color: var(--negative); font-weight: 600; }
.ladder-grid { display: flex; gap: 8px; flex-wrap: wrap; }
.ladder-card { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 10px; min-width: 140px; }
.ladder-level { font-size: 1.2em; font-weight: 700; color: var(--accent); } .ladder-count { color: var(--muted); } .ladder-names { font-size: 0.8em; margin-top: 4px; }
.sentiment-combined { display: flex; flex-direction: column; gap: 8px; margin: 16px 0; }
.sentiment-bar { display: flex; align-items: center; gap: 8px; }
.sentiment-label { width: 80px; font-size: 0.85em; } .sentiment-track { flex: 1; height: 20px; background: var(--card); border-radius: 10px; overflow: hidden; }
.sentiment-fill { height: 100%; border-radius: 10px; } .sentiment-score { width: 30px; text-align: right; font-weight: 600; } .sentiment-zone { width: 40px; font-size: 0.8em; color: var(--muted); }
.sector-flow { display: flex; gap: 16px; } .sector-col { flex: 1; }
.themes-section { display: flex; gap: 16px; } .themes-col { flex: 1; }
.watchlist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.watchlist-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.card-header { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; } .card-name { font-weight: 600; } .card-code { color: var(--muted); font-size: 0.85em; } .card-height { color: var(--accent); }
.card-notes p { font-size: 0.8em; margin: 4px 0; color: var(--muted); }
.decision-plan { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 16px 0; }
.scene-grid { display: flex; gap: 8px; margin-top: 12px; }
.scene-card { flex: 1; border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
.scene-up { border-color: var(--positive); } .scene-flat { border-color: var(--muted); } .scene-down { border-color: var(--negative); }
.analysis-block { background: var(--card); border: 2px dashed var(--accent); border-radius: 8px; padding: 16px; margin: 16px 0; }
.data-block-title { font-weight: 600; color: var(--accent); } .footnote { font-size: 0.8em; color: var(--muted); }
.no-data { color: var(--muted); font-style: italic; }
.summary-row { font-weight: 600; background: var(--card); }
.theme-toggle { position: fixed; top: 20px; right: 20px; z-index: 100; }
"""


def build_review_html(data_dir: Path) -> str:
    """生成 review V4 draft HTML。

    Args:
        data_dir: data/quantx/YYYYMMDD/ 目录
    Returns:
        HTML 字符串
    """
    data_dir = Path(data_dir)
    computed = _load_json(str(data_dir / "_computed.json"))
    tu = _load_json(str(data_dir / "tushare.json"))
    py = _load_json(str(data_dir / "pywencai.json"))
    ak = _load_json(str(data_dir / "akshare.json"))
    th = _load_json(str(data_dir / "ths_hot.json"))
    trade_date = computed.get("trade_date", data_dir.name)

    metric_strip = _build_metric_strip(computed, tu)
    toc_items = "".join(f'<a href="#{sid}">{title}</a>' for sid, title in SECTION_TITLES.items())
    toc = f'<nav class="toc">{toc_items}</nav>'

    s0 = f"""{_claude_analysis_marker("decision_summary")}
{_build_multi_dim_diagnosis(computed)}
{_build_risk_checklist(computed)}"""

    s1 = f"""{_build_index_table(tu)}
{_claude_analysis_marker("combined_environment_analysis")}"""

    s2 = f"""{_build_ebb_tide_table(computed)}
{_build_themes_table(py, th)}
{_build_new_high_block(py)}
{_claude_analysis_marker("theme_deep_dive")}"""

    s3 = f"""{_build_ladder_grid(computed, py)}
{_build_height_chart(computed)}
{_build_sentiment_combined(computed)}
{_claude_analysis_marker("sentiment_deep_dive")}"""

    s4 = f"""{_build_sector_flow(ak)}
{_claude_analysis_marker("trend_institution_analysis")}"""

    s5 = _claude_analysis_marker("watchlist_final")

    s6 = f"""{_build_next_day_plan(computed, py, tu)}
{_claude_analysis_marker("summary_lessons")}"""

    sections = ""
    for sid in ["s0", "s1", "s2", "s3", "s4", "s5", "s6"]:
        content = locals()[sid]
        sections += f'<h2 id="{sid}">{SECTION_TITLES[sid]}</h2>\n{content}\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{trade_date} A股复盘报告</title>
  <script>(function(){{var t=localStorage.getItem('theme')||'dark';document.documentElement.setAttribute('data-theme',t);}})()</script>
  <style>{REVIEW_CSS}</style>
</head>
<body>
  <button class="theme-toggle" onclick="(function(){{var d=document.documentElement;var c=d.getAttribute('data-theme')==='dark'?'light':'dark';d.setAttribute('data-theme',c);localStorage.setItem('theme',c);}})()">切换主题</button>
  <h1>{trade_date} A股市场复盘报告 <span>V4</span></h1>
  <div class="subtitle">生成时间: {datetime.now().isoformat()} | 情绪三件套驱动 | 数据驱动</div>
  {metric_strip}
  {toc}
  {sections}
</body>
</html>"""

    out_path = data_dir / "review.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("review_v4 → %s (%d bytes)", out_path, len(html))
    return html


def build_and_save(data_dir: Path) -> str:
    """生成 review HTML 并保存。"""
    return build_review_html(data_dir)


def build_review_data(data_dir: Path) -> dict:
    """生成结构化 JSON 供前端原生渲染（不生成 HTML）。

    返回七区数据 + 情绪数据 + metric strip，前端用 React + ECharts 原生渲染。
    """
    data_dir = Path(data_dir)
    computed = _load_json(str(data_dir / "_computed.json"))
    tu = _load_json(str(data_dir / "tushare.json"))
    py = _load_json(str(data_dir / "pywencai.json"))
    ak = _load_json(str(data_dir / "akshare.json"))
    th = _load_json(str(data_dir / "ths_hot.json"))
    ll = _load_json(str(data_dir / "legulegu.json"))
    dx = _load_json(str(data_dir / "duanxianxia.json"))
    ztk = _load_json(str(data_dir / "zhangtingke.json"))
    tp = _load_json(str(data_dir / "trend_pool.json"))
    trade_date = computed.get("trade_date", data_dir.name)

    mh = computed.get("market_heat", {})
    st = computed.get("short_term_sentiment", {})
    tr = computed.get("trend_sentiment", {})
    advance = computed.get("advance_stats", {})
    loss = computed.get("loss_effect", {})
    part = computed.get("participation_check", {})
    ebb = computed.get("ebb_risk_check", {})
    crash = computed.get("crash_signals", {})
    ht = computed.get("height_trend", {})
    ladder_data = computed.get("limit_ladder", {})
    zh = computed.get("zhangtingke_height", {})

    # metric strip
    dm = tu.get("daily_market", {})
    indexes = tu.get("indexes", {})
    idx_cards = []
    for code in ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"]:
        idx = indexes.get(code, {})
        if idx:
            pct = idx.get("pct_chg", 0)
            idx_cards.append({"code": code, "name": idx.get("name", ""), "close": idx.get("close", 0), "pct_chg": pct})

    # s0 诊断
    diagnosis = [
        {"name": "市场热度", "value": str(mh.get("score", 0)), "zone": mh.get("zone", "")},
        {"name": "短线情绪", "value": str(st.get("score", 0)), "zone": st.get("zone", "")},
        {"name": "趋势情绪", "value": str(tr.get("score", 0)), "zone": tr.get("zone", "")},
        {"name": "参与度", "value": "", "zone": part.get("verdict", "")},
        {"name": "退潮风险", "value": str(ebb.get("signal_count", 0)), "zone": ebb.get("verdict", "")},
        {"name": "崩塌信号", "value": "", "zone": "已触发" if crash.get("any_triggered") else "未触发"},
        {"name": "亏钱效应", "value": "", "zone": loss.get("severity", "")},
        {"name": "晋级率", "value": f"{advance.get('advance_rate', '--')}%", "zone": advance.get("source_quality", "")},
    ]

    # s0 风险清单
    risks = []
    for name, sig in (ebb.get("signals") or {}).items():
        if isinstance(sig, dict):
            risks.append({"name": name, "triggered": sig.get("triggered", False), "available": sig.get("available", False)})
    for s in (crash.get("signals") or []):
        risks.append({"name": s.get("name", ""), "triggered": s.get("triggered", False), "status": s.get("status", ""), "evidence": s.get("evidence", "")})
    risks.append({"name": "亏钱效应", "triggered": False, "status": loss.get("severity", ""), "evidence": ""})

    # s1 指数表
    index_rows = []
    for code in ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH", "000016.SH", "399303.SZ", "399905.SZ"]:
        idx = indexes.get(code, {})
        if idx:
            index_rows.append({"code": code, "name": idx.get("name", ""), "close": idx.get("close", 0), "pct_chg": idx.get("pct_chg", 0)})

    # s2 退潮表
    part_conditions = []
    for name, cond in (part.get("conditions") or {}).items():
        if isinstance(cond, dict):
            ok = cond.get("ok")
            part_conditions.append({"name": name, "value": cond.get("value", ""), "ok": ok, "available": cond.get("available", False)})

    # s2 题材
    lu = py.get("limit_up", {})
    themes_py = lu.get("themes", [])[:8]
    ths_tags = (th.get("reason_tags") or [])[:8]

    # s2 百日新高
    nh = py.get("new_high_100d", {})
    new_high_stocks = []
    if nh.get("status") == "ok":
        new_high_stocks = nh.get("stocks", [])[:10]

    # s3 连板网格
    ladder_by_height = ladder_data.get("ladder_by_height") or lu.get("ladder", {})
    ladder_grid = []
    for level in sorted(ladder_by_height.keys(), key=lambda x: int(x) if str(x).isdigit() else 0, reverse=True):
        stocks_raw = ladder_by_height.get(level, [])
        names = [s if isinstance(s, str) else s.get("name", "") for s in stocks_raw[:8]]
        ladder_grid.append({"level": str(level), "count": len(stocks_raw), "names": names})

    # s3 高度历史
    height_history = (zh.get("days") or [])

    # s3 退潮信号
    ebb_signals = []
    for name, sig in (ebb.get("signals") or {}).items():
        if isinstance(sig, dict):
            ebb_signals.append({"name": name, "triggered": sig.get("triggered", False), "available": sig.get("available", False), "value": sig.get("value"), "baseline": sig.get("baseline")})

    # s3 崩塌信号
    crash_signals = []
    for s in (crash.get("signals") or []):
        crash_signals.append({"name": s.get("name", ""), "triggered": s.get("triggered", False), "status": s.get("status", ""), "evidence": s.get("evidence", "")})

    # s4 资金流
    sectors = ak.get("sector_fund_flow", [])
    top_in = sorted(sectors, key=lambda x: float(x.get("net_inflow_yi", 0)), reverse=True)[:5]
    top_out = sorted(sectors, key=lambda x: float(x.get("net_inflow_yi", 0)))[:5]

    # s5 关注名单
    candidates = []
    for s in sorted(lu.get("stocks", []), key=lambda x: int(x.get("limit_times", 1)), reverse=True)[:6]:
        candidates.append({"code": s.get("code", ""), "name": s.get("name", ""), "limit_times": s.get("limit_times", 1), "reason": s.get("reason", "")})

    # s6 仓位
    score = mh.get("score", 50)
    if score >= 70:
        position = {"band": "高仓位(70-90%)", "action": "积极参与主线,关注退潮信号"}
    elif score >= 50:
        position = {"band": "中等仓位(40-60%)", "action": "脉冲处理,关注主线确认"}
    elif score >= 30:
        position = {"band": "低仓位(10-30%)", "action": "谨慎参与,等待情绪修复"}
    else:
        position = {"band": "空仓或极低仓位(0-10%)", "action": "规避风险,等待冰点反转"}
    scenes = [
        {"name": "走强", "condition": "热度>70 + 参与度=参与 + 退潮未触发", "tone": "positive"},
        {"name": "震荡", "condition": "热度40-70 + 参与度=脉冲处理", "tone": "neutral"},
        {"name": "走弱", "condition": "热度<40 或 退潮确认 或 崩塌触发", "tone": "negative"},
    ]

    # ── s1 图表数据: 指数K线 + 上涨家数历史 + 行业宽度 + 期货融资 ──
    # 指数 K线数据 (close + ma5/ma10/ma20 + cci5)
    kline_data = []
    for code in ["000985.CSI", "000001.SH", "399006.SZ"]:
        idx = indexes.get(code, {})
        if idx:
            kline_data.append({"code": code, "name": idx.get("name", ""), "close": idx.get("close"), "ma5": idx.get("ma5"), "ma10": idx.get("ma10"), "ma20": idx.get("ma20"), "cci5": idx.get("cci5")})

    # K线历史 (全A OHLCV + MA + CCI5) — 用于 candlestick 图
    kline_history = []
    for d in (tu.get("kline_history") or [])[-130:]:
        kline_history.append({
            "date": d.get("date", ""), "open": d.get("open"), "high": d.get("high"),
            "low": d.get("low"), "close": d.get("close"), "vol": d.get("vol"),
            "ma5": d.get("ma5"), "ma10": d.get("ma10"), "ma20": d.get("ma20"), "cci5": d.get("cci5"),
        })

    # 上涨家数历史 (advance_decline.history — 字段名 up/down)
    ad_history = (tu.get("advance_decline") or {}).get("history", [])
    up_count_history = [{"date": d.get("date", ""), "up_count": d.get("up", 0), "down_count": d.get("down", 0), "total_amount_yi": d.get("total_amount_yi", 0)} for d in ad_history[-30:]] if ad_history else []

    # 行业宽度热力表 (legulegu)
    sw_width = (ll.get("sw_market_width") or {}).get("data", {}) if isinstance(ll, dict) else {}
    width_heat = []
    for sw_code, rows in (sw_width or {}).items() if sw_width else []:
        if rows and isinstance(rows, list):
            latest = rows[-1] if rows else {}
            width_heat.append({"code": sw_code, "ma5": latest.get("value5"), "ma10": latest.get("value10"), "ma20": latest.get("value20"), "ma60": latest.get("value60")})

    # 期货+融资 (tushare margin + futures)
    margin_obj = tu.get("margin") or {}
    margin_data = margin_obj.get("latest", {}) if isinstance(margin_obj, dict) else {}
    margin_history = []
    for d in (margin_obj.get("history") or [])[-30:]:
        margin_history.append({"date": d.get("date", ""), "rzye_yi": d.get("rzye_yi"), "rz_net_buy_yi": d.get("rz_net_buy_yi")})
    futures_data = []
    futures_raw = tu.get("futures") or {}
    if isinstance(futures_raw, dict):
        for k, v in futures_raw.items():
            if isinstance(v, dict):
                futures_data.append({"contract": k, "pct_chg": v.get("pct_chg"), "open_interest": v.get("open_interest"), "oi_change": v.get("oi_change")})

    # 拥挤度 (legulegu)
    congestion_latest = ll.get("congestion_latest", {}) if isinstance(ll, dict) else {}
    congestion_table = (ll.get("congestion_table_1") or {}).get("rows", []) if isinstance(ll, dict) else []

    # ── s3 晋级率历史 (从 height_trend.days) ──
    advance_history = []
    for day in (ht.get("days") or []):
        advance_history.append({
            "date": day.get("date", ""),
            "advance_rate": day.get("advance_rate"),
            "premium_rate": day.get("premium_rate"),
            "limit_up_count": day.get("limit_up_count"),
            "max_board": day.get("max_board"),
            "seal_rate": day.get("seal_rate"),
        })

    # ── s3 连板详细 (zhangtingke ladder_stocks) ──
    ladder_detail = []
    for s in (ztk.get("ladder_stocks") or []):
        ladder_detail.append({"code": s.get("code", ""), "name": s.get("name", ""), "limit_times": s.get("limit_times"), "theme_name": s.get("theme_name", ""), "turnover_pct": s.get("turnover_pct"), "amount_yi": s.get("amount_yi")})

    # ── s4 机构数据 (trend_pool) ──
    tp_p0 = (tp.get("p0") or [])[:6] if isinstance(tp, dict) else []
    tp_p1 = (tp.get("p1") or [])[:6] if isinstance(tp, dict) else []
    tp_themes = (tp.get("themes") or [])[:10] if isinstance(tp, dict) else []
    tp_sectors = (tp.get("sectors") or []) if isinstance(tp, dict) else []

    # ── s4 短线侠强度榜 (duanxianxia) ──
    dx_strength = (dx.get("sector_strength") or [])[:10] if isinstance(dx, dict) else []

    # ── s4 机构图表数据: 全量板块按 abs(净流入) 排序 (对齐原版 60 板块) ──
    all_sectors = ak.get("sector_fund_flow") or []
    sector_treemap = []
    for s in sorted(all_sectors, key=lambda x: abs(float(x.get("net_inflow_yi", 0) or 0)), reverse=True)[:60]:
        sector_treemap.append({"name": s.get("name", ""), "value": s.get("net_inflow_yi", 0), "pct_chg": s.get("pct_chg", 0)})

    return {
        "trade_date": trade_date,
        "metric_strip": {
            "indexes": idx_cards,
            "up_count": dm.get("up_count", 0),
            "down_count": dm.get("down_count", 0),
            "flat_count": dm.get("flat_count", 0),
            "total_amount_yi": dm.get("total_amount_yi", 0),
            "advance_rate": advance.get("advance_rate"),
        },
        "emotion": {
            "market_heat": mh,
            "short_term_sentiment": st,
            "trend_sentiment": tr,
            "loss_effect": loss,
            "height_trend": ht,
            "daily_summary": computed.get("daily_summary", ""),
        },
        "sections": {
            "s0": {
                "title": SECTION_TITLES["s0"],
                "diagnosis": diagnosis,
                "risks": risks,
                "llm_block": "decision_summary",
            },
            "s1": {
                "title": SECTION_TITLES["s1"],
                "indexes": index_rows,
                "kline_data": kline_data,
                "kline_history": kline_history,
                "up_count_history": up_count_history,
                "width_heat": width_heat,
                "futures": futures_data,
                "margin": margin_data,
                "margin_history": margin_history,
                "congestion": {"latest": congestion_latest, "table": congestion_table[-10:] if congestion_table else []},
                "llm_block": "combined_environment_analysis",
            },
            "s2": {
                "title": SECTION_TITLES["s2"],
                "participation": {"conditions": part_conditions, "verdict": part.get("verdict", ""), "satisfied": part.get("satisfied", 0), "total": part.get("total", 4)},
                "ebb_risk": {"verdict": ebb.get("verdict", ""), "signal_count": ebb.get("signal_count", 0)},
                "themes_pywencai": themes_py,
                "themes_ths": ths_tags,
                "new_high": {"status": nh.get("status", "unavailable"), "stocks": new_high_stocks},
                "llm_block": "theme_deep_dive",
            },
            "s3": {
                "title": SECTION_TITLES["s3"],
                "ladder_grid": ladder_grid,
                "height_history": height_history,
                "emotion_scores": {"market_heat": mh.get("score", 0), "short_term": st.get("score", 0), "trend": tr.get("score", 0)},
                "emotion_zones": {"market_heat": mh.get("zone", ""), "short_term": st.get("zone", ""), "trend": tr.get("zone", "")},
                "emotion_inputs": {"limit_up_count": st.get("inputs", {}).get("limit_up_count"), "seal_rate": st.get("inputs", {}).get("seal_rate"), "max_board": st.get("inputs", {}).get("max_board")},
                "ebb_signals": ebb_signals,
                "crash_signals": crash_signals,
                "advance": {"advance_rate": advance.get("advance_rate"), "premium_rate": advance.get("premium_rate")},
                "advance_history": advance_history,
                "ladder_detail": ladder_detail,
                "llm_block": "sentiment_deep_dive",
            },
            "s4": {
                "title": SECTION_TITLES["s4"],
                "sector_flow": {"top_in": top_in, "top_out": top_out},
                "sector_treemap": sector_treemap,
                "institution": {"p0": tp_p0, "p1": tp_p1, "themes": tp_themes, "sectors": tp_sectors},
                "dx_strength": dx_strength,
                "llm_block": "trend_institution_analysis",
            },
            "s5": {
                "title": SECTION_TITLES["s5"],
                "candidates": candidates,
                "llm_block": "watchlist_final",
            },
            "s6": {
                "title": SECTION_TITLES["s6"],
                "position": position,
                "scenes": scenes,
                "llm_block": "summary_lessons",
        },
    }
    }
