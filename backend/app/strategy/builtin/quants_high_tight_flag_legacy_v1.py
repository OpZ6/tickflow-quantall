"""Independent Quants V4 high-tight-flag migration baseline."""

from _quants_high_tight_flag import ENTRY_IDS, EXIT_IDS, QuantsHighTightFlagStrategy

META = {
    "id": "quants_high_tight_flag_legacy_v1",
    "name": "高而紧旗形候选池（多尺度形态）",
    "version": "legacy-v1",
    "description": "多尺度识别快速上涨后的高位窄幅整理，以旗形上沿和放量确认突破，并限制过度追价。",
    "strategy_role": "candidate_screener",
    "tags": ["Quants", "high-tight-flag", "legacy-v1"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": False},
    "basic_filter": {"enabled": False},
    "params": [
        {
            "id": "pole_gain_min",
            "label": "旗杆涨幅",
            "type": "float",
            "default": 0.8,
            "min": 0.4,
            "max": 1.5,
            "step": 0.05,
        },
        {
            "id": "flag_depth_max",
            "label": "整理深度",
            "type": "float",
            "default": 0.22,
            "min": 0.08,
            "max": 0.35,
            "step": 0.01,
        },
        {
            "id": "breakout_volume_ratio_min",
            "label": "突破量比",
            "type": "float",
            "default": 1.3,
            "min": 0.8,
            "max": 3.0,
            "step": 0.1,
        },
        {
            "id": "max_chase",
            "label": "突破追价上限",
            "type": "float",
            "default": 0.025,
            "min": 0.005,
            "max": 0.08,
            "step": 0.005,
        },
        {
            "id": "plan_stop_pct",
            "label": "计划止损",
            "type": "float",
            "default": 0.08,
            "min": 0.02,
            "max": 0.2,
            "step": 0.01,
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
ENTRY_SIGNALS = list(ENTRY_IDS)
EXIT_SIGNALS = list(EXIT_IDS)
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 30
MATRIX_STRATEGY = QuantsHighTightFlagStrategy()
