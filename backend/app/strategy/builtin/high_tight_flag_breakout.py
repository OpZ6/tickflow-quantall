"""高而紧旗形突破 — 强旗杆、浅整理、缩量后突破。"""

import numpy as np
from _price_structure import high_tight_flag_breakout, ma20_breakdown

from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix

META = {
    "id": "high_tight_flag_breakout",
    "name": "高而紧旗形突破",
    "version": "1.0.0",
    "description": "旗杆涨幅充分, 整理浅且缩量, 随后放量突破旗形上沿",
    "tags": ["高而紧", "旗形", "突破"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "basic_filter": {
        "price_min": 3,
        "amount_min": 0.2e8,
        "exclude_st": True,
        "exclude_new_days": 60,
    },
    "params": [
        {
            "id": "pole_window",
            "label": "旗杆观察窗口",
            "type": "int",
            "default": 30,
            "min": 20,
            "max": 60,
            "step": 5,
        },
        {
            "id": "flag_window",
            "label": "旗形整理窗口",
            "type": "int",
            "default": 6,
            "min": 3,
            "max": 15,
            "step": 1,
        },
        {
            "id": "pole_gain_min",
            "label": "旗杆最小涨幅",
            "type": "float",
            "default": 0.80,
            "min": 0.40,
            "max": 1.50,
            "step": 0.05,
        },
        {
            "id": "flag_depth_max",
            "label": "整理最大深度",
            "type": "float",
            "default": 0.22,
            "min": 0.08,
            "max": 0.35,
            "step": 0.01,
        },
        {
            "id": "flag_volume_ratio_max",
            "label": "整理缩量上限",
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
    "scoring": {"momentum_60d": 0.5, "vol_ratio_5d": 0.3, "change_pct": 0.2},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_high_tight_flag_breakout"]
EXIT_SIGNALS = ["signal_high_tight_flag_exit_ma20"]
STOP_LOSS = -0.10
MAX_HOLD_DAYS = 30


class HighTightFlagBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return max(60, int(params.get("pole_window", 30)) + 2)

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        entry, exit_ = high_tight_flag_breakout(market, params), ma20_breakdown(market)
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=tuple(ENTRY_SIGNALS),
            exit_signal_ids=tuple(EXIT_SIGNALS),
        )


MATRIX_STRATEGY = HighTightFlagBreakoutMatrixStrategy()
