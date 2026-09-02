from __future__ import annotations

from types import SimpleNamespace

from app.services.depth_service import DepthService


def test_depth5_routes_to_selected_plugin(monkeypatch):
    provider = SimpleNamespace(
        get_depth5=lambda symbols: {
            symbols[0]: {"ask_volumes": [0], "bid_volumes": [100]},
        },
        depth5_batch_size=80,
        depth5_rpm=60,
    )
    monkeypatch.setattr(
        "app.services.preferences.get_depth5_data_provider", lambda: "tdx",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_data_provider_chain", lambda dataset: ["tdx"],
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset",
        lambda name, dataset: (name, dataset) == ("tdx", "depth5"),
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider", lambda name: provider,
    )
    monkeypatch.setattr(
        "app.services.preferences.get_depth_polling_interval", lambda: 10.0,
    )

    service = DepthService()
    assert service._has_capability() is True
    assert service._call_depth_batch(["600519.SH"])["600519.SH"]["ask_volumes"] == [0]
    interval, taken_over, user_interval = service._compute_interval(160)
    assert (interval, taken_over, user_interval) == (10.0, False, 10.0)


def test_depth5_tickflow_route_keeps_capability_gate(monkeypatch):
    monkeypatch.setattr(
        "app.services.preferences.get_depth5_data_provider", lambda: "tickflow",
    )
    monkeypatch.setattr(
        "app.services.preferences.get_data_provider_chain", lambda dataset: ["tickflow"],
    )
    service = DepthService()
    service._app_state = SimpleNamespace(
        capabilities=SimpleNamespace(has=lambda cap: False),
    )
    assert service._has_capability() is False


def test_depth5_fails_over_to_next_provider(monkeypatch):
    broken = SimpleNamespace(get_depth5=lambda _symbols: (_ for _ in ()).throw(TimeoutError("down")))
    healthy = SimpleNamespace(
        get_depth5=lambda symbols: {symbols[0]: {"ask_volumes": [0], "bid_volumes": [100]}},
    )
    monkeypatch.setattr(
        "app.services.preferences.get_data_provider_chain", lambda dataset: ["first", "second"],
    )
    monkeypatch.setattr(
        "app.data_providers.custom.provider_has_dataset", lambda name, dataset: True,
    )
    monkeypatch.setattr(
        "app.data_providers.custom.get_provider",
        lambda name: broken if name == "first" else healthy,
    )
    monkeypatch.setattr("app.data_providers.routing._persist_lineage", lambda: None)
    from app.data_providers import routing
    routing.reset_health()

    data = DepthService()._call_depth_batch(["600519.SH"])

    assert data["600519.SH"]["source"] == "second"
