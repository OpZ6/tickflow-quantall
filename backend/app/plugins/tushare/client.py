"""Build a Tushare-compatible client with mirror-first routing."""
from __future__ import annotations

import logging
import os
import threading
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TRANSPORT_ATTEMPTS = 2
_MIRROR_LABEL = "mirror"
# 镜像站偶发拥塞时, 逐方法各自重试会让 60 个并发 daily 调用每个都白等
# 2*timeout 才回退官方, 直接把整条 180s 管线拖爆。连续 N 次传输失败后
# 在本进程内熔断镜像, 后续调用直接走官方（进程重启/成功一次即复位）。
_MIRROR_BREAKER_THRESHOLD = 3


class TushareClientChain:
    """Forward every ``pro.<api>()`` call without changing call sites."""

    def __init__(
        self,
        clients: list[tuple[str, object]],
        *,
        mirror_breaker_threshold: int = _MIRROR_BREAKER_THRESHOLD,
    ) -> None:
        self._clients = clients
        self._breaker_threshold = mirror_breaker_threshold
        self._mirror_failures = 0
        self._mirror_open = False
        self._lock = threading.Lock()

    def _active_clients(self) -> list[tuple[str, object]]:
        with self._lock:
            opened = self._mirror_open
        # 只有配置了备用 client 才允许跳过镜像；否则宁可继续重试。
        if opened and len(self._clients) > 1:
            return [item for item in self._clients if item[0] != _MIRROR_LABEL]
        return self._clients

    def _note_mirror_outcome(self, *, transport_failed: bool, succeeded: bool) -> None:
        with self._lock:
            if succeeded:
                self._mirror_failures = 0
                self._mirror_open = False
                return
            if not transport_failed or self._mirror_open:
                return
            self._mirror_failures += 1
            if self._mirror_failures >= self._breaker_threshold:
                self._mirror_open = True
                logger.warning(
                    "Tushare mirror circuit breaker opened after %s consecutive transport "
                    "failures; remaining calls in this process go straight to official",
                    self._mirror_failures,
                )

    def __getattr__(self, method_name: str):
        def invoke(*args, **kwargs):
            clients = self._active_clients()
            for index, (label, client) in enumerate(clients):
                last_exception: Exception | None = None
                client_failed = True
                client_transport_failed = False
                for attempt in range(_TRANSPORT_ATTEMPTS):
                    try:
                        value = getattr(client, method_name)(*args, **kwargs)
                        client_failed = False
                        if label == _MIRROR_LABEL:
                            self._note_mirror_outcome(transport_failed=False, succeeded=True)
                        return value
                    except Exception as exc:
                        last_exception = exc
                        transport_error = _is_transport_error(exc)
                        client_transport_failed = client_transport_failed or transport_error
                        if not transport_error or attempt + 1 >= _TRANSPORT_ATTEMPTS:
                            break
                        logger.warning(
                            "Tushare %s %s transport error; retrying once: %s",
                            label,
                            method_name,
                            type(exc).__name__,
                        )
                if label == _MIRROR_LABEL and client_failed:
                    self._note_mirror_outcome(
                        transport_failed=client_transport_failed, succeeded=False
                    )
                if index + 1 >= len(clients):
                    assert last_exception is not None
                    raise last_exception
                next_label = clients[index + 1][0]
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
