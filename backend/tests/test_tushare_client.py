from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from app.plugins.tushare.client import build_tushare_client, credentials_configured


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
