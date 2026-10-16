from __future__ import annotations


def availability() -> tuple[bool, str]:
    try:
        import akshare  # noqa: F401
    except ImportError:
        return False, "未安装 akshare，请运行 uv sync"
    return True, "ok"
