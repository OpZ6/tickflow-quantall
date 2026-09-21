"""Frozen VCP leader-breakout candidate for forward observation."""

from _quants_vcp import ENTRY_IDS, EXIT_IDS, QuantsLegacyVcpStrategy

META = {
    "id": "vcp_leader_breakout",
    "name": "VCP · 标记买入",
    "version": "forward-v2",
    "description": "冻结规则的全量候选；信号列标谁可买。不是只出买入名单。",
    "tags": ["VCP", "股票魔法师形态", "领涨突破", "前向观察"],
    "strategy_role": "complete_strategy",
    "research_only": True,
    "live_qualified": False,
    "completed_daily_only": True,
    "realtime_supported": False,
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": False},
    "recommended_max_positions": 4,
    "profit_lock_steps": [
        {"activate_pct": 0.10, "floor_return_pct": 0.0},
        {"activate_pct": 0.20, "trailing_drawdown_pct": 0.10},
    ],
    "basic_filter": {
        "enabled": True,
        "price_min": 3.0,
        "price_max": 300.0,
        "market_cap_min": 1_000_000_000.0,
        "float_cap_min": None,
        "float_cap_max": None,
        "amount_min": 20_000_000.0,
        "amount_max": None,
        "turnover_min": 0.0,
        "turnover_max": None,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [
        {"id": "trend_filter", "label": "趋势模板与周期收益", "type": "bool", "default": True},
        {"id": "rs_min", "label": "RS百分位下限", "type": "float", "default": 85.0, "min": 0.0, "max": 100.0, "step": 1.0},
        {"id": "distance_high_max", "label": "距年度高点上限", "type": "float", "default": 0.12, "min": 0.02, "max": 0.4, "step": 0.01},
        {"id": "min_legs", "label": "最少收缩段", "type": "int", "default": 2, "min": 2, "max": 4, "step": 1},
        {"id": "plan_stop_pct", "label": "形态计划止损比例", "type": "float", "default": 0.03, "min": 0.01, "max": 0.08, "step": 0.005},
        {"id": "allow_cheat", "label": "允许枢轴下方提前试探", "type": "bool", "default": False},
        {"id": "require_pivot_cross", "label": "只允许首次上穿枢轴", "type": "bool", "default": False},
        {"id": "require_fresh_20d_breakout", "label": "只允许新鲜20日突破机会", "type": "bool", "default": False},
        {"id": "breakout_volume_ratio_min", "label": "突破量比下限", "type": "float", "default": 1.25, "min": 1.0, "max": 3.0, "step": 0.05},
        {"id": "breakout_volume_score_weight", "label": "突破量比排序权重", "type": "float", "default": 0.0, "min": 0.0, "max": 20.0, "step": 1.0},
        {"id": "turnover_rank_weight", "label": "换手率排序权重", "type": "float", "default": 0.0, "min": 0.0, "max": 0.5, "step": 0.05},
        {"id": "turnover_market_percentile_min", "label": "全市场换手率分位下限", "type": "float", "default": 0.0, "min": 0.0, "max": 100.0, "step": 5.0},
        {"id": "roe_rank_weight", "label": "已公告ROE排序权重", "type": "float", "default": 0.0, "min": 0.0, "max": 0.5, "step": 0.05},
        {"id": "short_scale_score_penalty", "label": "短周期候选排序扣分", "type": "float", "default": 0.0, "min": 0.0, "max": 30.0, "step": 1.0},
        {"id": "short_scale_enabled", "label": "复苏阶段允许短周期VCP", "type": "bool", "default": True},
        {"id": "breakout_close_location_min", "label": "突破K线收盘位置下限", "type": "float", "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05},
        {"id": "prebreakout_pivot_closes_max", "label": "突破前枢轴上方收盘次数上限", "type": "int", "default": 20, "min": 0, "max": 20, "step": 1},
        {"id": "contraction_strength_rank_weight", "label": "收缩递减强度排序权重", "type": "float", "default": 0.25, "min": 0.0, "max": 1.0, "step": 0.05},
        {"id": "market_breadth_percentile_lookback", "label": "市场宽度滚动分位回看天数", "type": "int", "default": 0, "min": 0, "max": 504, "step": 21},
        {"id": "market_breadth_percentile_min", "label": "市场宽度滚动分位下限", "type": "float", "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05},
        {"id": "market_breadth_percentile_max", "label": "市场宽度滚动分位上限", "type": "float", "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05},
        {"id": "market_breadth_ma20_min", "label": "市场MA20宽度下限", "type": "float", "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05},
        {"id": "market_breadth_ma20_max", "label": "市场MA20宽度上限", "type": "float", "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05},
        {"id": "market_equal_weight_return_lookback", "label": "市场等权收益回看天数", "type": "int", "default": 0, "min": 0, "max": 252, "step": 21},
        {"id": "market_equal_weight_return_min", "label": "市场等权收益下限", "type": "float", "default": 0.0, "min": -0.5, "max": 0.5, "step": 0.01},
        {"id": "a_share_dual_regime", "label": "A股VCP双市场阶段", "type": "bool", "default": True},
        {"id": "exit_ma_days", "label": "趋势退出均线周期", "type": "int", "default": 20, "min": 5, "max": 60, "step": 5},
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = list(ENTRY_IDS)
EXIT_SIGNALS = list(EXIT_IDS)
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 40
MATRIX_STRATEGY = QuantsLegacyVcpStrategy()
