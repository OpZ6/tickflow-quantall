from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from app.services import index_sync


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
        "000985.CSI",
    }
