"""Tushare 插件可用性检测。"""
from __future__ import annotations

import os


def availability() -> tuple[bool, str]:
    """返回 (是否可用, 原因)。不抛异常。"""
    try:
        import tushare  # noqa: F401
    except ImportError:
        return False, "未安装 tushare,运行: uv sync --extra tushare"
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        return False, "TUSHARE_TOKEN 环境变量未设置"
    return True, "ok"
