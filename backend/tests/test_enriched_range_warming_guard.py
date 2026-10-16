"""get_enriched_range 的预热守卫测试 — 预热期间不得触发同步全量重算。

启动后台预热线程正在 _refresh_enriched (300 天 scan + compute, 低配机 50s+)
时, 请求线程进入 get_enriched_range 应返回 None (缓存不覆盖语义),
不能在请求线程里并发跑第二次全量重算。与 get_enriched_latest 守卫对齐。
"""
from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from app.tickflow.repository import DataStore, KlineRepository


def _bare_repo() -> KlineRepository:
    """跳过 __init__ (避免 DataStore/目录依赖), 只装配守卫涉及的属性。"""
    repo = KlineRepository.__new__(KlineRepository)
    repo._enriched_history_cache = None
    repo._enriched_warming = True
    return repo


def test_get_enriched_range_returns_none_while_warming():
    repo = _bare_repo()
    refresh_calls: list[int] = []

    def _spy_refresh():
        refresh_calls.append(1)

    repo._refresh_enriched = _spy_refresh  # type: ignore[method-assign]

    result = repo.get_enriched_range(date(2026, 1, 1), date(2026, 8, 14))

    assert result is None
    assert refresh_calls == [], "预热期间不得触发 _refresh_enriched"


def test_get_enriched_range_rebuilds_when_cold_and_not_warming():
    repo = _bare_repo()
    repo._enriched_warming = False
    built = pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH"],
        "date": [date(2026, 1, 1), date(2026, 8, 14)],
    })

    def _fake_refresh():
        repo._enriched_history_cache = built

    repo._refresh_enriched = _fake_refresh  # type: ignore[method-assign]

    result = repo.get_enriched_range(date(2026, 1, 1), date(2026, 8, 14))

    assert result is not None
    assert result.height == 2
    assert result["symbol"].unique().to_list() == ["600000.SH"]


def test_refresh_enriched_history_keeps_persisted_turnover_rate(tmp_path, monkeypatch):
    days = [date(2026, 8, 13), date(2026, 8, 14)]
    for index, day in enumerate(days):
        target = tmp_path / "kline_daily_enriched" / f"date={day.isoformat()}"
        target.mkdir(parents=True)
        pl.DataFrame(
            {
                "symbol": ["600000.SH"],
                "date": [day],
                "open": [10.0 + index],
                "high": [11.0 + index],
                "low": [9.0 + index],
                "close": [10.5 + index],
                "volume": [100.0],
                "amount": [1_000.0],
                "raw_close": [10.5 + index],
                "raw_high": [11.0 + index],
                "raw_low": [9.0 + index],
                "turnover_rate": [3.5 + index],
            }
        ).write_parquet(target / "part.parquet")

    monkeypatch.setattr(
        "app.indicators.pipeline.compute_enriched_history_window",
        lambda frame, *_args, **_kwargs: frame,
    )
    monkeypatch.setattr(
        "app.indicators.pipeline.repair_today_deviation_columns",
        lambda frame, *_args, **_kwargs: frame,
    )
    repo = KlineRepository(DataStore(tmp_path))
    monkeypatch.setattr(repo, "get_matrix_data_generation", lambda _asset_type: "test")
    monkeypatch.setattr(repo, "_build_live_agg", lambda _latest: None)

    repo._refresh_enriched()
    result = repo.get_enriched_range(days[0], days[-1], columns=["turnover_rate"])

    assert result is not None
    assert result["turnover_rate"].to_list() == [3.5, 4.5]


@pytest.mark.parametrize("symbols", [None, ["600000.SH"], ["missing"], []])
def test_range_projects_before_filter_and_preserves_empty_schema(monkeypatch, symbols):
    repo = _bare_repo()
    cache = pl.DataFrame({
        "symbol": ["600000.SH", "600001.SH"],
        "date": [date(2026, 1, 1), date(2026, 1, 2)],
        "close": [10.0, 11.0], "unused": [100.0, 200.0],
    })
    repo._enriched_history_cache = cache
    original_filter = pl.DataFrame.filter

    def narrow_filter(frame, *args, **kwargs):
        assert "unused" not in frame.columns
        return original_filter(frame, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "filter", narrow_filter)
    result = repo.get_enriched_range(date(2026, 1, 1), date(2026, 1, 2), symbols, ["close", "absent"])
    assert result is not None
    if symbols is not None and "600000.SH" not in symbols:
        assert result.is_empty()
        assert result.schema == cache.schema
    else:
        assert result.columns == ["symbol", "date", "close"]
        assert result.height == (2 if symbols is None else 1)


def test_range_duplicate_columns_keep_legacy_empty_behavior():
    repo = _bare_repo()
    cache = pl.DataFrame({"symbol": ["600000.SH"], "date": [date(2026, 1, 1)], "close": [10.0]})
    repo._enriched_history_cache = cache
    empty = repo.get_enriched_range(date(2026, 1, 1), date(2026, 1, 1), [], ["close", "close"])
    assert empty.schema == cache.schema
    with pytest.raises(pl.exceptions.DuplicateError):
        repo.get_enriched_range(date(2026, 1, 1), date(2026, 1, 1), None, ["close", "close"])
