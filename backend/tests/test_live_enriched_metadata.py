from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

from app.market_time import cn_today
from app.strategy.engine import StrategyEngine
from app.strategy.monitor import MonitorRuleEngine
from app.tickflow.repository import DataStore, KlineRepository


def _repo(tmp_path) -> KlineRepository:
    repo = KlineRepository(DataStore(tmp_path))
    repo._instruments_cache = pl.DataFrame({
        "symbol": ["600000.SH", "000001.SZ"],
        "name": ["浦发银行", "平安银行"],
        "total_shares": [29_352_080_397.0, 19_405_918_198.0],
        "float_shares": [29_352_080_397.0, 19_405_918_198.0],
    })
    return repo


def _live_row(symbol: str, close: float) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": [symbol],
        "date": [cn_today()],
        "open": [close],
        "high": [close],
        "low": [close],
        "close": [close],
        "volume": [1000.0],
        "amount": [close * 1000.0],
        "raw_close": [close],
        "raw_high": [close],
        "raw_low": [close],
    })


def test_live_enriched_cache_keeps_instrument_metadata_without_persisting_it(tmp_path):
    repo = _repo(tmp_path)

    repo.flush_live_enriched_asset("stock", _live_row("600000.SH", 10.0))
    repo.merge_live_enriched_asset("stock", _live_row("000001.SZ", 12.0))

    cached, cached_date = repo.get_enriched_latest()
    assert cached_date == cn_today()
    assert cached.select("symbol", "name").sort("symbol").to_dicts() == [
        {"symbol": "000001.SZ", "name": "平安银行"},
        {"symbol": "600000.SH", "name": "浦发银行"},
    ]
    assert cached["total_shares"].null_count() == 0
    assert cached["float_shares"].null_count() == 0

    persisted = pl.read_parquet(
        tmp_path / "kline_daily_enriched" / f"date={cn_today().isoformat()}" / "part.parquet"
    )
    assert "name" not in persisted.columns
    assert "total_shares" not in persisted.columns
    assert "float_shares" not in persisted.columns


def test_live_enriched_fills_missing_quote_names_from_instruments(tmp_path):
    repo = _repo(tmp_path)
    rows = pl.concat([
        _live_row("600000.SH", 10.0).with_columns(pl.lit(None, dtype=pl.Utf8).alias("name")),
        _live_row("000001.SZ", 12.0).with_columns(pl.lit("现有名称").alias("name")),
    ])

    repo.flush_live_enriched_asset("stock", rows)

    cached, _ = repo.get_enriched_latest()
    assert dict(cached.select("symbol", "name").iter_rows()) == {
        "000001.SZ": "现有名称",
        "600000.SH": "浦发银行",
    }


def test_live_flush_keeps_historical_range_current(tmp_path):
    repo = _repo(tmp_path)
    today = cn_today()
    yesterday = today - timedelta(days=1)
    old_today = _live_row("600000.SH", 9.0)
    history = pl.concat(
        [
            old_today.with_columns(pl.lit(yesterday).cast(pl.Date).alias("date")),
            old_today,
        ]
    )
    repo._enriched_history_cache = history
    repo._enriched_history_start = yesterday
    repo._enriched_history_generation = repo.get_matrix_data_generation("stock")

    repo.flush_live_enriched_asset("stock", _live_row("600000.SH", 10.0))

    result = repo.get_enriched_range(yesterday, today)
    assert result is not None
    assert result.select("date", "close").sort("date").to_dicts() == [
        {"date": yesterday, "close": 9.0},
        {"date": today, "close": 10.0},
    ]


def test_live_flush_extends_cached_range_to_live_day(tmp_path):
    repo = _repo(tmp_path)
    today = cn_today()
    yesterday = today - timedelta(days=1)
    history = _live_row("600000.SH", 9.0).with_columns(
        pl.lit(yesterday).cast(pl.Date).alias("date")
    )
    repo._enriched_history_cache = history
    repo._enriched_history_start = yesterday
    repo._enriched_history_generation = repo.get_matrix_data_generation("stock")

    repo.flush_live_enriched_asset("stock", _live_row("600000.SH", 10.0))

    result = repo.get_enriched_range(yesterday, today)
    assert result is not None
    assert result.select("date", "close").sort("date").to_dicts() == [
        {"date": yesterday, "close": 9.0},
        {"date": today, "close": 10.0},
    ]


def test_live_flush_does_not_bridge_missing_trading_partitions(tmp_path):
    repo = _repo(tmp_path)
    today = cn_today()
    gap_day = today - timedelta(days=1)
    cache_max = today - timedelta(days=2)
    history = _live_row("600000.SH", 9.0).with_columns(
        pl.lit(cache_max).cast(pl.Date).alias("date")
    )
    repo._enriched_history_cache = history
    repo._enriched_history_start = cache_max
    repo._enriched_history_generation = repo.get_matrix_data_generation("stock")
    (tmp_path / "kline_daily_enriched" / f"date={gap_day.isoformat()}").mkdir(parents=True)

    repo.flush_live_enriched_asset("stock", _live_row("600000.SH", 10.0))

    assert repo.get_enriched_range(cache_max, today) is None


def test_live_flush_extends_history_window_to_live_day(tmp_path):
    repo = _repo(tmp_path)
    today = cn_today()
    days = [today - timedelta(days=offset) for offset in range(130, 0, -1)]
    history = pl.concat(
        _live_row("600000.SH", 10.0 + index).with_columns(
            pl.lit(day).cast(pl.Date).alias("date")
        )
        for index, day in enumerate(days)
    )
    repo._enriched_history_cache = history
    repo._enriched_history_start = days[0]
    repo._enriched_history_generation = repo.get_matrix_data_generation("stock")

    repo.flush_live_enriched_asset("stock", _live_row("600000.SH", 99.0))

    result = repo.get_enriched_history(today, 1)
    assert result is not None
    rows = result.select("date", "close").sort("date").to_dicts()
    assert [row["date"] for row in rows] == [today - timedelta(days=1), today]
    assert rows[-1]["close"] == 99.0


def test_history_strategy_monitor_keeps_live_row_with_exclude_st_enabled(tmp_path):
    strategy_dir = tmp_path / "strategies"
    strategy_dir.mkdir()
    (strategy_dir / "history_strategy.py").write_text(
        """import polars as pl

META = {
    "id": "history_strategy",
    "name": "历史策略",
    "basic_filter": {"exclude_st": True},
}
LOOKBACK_DAYS = 2

def filter_history(df: pl.DataFrame, params: dict) -> pl.DataFrame:
    return df
""",
        encoding="utf-8",
    )
    repo = _repo(tmp_path / "data")
    live = _live_row("600000.SH", 10.0).with_columns(
        pl.lit(30_000_000.0).alias("amount")
    )
    repo.flush_live_enriched_asset("stock", live)
    current, _ = repo.get_enriched_latest()
    history = current.with_columns(pl.lit(cn_today() - timedelta(days=3)).alias("date"))

    monitor = MonitorRuleEngine()
    monitor.set_strategy_engine(StrategyEngine([Path(strategy_dir)]))
    monitor.set_history_loader(lambda _as_of, _lookback: history)
    monitor.set_rules([{
        "id": "history_strategy_monitor",
        "name": "历史策略监控",
        "type": "strategy",
        "asset_type": "stock",
        "strategy_id": "history_strategy",
        "scope": "all",
    }])

    monitor.evaluate(current)

    assert monitor.latest_strategy_results()["history_strategy"]["total"] == 1
