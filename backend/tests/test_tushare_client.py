from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from app.plugins.tushare.client import (
    TushareClientChain,
    build_tushare_client,
    credentials_configured,
)


def _install_clients(monkeypatch, clients: dict[str, MagicMock]) -> None:
    import tushare as ts

    monkeypatch.setattr(ts, "pro_api", lambda token, *, timeout: clients[token])


def test_mirror_is_transparent_primary_with_official_fallback(monkeypatch) -> None:
    mirror = MagicMock()
    official = MagicMock()
    mirror.daily.side_effect = RuntimeError("mirror rejected request")
    official.daily.return_value = pd.DataFrame([{"ts_code": "000001.SZ"}])
    _install_clients(monkeypatch, {"mirror-token": mirror, "official-token": official})
    monkeypatch.setenv("TUSHARE_MIRROR_TOKEN", "mirror-token")
    monkeypatch.setenv("TUSHARE_MIRROR_API_URL", "https://mirror.example/dataapi/")
    monkeypatch.setenv("TUSHARE_TOKEN", "official-token")

    client = build_tushare_client(timeout=12)
    result = client.daily(trade_date="20260904")

    assert len(result) == 1
    assert mirror._DataApi__http_url == "https://mirror.example/dataapi"
    mirror.daily.assert_called_once_with(trade_date="20260904")
    official.daily.assert_called_once_with(trade_date="20260904")


def test_mirror_transport_error_retries_before_fallback(monkeypatch) -> None:
    mirror = MagicMock()
    official = MagicMock()
    mirror.moneyflow.side_effect = [
        RequestsConnectionError("connection reset"),
        pd.DataFrame([{"ts_code": "000001.SZ"}]),
    ]
    _install_clients(monkeypatch, {"mirror-token": mirror, "official-token": official})
    monkeypatch.setenv("TUSHARE_MIRROR_TOKEN", "mirror-token")
    monkeypatch.setenv("TUSHARE_MIRROR_API_URL", "https://mirror.example")
    monkeypatch.setenv("TUSHARE_TOKEN", "official-token")

    result = build_tushare_client().moneyflow(trade_date="20260904")

    assert len(result) == 1
    assert mirror.moneyflow.call_count == 2
    official.moneyflow.assert_not_called()


def test_official_only_keeps_original_behavior(monkeypatch) -> None:
    official = MagicMock()
    official.trade_cal.return_value = pd.DataFrame([{"cal_date": "20260904"}])
    _install_clients(monkeypatch, {"official-token": official})
    monkeypatch.delenv("TUSHARE_MIRROR_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_MIRROR_API_URL", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN", "official-token")

    result = build_tushare_client().trade_cal(start_date="20260904", end_date="20260904")

    assert len(result) == 1


def test_mirror_requires_absolute_api_url(monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_MIRROR_TOKEN", "mirror-token")
    monkeypatch.setenv("TUSHARE_MIRROR_API_URL", "mirror.example")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    with pytest.raises(ValueError, match="http"):
        build_tushare_client()


def test_credentials_accept_mirror_only(monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_MIRROR_TOKEN", "mirror-token")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    assert credentials_configured() is True


def test_mirror_circuit_breaker_skips_mirror_after_consecutive_timeouts() -> None:
    """镜像拥塞时不应让每个后续方法都白等两轮超时才回退官方。"""
    mirror = MagicMock()
    official = MagicMock()
    mirror.daily.side_effect = RequestsConnectionError("read timeout")
    official.daily.return_value = pd.DataFrame([{"ts_code": "000001.SZ"}])
    chain = TushareClientChain(
        [("mirror", mirror), ("official", official)], mirror_breaker_threshold=2
    )

    for _ in range(5):
        assert len(chain.daily(trade_date="20261106")) == 1

    # 熔断前 2 次调用各尝试 2 轮，之后全部直达官方。
    assert mirror.daily.call_count == 4
    assert official.daily.call_count == 5


def test_mirror_circuit_breaker_resets_after_success() -> None:
    mirror = MagicMock()
    official = MagicMock()
    mirror.daily.side_effect = [
        RequestsConnectionError("read timeout"),
        RequestsConnectionError("read timeout"),  # 调用 1: 两次失败 -> 官方
        pd.DataFrame([{"ts_code": "000001.SZ"}]),  # 调用 2: 镜像成功 -> 计数复位
        RequestsConnectionError("read timeout"),
        RequestsConnectionError("read timeout"),  # 调用 3: 再次失败, 计数从 0 起
    ]
    official.daily.return_value = pd.DataFrame([{"ts_code": "000001.SZ"}])
    chain = TushareClientChain(
        [("mirror", mirror), ("official", official)], mirror_breaker_threshold=2
    )

    for _ in range(3):
        assert len(chain.daily(trade_date="20261106")) == 1

    assert chain._mirror_failures == 1
    assert chain._mirror_open is False
    assert official.daily.call_count == 2
