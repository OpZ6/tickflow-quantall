"""多日驾驶舱:跨日快照 + 题材生命周期 + 5-10-20日窗口。

从 QuantX report_catalog.py 移植精简版。
扫描 data/quantx/ 下所有日期目录,提取每日情绪指标,构建 catalog.json。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from app.services.emotion_state import _load_json

logger = logging.getLogger(__name__)


def _extract_record(date_dir: Path) -> dict | None:
    """提取单日快照。"""
    trade_date = date_dir.name
    computed = _load_json(str(date_dir / "_computed.json"))
    has_computed = bool(computed)
    has_review = (date_dir / "review.html").exists()

    if not has_computed and not has_review:
        return None

    if has_review:
        stage = "complete"
    elif has_computed:
        stage = "data_only"
    else:
        stage = "draft_only"

    mh = computed.get("market_heat", {})
    st = computed.get("short_term_sentiment", {})
    tr = computed.get("trend_sentiment", {})
    advance = computed.get("advance_stats", {})
    loss = computed.get("loss_effect", {})
    part = computed.get("participation_check", {})
    ebb = computed.get("ebb_risk_check", {})
    crash = computed.get("crash_signals", {})
    height = computed.get("height_trend", {})

    py = _load_json(str(date_dir / "pywencai.json"))
    lu = py.get("limit_up", {})
    themes = lu.get("themes", [])[:5]
    theme_list = [{"name": t.get("name", ""), "count": t.get("count", 0)} for t in themes]

    metrics = {
        "market_heat_score": mh.get("score"),
        "market_heat_zone": mh.get("zone"),
        "short_term_sentiment_score": st.get("score"),
        "short_term_sentiment_zone": st.get("zone"),
        "trend_sentiment_score": tr.get("score"),
        "trend_sentiment_zone": tr.get("zone"),
        "limit_up_count": st.get("inputs", {}).get("limit_up_count"),
        "seal_rate": st.get("inputs", {}).get("seal_rate"),
        "max_board": st.get("inputs", {}).get("max_board"),
        "advance_rate": advance.get("advance_rate"),
        "premium_rate": advance.get("premium_rate"),
        "loss_severity": loss.get("severity"),
        "limit_down_count": loss.get("limit_down_count"),
        "participation_verdict": part.get("verdict"),
        "participation_satisfied": part.get("satisfied"),
        "ebb_risk_verdict": ebb.get("verdict"),
        "ebb_signal_count": ebb.get("signal_count"),
        "crash_triggered": crash.get("any_triggered"),
        "previous_high_5d": height.get("previous_high_5d"),
        "height_compressed": height.get("height_compressed"),
    }

    return {
        "trade_date": trade_date,
        "stage": stage,
        "metrics": metrics,
        "themes": theme_list,
        "artifacts": {
            "computed": "_computed.json" if has_computed else None,
            "review": "review.html" if has_review else None,
        },
    }


def _compute_deltas(records: list[dict]) -> None:
    """计算与前日的 delta。"""
    for i, rec in enumerate(records):
        if i == 0:
            rec["deltas"] = {}
            continue
        prev = records[i - 1].get("metrics", {})
        curr = rec.get("metrics", {})
        deltas = {}
        for key in ("market_heat_score", "short_term_sentiment_score", "trend_sentiment_score",
                     "limit_up_count", "seal_rate", "advance_rate", "premium_rate"):
            p = prev.get(key)
            c = curr.get(key)
            if p is not None and c is not None:
                deltas[key] = round(c - p, 2)
        rec["deltas"] = deltas


def _build_change_summary(rec: dict, prev: dict | None) -> str:
    """生成与前日的变化摘要。"""
    if not prev:
        return ""
    parts = []
    prev_heat = prev.get("metrics", {}).get("market_heat_zone", "")
    curr_heat = rec.get("metrics", {}).get("market_heat_zone", "")
    if prev_heat and curr_heat and prev_heat != curr_heat:
        parts.append(f"{prev_heat}→{curr_heat}")
    d = rec.get("deltas", {})
    if d.get("market_heat_score"):
        parts.append(f"热度{d['market_heat_score']:+.0f}")
    if d.get("limit_up_count"):
        parts.append(f"涨停{d['limit_up_count']:+.0f}")
    return "；".join(parts) if parts else "持平"


def _extract_theme_events(records: list[dict]) -> list[dict]:
    """提取题材生命周期事件。"""
    events = []
    theme_history: dict[str, list[str]] = {}
    for rec in records:
        td = rec["trade_date"]
        seen_today = set()
        for theme in rec.get("themes", []):
            name = theme.get("name", "")
            if not name or name in seen_today:
                continue
            seen_today.add(name)
            history = theme_history.setdefault(name, [])
            prev_dates = [d for d in history if d != td]
            if not prev_dates:
                lifecycle = "new"
            else:
                last_date = prev_dates[-1]
                gap = records.index(rec) - records.index(next(r for r in records if r["trade_date"] == last_date))
                if gap > 3:
                    lifecycle = "continuing"
                else:
                    lifecycle = "strengthening" if theme.get("count", 0) > 3 else "weakening"
            history.append(td)
            events.append({
                "trade_date": td,
                "name": name,
                "count": theme.get("count", 0),
                "lifecycle": lifecycle,
            })
    return events


def build_catalog(quantx_dir: Path) -> dict:
    """构建多日驾驶舱 catalog.json。

    Args:
        quantx_dir: data/quantx/ 目录
    Returns:
        catalog dict
    """
    quantx_dir = Path(quantx_dir)
    records = []
    if quantx_dir.exists():
        for item in sorted(quantx_dir.iterdir(), key=lambda p: p.name):
            if not item.is_dir() or not item.name.isdigit():
                continue
            rec = _extract_record(item)
            if rec:
                records.append(rec)

    _compute_deltas(records)
    for i, rec in enumerate(records):
        rec["change_summary"] = _build_change_summary(rec, records[i - 1] if i > 0 else None)

    theme_events = _extract_theme_events(records)

    stats = {
        "total_dates": len(records),
        "complete": sum(1 for r in records if r["stage"] == "complete"),
        "data_only": sum(1 for r in records if r["stage"] == "data_only"),
        "draft_only": sum(1 for r in records if r["stage"] == "draft_only"),
    }

    catalog = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "records": records,
        "theme_events": theme_events,
    }

    out_path = quantx_dir / "catalog.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    logger.info("market_catalog → %s (%d dates)", out_path, len(records))
    return catalog


def build_catalog_html(catalog: dict) -> str:
    """生成多日驾驶舱 index.html。"""
    records = catalog.get("records", [])
    stats = catalog.get("stats", {})

    rows = ""
    for rec in reversed(records):
        m = rec.get("metrics", {})
        heat = m.get("market_heat_score")
        heat_color = _score_color(heat) if heat is not None else "#8b949e"
        review_link = f'<a href="quantx/{rec["trade_date"]}/review.html">查看</a>' if rec.get("artifacts", {}).get("review") else ""
        rows += f"""<tr>
          <td>{rec["trade_date"]}</td>
          <td><span class="score-badge" style="background:{heat_color}">{heat or "--"}</span> {m.get("market_heat_zone", "")}</td>
          <td>{m.get("short_term_sentiment_score", "--")} ({m.get("short_term_sentiment_zone", "")})</td>
          <td>{m.get("trend_sentiment_score", "--")} ({m.get("trend_sentiment_zone", "")})</td>
          <td>{m.get("limit_up_count", "--")}</td>
          <td>{m.get("seal_rate", "--")}%</td>
          <td>{m.get("max_board", "--")}</td>
          <td>{m.get("advance_rate", "--")}%</td>
          <td>{m.get("participation_verdict", "")}</td>
          <td>{m.get("ebb_risk_verdict", "")}</td>
          <td>{(m.get("crash_triggered", False) and "是") or "否"}</td>
          <td>{rec.get("change_summary", "")}</td>
          <td>{review_link}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>TickFlow 多日驾驶舱</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:0;padding:20px}}
