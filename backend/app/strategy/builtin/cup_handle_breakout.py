"""杯柄突破 — 杯体恢复、柄部缩量后突破杯沿。"""

import numpy as np
from _price_structure import cup_handle_breakout, ma20_breakdown

from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix

META = {
    "id": "cup_handle_breakout",
    "name": "杯柄突破",
    "version": "1.0.0",
    "description": "杯体深度合理、右沿恢复、柄部浅且缩量后突破杯沿",
    "tags": ["杯柄", "突破"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "chart_preview": {"enabled": True, "mode": "single_asset"},
    "basic_filter": {
        "price_min": 3,
        "amount_min": 0.2e8,
        "exclude_st": True,
        "exclude_new_days": 60,
    },
    "params": [
        {
            "id": "cup_window",
            "label": "杯体窗口",
            "type": "int",
            "default": 45,
            "min": 35,
            "max": 120,
            "step": 5,
        },
        {
            "id": "handle_window",
            "label": "柄部窗口",
            "type": "int",
            "default": 5,
            "min": 3,
            "max": 15,
            "step": 1,
        },
        {
            "id": "cup_depth_min",
            "label": "杯体最小深度",
            "type": "float",
            "default": 0.12,
            "min": 0.05,
            "max": 0.25,
            "step": 0.01,
        },
        {
            "id": "cup_depth_max",
            "label": "杯体最大深度",
            "type": "float",
            "default": 0.45,
            "min": 0.25,
            "max": 0.60,
            "step": 0.01,
        },
        {
            "id": "rim_tolerance",
            "label": "右沿容差",
            "type": "float",
            "default": 0.08,
            "min": 0.02,
            "max": 0.15,
            "step": 0.01,
        },
        {
            "id": "handle_depth_max",
            "label": "柄部最大深度",
            "type": "float",
            "default": 0.18,
            "min": 0.05,
            "max": 0.25,
            "step": 0.01,
        },
        {
            "id": "handle_volume_ratio_max",
            "label": "柄部缩量上限",
            "type": "float",
            "default": 0.85,
            "min": 0.30,
            "max": 1.00,
            "step": 0.05,
        },
        {
            "id": "breakout_volume_ratio_min",
            "label": "突破量比下限",
            "type": "float",
            "default": 1.2,
            "min": 0.8,
            "max": 3.0,
            "step": 0.1,
        },
    ],
    "scoring": {"momentum_60d": 0.4, "vol_ratio_5d": 0.35, "change_pct": 0.25},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_cup_handle_breakout"]
EXIT_SIGNALS = ["signal_cup_handle_exit_ma20"]
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 35


class CupHandleBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return max(60, int(params.get("cup_window", 45)) + 2)

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        entry, exit_ = cup_handle_breakout(market, params), ma20_breakdown(market)
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=tuple(ENTRY_SIGNALS),
            exit_signal_ids=tuple(EXIT_SIGNALS),
        )


MATRIX_STRATEGY = CupHandleBreakoutMatrixStrategy()
