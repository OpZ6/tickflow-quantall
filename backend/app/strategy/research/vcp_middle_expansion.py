"""Research-only VCP branch for an advancing middle-breadth market."""

from _quants_vcp import (
    EXIT_IDS,
    EXPANDED_ENTRY_IDS,
    QuantsLegacyVcpStrategy,
)

META = {
    "id": "vcp_middle_expansion",
    "name": "VCP 中段扩散突破（研究）",
    "version": "method-v1",
    "description": (
        "沿用 VCP 领涨突破，只补入市场宽度处于 30% 至 70%、较五个交易日前扩张且"
        "63 日等权市场收益非负时的中长周期首次枢轴突破。"
    ),
    "research_only": True,
    "strategy_role": "research_variant",
    "live_qualified": False,
    "completed_daily_only": True,
    "realtime_supported": False,
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": False},
    "profit_lock_steps": [
        {"activate_pct": 0.10, "floor_return_pct": 0.0},
        {"activate_pct": 0.20, "trailing_drawdown_pct": 0.10},
    ],
    "basic_filter": {
        "enabled": True,
        "price_min": 3.0,
        "price_max": 300.0,
        "market_cap_min": 1_000_000_000.0,
        "amount_min": 20_000_000.0,
        "turnover_min": 0.0,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [
        {"id": "trend_filter", "type": "bool", "default": True},
        {"id": "rs_min", "type": "float", "default": 85.0},
        {"id": "distance_high_max", "type": "float", "default": 0.12},
        {"id": "min_legs", "type": "int", "default": 2},
        {"id": "plan_stop_pct", "type": "float", "default": 0.03},
        {"id": "allow_cheat", "type": "bool", "default": False},
        {"id": "require_pivot_cross", "type": "bool", "default": False},
        {"id": "breakout_volume_ratio_min", "type": "float", "default": 1.25},
        {"id": "breakout_volume_score_weight", "type": "float", "default": 0.0},
        {"id": "turnover_rank_weight", "type": "float", "default": 0.0},
        {"id": "turnover_market_percentile_min", "type": "float", "default": 0.0},
        {"id": "roe_rank_weight", "type": "float", "default": 0.0},
        {"id": "short_scale_score_penalty", "type": "float", "default": 0.0},
        {"id": "short_scale_enabled", "type": "bool", "default": True},
        {"id": "breakout_close_location_min", "type": "float", "default": 0.0},
        {"id": "prebreakout_pivot_closes_max", "type": "int", "default": 20},
        {"id": "contraction_strength_rank_weight", "type": "float", "default": 0.25},
        {"id": "market_breadth_percentile_lookback", "type": "int", "default": 0},
        {"id": "market_breadth_percentile_min", "type": "float", "default": 0.0},
        {"id": "market_breadth_percentile_max", "type": "float", "default": 1.0},
        {"id": "market_breadth_ma20_min", "type": "float", "default": 0.0},
        {"id": "market_breadth_ma20_max", "type": "float", "default": 1.0},
        {"id": "market_equal_weight_return_lookback", "type": "int", "default": 0},
        {"id": "market_equal_weight_return_min", "type": "float", "default": 0.0},
        {"id": "a_share_dual_regime", "type": "bool", "default": True},
        {"id": "include_middle_expansion_regime", "type": "bool", "default": True},
        {"id": "exit_ma_days", "type": "int", "default": 20},
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = list(EXPANDED_ENTRY_IDS)
EXIT_SIGNALS = list(EXIT_IDS)
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 40
MATRIX_STRATEGY = QuantsLegacyVcpStrategy()
