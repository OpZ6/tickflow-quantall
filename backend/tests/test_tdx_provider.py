from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.plugins.tdx.provider import TdxProvider

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def get_kline(self, period, code, *, start, count, kind):
        assert (period, code, start, count, kind) == (
            "1m", "sh600519", 0, 800, "stock",
        )
        return SimpleNamespace(items=[
            SimpleNamespace(
                time=datetime(2026, 9, 1, 9, 31, tzinfo=SHANGHAI),
                open_price=100.0,
                high_price=101.0,
                low_price=99.0,
                close_price=100.5,
                volume=12,
                amount=120_600.0,
            ),
            SimpleNamespace(
                time=datetime(2026, 9, 1, 9, 32, tzinfo=SHANGHAI),
                open_price=100.5,
                high_price=102.0,
                low_price=100.0,
                close_price=101.5,
                volume=8,
                amount=81_200.0,
            ),
        ])

    def get_quote(self, codes):
        assert codes == ["sh600519"]
        return [SimpleNamespace(
            exchange="sh",
            code="600519",
            server_time=None,
            last_price=101.5,
            last_close_price=100.0,
            open_price=100.0,
            high_price=102.0,
            low_price=99.0,
            total_hand=20,
            amount=202_000.0,
            buy_levels=[SimpleNamespace(price=101.4, number=3)],
            sell_levels=[SimpleNamespace(price=101.6, number=4)],
        )]

    def close(self) -> None:
        self.closed = True


def test_minute_normalizes_beijing_time_and_volume_shares():
    provider = TdxProvider(client=FakeClient())
    df = provider.get_minute(
        ["600519.SH"],
        datetime(2026, 9, 1, 9, 32),
        datetime(2026, 9, 1, 9, 32),
    )

    assert df.columns == [
        "symbol", "datetime", "open", "high", "low", "close", "volume", "amount",
    ]
    assert df.to_dicts() == [{
        "symbol": "600519.SH",
        "datetime": datetime(2026, 9, 1, 9, 32),
        "open": 100.5,
        "high": 102.0,
        "low": 100.0,
        "close": 101.5,
        "volume": 800.0,
        "amount": 81_200.0,
    }]


def test_realtime_and_depth5_share_one_quote_contract(monkeypatch):
    provider = TdxProvider(client=FakeClient())
    monkeypatch.setattr(provider, "_a_share_codes", lambda: ["sh600519"])

    rows = provider.get_realtime()
    assert rows[0]["symbol"] == "600519.SH"
    assert rows[0]["volume"] == 2_000.0
    assert rows[0]["change_pct"] == 0.015

    depth = provider.get_depth5(["600519.SH"])
    assert depth["600519.SH"]["bid_prices"] == [101.4]
    assert depth["600519.SH"]["bid_volumes"] == [300.0]
    assert depth["600519.SH"]["ask_volumes"] == [400.0]


def test_close_releases_eltdx_client():
    client = FakeClient()
    TdxProvider(client=client).close()
    assert client.closed is True
