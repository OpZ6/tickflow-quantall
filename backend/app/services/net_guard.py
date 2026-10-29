"""出站网络自检 — 启动 / 盘后管道开始前校验代理是否真的能出网。

背景: 代理地址来自环境变量, 而环境变量在进程启动时就被固化。本地代理(Clash
等)常见故障是「端口仍在监听, 但上游出口已死」(TUN 异常 / 订阅失效 / 节点掉线)。
此时只测 TCP 端口会误判为可用, 实际请求在 TLS 握手后被掐断, 约 60s 抛
`[SSL: UNEXPECTED_EOF_WHILE_READING]`。表现为: 数据源全部超时、盘后管道整批
失败、数据静默停更, 而 /health 之类本地接口照常 200 —— 极难发现。

因此这里做**端到端**探测: 经代理发一次真实 HTTPS 请求; 失败则再试直连, 直连
通则摘掉本进程的代理环境变量, 后续 httpx 客户端(trust_env=True)自动走直连。
"""
from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)

# 探测目标: 免费日K接口, 无需鉴权、响应极小(count=1)。
PROBE_URL = "https://free-api.tickflow.org/v1/klines/batch?period=1d&count=1&symbols=000001.SZ"


def _first_proxy() -> str | None:
    return next((os.environ[k] for k in PROXY_ENV_KEYS if os.environ.get(k)), None)


def _clear_proxy_env() -> None:
    for k in PROXY_ENV_KEYS:
        os.environ.pop(k, None)
    # 双保险: 仍读取 NO_PROXY 的库也一并走直连。
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def _http_ok(url: str, *, timeout_s: float, direct: bool) -> bool:
    """发一次真实请求; 4xx 也算通(说明链路可达, 只是鉴权/参数问题)。"""
    import httpx

    try:
        resp = httpx.get(
            url,
            timeout=timeout_s,
            trust_env=not direct,
            follow_redirects=True,
        )
    except Exception:  # noqa: BLE001 — 探测失败即视为不通
        return False
    return resp.status_code < 500


def ensure_outbound_proxy(
    tcp_timeout_s: float = 2.0,
    http_timeout_s: float = 10.0,
) -> str:
    """校验出站代理, 必要时切换为直连。

    Returns:
        "none"   — 未配置代理(本来就走直连)
        "proxy"  — 代理可用(或代理与直连都不可用, 保持原配置)
        "direct" — 代理不可用, 本进程已切直连
    """
    raw = _first_proxy()
    if not raw:
        return "none"
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return "none"

    # 第一段: 端口是否在监听
    try:
        with socket.create_connection((host, port), timeout=tcp_timeout_s):
            pass
    except OSError as e:
        _clear_proxy_env()
        logger.warning(
            "出站代理 %s 不可达 (%s), 已改为直连 — 若网络强制走代理, "
            "请修正 HTTP_PROXY/HTTPS_PROXY 后重启",
            f"{host}:{port}", e,
        )
        return "direct"

    # 第二段: 经代理真的能出网吗
    if _http_ok(PROBE_URL, timeout_s=http_timeout_s, direct=False):
        return "proxy"

    if _http_ok(PROBE_URL, timeout_s=http_timeout_s, direct=True):
        _clear_proxy_env()
        logger.warning(
            "出站代理 %s 端口可连但请求失败(上游出口不通), 已改为直连 — "
            "请检查本地代理(Clash 等)的节点/订阅状态",
            f"{host}:{port}",
        )
        return "direct"

    logger.error(
        "出站代理 %s 不可用且直连同样失败, 保持现有配置 — 数据源可能无法访问",
        f"{host}:{port}",
    )
    return "proxy"
