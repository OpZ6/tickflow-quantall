from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.api import backtest


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_research_run_archive_lists_and_loads_completed_results(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest.settings, "data_dir", tmp_path)
    run_dir = tmp_path / "research" / "vcp" / "runs" / "20260906T010000Z"
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "status.json", {
        "status": "completed", "phase": "train", "started_at": "2026-09-06T01:00:00Z",
    })
    _write_json(run_dir / "protocol.json", {"experiment": "vcp-test"})
    result = {
        "run_id": "engine-hash",
        "config": {"strategy_id": "quants_vcp_legacy_v1", "start": "2021-01-01", "end": "2023-12-31"},
        "stats": {"total_return": 0.12, "n_trades": 23, "timing_ms": {"total": 1}},
        "equity_curve": [],
        "trades": [],
    }
    _write_json(run_dir / "result.json", result)

    listing = backtest.strategy_research_runs("quants_vcp_legacy_v1", 10)

    item = listing["items"][0]
    assert item["research_key"] == "vcp"
    assert item["run_id"] == "20260906T010000Z"
    assert item["result_id"] == "engine-hash"
    assert item["stats"]["total_return"] == 0.12
    assert item["stats"]["n_trades"] == 23
    assert "timing_ms" not in item["stats"]
    assert backtest.strategy_research_run("vcp", "20260906T010000Z") == result


def test_research_run_archive_rejects_path_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest.settings, "data_dir", tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        backtest.strategy_research_run("..", "secrets")

    assert exc_info.value.status_code == 404
