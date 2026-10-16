"""QuantX 数据采集管线 API (采集/质量/清单/迁移)。

以源码内二次开发插件形式挂载: 由 app.extensions.loader 自动发现并 include_router,
核心 main.py 无需任何改动。
"""
from __future__ import annotations

from app.api.quantx_data import router as _router

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "tickflow.quantx.data"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(_router)
