"""启动后缩量回踩，只保留总闸打开且 RS≥85 的可买入标的。"""

import numpy as np
from _price_structure import launch_pullback_support
from _quants_vcp import ScreenFilterStrategy

from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix

META = {
    "id": "launch_pullback_leader_v1",
    "name": "回踩 · 买入名单",
    "version": "leader-v1",
    "description": "回踩且总闸打开、相对强。只出可买的票。",
    "tags": ["启动", "缩量", "回踩", "守轴", "可买入"],
    "strategy_role": "complete_strategy",
    "live_qualified": False,
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": True, "mode": "single_asset"},
    "basic_filter": {
        "price_min": 3,
        "amount_min": 0.2e8,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [
        {
            "id": "launch_lookback",
            "label": "启动回看窗口",
            "type": "int",
            "default": 10,
            "min": 3,
            "max": 20,
            "step": 1,
        },
        {
            "id": "launch_gain_min",
            "label": "启动日最小涨幅",
            "type": "float",
            "default": 0.06,
            "min": 0.03,
            "max": 0.15,
            "step": 0.01,
        },
        {
            "id": "launch_volume_ratio_min",
            "label": "启动日量比下限",
            "type": "float",
            "default": 2.0,
            "min": 1.2,
            "max": 5.0,
            "step": 0.1,
        },
        {
            "id": "pullback_volume_ratio_max",
            "label": "回踩量/启动量上限",
            "type": "float",
            "default": 0.60,
            "min": 0.20,
            "max": 1.00,
            "step": 0.05,
        },
        {
            "id": "pullback_change_abs_max",
            "label": "回踩日最大绝对涨跌",
            "type": "float",
            "default": 0.02,
            "min": 0.01,
            "max": 0.05,
            "step": 0.005,
        },
        {
            "id": "support_tolerance",
            "label": "中位支撑容差",
            "type": "float",
            "default": 0.02,
            "min": 0.005,
            "max": 0.05,
            "step": 0.005,
        },
        {
            "id": "failure_buffer",
            "label": "支撑失效缓冲",
            "type": "float",
            "default": 0.02,
            "min": 0.005,
            "max": 0.08,
            "step": 0.005,
        },
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
    "scoring": {"momentum_20d": 0.4, "vol_ratio_5d": 0.3, "turnover_rate": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_launch_pullback_support"]
EXIT_SIGNALS = ["signal_launch_support_failure"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 20


class _LaunchPullbackSupportMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return max(30, int(params.get("launch_lookback", 10)) + 22)

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        entry, exit_ = launch_pullback_support(market, params)
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=tuple(ENTRY_SIGNALS),
            exit_signal_ids=tuple(EXIT_SIGNALS),
        )


MATRIX_STRATEGY = ScreenFilterStrategy(
    _LaunchPullbackSupportMatrixStrategy(),
    apply_leader_open=True,
    entries_only=True,
)
