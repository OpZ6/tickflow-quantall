from _quants_legacy_patterns import LegacyPatternStrategy
from _quants_vcp import ScreenFilterStrategy

META = {
    "id": "cup_handle_leader_v1",
    "name": "杯柄 · 买入名单",
    "version": "leader-v1",
    "description": "只出总闸打开且相对强的可执行。观察和待突破不出。",
    "strategy_role": "complete_strategy",
    "live_qualified": False,
    "tags": ["Quants", "cup-with-handle", "可买入"],
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
        {
            "id": "rs_min",
            "label": "RS百分位下限",
            "type": "float",
            "default": 85.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
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
MATRIX_STRATEGY = ScreenFilterStrategy(
    LegacyPatternStrategy(
        "cup", "signal_quants_cup_handle_entry", "signal_quants_cup_handle_exit"
    ),
    apply_leader_open=True,
    entries_only=True,
)
