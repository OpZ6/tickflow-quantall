from _quants_legacy_patterns import LegacyPatternStrategy

META = {
    "id": "quants_cup_handle_legacy_v1",
    "name": "杯柄 · 观察",
    "version": "legacy-v1",
    "description": "多尺度杯柄候选，含观察和待突破，不是买入名单。",
    "strategy_role": "candidate_screener",
    "tags": ["Quants", "cup-with-handle", "legacy-v1"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": False},
    "params": [
        {"id": "cup_min_depth_pct", "type": "float", "default": 0.12},
        {
            "id": "cup_max_depth_pct",
            "label": "杯体最大深度(原版实际值)",
            "type": "float",
            "default": 0.45,
        },
        {"id": "breakout_max_chase_pct", "type": "float", "default": 0.025},
        {"id": "breakout_stop_pct", "type": "float", "default": 0.07},
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
    "completed_daily_only": True,
    "realtime_supported": False,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_quants_cup_handle_entry"]
EXIT_SIGNALS = ["signal_quants_cup_handle_exit"]
STOP_LOSS = -0.07
MAX_HOLD_DAYS = 30
MATRIX_STRATEGY = LegacyPatternStrategy(
    "cup", "signal_quants_cup_handle_entry", "signal_quants_cup_handle_exit"
)
