from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import polars as pl

from app.data_providers.tencent_index import fetch_index_daily, fetch_index_realtime
from app.services import index_sync
from app.services.quote_service import supplement_realtime_indices


def test_index_instrument_sync_always_includes_quantx_all_a_index(monkeypatch) -> None:
    captured: dict[str, pl.DataFrame] = {}

    class Repo:
        def save_index_instruments(self, frame: pl.DataFrame) -> None:
            captured["frame"] = frame

        def save_etf_instruments(self, frame: pl.DataFrame) -> None:
            raise AssertionError("ETF sync should not run")

        def refresh_index_views(self) -> None:
            captured["refreshed"] = pl.DataFrame()

    monkeypatch.setattr(
        index_sync,
        "_fetch_instruments_by_type",
        lambda instrument_type, asset_type: pl.DataFrame(
            {
                "symbol": ["000001.SH"],
                "name": ["上证指数"],
                "code": ["000001"],
                "asset_type": ["index"],
            }
        ),
    )
    monkeypatch.setattr(
        "app.tickflow.policy.detect_capabilities",
        lambda force=False: SimpleNamespace(has=lambda cap: False),
    )

    count = index_sync.sync_index_instruments(
        Repo(), pull_index=True, pull_etf=False
    )

    assert count == 2
    assert set(captured["frame"]["symbol"].to_list()) == {
        "000001.SH",
        "000985.SH",
    }


def test_required_index_dimension_survives_unavailable_tickflow_client(monkeypatch) -> None:
    captured: dict[str, pl.DataFrame | bool] = {}

    class Repo:
        def save_index_instruments(self, frame: pl.DataFrame) -> None:
            captured["frame"] = frame

        def refresh_index_views(self) -> None:
            captured["refreshed"] = True

    def _unavailable():
        raise ImportError("missing proxy transport")

    monkeypatch.setattr(index_sync, "get_client", _unavailable)
    monkeypatch.setattr(
        "app.tickflow.policy.detect_capabilities",
        lambda force=False: SimpleNamespace(has=lambda _cap: True),
    )

    count = index_sync.sync_index_instruments(
        Repo(),
        pull_index=True,
        pull_etf=False,
    )

    assert count == 1
    assert captured["frame"]["symbol"].to_list() == ["000985.SH"]
    assert captured["refreshed"] is True


def test_tencent_index_provider_normalizes_and_filters_daily_rows() -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "code": 0,
                "data": {
                    "sh000985": {
                        "day": [
                            ["2026-08-24", "5906.86", "5818.51", "5908.51", "5755.08", "100.0"],
                            ["2026-08-25", "5777.70", "5832.92", "5855.14", "5743.07", "200.0"],
                            ["2026-08-26", "5834.28", "5867.44", "5899.54", "5820.68", "300.0"],
                        ]
                    }
                },
            }

    class Client:
        def get(self, url, *, params, headers):
            captured.update({"url": url, "params": params, "headers": headers})
            return Response()

    frame = fetch_index_daily(
        "000985.SH",
        date(2026, 8, 25),
        date(2026, 8, 26),
        client=Client(),
    )

    assert frame.select("symbol", "date", "open", "close", "high", "low", "volume").rows() == [
        ("000985.SH", date(2026, 8, 25), 5777.7, 5832.92, 5855.14, 5743.07, 200.0),
        ("000985.SH", date(2026, 8, 26), 5834.28, 5867.44, 5899.54, 5820.68, 300.0),
    ]
    assert frame["data_source"].unique().to_list() == ["tencent_index"]
    assert captured["params"]["param"].startswith("sh000985,day")


def test_tencent_index_realtime_uses_latest_two_rows_and_decimal_change() -> None:
    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "code": 0,
                "data": {
                    "sh000001": {
                        "day": [
                            ["2026-08-31", "3950", "3980", "3990", "3940", "100"],
                            ["2026-09-01", "3979", "4020", "4030", "3970", "200"],
                        ]
                    }
                },
            }

    class Client:
        def get(self, url, *, params, headers):
            return Response()

    rows = fetch_index_realtime(
        ["000001.SH"],
        as_of=date(2026, 9, 1),
        client=Client(),
        fetched_ms=123_000,
    )

    assert rows == [{
        "symbol": "000001.SH",
        "name": None,
        "last_price": 4020.0,
        "prev_close": 3980.0,
        "open": 3979.0,
        "high": 4030.0,
        "low": 3970.0,
        "volume": 200.0,
        "amount": None,
        "change_pct": (4020.0 - 3980.0) / 3980.0,
        "change_amount": 40.0,
        "amplitude": None,
        "turnover_rate": None,
        "timestamp": 123_000,
        "session": None,
    }]


def test_realtime_index_supplement_only_fetches_missing_symbols(monkeypatch) -> None:
    captured: list[str] = []

    def fake_fetch(symbols):
        captured.extend(symbols)
        return [{"symbol": symbol, "last_price": 1.0} for symbol in symbols]

    monkeypatch.setattr(
        "app.data_providers.tencent_index.fetch_index_realtime",
        fake_fetch,
    )
    existing = [{"symbol": "600000.SH"}, {"symbol": "000001.SH", "last_price": 2.0}]

    combined = supplement_realtime_indices(
        existing,
        ["000001.SH", "399001.SZ"],
    )

    assert captured == ["399001.SZ"]
    assert [row["symbol"] for row in combined] == ["600000.SH", "000001.SH", "399001.SZ"]


def test_required_quantx_index_fallback_publishes_raw_and_enriched(monkeypatch) -> None:
    captured: dict[str, pl.DataFrame | bool] = {}

    class Repo:
        def append_index_daily(self, frame: pl.DataFrame) -> None:
            captured["raw"] = frame

        def append_index_enriched(self, frame: pl.DataFrame) -> None:
            captured["enriched"] = frame

        def refresh_index_views(self) -> None:
            captured["refreshed"] = True

    frame = pl.DataFrame(
        {
            "symbol": ["000985.SH", "000985.SH"],
            "date": [date(2026, 8, 25), date(2026, 8, 26)],
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [100.0, 110.0],
            "amount": [None, None],
            "data_source": ["tencent_index", "tencent_index"],
        }
    )
    monkeypatch.setattr(index_sync, "fetch_tencent_index_daily", lambda *args, **kwargs: frame)

    rows = index_sync.sync_quantx_all_a_fallback(
        Repo(),
        start_date=datetime(2026, 8, 25),
        end_date=datetime(2026, 8, 26),
    )

    assert rows == 2
    assert captured["raw"]["data_source"].unique().to_list() == ["tencent_index"]
    assert captured["enriched"]["data_source"].unique().to_list() == ["tencent_index"]
    assert captured["refreshed"] is True
