"""Tushare 插件可用性检测。"""
from __future__ import annotations


def availability() -> tuple[bool, str]:
    """返回 (是否可用, 原因)。不抛异常。"""
    try:
        import tushare  # noqa: F401
    except ImportError:
        return False, "未安装 tushare,运行: uv sync --extra tushare"
    from app.plugins.tushare.client import configuration_error

    error = configuration_error()
    if error:
        return False, error
    return True, "ok"
