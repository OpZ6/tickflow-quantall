from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from app.api import strategy as strategy_api
from app.services.strategy_preview import StrategyPreviewService
from app.strategy.engine import StrategyEngine

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def _history() -> pl.DataFrame:
    closes = (
        [10.0 + index * 0.12 for index in range(35)]
        + [14.35, 14.55, 14.42, 14.62, 14.48, 14.66, 14.54, 14.70, 14.61, 14.72]
        + [15.05]
    )
    volumes = [1_000.0] * 35 + [520.0] * 10 + [1_300.0]
    start = date(2025, 1, 2)
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"] * len(closes),
            "date": [start + timedelta(days=index) for index in range(len(closes))],
            "open": [close * 0.998 for close in closes],
            "high": [close * 1.005 for close in closes],
            "low": [close * 0.995 for close in closes],
            "close": closes,
            "volume": volumes,
            "amount": [1.0e9] * len(closes),
        }
    )


class _SingleSymbolRepo:
    def __init__(self, history: pl.DataFrame) -> None:
        self.history = history
        self.calls: list[tuple[str, str, date, date]] = []

    def get_daily_asset(self, asset_type: str, symbol: str, start: date, end: date) -> pl.DataFrame:
        self.calls.append((asset_type, symbol, start, end))
        return self.history.filter(
            (pl.col("symbol") == symbol)
            & pl.col("date").is_between(start, end)
        )

    def get_instruments_asset(self, _asset_type: str) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "symbol": ["600000.SH"],
                "name": ["浦发银行"],
                "total_shares": [1_000_000.0],
                "float_shares": [800_000.0],
            }
        )


def test_single_stock_preview_returns_registered_strategy_history_without_event_write(tmp_path):
    history = _history()
    repo = _SingleSymbolRepo(history)
    engine = StrategyEngine([BUILTIN_DIR])
    service = StrategyPreviewService(repo, engine)
    start = history["date"][0]
    end = history["date"][-1]

    payload = service.preview(
        symbol="600000.SH",
        asset_type="stock",
        timeframe="1d",
        start_date=start,
        end_date=end,
        strategy_ids=["vcp_breakout"],
        overrides_by_strategy={"vcp_breakout": {"basic_filter": {"enabled": False}}},
    )

    assert len(repo.calls) == 1
    assert repo.calls[0][:2] == ("stock", "600000.SH")
    assert repo.calls[0][3] == end
    assert repo.calls[0][2] < start
    assert payload["mode"] == "single_asset_preview"
    assert payload["layers"][0]["id"] == "strategy.preview.vcp_breakout"
    assert any(marker["role"] == "strategy_entry" for marker in payload["layers"][0]["markers"])
    assert payload["layers"][0]["evidence"][0]["metadata"]["provenance"] == "single_asset_preview"
    assert not (tmp_path / "strategy_signal_events").exists()


def test_single_stock_preview_rejects_strategy_without_preview_contract():
    history = _history()
    service = StrategyPreviewService(_SingleSymbolRepo(history), StrategyEngine([BUILTIN_DIR]))

    with pytest.raises(ValueError, match="不支持个股即时预览"):
        service.preview(
            symbol="600000.SH",
            asset_type="stock",
            timeframe="1d",
            start_date=history["date"][0],
            end_date=history["date"][-1],
            strategy_ids=["ma_golden_cross"],
        )


def test_preview_endpoint_is_read_only_and_does_not_run_the_screener(tmp_path):
    history = _history()
    repo = _SingleSymbolRepo(history)
    repo.store = SimpleNamespace(data_dir=tmp_path)
    engine = StrategyEngine([BUILTIN_DIR])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo, strategy_engine=engine)))

    payload = strategy_api.preview_strategy(
        strategy_api.PreviewRequest(
            symbol="600000.SH",
            asset_type="stock",
            timeframe="1d",
            start_date=history["date"][0],
            end_date=history["date"][-1],
            strategy_ids=["vcp_breakout"],
        ),
        request,
    )

    assert payload["layers"][0]["status"] == "available"
    assert len(repo.calls) == 1
    assert not (tmp_path / "strategy_signal_events").exists()
