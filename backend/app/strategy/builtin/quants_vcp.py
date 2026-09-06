"""Quants VCP 的 TickFlow 原生移植, 保留原有简化 VCP 策略。"""

from _quants_vcp import ENTRY_IDS, EXIT_IDS, QuantsVcpStrategy

META = {
    "id": "quants_vcp",
    "research_only": True,
    "strategy_role": "research_variant",
    "name": "VCP 多段收缩(研究变体)",
    "version": "1.0.0",
    "description": "多尺度真实回撤收缩、末段枢轴、RS与趋势筛选; 候选状态与买入信号分离。技术评分, 不含原版财务/行业加分。仅盘后日线, 不支持实时监控和单股预览; 收盘确认后下一交易日执行。",
    "completed_daily_only": True,
    "realtime_supported": False,
    "tags": ["VCP", "Quants", "多段收缩"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    # RS is cross-sectional. Single-asset preview must not fabricate a universe rank.
    "chart_preview": {"enabled": False},
    "basic_filter": {
        "price_min": 3,
        "price_max": None,
        "market_cap_min": None,
        "amount_min": 20_000_000,
        "exclude_st": True,
        "exclude_new_days": 0,
    },
    "params": [
        {"id": "trend_filter", "label": "趋势模板与多周期正收益", "type": "bool", "default": True},
        {
            "id": "rs_min",
            "label": "RS百分位下限(0关闭)",
            "type": "float",
            "default": 85.0,
            "min": 0.0,
            "max": 100.0,
            "step": 1.0,
        },
        {
            "id": "distance_high_max",
            "label": "距年内高点上限",
            "type": "float",
            "default": 0.12,
            "min": 0.02,
            "max": 0.4,
            "step": 0.01,
        },
        {
            "id": "min_legs",
            "label": "最少连续收缩段",
            "type": "int",
            "default": 2,
            "min": 2,
            "max": 4,
            "step": 1,
        },
        {
            "id": "contraction_ratio_max",
            "label": "相邻回撤深度比上限",
            "type": "float",
            "default": 0.95,
            "min": 0.5,
            "max": 0.99,
            "step": 0.01,
        },
        {
            "id": "tightness_min",
            "label": "收缩紧致度下限",
            "type": "float",
            "default": 0.25,
            "min": 0.1,
            "max": 0.8,
            "step": 0.05,
        },
        {
            "id": "dry_volume_ratio_max",
            "label": "触发前缩量比上限",
            "type": "float",
            "default": 0.9,
            "min": 0.2,
            "max": 1.0,
            "step": 0.05,
        },
        {
            "id": "breakout_volume_ratio_min",
            "label": "突破量比下限",
            "type": "float",
            "default": 1.25,
            "min": 1.0,
            "max": 3.0,
            "step": 0.05,
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
        {"id": "allow_cheat", "label": "允许紧致缩量提前试探", "type": "bool", "default": False},
        {
            "id": "plan_stop_pct",
            "label": "计划失效距枢轴(仅计划)",
            "type": "float",
            # The source OptimizedVcpDetector uses trigger * 0.97 for the
            # plan level. Execution stop settings remain separate below.
            "default": 0.03,
            "min": 0.01,
            "max": 0.08,
            "step": 0.005,
        },
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = list(ENTRY_IDS)
EXIT_SIGNALS = list(EXIT_IDS)
# Execution risk settings remain explicit matcher defaults, separate from plan levels.
STOP_LOSS = -0.035
MAX_HOLD_DAYS = 30


class QuantsVcpMatrixStrategy(QuantsVcpStrategy):
    """Registered strategy; shared pure implementation lives in the helper module."""


MATRIX_STRATEGY = QuantsVcpMatrixStrategy()
