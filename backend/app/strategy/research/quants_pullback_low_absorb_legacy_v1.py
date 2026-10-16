from _quants_legacy_patterns import LegacyPatternStrategy

META = {
    "id": "quants_pullback_low_absorb_legacy_v1",
    "name": "回调低吸候选池（龙吸水·需资金流）",
    "version": "legacy-v1",
    "description": "启动后缩量回调的观察候选，需要真实个股日资金流；数据接入完成前不进入默认策略列表。",
    "strategy_role": "candidate_screener",
    "research_only": True,
    "required_data_fields": ["net_mf_amount"],
    "unavailable_reason": "本地行情尚未接入真实个股日资金流 net_mf_amount（万元）",
    "tags": ["Quants", "pullback-low-absorb", "legacy-v1"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": False},
    "params": [
        {"id": "anchor_lookback_days", "type": "int", "default": 10},
        {"id": "anchor_min_pct_chg", "type": "float", "default": 0.06},
        {"id": "anchor_min_volume_ratio", "type": "float", "default": 2.0},
        {"id": "max_volume_to_anchor_ratio", "type": "float", "default": 0.6},
        {"id": "max_volume_to_ma20_ratio", "type": "float", "default": 1.2},
        {"id": "max_abs_pullback_pct_chg", "type": "float", "default": 0.02},
        {"id": "support_stop_pct", "type": "float", "default": 0.06},
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
    "completed_daily_only": True,
    "realtime_supported": False,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_quants_pullback_low_absorb_entry"]
EXIT_SIGNALS = ["signal_quants_pullback_low_absorb_exit"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 20
MATRIX_STRATEGY = LegacyPatternStrategy(
    "pullback", "signal_quants_pullback_low_absorb_entry", "signal_quants_pullback_low_absorb_exit"
)
