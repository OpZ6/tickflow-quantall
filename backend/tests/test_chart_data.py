from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.kline import router as kline_router
from app.indicators.pipeline import compute_indicators
from app.services.chart_data import (
    ChartQuery,
    adjust_minute,
    aggregate_daily,
    aggregate_minute,
    apply_adjustment,
    build_chart_response,
    resolve_date_range,
)


def _daily_rows() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "date": [date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 31), date(2026, 9, 1)],
            "open": [10.0, 11.0, 6.0, 7.0],
            "high": [11.0, 12.0, 7.0, 8.0],
            "low": [9.0, 10.0, 5.0, 6.0],
            "close": [10.5, 11.5, 6.5, 7.5],
            "volume": [100, 200, 300, 400],
            "amount": [1000, 2200, 1800, 2800],
            "signal_limit_up": [False, True, False, False],
            "signal_broken_limit_up": [False, False, True, False],
        }
    )


def _factors() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 31)],
            "ex_factor": [2.0],
        }
    )


def test_none_qfq_hfq_use_one_event_factor_contract() -> None:
    rows = _daily_rows()
    none = apply_adjustment(rows, _factors(), "none")
    qfq = apply_adjustment(rows, _factors(), "qfq")
    hfq = apply_adjustment(rows, _factors(), "hfq")

    assert none["close"].to_list() == [10.5, 11.5, 6.5, 7.5]
    assert qfq["close"].to_list() == [5.25, 5.75, 6.5, 7.5]
    assert hfq["close"].to_list() == [10.5, 11.5, 13.0, 15.0]
    assert qfq["close"][1] == pytest.approx(qfq["close"][2], rel=0.15)


def test_weekly_and_monthly_ohlcv_aggregation() -> None:
    rows = _daily_rows()
    weekly = aggregate_daily(rows, "1w")
    monthly = aggregate_daily(rows, "1mo")

    assert weekly.height == 2
    assert weekly.row(0, named=True)["open"] == 10.0
    assert weekly.row(0, named=True)["close"] == 11.5
    assert weekly.row(0, named=True)["volume"] == 300
    assert weekly.row(0, named=True)["signal_limit_up"] is True
    assert weekly.row(1, named=True)["signal_broken_limit_up"] is True
    assert monthly.height == 2
    assert monthly.row(0, named=True)["high"] == 12.0
    assert monthly.row(0, named=True)["low"] == 5.0


def test_minute_aggregation_never_bridges_lunch_or_trading_days() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 6,
            "datetime": [
                datetime(2026, 8, 31, 11, 29),
                datetime(2026, 8, 31, 11, 30),
                datetime(2026, 8, 31, 13, 0),
                datetime(2026, 8, 31, 13, 1),
                datetime(2026, 9, 1, 9, 30),
                datetime(2026, 9, 1, 9, 31),
            ],
            "open": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "high": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
            "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5],
            "close": [1.2, 2.2, 3.2, 4.2, 5.2, 6.2],
            "volume": [1, 2, 3, 4, 5, 6],
        }
    )
    result = aggregate_minute(rows, "60m")

    buckets = result["datetime"].to_list()
    assert buckets == [
        datetime(2026, 8, 31, 10, 30),
        datetime(2026, 8, 31, 11, 30),
        datetime(2026, 8, 31, 13, 0),
        datetime(2026, 9, 1, 9, 30),
    ]
    assert result["volume"].to_list() == [1, 2, 7, 11]


def test_minute_qfq_can_convert_to_none_and_hfq() -> None:
    raw = _daily_rows()
    qfq_daily = apply_adjustment(raw, _factors(), "qfq")
    minute = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 2,
            "datetime": [datetime(2026, 8, 28, 10), datetime(2026, 8, 31, 10)],
            "open": [qfq_daily["open"][1], qfq_daily["open"][2]],
            "high": [qfq_daily["high"][1], qfq_daily["high"][2]],
            "low": [qfq_daily["low"][1], qfq_daily["low"][2]],
            "close": [qfq_daily["close"][1], qfq_daily["close"][2]],
            "volume": [100, 100],
        }
    )

    none = adjust_minute(minute, "000001.SZ", _factors(), "none")
    hfq = adjust_minute(minute, "000001.SZ", _factors(), "hfq")
    assert none["close"].to_list() == pytest.approx([11.5, 6.5])
    assert hfq["close"].to_list() == pytest.approx([11.5, 13.0])


