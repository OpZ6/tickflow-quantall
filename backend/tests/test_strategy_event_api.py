from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import polars as pl

from app.api import strategy as strategy_api
from app.services.strategy_signal_events import StrategySignalEventRepository
from app.strategy.engine import StrategyResult


def _request(tmp_path, engine=None):
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo, strategy_engine=engine)))


def test_event_query_endpoint_exposes_generation_and_filters(tmp_path):
    StrategySignalEventRepository(tmp_path).upsert([{
        "strategy_id": "s1", "strategy_version": "1", "params_fingerprint": "p1",
        "symbol": "000001.SZ", "event_date": "2026-08-28", "event_type": "entry",
        "source_run_id": "r1", "signal_kind": "strategy_signal",
    }])

    payload = strategy_api.query_strategy_events(
        _request(tmp_path), symbol="000001.SZ", strategy_ids="s1", limit=10,
    )

    assert payload["total"] == 1
    assert payload["generation"] == 1
    assert payload["rows"][0]["source_run_id"] == "r1"


def test_controlled_backfill_marks_results_recomputed(monkeypatch, tmp_path):
    partition = tmp_path / "kline_daily_enriched" / "date=2026-08-28" / "part.parquet"
    partition.parent.mkdir(parents=True)
    pl.DataFrame({"symbol": ["000001.SZ"], "date": [date(2026, 8, 28)]}).write_parquet(partition)

    strategy = SimpleNamespace(source="builtin", meta={"id": "s1", "version": "1"})

    class Engine:
        def list_strategies(self):
            return [{"id": "s1"}]

        def get(self, strategy_id):
            if strategy_id != "s1":
                raise ValueError("unknown")
            return strategy

        def run_all(self, context, **_kwargs):
            return {"s1": StrategyResult(
                as_of=context.as_of,
                strategy_id="s1",
                rows=[{"symbol": "000001.SZ", "close": 10.0}],
                total=1,
            )}

    class Service:
        def __init__(self, _repo, asset_type="stock"):
            self.asset_type = asset_type

        def build_strategy_context(self, _engine, as_of, _ids, **_kwargs):
            return SimpleNamespace(
                as_of=as_of, asset_type="stock", timeframe="1d",
                current=pl.DataFrame({"symbol": ["000001.SZ"], "date": [as_of], "close": [10.0]}),
            )

    monkeypatch.setattr("app.services.screener.ScreenerService", Service)
    monkeypatch.setattr(strategy_api.strategy_config, "list_overrides", lambda *_args: {})
    engine = Engine()

    payload = strategy_api.backfill_strategy_events(
        strategy_api.EventBackfillRequest(
            start_date=date(2026, 8, 28), end_date=date(2026, 8, 28), strategy_ids=["s1"],
        ),
        _request(tmp_path, engine),
    )

    assert payload["events_written"] == 1
    assert payload["failures"] == []
    rows = StrategySignalEventRepository(tmp_path).query(symbol="000001.SZ")
    assert rows[0]["provenance"] == "recomputed"
