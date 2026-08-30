"""Standalone MarketLab interaction test (Microsoft Edge, headless)."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "e2e" / "results"
SECTORS = [
    "信息技术-电子-半导体", "信息技术-通信-通信设备", "信息技术-电子-消费电子",
    "信息技术-软件-软件开发", "工业-电力设备-电池", "可选消费-汽车-汽车零部件",
    "金融-银行-股份制银行", "日常消费-食品饮料-白酒", "能源-煤炭-焦煤",
    "原材料-钢铁-普钢", "房地产-房地产开发", "工业-建筑装饰-基础建设",
]


def _json(route: Route, payload: object) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))


def _radar_row(index: int, sector: str) -> dict:
    rank = index + 1
    rank_pct = (12 - index) / 12 * 100
    row = {
        "rank": rank, "sector": sector, "as_of": "2026-08-28", "score": 9.16 * rank_pct + 61.53,
        "return_pct": 2.4 - index * 0.38, "flow_yuan": (6 - index) * 2.1e8,
        "flow_ratio_pct": 8.4 - index * 1.45, "ema_swing_pct": 6.8 - index,
        "positive_days_30": max(0, 10 - index), "swing_ratio_pct": 6.8 - index,
        "swing_amount_yuan": (6 - index) * 1.6e8,
    }
    for metric, slope, intercept in (("swing", 9.16, 61.53), ("ratio", 10.74, -10.61), ("amount", 11.11, -28.26)):
        row.update({
            f"{metric}_rank": rank, f"{metric}_rank_pct": rank_pct,
            f"{metric}_score": slope * rank_pct + intercept,
            f"{metric}_rank_change_1d": 2 - index % 4, f"{metric}_rank_change_3d": 3 - index % 6,
            f"{metric}_rank_change_5d": 4 - index % 8, f"{metric}_top_30d": max(0, 10 - index),
            f"{metric}_bottom_30d": max(0, index - 5),
        })
    return row


RADAR_ROWS = [_radar_row(index, name) for index, name in enumerate(SECTORS)]


def _strategy(index: int, basis: str) -> dict:
    risk = (index + 1) * 0.35
    middle = [100_000 * (1 + step * risk / 1000) for step in range(21)]
    return {
        "id": f"{basis}-{index}", "name": f"{'风险' if basis == 'decision' else 'Kelly'}档位 {index + 1}",
        "basis": basis, "risk_pct": risk, "p10_final": 91_000 + index * 1000,
        "p50_final": 112_000 + index * 3000, "p90_final": 145_000 + index * 5000,
        "p80_drawdown_pct": 8 + index * 2, "p50_drawdown_pct": 6 + index,
        "p95_drawdown_pct": 14 + index * 3, "ruin_probability_pct": index * 0.2,
        "halve_probability_pct": index * 0.8, "p10_path": [value * 0.94 for value in middle],
        "median_path": middle, "p90_path": [value * 1.06 for value in middle],
        "sample_paths": [middle, [value * 0.98 for value in middle]],
    }


def handle_api(route: Route) -> None:
    parsed = urlparse(route.request.url)
    path = parsed.path
    if path == "/api/settings":
        return _json(route, {"mode": "free", "tier_label": "Free", "current_endpoint": "", "probe_log": [], "missing_caps": [], "extras_caps": [], "onboarding_completed": True, "tickflow_api_key_masked": "", "has_tickflow_key": False, "ai_provider": "", "ai_base_url": "", "ai_api_key_masked": "", "has_ai_key": False, "ai_model": "", "ai_user_agent": ""})
    if path == "/api/settings/preferences":
        return _json(route, {"realtime_quotes_enabled": False, "indices_nav_pinned": False, "sidebar_index_symbols": [], "nav_order": [], "nav_hidden": [], "sse_refresh_pages": {}, "pipeline_pull_a_share": True, "pipeline_pull_etf": True, "pipeline_pull_index": True})
    if path == "/api/capabilities":
        return _json(route, {"label": "Free", "capabilities": {}})
    if path == "/api/data/version":
        return _json(route, {"version": "e2e"})
    if path == "/api/intraday/status":
        return _json(route, {"enabled": False, "running": False, "interval_s": 10, "symbol_count": 0})
    if path == "/api/intraday/indices":
        return _json(route, {"rows": [], "count": 0})
    if path == "/api/market-lab/etf-momentum":
        return _json(route, {"available": True, "unit": "percent", "formula": "1d x 0.4 + 5d x 0.3 + 20d x 0.2 + 50d x 0.1", "rows": [{"rank": 1, "previous_rank": 2, "rank_change": 1, "symbol": "510300.SH", "name": "沪深300ETF", "as_of": "2026-08-28", "return_1d_pct": 1.2, "return_5d_pct": 3.4, "return_20d_pct": 8.6, "return_50d_pct": 12.1, "weighted_momentum_pct": 5.43, "slope_momentum_pct": 18.5, "volume_ratio_5_20": 1.22, "momentum_change_pct": 0.31}]})
    if path == "/api/market-lab/sector-flow":
        return _json(route, {"available": True, "quality": "proxy", "basis": "clv_amount_pressure", "unit": "CNY", "detail": "代理值仅表示收盘位置 x 成交额, 不等同主力净流入", "dates": ["2026-08-26", "2026-08-27", "2026-08-28"], "rows": [{"sector": name, "total_flow_yuan": (6 - index) * 2e8, "points": [{"date": f"2026-08-{day}", "flow_yuan": (6 - index) * day * 1e7} for day in (26, 27, 28)]} for index, name in enumerate(SECTORS)]})
    if path == "/api/market-lab/sector-radar":
        history = {name: [{"date": f"2026-08-{day}", "swing_rank": min(12, row["rank"] + 28 - day), "ratio_rank": row["rank"], "amount_rank": row["rank"], "swing_rank_pct": row["swing_rank_pct"], "ratio_rank_pct": row["ratio_rank_pct"], "amount_rank_pct": row["amount_rank_pct"]} for day in range(21, 29)] for name, row in zip(SECTORS, RADAR_ROWS, strict=True)}
        return _json(route, {"available": True, "quality": "proxy", "basis": "clv_amount_pressure", "detail": "资金项为收盘位置 x 成交额代理, 不等同主力净流入", "as_of": "2026-08-28", "available_dates": ["2026-08-27", "2026-08-28"], "universe_size": 12, "unit": "CNY", "rows": RADAR_ROWS, "rank_history": history})
    if path == "/api/market-lab/sector-members":
        sector = parse_qs(parsed.query).get("sector", [SECTORS[0]])[0]
        stocks = [{"symbol": f"60000{index}.SH", "name": f"样本股{index + 1}", "return_pct": 4.2 - index, "main_net_amount": (3 - index) * 1e7, "active_buy_net_amount": None} for index in range(6)]
        metrics = {key: {"top": stocks[:3], "bottom": list(reversed(stocks[-3:]))} for key in ("return_pct", "main_net_amount", "active_buy_net_amount")}
        return _json(route, {"available": True, "as_of": "2026-08-28", "sector": sector, "member_count": 6, "flow_quality": "proxy", "active_quality": "unavailable", "metrics": metrics})
    if path == "/api/market-lab/macro-dispersion":
        dates = [f"2026-08-{day:02d}" for day in range(10, 29)]
        contributions = [{"name": name.split("-")[1], "contribution_pct": 18 - index, "direction": 1 if index < 6 else -1, "state": "强者扩张" if index < 6 else "弱者下沉"} for index, name in enumerate(SECTORS)]
        return _json(route, {"available": True, "as_of": "2026-08-28", "window": "daily industry cross-section", "unit": "percent", "industry_level": 2, "basis": "本地同花顺二级行业当前成分快照回看历史的成分股市值加权日收益横截面", "mean_pct": 0.2, "dispersion": 53.8, "ma3": 52, "percentile": 76.5, "ma3_percentile": 72.5, "change_1d": 1.8, "change_5d": 9, "zone": "正常区间", "industry_count": 31, "history": [{"date": value, "dispersion": 32 + index * 1.2, "ma3": 31 + index * 1.2, "mean_pct": 0.2, "industry_count": 31} for index, value in enumerate(dates)], "indices": [{"symbol": "000001.SH", "label": "上证", "name": "上证指数", "points": [{"date": value, "normalized": index * 0.4} for index, value in enumerate(dates)]}], "contributions": contributions, "contribution_windows": {str(days): {"high": contributions[:6], "low": contributions[6:]} for days in (1, 3, 5, 10)}})
    if path == "/api/market-lab/position":
        return _json(route, {"shares": 1000, "market_value": 10_000, "risk_budget": 1000, "planned_loss": 1000, "capital_usage_pct": 10, "reward_risk": 10, "target_price": 20, "target_r": 10, "breakeven_price": 14, "breakeven_r": 4, "projected_profit": 10_000, "actual_risk_pct": 1, "stop_pct": 10, "target_upside_pct": 100, "risk_level": "标准风险", "cash_limited": False, "warnings": ["目标涨幅超过 50%, 请核对预期是否合理"]})
    if path == "/api/market-lab/pit":
        return _json(route, {"target": 12, "depth_pct": 20, "upside_pct": 33.3333})
    if path == "/api/market-lab/drawdown":
        return _json(route, {"actual_r": 10, "draw_amount": 1, "exit_price": 19, "max_profit_pct": 100, "locked_profit_pct": 90, "target_achieved": True})
    if path == "/api/market-lab/simulate":
        strategies = [_strategy(index, "decision") for index in range(5)] + [_strategy(index, "theory") for index in range(8)]
        return _json(route, {"paths": 1000, "trades": 100, "kelly_pct": 25, "half_kelly_pct": 12.5, "expectancy_r": 0.375, "break_even_pct": 40, "p10_final": 87_000, "p50_final": 128_000, "p90_final": 185_000, "p50_max_drawdown_pct": 12, "p95_max_drawdown_pct": 25, "loss_probability_pct": 18, "sample_paths": [[100_000, 101_500, 100_500]], "reverse": {"recommended_risk_pct": 1.4, "test_risk_pct": 0.7, "target_required_risk_pct": 1.2, "drawdown_risk_pct": 1.4, "limiting_factor": "drawdown", "target_reachable": True, "target_return_pct": 50}, "strategies": strategies, "distribution": {"bins": [{"from": 80_000 + index * 5000, "to": 85_000 + index * 5000, "count": 20 + index, "density": 0.03 + index * 0.01} for index in range(12)]}})
    return _json(route, {"rows": [], "count": 0})


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.add_init_script("window.EventSource = class { close(){} addEventListener(){} }")
        page.on("console", lambda msg: errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror:{exc}"))
        page.route("**/api/**", handle_api)
        page.route("**/health", lambda route: _json(route, {"status": "ok", "version": "e2e", "mode": "free"}))
        page.goto("http://127.0.0.1:4173/market-lab", wait_until="networkidle")
        page.get_by_test_id("market-lab").wait_for()
        page.get_by_text("510300.SH", exact=True).wait_for()
        page.get_by_role("button", name="板块资金").click()
        page.get_by_test_id("sector-rank-calendar").locator("canvas").wait_for()
        page.get_by_test_id("sector-member-evidence").get_by_text("样本股1", exact=True).wait_for()
        page.get_by_role("button", name="单日净额").click()
        page.screenshot(path=str(RESULTS / "market-lab-sector.png"), full_page=True)
        page.get_by_role("button", name="宏观离散度").click()
        page.get_by_test_id("macro-dispersion-combined-chart").locator("canvas").wait_for()
        page.get_by_text("本地同花顺二级行业当前成分快照回看历史", exact=False).wait_for()
        page.get_by_role("button", name="5日").click()
        page.screenshot(path=str(RESULTS / "market-lab-macro.png"), full_page=True)
        page.get_by_role("button", name="仓位与模拟").click()
        page.get_by_role("button", name="计算仓位").click()
        page.get_by_text("标准风险", exact=True).wait_for()
        page.get_by_role("button", name="计算出坑").click()
        page.get_by_text("33.33%", exact=True).wait_for()
        page.get_by_role("button", name="计算保护位").click()
        page.get_by_text("已达到", exact=True).wait_for()
        page.get_by_role("button", name="运行模拟").click()
        page.get_by_test_id("simulation-evidence").wait_for()
        page.get_by_role("button", name="Kelly 理论档").click()
        page.get_by_role("button", name="Kelly档位 8").wait_for()
        page.get_by_role("button", name="应用满额到仓位").click()
        assert abs(float(page.get_by_label("单笔风险(小数)").input_value()) - 0.014) < 1e-9
        page.screenshot(path=str(RESULTS / "market-lab-risk.png"), full_page=True)
        page.set_viewport_size({"width": 768, "height": 1000})
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="板块资金").click()
        page.get_by_test_id("sector-member-evidence").wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.screenshot(path=str(RESULTS / "market-lab-sector-narrow.png"), full_page=True)
        page.get_by_role("button", name="仓位与模拟").click()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.screenshot(path=str(RESULTS / "market-lab-risk-narrow.png"), full_page=True)
        browser.close()
    actionable = [error for error in errors if "ERR_CONNECTION_CLOSED" not in error]
    if actionable:
        raise AssertionError("browser errors:\n" + "\n".join(actionable))
    print("MARKET_LAB_E2E_OK")


if __name__ == "__main__":
    main()
