from __future__ import annotations

from datetime import date, datetime

import polars as pl

from app.services.strategy_evidence import (
    enrich_and_persist_strategy_result,
    persist_backtest_fill_events,
    persist_realtime_trigger_events,
)
from app.services.strategy_signal_events import StrategySignalEventRepository
from app.strategy.engine import StrategyDataContext, StrategyResult


def _event(**overrides):
    value = {
        "strategy_id": "trend_breakout",
        "strategy_version": "1.0.0",
        "params_fingerprint": "params-a",
        "symbol": "600000.SH",
        "asset_type": "stock",
        "event_date": date(2026, 8, 28),
        "event_type": "entry",
        "signal_kind": "strategy_signal",
        "score": 88.0,
        "source_run_id": "run-a",
        "provenance": "observed_run",
        "input_fingerprint": "input-a",
        "reason_codes": ["signal_breakout"],
        "metrics": [{"name": "close", "value": 12.3, "unit": "price", "passed": True}],
        "anchors": [{"date": "2026-08-28", "role": "entry"}],
        "levels": [{"role": "trigger", "value": 12.2}],
        "pattern_refs": ["pattern.classic:2026-08-28"],
        "observed_at": datetime(2026, 8, 28, 15, 1),
    }
    value.update(overrides)
    return value


def test_repository_is_idempotent_queryable_and_restart_readable(tmp_path):
    repository = StrategySignalEventRepository(tmp_path)
    assert repository.upsert([_event()]) == 1
    assert repository.upsert([_event(score=91.0)]) == 1
    assert repository.generation() == 2

    restarted = StrategySignalEventRepository(tmp_path)
    rows = restarted.query(symbol="600000.SH", strategy_ids=["trend_breakout"])
    assert len(rows) == 1
    assert rows[0]["score"] == 91.0
    assert rows[0]["reason_codes"] == ["signal_breakout"]
    assert rows[0]["pattern_refs"] == ["pattern.classic:2026-08-28"]


def test_repository_keeps_observed_and_recomputed_provenance_separate(tmp_path):
    repository = StrategySignalEventRepository(tmp_path)
    repository.upsert([_event(), _event(source_run_id="run-recomputed", provenance="recomputed")])
    rows = repository.query(event_types=["entry"])
    assert {row["provenance"] for row in rows} == {"observed_run", "recomputed"}


def test_repository_can_restore_one_exact_run_and_parameter_set(tmp_path):
    repository = StrategySignalEventRepository(tmp_path)
    repository.upsert([
        _event(),
        _event(source_run_id="run-b", params_fingerprint="params-b"),
    ])
    rows = repository.query(
        symbol="600000.SH",
        source_run_id="run-b",
        params_fingerprint="params-b",
    )
    assert len(rows) == 1
    assert rows[0]["source_run_id"] == "run-b"


def test_repository_reads_legacy_partition_with_missing_nullable_columns(tmp_path):
    path = tmp_path / "strategy_signal_events" / "date=2026-08-28" / "part.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "schema_version": [1], "strategy_id": ["legacy"], "strategy_version": ["1"],
        "params_fingerprint": ["p"], "symbol": ["000001.SZ"], "event_date": [date(2026, 8, 28)],
        "event_type": ["candidate"], "source_run_id": ["r"],
    }).write_parquet(path)
    rows = StrategySignalEventRepository(tmp_path).query(symbol="000001.SZ")
    assert len(rows) == 1
    assert rows[0]["metrics"] == []
    assert rows[0]["provenance"] is None
    assert rows[0]["signal_kind"] is None


def test_repository_keeps_signal_backtest_and_realtime_semantics_distinct(tmp_path):
    repository = StrategySignalEventRepository(tmp_path)
    repository.upsert([
        _event(source_run_id="signal", signal_kind="strategy_signal"),
        _event(source_run_id="backtest", signal_kind="backtest_fill"),
        _event(source_run_id="realtime", signal_kind="realtime_trigger"),
    ])
    assert {row["signal_kind"] for row in repository.query()} == {
        "strategy_signal", "backtest_fill", "realtime_trigger",
    }


def test_backtest_and_realtime_adapters_persist_truthful_event_kinds(tmp_path):
    payload = {
        "run_id": "bt-run",
        "config": {"strategy_id": "trend_breakout", "params": {"n": 20}, "asset_type": "stock"},
        "strategy_info": {"version": "2.0"},
        "trades": [{
            "symbol": "600000.SH", "entry_date": "2026-08-27", "exit_date": "2026-08-28",
            "entry_price": 10.0, "exit_price": 10.5, "pnl_pct": 5.0,
            "entry_signal_id": "breakout", "exit_reason": "signal",
        }],
    }
    assert persist_backtest_fill_events(tmp_path, payload) == 2
    assert persist_realtime_trigger_events(
        data_dir=tmp_path,
        strategy_id="trend_breakout",
        strategy_version="2.0",
        params={"n": 20},
        as_of=date(2026, 8, 28),
        asset_type="stock",
        changes={"buy_signal": {"600000.SH"}},
        rows={"600000.SH": {"close": 10.6, "score": 80}},
    ) == 1
    rows = StrategySignalEventRepository(tmp_path).query(symbol="600000.SH")
    assert [row["signal_kind"] for row in rows].count("backtest_fill") == 2
    assert [row["signal_kind"] for row in rows].count("realtime_trigger") == 1


def test_custom_strategy_without_dedicated_adapter_gets_generic_evidence(tmp_path):
    strategy = type("CustomStrategy", (), {
        "meta": {"id": "my_custom", "version": "7"},
        "entry_signals": ["custom_entry"],
        "exit_signals": ["custom_exit"],
    })()
    result = StrategyResult(
        as_of=date(2026, 8, 28), strategy_id="my_custom",
        rows=[{"symbol": "600000.SH", "close": 12.3, "score": 75.0}], total=1,
        entry_signal_hits=[{"symbol": "600000.SH", "signals": ["custom_entry"]}],
        exit_signal_hits=[{"symbol": "600000.SH", "signals": ["custom_exit"]}],
    )
    context = StrategyDataContext(
        asset_type="stock", timeframe="1d", as_of=result.as_of,
        current=pl.DataFrame({"symbol": ["600000.SH"], "date": [result.as_of], "close": [12.3], "volume": [1000]}),
    )
    events = enrich_and_persist_strategy_result(
        data_dir=tmp_path, result=result, strategy=strategy, params={"threshold": 2.0}, context=context,
    )
    assert {event["event_type"] for event in events} == {"candidate", "entry", "exit"}
    assert all(event["strategy_version"] == "7" for event in events)
    assert all(event["params_fingerprint"] for event in events)
    assert StrategySignalEventRepository(tmp_path).query(symbol="600000.SH")
