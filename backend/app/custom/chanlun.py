"""本地缠论工作台状态探测 (可选隔离引擎就绪检查)。

以源码内二次开发插件形式挂载: 由 app.extensions.loader 自动发现并 include_router,
核心 main.py 无需任何改动。
"""
from __future__ import annotations

from app.api.chanlun import router as _router

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "tickflow.chanlun"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(_router)
