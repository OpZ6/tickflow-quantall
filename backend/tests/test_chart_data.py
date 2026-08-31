from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

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
    assert set(result["levels"]) == {"sr", "pivot", "extreme", "boll", "keltner_s", "keltner_m", "keltner_l", "atr_stop", "gap", "fib", "round"}


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
