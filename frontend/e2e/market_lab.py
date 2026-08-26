"""Standalone Playwright smoke test for MarketLab (Microsoft Edge, headless)."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "e2e" / "results"


def _json(route: Route, payload: object) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))


def handle_api(route: Route) -> None:
    path = urlparse(route.request.url).path
    if path == "/api/settings":
        return _json(route, {
            "mode": "free", "tickflow_api_key_masked": "", "has_tickflow_key": False,
            "tier_label": "Free", "current_endpoint": "", "probe_log": [],
            "missing_caps": [], "extras_caps": [], "onboarding_completed": True,
            "ai_provider": "", "ai_base_url": "", "ai_api_key_masked": "",
            "has_ai_key": False, "ai_model": "", "ai_user_agent": "",
        })
    if path == "/api/settings/preferences":
        return _json(route, {
            "realtime_quotes_enabled": False, "indices_nav_pinned": False,
            "sidebar_index_symbols": [], "nav_order": [], "nav_hidden": [],
            "sse_refresh_pages": {}, "pipeline_pull_a_share": True,
            "pipeline_pull_etf": True, "pipeline_pull_index": True,
        })
    if path == "/api/capabilities":
        return _json(route, {"label": "Free", "capabilities": {}})
    if path == "/api/data/version":
        return _json(route, {"version": "e2e"})
    if path == "/api/intraday/status":
        return _json(route, {"enabled": False, "running": False, "interval_s": 10, "symbol_count": 0, "quote_age_ms": None, "is_trading_hours": False, "last_fetch_ms": None})
    if path == "/api/intraday/indices":
        return _json(route, {"rows": [], "count": 0})
    if path == "/api/market-lab/etf-momentum":
        return _json(route, {
            "available": True, "unit": "percent",
            "formula": "1d x 0.4 + 5d x 0.3 + 20d x 0.2 + 50d x 0.1",
            "rows": [
                {"rank": 1, "previous_rank": 2, "rank_change": 1, "symbol": "510300.SH", "name": "沪深300ETF", "as_of": "2026-08-21", "return_1d_pct": 1.2, "return_5d_pct": 3.4, "return_20d_pct": 8.6, "return_50d_pct": 12.1, "weighted_momentum_pct": 5.43, "slope_momentum_pct": 18.5, "volume_ratio_5_20": 1.22, "momentum_change_pct": 0.31},
                {"rank": 2, "previous_rank": 1, "rank_change": -1, "symbol": "512480.SH", "name": "半导体ETF", "as_of": "2026-08-21", "return_1d_pct": -0.3, "return_5d_pct": 2.5, "return_20d_pct": 10.2, "return_50d_pct": 20.0, "weighted_momentum_pct": 4.67, "slope_momentum_pct": 25.1, "volume_ratio_5_20": 1.08, "momentum_change_pct": -0.12},
            ],
        })
    if path == "/api/market-lab/sector-flow":
        return _json(route, {
            "available": True, "quality": "proxy", "basis": "clv_amount_pressure",
            "unit": "CNY", "detail": "代理值仅表示收盘位置 x 成交额, 不等同主力净流入",
            "dates": ["2026-08-19", "2026-08-20", "2026-08-21"],
            "rows": [
                {"sector": "半导体", "total_flow_yuan": 2.2e9, "points": [{"date": "2026-08-19", "flow_yuan": 4e8}, {"date": "2026-08-20", "flow_yuan": 7e8}, {"date": "2026-08-21", "flow_yuan": 1.1e9}]},
                {"sector": "银行", "total_flow_yuan": -8e8, "points": [{"date": "2026-08-19", "flow_yuan": -2e8}, {"date": "2026-08-20", "flow_yuan": -1e8}, {"date": "2026-08-21", "flow_yuan": -5e8}]},
            ],
        })
    if path == "/api/market-lab/sector-radar":
        names = ["半导体", "通信设备", "消费电子", "软件开发", "电池", "汽车零部件", "银行", "白酒", "煤炭", "钢铁", "房地产", "建筑装饰"]
        rows = []
        for index, name in enumerate(names):
            rank = index + 1
            rank_pct = (len(names) - index) / len(names) * 100
            flow_ratio = 8.4 - index * 1.45
            flow_yuan = (6 - index) * 2.1e8
            row = {
                "rank": rank, "sector": name, "as_of": "2026-08-21",
                "score": 9.16 * rank_pct + 61.53, "return_pct": 2.4 - index * 0.38,
                "flow_yuan": flow_yuan, "flow_ratio_pct": flow_ratio,
                "ema_swing_pct": flow_ratio * 0.82, "positive_days_30": max(0, 10 - index),
                "swing_ratio_pct": flow_ratio * 0.82, "swing_amount_yuan": flow_yuan * 0.76,
            }
            for metric, slope, intercept in (("swing", 9.16, 61.53), ("ratio", 10.74, -10.61), ("amount", 11.11, -28.26)):
                row.update({
                    f"{metric}_rank": rank, f"{metric}_rank_pct": rank_pct,
                    f"{metric}_score": slope * rank_pct + intercept,
                    f"{metric}_rank_change_1d": 2 - index % 4,
                    f"{metric}_rank_change_3d": 3 - index % 6,
                    f"{metric}_rank_change_5d": 4 - index % 8,
                    f"{metric}_top_30d": max(0, 10 - index),
                    f"{metric}_bottom_30d": max(0, index - 5),
                })
            rows.append(row)
        return _json(route, {
            "available": True, "quality": "proxy", "basis": "clv_amount_pressure",
            "detail": "资金项为收盘位置 × 成交额代理，不等同主力净流入",
            "as_of": "2026-08-21", "available_dates": ["2026-08-20", "2026-08-21"],
            "universe_size": len(rows), "unit": "CNY", "rows": rows,
        })
    if path == "/api/market-lab/macro-dispersion":
        dates = [f"2026-08-{day:02d}" for day in range(10, 22)]
        history = [{"date": value, "dispersion": 34 + index * 1.8, "ma3": 34 + max(0, index - 1) * 1.8, "mean_pct": 0.2, "industry_count": 31} for index, value in enumerate(dates)]
        contribution_rows = [
            {"name": name, "contribution_pct": 18.5 - index * 1.35, "direction": 1 if index < 5 else -1, "state": "强者扩张" if index < 5 else "弱者下沉"}
            for index, name in enumerate(["半导体", "通信", "电池", "证券", "军工", "银行", "白酒", "煤炭", "地产", "钢铁", "农业", "建筑"])
        ]
        indices = []
        for offset, (symbol, label, name) in enumerate((("000001.SH", "上证", "上证指数"), ("399006.SZ", "创业", "创业板指"), ("000688.SH", "科创", "科创50"), ("000016.SH", "50", "上证50"), ("000300.SH", "300", "沪深300"), ("000852.SH", "1000", "中证1000"), ("932000.CSI", "2000", "中证2000"))):
            indices.append({"symbol": symbol, "label": label, "name": name, "points": [{"date": value, "normalized": index * (0.35 + offset * 0.04) - offset} for index, value in enumerate(dates)]})
        windows = {str(days): {"high": contribution_rows[:10], "low": list(reversed(contribution_rows[-10:]))} for days in (1, 3, 5, 10)}
        return _json(route, {
            "available": True, "as_of": "2026-08-21", "window": "daily industry cross-section", "unit": "percent",
            "basis": "本地行业映射的成分股日收益横截面（非申万二级官方指数）",
            "mean_pct": 0.2, "dispersion": 53.8, "ma3": 52.0, "percentile": 76.5,
            "ma3_percentile": 72.5, "change_1d": 1.8, "change_5d": 9.0,
            "zone": "正常区间", "industry_count": 31, "history": history,
            "indices": indices, "contributions": contribution_rows,
            "contribution_windows": windows,
        })
    if path == "/api/market-lab/position":
        return _json(route, {"shares": 1000, "market_value": 10000, "risk_budget": 1000, "planned_loss": 1000, "capital_usage_pct": 10, "reward_risk": 10, "target_price": 20, "target_r": 10, "breakeven_price": 14, "breakeven_r": 4, "projected_profit": 10000})
    if path == "/api/market-lab/pit":
        return _json(route, {"target": 12, "depth_pct": 20, "upside_pct": 33.3333})
    if path == "/api/market-lab/drawdown":
        return _json(route, {"actual_r": 10, "draw_amount": 1, "exit_price": 19, "max_profit_pct": 100, "locked_profit_pct": 90, "target_achieved": True})
    if path == "/api/market-lab/simulate":
        return _json(route, {"paths": 1000, "trades": 100, "kelly_pct": 25, "half_kelly_pct": 12.5, "expectancy_r": 0.375, "break_even_pct": 40, "p10_final": 87000, "p50_final": 128000, "p90_final": 185000, "p50_max_drawdown_pct": 12, "p95_max_drawdown_pct": 25, "loss_probability_pct": 18, "sample_paths": [[100000, 101500, 100500, 102000, 103500], [100000, 99000, 100500, 102000, 101000]]})
    return _json(route, {"rows": [], "count": 0})


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        page.add_init_script("window.EventSource = class { constructor(){} close(){} addEventListener(){} }")
        page.on("console", lambda msg: errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror:{exc}"))
        page.on("requestfailed", lambda request: errors.append(f"requestfailed:{request.url}:{request.failure}"))
        page.route("**/api/**", handle_api)
        page.route("**/health", lambda route: _json(route, {"status": "ok", "version": "e2e", "mode": "free"}))
        page.goto("http://127.0.0.1:4173/market-lab", wait_until="networkidle")
        page.get_by_test_id("market-lab").wait_for()
        page.get_by_role("heading", name="市场实验室").wait_for()
        page.screenshot(path=str(RESULTS / "market-lab-loaded.png"), full_page=True)
        page.get_by_text("510300.SH", exact=True).wait_for()
        page.wait_for_timeout(800)
        page.screenshot(path=str(RESULTS / "market-lab-etf.png"), full_page=True)

        page.get_by_role("button", name="板块资金").click()
        page.get_by_text("OHLCV 资金压力代理", exact=True).wait_for()
        page.get_by_text("板块资金雷达", exact=True).wait_for()
        page.get_by_text("进攻方 · 流入", exact=True).wait_for()
        page.get_by_text("流出 · 撤退方", exact=True).wait_for()
        page.get_by_test_id("sector-radar-mirror").wait_for()
        page.get_by_test_id("sector-flow-trend-chart").locator("canvas").wait_for()
        page.wait_for_timeout(800)
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(RESULTS / "market-lab-sector.png"), full_page=True)

        page.get_by_role("button", name="宏观离散度").click()
        page.get_by_text("72.50%", exact=True).wait_for()
        page.get_by_text("离散度与指数走势", exact=True).wait_for()
        page.get_by_test_id("macro-dispersion-combined-chart").locator("canvas").wait_for()
        page.get_by_test_id("macro-contribution-board").wait_for()
        page.wait_for_timeout(800)
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(RESULTS / "market-lab-macro.png"), full_page=True)
        page.get_by_role("button", name="仓位与模拟").click()
        page.get_by_role("button", name="计算仓位").click()
        page.get_by_text("1000", exact=True).wait_for()
        page.get_by_role("button", name="计算出坑").click()
        page.get_by_text("33.33%", exact=True).wait_for()
        page.get_by_role("button", name="计算保护位").click()
        page.get_by_text("已达到", exact=True).wait_for()
        page.get_by_role("button", name="运行模拟").click()
        page.get_by_text("25.00%", exact=True).first.wait_for()
        page.wait_for_timeout(800)
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(RESULTS / "market-lab-risk.png"), full_page=True)

        page.evaluate("localStorage.setItem('tf-theme', 'light')")
        page.set_viewport_size({"width": 768, "height": 1000})
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="板块资金").click()
        page.get_by_test_id("sector-radar-mirror").wait_for()
        page.wait_for_timeout(800)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.screenshot(path=str(RESULTS / "market-lab-sector-light-narrow.png"), full_page=True)
        page.get_by_role("button", name="宏观离散度").click()
        page.get_by_test_id("macro-dispersion-combined-chart").locator("canvas").wait_for()
        page.wait_for_timeout(800)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        page.screenshot(path=str(RESULTS / "market-lab-macro-light-narrow.png"), full_page=True)
        browser.close()
    actionable = [error for error in errors if "ERR_CONNECTION_CLOSED" not in error]
    if actionable:
        raise AssertionError("browser errors:\n" + "\n".join(actionable))
    print("MARKET_LAB_E2E_OK")


if __name__ == "__main__":
    main()
