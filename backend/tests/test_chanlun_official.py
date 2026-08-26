"""ZenChart 官方适配器与 /api/chanlun/candles、/official 端点测试。"""
from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.chanlun.zen as zen
import app.api.chanlun_analysis as ca
from app.api.chanlun_analysis import router as chanlun_router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chanlun_router)
    return TestClient(app)


def _install_repo(app: FastAPI, df: pl.DataFrame) -> None:
    class _Repo:
        def resolve_asset_type(self, symbol: str) -> str:
            return "stock"

        def get_daily_asset(self, asset_type: str, symbol: str, start, end):
            return df

    app.state.repo = _Repo()


def test_official_fail_closed_on_zen_error(client: TestClient, monkeypatch) -> None:
    def _boom(*a, **k):
        raise zen.ZenError("网络错误: ConnectTimeout")

    monkeypatch.setattr(ca, "fetch_official", _boom)
    resp = client.get("/api/chanlun/official", params={"symbol": "600460"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "网络错误" in body["detail"]


def test_official_returns_layers(monkeypatch) -> None:
    monkeypatch.setattr(ca, "fetch_official", lambda *a, **k: {
        "source": "free",
        "name": "士兰微",
        "official": {
            "candles": [], "merged_klines": [], "fenxing": [],
            "bi": [{"start_time": 1, "start_price": 1.0, "end_time": 2,
                    "end_price": 2.0, "direction": "up"}],
            "segments": [], "zhongshu": [], "zhongshu_seg": [],
            "macd": [], "bsp": [],
        },
    })
    app = FastAPI()
    app.include_router(chanlun_router)
    client = TestClient(app)
    body = client.get("/api/chanlun/official", params={"symbol": "600460"}).json()
    assert body["available"] is True
    assert body["source"] == "free"
    assert body["counts"]["bi"] == 1


def test_candles_live_fallback_when_local_short(client: TestClient, monkeypatch) -> None:
    # 本地只有 3 行 → 触发实时拉取回退 (不落盘)
    local = pl.DataFrame({
        "date": [date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)],
        "open": [1.0, 2.0, 3.0], "high": [1.5, 2.5, 3.5], "low": [0.5, 1.5, 2.5],
        "close": [1.2, 2.2, 3.2], "volume": [10, 20, 30],
    })
    _install_repo(client.app, local)

    live = pl.DataFrame({
        "symbol": ["600460.SH"] * 5,
        "date": [date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19),
                 date(2026, 8, 20), date(2026, 8, 21)],
        "open": [1.0, 2.0, 3.0, 4.0, 5.0], "high": [1.5, 2.5, 3.5, 4.5, 5.5],
        "low": [0.5, 1.5, 2.5, 3.5, 4.5], "close": [1.2, 2.2, 3.2, 4.2, 5.2],
        "volume": [10, 20, 30, 40, 50], "amount": [1.0] * 5,
    })
    called = {}
    def fake_fetch(symbols, count=None, **k):
        called["count"] = count
        return live

    monkeypatch.setattr(ca, "fetch_daily_selected", fake_fetch)
    monkeypatch.setattr(ca.preferences, "get_daily_data_provider", lambda: "stocksdk")
    resp = client.get("/api/chanlun/candles",
                      params={"symbol": "600460.SH", "days": 500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "live"
    assert body["provider"] == "stocksdk"
    assert len(body["rows"]) == 5
    assert called["count"] >= 500
    assert body["rows"][0]["date"].startswith("2026-08-17")


def test_candles_fallback_uses_selected_provider(client: TestClient, monkeypatch) -> None:
    _install_repo(client.app, pl.DataFrame())
    called = {}

    def fake_fetch(symbols, **kwargs):
        called["symbols"] = symbols
        called["kwargs"] = kwargs
        return pl.DataFrame({
            "symbol": ["600460.SH"],
            "date": [date(2026, 8, 21)],
            "open": [1.0], "high": [1.2], "low": [0.9], "close": [1.1],
            "volume": [100.0], "amount": [1000.0],
        })

    monkeypatch.setattr(ca, "fetch_daily_selected", fake_fetch)
    body = client.get(
        "/api/chanlun/candles", params={"symbol": "600460.SH", "days": 30}
    ).json()
    assert body["source"] == "live"
    assert called["symbols"] == ["600460.SH"]
    assert called["kwargs"]["count"] >= 30