h1{{font-size:1.4em}} .stats{{color:var(--muted);font-size:0.85em;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;font-size:0.8em}}
th,td{{border:1px solid var(--border);padding:6px 8px;text-align:left}}
th{{background:var(--card);position:sticky;top:0}}
.score-badge{{display:inline-block;width:28px;height:20px;line-height:20px;text-align:center;border-radius:4px;color:#fff;font-weight:600}}
a{{color:#58a6ff}}
</style></head>
<body>
<h1>TickFlow 多日驾驶舱</h1>
<div class="stats">总日数: {stats.get("total_dates", 0)} | 完整报告: {stats.get("complete", 0)} | 仅数据: {stats.get("data_only", 0)}</div>
<table><thead><tr>
  <th>日期</th><th>市场热度</th><th>短线情绪</th><th>趋势情绪</th>
  <th>涨停</th><th>封板率</th><th>最高板</th><th>晋级率</th>
  <th>参与度</th><th>退潮</th><th>崩塌</th><th>变化</th><th>报告</th>
</tr></thead><tbody>{rows}</tbody></table>
</body></html>"""
    return html


def _score_color(score) -> str:
    if score is None: return "#8b949e"
    if score >= 70: return "#ef4444"
    if score >= 60: return "#f97316"
    if score >= 40: return "#3b82f6"
    if score >= 30: return "#6b7280"
    return "#1e40af"


def build_and_save_catalog(quantx_dir: Path) -> tuple[dict, str]:
    """构建 catalog.json + index.html,返回 (catalog, html)。"""
    catalog = build_catalog(quantx_dir)
    html = build_catalog_html(catalog)
    html_path = Path(quantx_dir) / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("market_catalog html → %s", html_path)
    return catalog, html
