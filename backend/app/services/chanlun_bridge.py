"""Local openclarr-chanlun service discovery.

The Chanlun prototype uses a Python 3.10/czsc runtime that is intentionally
kept outside the TickFlow Python 3.11+ dependency graph. TickFlow only embeds
an explicitly configured loopback service; this is not an outbound proxy.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

DEFAULT_CHANLUN_URL = "http://127.0.0.1:3020"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _configured_url() -> str:
    return os.getenv("TICKFLOW_CHANLUN_URL", DEFAULT_CHANLUN_URL).strip().rstrip("/")


def is_loopback_url(value: str) -> bool:
    """Return whether *value* is an HTTP loopback origin without credentials."""
    parsed = urlparse(value)
    return (
        parsed.scheme == "http"
        and parsed.hostname in _LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def get_status(*, client: httpx.Client | None = None) -> dict:
    """Probe the optional local service and return a stable frontend contract."""
    viewer_url = _configured_url()
    capabilities = {
        "structures": ["包含处理", "分型", "笔", "线段", "中枢", "买卖点"],
        "main_indicators": 20,
        "sub_indicators": 38,
    }
    if not is_loopback_url(viewer_url):
        return {
            "available": False,
            "viewer_url": None,
            "detail": "TICKFLOW_CHANLUN_URL 只允许本机 HTTP 地址",
            "capabilities": capabilities,
        }

    owns_client = client is None
    probe_client = client or httpx.Client(timeout=2.0, trust_env=False)
    try:
        response = probe_client.get(viewer_url)
        response.raise_for_status()
        available = "Chanlun" in response.text or "缠论" in response.text
        detail = "本地缠论引擎已连接" if available else "服务可访问, 但页面签名不匹配"
    except httpx.HTTPError as exc:
        available = False
        detail = f"本地缠论引擎未连接: {type(exc).__name__}"
    finally:
        if owns_client:
            probe_client.close()

    return {
        "available": available,
        "viewer_url": viewer_url,
        "detail": detail,
        "capabilities": capabilities,
    }