def test_custom_range_requires_start_and_rejects_reverse_range() -> None:
    base = dict(
        symbol="000001.SZ",
        asset_type="stock",
        interval="1d",
        adjustment="qfq",
        range_name="custom",
        end_date=date(2026, 8, 31),
    )
    with pytest.raises(ValueError, match="必须提供 start_date"):
        resolve_date_range(ChartQuery(start_date=None, **base))
    with pytest.raises(ValueError, match="不能晚于"):
        resolve_date_range(ChartQuery(start_date=date(2026, 9, 1), **base))


def test_all_range_starts_from_symbol_listing_date_not_local_cache_floor() -> None:
    class Repo:
        def earliest_daily_date(self):
            return date(2025, 1, 1)

        def get_instruments_asset(self, _asset_type):
            return pl.DataFrame({
                "symbol": ["000001.SZ"],
                "listing_date": ["1991-04-03"],
            })

        def get_adjustment_factors(self, *_args):
            return pl.DataFrame()

        def get_raw_daily_asset(self, *_args):
            return pl.DataFrame()

        def get_daily_asset(self, *_args, **_kwargs):
            return pl.DataFrame()

    result = build_chart_response(Repo(), ChartQuery(
        symbol="000001.SZ", asset_type="stock", interval="1d", adjustment="none",
        range_name="all", start_date=None, end_date=date(2026, 9, 1),
    ))

    assert result["meta"]["requested_start"] == "1991-04-03"
    assert result["meta"]["complete"] is False


def test_preset_range_does_not_request_history_before_listing() -> None:
    class Repo:
        def earliest_daily_date(self):
            return date(2020, 1, 1)

        def get_instruments_asset(self, _asset_type):
            return pl.DataFrame({
                "symbol": ["301999.SZ"],
                "listing_date": ["2024-06-20"],
            })

        def get_adjustment_factors(self, *_args):
            return pl.DataFrame()

        def get_raw_daily_asset(self, *_args):
            return pl.DataFrame()

        def get_daily_asset(self, *_args, **_kwargs):
            return pl.DataFrame()

    result = build_chart_response(Repo(), ChartQuery(
        symbol="301999.SZ", asset_type="stock", interval="1d", adjustment="none",
        range_name="5y", start_date=date(2020, 8, 31), end_date=date(2026, 9, 1),
    ))

    assert result["meta"]["requested_start"] == "2024-06-20"
    assert result["meta"]["required_fetch_start"] == "2024-06-20"
    assert result["meta"]["warmup_complete"] is True
    assert not any("指标预热数据不足" in warning for warning in result["meta"]["warnings"])


def test_chart_response_warms_indicators_before_trimming_and_uses_same_rows_for_levels() -> None:
    dates = pl.date_range(date(2026, 1, 1), date(2026, 8, 31), interval="1d", eager=True)
    frame = pl.DataFrame({
        "symbol": ["000001.SZ"] * len(dates),
        "date": dates,
        "open": [10.0 + index / 100 for index in range(len(dates))],
        "high": [10.5 + index / 100 for index in range(len(dates))],
        "low": [9.5 + index / 100 for index in range(len(dates))],
        "close": [10.1 + index / 100 for index in range(len(dates))],
        "volume": [10_000 + index for index in range(len(dates))],
        "amount": [100_000 + index for index in range(len(dates))],
    })

    class Repo:
        def earliest_daily_date(self):
            return date(2026, 1, 1)

        def get_adjustment_factors(self, *_args):
            return pl.DataFrame()

        def get_raw_daily_asset(self, _asset_type, _symbol, start, end):
            return frame.filter(pl.col("date").is_between(start, end))

        def get_daily_asset(self, *_args, **_kwargs):
            return pl.DataFrame()

    result = build_chart_response(Repo(), ChartQuery(
        symbol="000001.SZ", asset_type="stock", interval="1d", adjustment="none",
        range_name="custom", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
    ))

    assert result["rows"][0]["date"] == "2026-08-01"
    assert result["rows"][0]["ma20"] is not None
    assert result["analysis_rows"][0]["date"] < result["rows"][0]["date"]
    assert result["meta"]["required_warmup_bars"] == 160
    assert result["meta"]["actual_warmup_bars"] == result["meta"]["warmup_bars"]
    assert set(result["levels"]) == {"sr", "pivot", "extreme", "boll", "keltner_s", "keltner_m", "keltner_l", "atr_stop", "gap", "fib", "round"}


