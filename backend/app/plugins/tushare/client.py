"""Build a Tushare-compatible client with mirror-first routing."""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TRANSPORT_ATTEMPTS = 2


class TushareClientChain:
    """Forward every ``pro.<api>()`` call without changing call sites."""

    def __init__(self, clients: list[tuple[str, object]]) -> None:
        self._clients = clients

    def __getattr__(self, method_name: str):
        def invoke(*args, **kwargs):
            for index, (label, client) in enumerate(self._clients):
                last_exception: Exception | None = None
                for attempt in range(_TRANSPORT_ATTEMPTS):
                    try:
                        return getattr(client, method_name)(*args, **kwargs)
                    except Exception as exc:
                        last_exception = exc
                        if not _is_transport_error(exc) or attempt + 1 >= _TRANSPORT_ATTEMPTS:
                            break
                        logger.warning(
                            "Tushare %s %s transport error; retrying once: %s",
                            label,
                            method_name,
                            type(exc).__name__,
                        )
                if index + 1 >= len(self._clients):
                    assert last_exception is not None
                    raise last_exception
                next_label = self._clients[index + 1][0]
                logger.warning(
                    "Tushare %s %s failed; falling back to %s: %s",
                    label,
                    method_name,
                    next_label,
                    type(last_exception).__name__,
                )
            raise RuntimeError(f"Tushare {method_name} failed: no configured client")

        return invoke


def credentials_configured() -> bool:
    return bool(
        os.environ.get("TUSHARE_MIRROR_TOKEN", "").strip()
        or os.environ.get("TUSHARE_TOKEN", "").strip()
    )


def configuration_error() -> str | None:
    mirror_token = os.environ.get("TUSHARE_MIRROR_TOKEN", "").strip()
    official_token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not mirror_token and not official_token:
        return "TUSHARE_MIRROR_TOKEN/TUSHARE_TOKEN 环境变量未设置"
    if mirror_token:
        mirror_url = os.environ.get("TUSHARE_MIRROR_API_URL", "")
        if not mirror_url.strip():
            return "已配置 TUSHARE_MIRROR_TOKEN, 但未配置 TUSHARE_MIRROR_API_URL"
        try:
            _normalize_api_url(mirror_url)
        except ValueError as exc:
            return str(exc)
    return None


def build_tushare_client(*, timeout: float = 30.0) -> TushareClientChain:
    """Return mirror-first client; preserve official Tushare as fallback."""
    mirror_token = os.environ.get("TUSHARE_MIRROR_TOKEN", "").strip()
    official_token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not mirror_token and not official_token:
        raise RuntimeError(
            "Tushare token 未配置: 设置 TUSHARE_MIRROR_TOKEN 或 TUSHARE_TOKEN 环境变量"
        )

    import tushare as ts

    clients: list[tuple[str, object]] = []
    if mirror_token:
        mirror_url = _normalize_api_url(
            os.environ.get("TUSHARE_MIRROR_API_URL", "")
        )
        if not mirror_url:
            raise RuntimeError(
                "已配置 TUSHARE_MIRROR_TOKEN, 但未配置 TUSHARE_MIRROR_API_URL"
            )
        mirror = ts.pro_api(mirror_token, timeout=timeout)
        mirror._DataApi__http_url = mirror_url  # type: ignore[attr-defined]
        clients.append(("mirror", mirror))

    if official_token:
        clients.append(("official", ts.pro_api(official_token, timeout=timeout)))

    logger.info("Tushare client order: %s", " -> ".join(label for label, _ in clients))
    return TushareClientChain(clients)


def _normalize_api_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TUSHARE_MIRROR_API_URL 必须是完整的 http(s) 地址")
    return normalized


def _is_transport_error(exc: Exception) -> bool:
    try:
        from requests.exceptions import RequestException
    except ModuleNotFoundError:
        return isinstance(exc, (ConnectionError, TimeoutError))
    return isinstance(exc, (RequestException, ConnectionError, TimeoutError))
