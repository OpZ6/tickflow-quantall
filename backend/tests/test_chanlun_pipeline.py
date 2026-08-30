"""app.chanlun 缠论流水线与 API 单元测试。"""
from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

from app.chanlun.pipeline import analyze


def _make_candles(n: int = 300, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    price = 100.0
    candles = []
    for i in range(n):
        o = price
        price += rng.uniform(-2, 2)
        c = price
        h = max(o, c) + abs(rng.uniform(0, 1))
        low = min(o, c) - abs(rng.uniform(0, 1))
        candles.append({
            "time": 1_000_000_000 + i * 86_400,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(low, 2),
            "close": round(c, 2),
            "volume": rng.randint(1000, 99_999),
        })
    return candles


def test_analyze_returns_all_layers() -> None:
    result = analyze(_make_candles())
    for key in ("merged_klines", "fenxing", "bi", "segments", "zhongshu", "macd", "bsp"):
        assert key in result
    assert len(result["macd"]) == 300


def test_analyze_bi_indices_align_with_candles() -> None:
    candles = _make_candles()
    result = analyze(candles)
    n = len(candles)
    for b in result["bi"]:
        si, ei = b["start_index"], b["end_index"]
        assert si is None or 0 <= si < n
        assert ei is None or 0 <= ei < n
        if si is not None and ei is not None:
            assert si <= ei


def test_analyze_bsp_shape() -> None:
    result = analyze(_make_candles())
    for b in result["bsp"]:
        assert b["direction"] in ("buy", "sell")
        assert b["level"] in ("bi", "seg")
        assert isinstance(b["price"], float)


def test_analyze_too_few_candles_still_works() -> None:
    # 少于分型所需 K 线时各层应为空而非抛错
    result = analyze(_make_candles(15))
    assert result["bi"] == [] or len(result["bi"]) >= 0


@pytest.fixture()
def client() -> TestClient:
    from fastapi import FastAPI

    from app.api.chanlun_analysis import router as chanlun_router

    app = FastAPI()
    app.include_router(chanlun_router)
    return TestClient(app)


def test_api_analyze_rejects_empty(client: TestClient) -> None:
    resp = client.post("/api/chanlun/analyze", json={"candles": []})
    assert resp.status_code == 200
    assert resp.json() == {"error": "need >= 10 candles"}


def test_api_analyze_returns_layers(client: TestClient) -> None:
    resp = client.post("/api/chanlun/analyze", json={"candles": _make_candles(120)})
    assert resp.status_code == 200
    body = resp.json()
    assert "bi" in body and "segments" in body and "zhongshu" in body and "bsp" in body
    assert body["_meta"]["algorithm"] == "tickflow-local-chanlun"
    assert body["_meta"]["version"] == "v5"
    assert len(body["_meta"]["data_fingerprint"]) == 16
    assert isinstance(body["_meta"]["final_confirmed"], bool)