def test_chart_response_uses_requested_warmup_and_keeps_it_hidden() -> None:
    dates = pl.date_range(date(2024, 1, 1), date(2026, 8, 31), interval="1d", eager=True)
    frame = pl.DataFrame({
        "symbol": ["000001.SZ"] * len(dates), "date": dates,
        "open": [10.0] * len(dates), "high": [11.0] * len(dates),
        "low": [9.0] * len(dates), "close": [10.5] * len(dates),
        "volume": [10_000] * len(dates), "amount": [100_000] * len(dates),
    })

    class Repo:
        def earliest_daily_date(self): return date(2024, 1, 1)
        def get_adjustment_factors(self, *_args): return pl.DataFrame()
        def get_raw_daily_asset(self, _asset_type, _symbol, start, end):
            return frame.filter(pl.col("date").is_between(start, end))
        def get_daily_asset(self, *_args, **_kwargs): return pl.DataFrame()

    result = build_chart_response(Repo(), ChartQuery(
        symbol="000001.SZ", asset_type="stock", interval="1d", adjustment="none",
        range_name="custom", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31),
        required_warmup_bars=160,
        indicator_warmups=(("macd", 120), ("chanlun", 500)),
    ))
    assert result["meta"]["required_warmup_bars"] == 500
    assert result["meta"]["required_fetch_start"] < result["meta"]["requested_start"]
    assert result["meta"]["actual_warmup_bars"] >= 500
    assert result["meta"]["warmup_complete"] is True
    assert result["meta"]["indicator_readiness"]["macd"]["status"] == "ready"
    assert result["meta"]["indicator_readiness"]["chanlun"] == {
        "required_warmup_bars": 500,
        "actual_warmup_bars": result["meta"]["actual_warmup_bars"],
        "status": "ready",
    }
    assert result["rows"][0]["date"] == "2026-08-01"
    assert result["analysis_rows"][0]["date"] < "2026-08-01"


def test_chart_response_layers_share_the_final_candle_fingerprint() -> None:
    dates = pl.date_range(date(2026, 1, 1), date(2026, 8, 31), interval="1d", eager=True)
    frame = pl.DataFrame({
        "symbol": ["000001.SZ"] * len(dates),
        "date": dates,
        "open": [10.0] * len(dates),
        "high": [10.5] * len(dates),
        "low": [9.5] * len(dates),
        "close": [10.1] * len(dates),
        "volume": [10_000] * len(dates),
        "amount": [100_000] * len(dates),
    })

    class Repo:
        def earliest_daily_date(self):
            return date(2026, 1, 1)

        def get_adjustment_factors(self, *_args):
            return pl.DataFrame()

        def get_raw_daily_asset(self, _asset_type, _symbol, start, end):
            return frame.filter(pl.col("date").is_between(start, end))

        def get_daily_asset(self, *_args, **_kwargs):
            return pl.DataFrame()

    result = build_chart_response(
        Repo(),
        ChartQuery(
            symbol="000001.SZ", asset_type="stock", interval="1d", adjustment="none",
            range_name="custom", start_date=date(2026, 7, 1), end_date=date(2026, 8, 31),
        ),
        layer_categories={"pattern", "event", "plan"},
    )
    assert result["annotation_layers"]
    assert all(
        layer["input_fingerprint"] == result["meta"]["input_fingerprint"]
        for layer in result["annotation_layers"]
    )
    key_level_layer = next(layer for layer in result["annotation_layers"] if layer["id"] == "plan.key_levels")
    assert len(key_level_layer["lines"]) == sum(len(items) for items in result["levels"].values())
    assert {line["value"] for line in key_level_layer["lines"]} == {
        level["value"] for items in result["levels"].values() for level in items
    }


