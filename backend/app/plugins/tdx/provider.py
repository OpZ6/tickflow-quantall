"""Native TDX provider backed by eltdx.

The app calls the Python client directly. The tdx-mcp package remains useful
for agent/debug access, but putting an MCP hop in the backend would duplicate
transport and lifecycle management without creating an independent data source.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import polars as pl

from app.data_providers.base import AssetType

logger = logging.getLogger(__name__)

_DATASETS = ("realtime", "minute", "depth5")
_MINUTE_COLUMNS = [
    "symbol", "datetime", "open", "high", "low", "close", "volume", "amount",
]
_SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
_KLINE_PAGE_SIZE = 800


@dataclass
class _TdxConfig:
    name: str = "tdx"
    display_name: str = "通达信(免费行情)"
    datasets: dict = field(default_factory=lambda: dict.fromkeys(_DATASETS))
    path: None = None
    builtin: bool = True


def availability() -> tuple[bool, str]:
    """Keep a missing optional dependency isolated from application startup."""
    if importlib.util.find_spec("eltdx") is None:
        return False, "未安装 eltdx(点击安装)"
    return True, "ok"


def _to_tdx_code(symbol: str) -> str:
    code, separator, exchange = str(symbol).strip().upper().partition(".")
    if (
        not separator
        or exchange not in {"SH", "SZ", "BJ"}
        or len(code) != 6
        or not code.isdigit()
    ):
        raise ValueError(f"非法 A 股代码: {symbol}")
    return f"{exchange.lower()}{code}"


def _to_symbol(exchange: str, code: str) -> str:
    return f"{code}.{str(exchange).upper()}"


def _beijing_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(_SHANGHAI_TZ).replace(tzinfo=None)


def _timestamp_ms(value: datetime | None) -> int:
    if value is None:
        return int(time.time() * 1000)
    aware = value if value.tzinfo is not None else value.replace(tzinfo=_SHANGHAI_TZ)
    return int(aware.timestamp() * 1000)


class TdxProvider:
    """TDX L1 provider for full-market snapshots, per-symbol minute K and depth5."""

    name = "tdx"
    builtin = True
    minute_history_days = 270
    depth5_batch_size = 80
    depth5_rpm = 60

    def __init__(self, client: Any | None = None) -> None:
        self.config = _TdxConfig()
        self._client = client
        self._client_lock = threading.RLock()
        self._codes_cache: list[str] | None = None

    def _get_client(self):
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @staticmethod
    def _create_client():
        from eltdx import TdxClient

        raw_hosts = os.getenv("TDX_HOSTS", "")
        hosts = [item.strip() for item in raw_hosts.split(",") if item.strip()]
        kwargs: dict[str, Any] = {
            "timeout": 5.0,
            "pool_size": 4,
            "batch_size": 80,
            "probe_hosts": True,
        }
        if hosts:
            kwargs["hosts"] = hosts
        return TdxClient(**kwargs)

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _a_share_codes(self) -> list[str]:
        if self._codes_cache is None:
            with self._client_lock:
                self._codes_cache = list(self._get_client().get_a_share_codes_all())
        return list(self._codes_cache)

    def get_instruments(self, asset_type: str = "stock") -> list[dict]:
        if asset_type != "stock":
            return []
        with self._client_lock:
            client = self._get_client()
            allowed = set(client.get_a_share_codes_all())
            rows = []
            for exchange in ("sh", "sz", "bj"):
                try:
                    items = client.get_codes_all(exchange)
                except Exception as exc:
                    logger.warning("TDX instruments %s 拉取失败: %s", exchange, exc)
                    continue
                for item in items:
                    if item.full_code not in allowed:
                        continue
                    rows.append({
                        "symbol": _to_symbol(item.exchange, item.code),
                        "name": item.name,
                        "code": item.code,
                        "exchange": item.exchange.upper(),
                        "region": "CN",
                        "type": "stock",
                        "ext": {},
                    })
            return rows

    def get_realtime(self) -> list[dict]:
        """Return an A-share snapshot. Failures are soft so polling stays alive."""
        try:
            codes = self._a_share_codes()
            with self._client_lock:
                quotes = self._get_client().get_quote(codes)
            return [self._quote_record(quote) for quote in quotes]
        except Exception as exc:
            logger.warning("TDX realtime 拉取失败: %s", exc)
            return []

    def get_realtime_indices(self, symbols: list[str]) -> list[dict]:
        try:
            codes = [_to_tdx_code(symbol) for symbol in symbols]
            with self._client_lock:
                quotes = self._get_client().get_quote(codes)
            return [self._quote_record(quote) for quote in quotes]
        except Exception as exc:
            logger.warning("TDX index realtime 拉取失败: %s", exc)
            return []

    @staticmethod
    def _quote_record(quote: Any) -> dict:
        previous = float(quote.last_close_price or 0)
        current = float(quote.last_price or 0)
        change = current - previous if previous else None
        amplitude = (
            (float(quote.high_price) - float(quote.low_price)) / previous
            if previous
            else None
        )
        return {
            "symbol": _to_symbol(quote.exchange, quote.code),
            "last_price": current,
            "prev_close": previous,
            "open": float(quote.open_price or 0),
            "high": float(quote.high_price or 0),
            "low": float(quote.low_price or 0),
            # eltdx exposes TDX total_hand; the panel contract is shares.
            "volume": float(quote.total_hand or 0) * 100,
            "amount": float(quote.amount or 0),
            "change_amount": change,
            "change_pct": change / previous if change is not None else None,
            "amplitude": amplitude,
            "timestamp": _timestamp_ms(quote.server_time),
        }

    def get_depth5(self, symbols: list[str]) -> dict[str, dict]:
        """Return prices and volumes ordered level 1 through level 5."""
        if not symbols:
            return {}
        try:
            codes = [_to_tdx_code(symbol) for symbol in symbols]
            with self._client_lock:
                quotes = self._get_client().get_quote(codes)
        except Exception as exc:
            logger.warning("TDX depth5 拉取失败(%d symbols): %s", len(symbols), exc)
            return {}

        result: dict[str, dict] = {}
        for quote in quotes:
            result[_to_symbol(quote.exchange, quote.code)] = {
                "bid_prices": [float(level.price) for level in quote.buy_levels],
                "bid_volumes": [float(level.number) * 100 for level in quote.buy_levels],
                "ask_prices": [float(level.price) for level in quote.sell_levels],
                "ask_volumes": [float(level.number) * 100 for level in quote.sell_levels],
                "timestamp": _timestamp_ms(quote.server_time),
            }
        return result

    def get_minute(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType = "stock",
        freq: str = "1m",
        on_chunk_done=None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()
        if str(freq).lower() not in {"1", "1m", "1min"}:
            raise ValueError("TDX provider 当前只支持 1m 分钟 K")

        frames: list[pl.DataFrame] = []
        for index, symbol in enumerate(symbols):
            try:
                rows = self._minute_rows(symbol, start_time, end_time, asset_type)
                if rows:
                    frames.append(pl.DataFrame(rows).select(_MINUTE_COLUMNS))
            except Exception as exc:
                logger.warning("TDX minute %s 拉取失败: %s", symbol, exc)
            if on_chunk_done:
                on_chunk_done(index + 1, len(symbols))
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    def _minute_rows(
        self,
        symbol: str,
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType,
    ) -> list[dict]:
        code = _to_tdx_code(symbol)
        kind = "index" if asset_type == "index" else "stock"
        start_time = _beijing_naive(start_time) if start_time else None
        end_time = _beijing_naive(end_time) if end_time else None
        items: list[Any] = []
        offset = 0
        with self._client_lock:
            client = self._get_client()
            while offset < 65_536:
                page = client.get_kline(
                    "1m", code, start=offset, count=_KLINE_PAGE_SIZE, kind=kind,
                ).items
                if not page:
                    break
                items.extend(page)
                oldest = min(_beijing_naive(item.time) for item in page)
                if len(page) < _KLINE_PAGE_SIZE or (start_time and oldest <= start_time):
                    break
                if start_time is None:
                    break
                offset += len(page)

        rows: list[dict] = []
        seen: set[datetime] = set()
        for item in sorted(items, key=lambda value: value.time):
            dt = _beijing_naive(item.time)
            if dt in seen or (start_time and dt < start_time) or (end_time and dt > end_time):
                continue
            seen.add(dt)
            rows.append({
                "symbol": symbol.upper(),
                "datetime": dt,
                "open": float(item.open_price),
                "high": float(item.high_price),
                "low": float(item.low_price),
                "close": float(item.close_price),
                # eltdx normalizes intraday stock K volume to hands.
                "volume": float(item.volume) * (1 if asset_type == "index" else 100),
                "amount": float(item.amount),
            })
        return rows

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        test_symbols = symbols or ["600519.SH"]
        if dataset == "realtime":
            rows = self.get_realtime()
            return self._rows_preview(dataset, rows)
        if dataset == "depth5":
            data = self.get_depth5(test_symbols)
            rows = [dict(symbol=symbol, **row) for symbol, row in data.items()]
            return self._rows_preview(dataset, rows)
        if dataset == "minute":
            end = datetime.now()
            df = self.get_minute(test_symbols, end - timedelta(days=1), end)
            return {
                "provider": self.name,
                "dataset": dataset,
                "rows": df.height,
                "columns": df.columns,
                "preview": df.head(5).to_dicts() if not df.is_empty() else [],
            }
        raise ValueError(f"TDX 不支持数据集: {dataset}")

    def _rows_preview(self, dataset: str, rows: list[dict]) -> dict:
        head = rows[:5]
        return {
            "provider": self.name,
            "dataset": dataset,
            "rows": len(rows),
            "columns": list(head[0]) if head else [],
            "preview": head,
        }
