"""市场实验室: ETF 动量 / 板块资金流 / 宏观择时 / 仓位与蒙特卡洛模拟。

以源码内二次开发插件形式挂载: 由 app.extensions.loader 自动发现并 include_router,
核心 main.py 无需任何改动。
"""
from __future__ import annotations

from app.api.market_lab import router as _router

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "tickflow.marketlab"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(_router)
