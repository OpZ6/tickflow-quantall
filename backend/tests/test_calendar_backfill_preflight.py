import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

spec = importlib.util.spec_from_file_location(
    "calendar_backfill", Path(__file__).resolve().parents[2] / "scripts/backfill_trading_calendar.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def frame(days=(1, 2), exchanges=("SSE", "SSE")):
    return pl.DataFrame({"trade_date": [date(2020, 1, d) for d in days],
                         "exchange": exchanges, "is_open": [False, True]})


def test_exact_calendar_range_passes():
    report = module.calendar_preflight(frame(), date(2020, 1, 1), date(2020, 1, 2))
    assert report["rows"] == 2
    assert report["open_days"] == 1


@pytest.mark.parametrize("data", [
    frame((2, 3)), frame((1, 1)), frame(exchanges=("SSE", "SZSE")),
    frame().with_columns(pl.lit(None, dtype=pl.Boolean).alias("is_open")),
])
def test_count_alone_does_not_prove_calendar_coverage(data):
    with pytest.raises(ValueError, match="calendar preflight"):
        module.calendar_preflight(data, date(2020, 1, 1), date(2020, 1, 2))


def test_saved_response_reused_without_second_request(tmp_path, monkeypatch):
    calls = []
    payload = {"status": "ok", "scraped_at": "2026-09-07T03:00:00+00:00", "trade_calendar": {"records": []}}

    def collect(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(ok=True, payload=payload)

    monkeypatch.setattr(module.SourceManager, "collect", collect)
    path = tmp_path / "source.json"
    assert module.calendar_payload(date(2020, 1, 1), date(2020, 1, 2), path) == payload
    assert module.calendar_payload(date(2020, 1, 1), date(2020, 1, 2), path) == payload
    assert calls == [1]
    with pytest.raises(ValueError, match="mismatch"):
        module.calendar_payload(date(2019, 1, 1), date(2020, 1, 2), path)
    assert calls == [1]


def test_failed_request_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(module.SourceManager, "collect", lambda *a, **k: SimpleNamespace(ok=False, error="rate_limit"))
    path = tmp_path / "source.json"
    with pytest.raises(RuntimeError, match="rate_limit"):
        module.calendar_payload(date(2020, 1, 1), date(2020, 1, 2), path)
    assert not path.exists()
