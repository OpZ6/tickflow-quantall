from __future__ import annotations

import json

import pytest

from app.data_providers import routing
from app.services import preferences


@pytest.fixture(autouse=True)
def _reset_provider_health():
    routing.reset_health()
    yield
    routing.reset_health()


def _preferences_path(monkeypatch, tmp_path):
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(preferences, "_path", lambda: path)
    preferences._invalidate_cache()
    return path


def test_promote_provider_keeps_existing_fallbacks(monkeypatch, tmp_path):
    path = _preferences_path(monkeypatch, tmp_path)
    path.write_text(
        json.dumps({
            "realtime_data_provider": "fuyao",
            "provider_chains": {"realtime": ["fuyao", "tdx", "tickflow"]},
        }),
        encoding="utf-8",
    )

    preferences.promote_data_provider("realtime", "tdx")

    assert preferences.get_data_provider_chain("realtime") == [
        "tdx", "fuyao", "tickflow",
    ]
    assert preferences.get_realtime_data_provider() == "tdx"


def test_provider_chain_deduplicates_and_rejects_unknown_sources(monkeypatch, tmp_path):
    path = _preferences_path(monkeypatch, tmp_path)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        preferences,
        "_allowed_data_providers",
        lambda: {"tickflow", "fuyao", "tdx"},
    )

    saved = preferences.set_data_provider_chain(
        "realtime", ["FUYAO", "tdx", "fuyao", "ghost"],
    )

    assert saved == ["fuyao", "tdx"]
    assert preferences.get_realtime_data_provider() == "fuyao"


def test_failover_uses_next_provider_and_records_lineage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        preferences,
        "get_data_provider_chain",
        lambda dataset: ["fuyao", "tdx"] if dataset == "realtime" else [],
    )
    monkeypatch.setattr(routing, "_lineage_path", lambda: tmp_path / "lineage.json")
    calls: list[str] = []

    def fetch(provider: str):
        calls.append(provider)
        if provider == "fuyao":
            raise TimeoutError("quota timeout")
        return [{"symbol": "600519.SH"}]

    result, provider = routing.run_with_failover(
        "realtime", fetch, is_success=lambda rows: bool(rows),
    )

    assert provider == "tdx"
    assert result == [{"symbol": "600519.SH"}]
    assert calls == ["fuyao", "tdx"]
    lineage = json.loads((tmp_path / "lineage.json").read_text(encoding="utf-8"))
    assert lineage["datasets"]["realtime"]["effective_provider"] == "tdx"
    assert lineage["datasets"]["realtime"]["providers"]["fuyao"]["healthy"] is False


def test_empty_result_is_failure_and_all_failures_are_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(preferences, "get_data_provider_chain", lambda _dataset: ["a", "b"])
    monkeypatch.setattr(routing, "_lineage_path", lambda: tmp_path / "lineage.json")

    with pytest.raises(routing.ProviderChainExhaustedError, match=r"a.*b"):
        routing.run_with_failover("minute", lambda _provider: [], is_success=bool)


def test_health_snapshot_exposes_cooldown_and_last_error(monkeypatch, tmp_path):
    monkeypatch.setattr(routing, "_lineage_path", lambda: tmp_path / "lineage.json")
    routing.record_failure("depth5", "tdx", "server unavailable")

    state = routing.health_snapshot("depth5")["tdx"]

    assert state["healthy"] is False
    assert state["cooldown_remaining_s"] > 0
    assert state["last_error"] == "server unavailable"
