from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from app.services import kline_sync
from app.tickflow.capabilities import Cap, CapabilityLimits, CapabilitySet


@pytest.fixture(autouse=True)
def _reset_provider_health():
    from app.data_providers import routing

    routing.reset_health()
    yield
    routing.reset_health()


class _Repo:
    def append_daily(self, _frame: pl.DataFrame) -> None:
        raise AssertionError("failed fetch must not write data")


def test_persist_daily_raises_when_every_batch_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kline_sync.preferences, "get_data_provider_chain", lambda dataset: ["tickflow"],
    )
    def failed_fetch(symbols, *, failed_out=None, **_kwargs):
        assert failed_out is not None
        failed_out.extend(symbols)
        return pl.DataFrame()

    monkeypatch.setattr(kline_sync, "sync_daily_batch", failed_fetch)
    capset = CapabilitySet(
        {Cap.KLINE_DAILY_BATCH: CapabilityLimits(rpm=60, batch=100)}
    )

    with pytest.raises(RuntimeError, match="2/2"):
        kline_sync.sync_and_persist_daily_batch(
            ["000001.SZ", "600000.SH"],
            _Repo(),  # type: ignore[arg-type]
            capset,
            start_date=datetime(2026, 8, 26),
            end_date=datetime(2026, 8, 27),
        )


def test_persist_daily_allows_legitimate_empty_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kline_sync.preferences, "get_data_provider_chain", lambda dataset: ["tickflow"],
    )
    monkeypatch.setattr(kline_sync, "sync_daily_batch", lambda *_args, **_kwargs: pl.DataFrame())
    capset = CapabilitySet(
        {Cap.KLINE_DAILY_BATCH: CapabilityLimits(rpm=60, batch=100)}
    )

    assert kline_sync.sync_and_persist_daily_batch(
        ["000001.SZ"],
        _Repo(),  # type: ignore[arg-type]
        capset,
        start_date=datetime(2026, 8, 22),
        end_date=datetime(2026, 8, 23),
    ) == 0
