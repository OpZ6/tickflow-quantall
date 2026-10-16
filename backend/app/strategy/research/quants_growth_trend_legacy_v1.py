from _quants_vcp import ENTRY_IDS, EXIT_IDS, QuantsVcpStrategy

META = {
    "research_only": True,
    "id": "quants_growth_trend_legacy_v1",
    "name": "成长趋势(经典 VCP)",
    "version": "legacy-v1",
    "description": "已退出主策略列表,仅保留兼容 ID 和历史配置。与 VCP 主策略核心主题重叠,不声明原版规则完全等价。",
    "tags": ["Quants", "growth-trend", "legacy-v1"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": False},
    "params": [
        {"id": "rs_min", "type": "float", "default": 85.0},
        {"id": "distance_high_max", "type": "float", "default": 0.08},
        {"id": "breakout_volume_ratio_min", "type": "float", "default": 1.5},
        {"id": "breakout_stop_pct", "type": "float", "default": 0.03},
    ],
    "scoring": {"finance_weight": 0.2, "near_high_bonus_cap": 6.0, "breakout_bonus": 6.0},
    "order_by": "score",
    "descending": True,
    "limit": 100,
    "completed_daily_only": True,
    "realtime_supported": False,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = list(ENTRY_IDS)
EXIT_SIGNALS = list(EXIT_IDS)
STOP_LOSS = -0.03
MAX_HOLD_DAYS = 30
MATRIX_STRATEGY = QuantsVcpStrategy()