def test_core_macd_has_fixed_numeric_sample() -> None:
    count = 80
    frame = pl.DataFrame({
        "symbol": ["000001.SZ"] * count,
        "date": [date(2026, 1, 1) + timedelta(days=index) for index in range(count)],
        "open": [10 + index * 0.1 for index in range(count)],
        "high": [11 + index * 0.1 for index in range(count)],
        "low": [9 + index * 0.1 for index in range(count)],
        "close": [10.2 + index * 0.1 for index in range(count)],
        "volume": [1_000 + index for index in range(count)],
    })
    last = compute_indicators(frame).row(-1, named=True)
    assert last["macd_dif"] == pytest.approx(0.6971405774)
    assert last["macd_dea"] == pytest.approx(0.6957971887)
    assert last["macd_hist"] == pytest.approx(0.0026867774)


def test_single_daily_sync_uses_explicit_range_without_full_market_job(monkeypatch) -> None:
    captured = {}

    class Repo:
        def resolve_asset_type(self, symbol):
            assert symbol == "000001.SZ"
            return "stock"

    class Capset:
        def has(self, _cap): return False

    def fake_sync(symbols, repo, capset, **kwargs):
        captured.update(symbols=symbols, repo=repo, capset=capset, **kwargs)
        return 321

    monkeypatch.setattr("app.services.kline_sync.sync_and_persist_daily_batch", fake_sync)
    monkeypatch.setattr("app.api.data.invalidate_storage_cache", lambda: captured.update(invalidated=True))
    app = FastAPI()
    app.state.repo = Repo()
    app.state.capabilities = Capset()
    app.include_router(kline_router)

    response = TestClient(app).post("/api/kline/sync_daily_single", json={
        "symbol": "000001.SZ", "start_date": "2023-09-01", "end_date": "2026-09-01",
    })
    assert response.status_code == 200
    assert response.json()["rows"] == 321
    assert captured["symbols"] == ["000001.SZ"]
    assert captured["start_date"].date() == date(2023, 9, 1)
    assert captured["end_date"].date() == date(2026, 9, 1)
    assert captured["invalidated"] is True


def test_single_daily_sync_skips_covered_prices_but_still_refreshes_adjustment_factors(monkeypatch) -> None:
    captured = {"daily_calls": 0, "factor_calls": 0}

    class Repo:
        def resolve_asset_type(self, _symbol):
            return "stock"

        def get_raw_daily_asset(self, _asset_type, _symbol, start, end):
            return pl.DataFrame({
                "symbol": ["605319.SH", "605319.SH"],
                "date": [start, end],
                "close": [10.0, 20.0],
            })

    class Capset:
        def has(self, _cap):
            return True

    def fake_daily_sync(*_args, **_kwargs):
        captured["daily_calls"] += 1
        return 999

    def fake_factor_sync(symbols, repo, capset, **kwargs):
        captured.update(
            factor_calls=captured["factor_calls"] + 1,
            factor_symbols=symbols,
            factor_repo=repo,
            factor_capset=capset,
            factor_kwargs=kwargs,
        )
        return 7, []

    monkeypatch.setattr("app.services.kline_sync.sync_and_persist_daily_batch", fake_daily_sync)
    monkeypatch.setattr("app.services.kline_sync.sync_adj_factor", fake_factor_sync)
    monkeypatch.setattr("app.api.data.invalidate_storage_cache", lambda: None)
    app = FastAPI()
    app.state.repo = Repo()
    app.state.capabilities = Capset()
    app.include_router(kline_router)

    response = TestClient(app).post("/api/kline/sync_daily_single", json={
        "symbol": "605319.SH", "start_date": "2021-06-07", "end_date": "2026-09-01",
    })

    assert response.status_code == 200
    assert response.json()["rows"] == 0
    assert response.json()["factor_rows"] == 7
    assert captured["daily_calls"] == 0
    assert captured["factor_calls"] == 1
    assert captured["factor_kwargs"]["start_time"].date() == date(2021, 6, 7)
    assert captured["factor_kwargs"]["end_time"].date() == date(2026, 9, 1)
