"""VCP 突破 — 波动与量能收缩后突破前高。"""

import numpy as np
from _price_structure import ma20_breakdown, vcp_breakout

from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix

META = {
    "id": "vcp_breakout",
    "name": "VCP 突破",
    "version": "1.0.0",
    "description": "中期基底内短期波动与量能收缩, 放量突破前高",
    "tags": ["VCP", "收缩", "突破"],
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
            "id": "base_window",
            "label": "基底窗口",
            "type": "int",
            "default": 40,
            "min": 30,
            "max": 120,
            "step": 5,
        },
        {
            "id": "contraction_window",
            "label": "末段收缩窗口",
            "type": "int",
            "default": 10,
            "min": 5,
            "max": 20,
            "step": 1,
        },
        {
            "id": "base_depth_min",
            "label": "基底最小深度",
            "type": "float",
            "default": 0.08,
            "min": 0.03,
            "max": 0.20,
            "step": 0.01,
        },
        {
            "id": "base_depth_max",
            "label": "基底最大深度",
            "type": "float",
            "default": 0.45,
            "min": 0.20,
            "max": 0.60,
            "step": 0.01,
        },
        {
            "id": "contraction_ratio_max",
            "label": "末段/基底波动上限",
            "type": "float",
            "default": 0.65,
            "min": 0.30,
            "max": 0.90,
            "step": 0.05,
        },
        {
            "id": "dry_volume_ratio_max",
            "label": "缩量上限",
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
    "scoring": {"momentum_60d": 0.4, "vol_ratio_5d": 0.4, "change_pct": 0.2},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_vcp_breakout"]
EXIT_SIGNALS = ["signal_vcp_exit_ma20"]
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 30


class VcpBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return max(60, int(params.get("base_window", 40)) + 2)

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        entry, exit_ = vcp_breakout(market, params), ma20_breakdown(market)
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=tuple(ENTRY_SIGNALS),
            exit_signal_ids=tuple(EXIT_SIGNALS),
        )


MATRIX_STRATEGY = VcpBreakoutMatrixStrategy()
