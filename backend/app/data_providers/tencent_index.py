"""Free daily-index fallback used by the shared post-market pipeline."""
from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any, Protocol

import httpx
import polars as pl

_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_USER_AGENT = "Mozilla/5.0 (compatible; TickFlow/0.2; index-data-sync)"


class _Response(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]: ...


class _Client(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> _Response: ...


class TencentIndexProviderError(RuntimeError):
    """The fallback endpoint could not provide a valid index series."""


def _market_key(symbol: str) -> str:
    code, separator, exchange = symbol.upper().partition(".")
    if not separator or not code.isdigit() or len(code) != 6:
        raise ValueError(f"invalid index symbol: {symbol}")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(exchange)
    if prefix is None:
        raise ValueError(f"unsupported index exchange: {exchange}")
    return f"{prefix}{code}"


def _parse_rows(
    payload: dict[str, Any],
    *,
    market_key: str,
    symbol: str,
) -> pl.DataFrame:
    data = payload.get("data")
    node = data.get(market_key) if isinstance(data, dict) else None
    if not isinstance(node, dict):
        raise TencentIndexProviderError(f"missing index payload: {market_key}")
    raw_rows = node.get("day") or node.get("qfqday") or []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        rows.append(
            {
                "symbol": symbol,
                "date": raw[0],
                "open": raw[1],
                "close": raw[2],
                "high": raw[3],
                "low": raw[4],
                "volume": raw[5],
                "amount": None,
                "data_source": "tencent_index",
            }
        )
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(
        rows,
        schema_overrides={
            "symbol": pl.String,
            "date": pl.String,
            "open": pl.String,
            "high": pl.String,
            "low": pl.String,
            "close": pl.String,
            "volume": pl.String,
            "amount": pl.Float64,
            "data_source": pl.String,
        },
    ).with_columns(
        pl.col("date").str.to_date("%Y-%m-%d", strict=False),
        pl.col("open").cast(pl.Float64, strict=False),
        pl.col("high").cast(pl.Float64, strict=False),
        pl.col("low").cast(pl.Float64, strict=False),
        pl.col("close").cast(pl.Float64, strict=False),
        pl.col("volume").cast(pl.Float64, strict=False),
    ).drop_nulls(["date", "open", "high", "low", "close"])


def fetch_index_daily(
    symbol: str,
    start: date,
    end: date,
    *,
    client: _Client | None = None,
) -> pl.DataFrame:
    """Fetch and normalize an inclusive daily OHLCV range.

    The endpoint exposes index rows as ``date, open, close, high, low, volume``
    and does not provide turnover amount. Missing amount remains null instead of
    being fabricated from volume.
    """
    if start > end:
        raise ValueError("start must not be after end")
    market_key = _market_key(symbol)
    trading_day_estimate = max(10, min(640, (end - start).days + 20))
    params = {
        "param": f"{market_key},day,,,{trading_day_estimate},qfq",
    }
    headers = {"User-Agent": _USER_AGENT}
    try:
        if client is None:
            with httpx.Client(timeout=15.0, trust_env=False) as http_client:
                response = http_client.get(_ENDPOINT, params=params, headers=headers)
        else:
            response = client.get(_ENDPOINT, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise TencentIndexProviderError(f"index request failed: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (None, 0):
        raise TencentIndexProviderError("index endpoint returned an error payload")
    frame = _parse_rows(payload, market_key=market_key, symbol=symbol)
    if frame.is_empty():
        return frame
    return frame.filter(
        (pl.col("date") >= start) & (pl.col("date") <= end)
    ).sort(["symbol", "date"])


def fetch_index_realtime(
    symbols: list[str],
    *,
    as_of: date | None = None,
    client: _Client | None = None,
    fetched_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch the latest live daily candle for core indices.

    Tencent's daily endpoint includes the in-progress trading-day candle.  The
    latest two rows provide the live price and previous close without inventing
    a percentage unit.  Stale/holiday rows are rejected so callers can fall
    back to their explicit historical source instead of labelling stale data as
    realtime.
    """
    target = as_of or date.today()
    timestamp = fetched_ms if fetched_ms is not None else int(time.time() * 1000)
    owned_client = None
    active_client = client
    if active_client is None:
        owned_client = httpx.Client(timeout=15.0, trust_env=False)
        active_client = owned_client
    out: list[dict[str, Any]] = []
    try:
        for symbol in dict.fromkeys(symbols):
            try:
                frame = fetch_index_daily(
                    symbol,
                    target - timedelta(days=14),
                    target,
                    client=active_client,
                )
            except (TencentIndexProviderError, ValueError):
                continue
            if frame.height < 2:
                continue
            previous, latest = frame.tail(2).to_dicts()
            if latest.get("date") != target:
                continue
            last_price = float(latest["close"])
            prev_close = float(previous["close"])
            change_amount = last_price - prev_close
            out.append({
                "symbol": symbol,
                "name": None,
                "last_price": last_price,
                "prev_close": prev_close,
                "open": float(latest["open"]),
                "high": float(latest["high"]),
                "low": float(latest["low"]),
                "volume": float(latest["volume"]) if latest.get("volume") is not None else None,
                "amount": None,
                "change_pct": change_amount / prev_close if prev_close else None,
                "change_amount": change_amount,
                "amplitude": None,
                "turnover_rate": None,
                "timestamp": timestamp,
                "session": None,
            })
    finally:
        if owned_client is not None:
            owned_client.close()
    return out
