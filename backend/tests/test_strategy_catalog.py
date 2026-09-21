from pathlib import Path

from app.strategy.catalog import (
    CATALOG_PROJECT,
    UPSTREAM_BUILTIN_IDS,
    catalog_label_for,
    catalog_origin,
)
from app.strategy.engine import StrategyEngine

BUILTIN = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"


def test_public_catalog_splits_upstream_and_project() -> None:
    engine = StrategyEngine([BUILTIN])
    public = engine.list_strategies()
    public_ids = {row["id"] for row in public}
    project = {sid for sid in public_ids if catalog_origin(sid, "builtin") == CATALOG_PROJECT}
    assert len(UPSTREAM_BUILTIN_IDS) == 25
    assert UPSTREAM_BUILTIN_IDS <= public_ids
    assert catalog_origin("trend_breakout", "builtin") is None
    assert catalog_label_for(None) is None
    assert catalog_label_for(CATALOG_PROJECT) == "右侧"
    assert "vcp_leader_tradable_v1" in project
    assert "cup_handle_leader_v1" in project
    assert "launch_pullback_leader_v1" in project
    assert "vcp_leader_breakout" not in public_ids
    assert catalog_origin("custom_foo", "custom") is None


def test_project_strategy_names_state_the_job() -> None:
    engine = StrategyEngine([BUILTIN])
    expected = {
        "quants_vcp_legacy_v1": "VCP · 观察",
        "vcp_leader_breakout": "VCP · 标记买入",
        "vcp_leader_tradable_v1": "VCP · 买入名单",
        "quants_cup_handle_legacy_v1": "杯柄 · 观察",
        "cup_handle_leader_v1": "杯柄 · 买入名单",
        "cup_handle_breakout": "杯柄 · 简化突破",
        "quants_high_tight_flag_legacy_v1": "高旗 · 观察",
        "high_tight_flag_breakout": "高旗 · 简化突破",
        "launch_pullback_support": "回踩 · 全市场",
        "launch_pullback_leader_v1": "回踩 · 买入名单",
    }
    for strategy_id, name in expected.items():
        meta = engine.get(strategy_id).meta
        assert meta["name"] == name
        assert "·" in meta["name"]
        assert len(str(meta.get("description") or "")) <= 28


def test_screener_keeps_observation_and_usable_pairs() -> None:
    engine = StrategyEngine([BUILTIN])
    public = {row["id"] for row in engine.list_strategies()}
    assert {
        "quants_vcp_legacy_v1",
        "vcp_leader_tradable_v1",
        "quants_cup_handle_legacy_v1",
        "cup_handle_leader_v1",
        "launch_pullback_support",
        "launch_pullback_leader_v1",
        "quants_high_tight_flag_legacy_v1",
    } <= public
    assert {
        "vcp_leader_breakout",
        "cup_handle_breakout",
        "high_tight_flag_breakout",
    }.isdisjoint(public)
    hidden = {row["id"] for row in engine.list_strategies(include_research=True)}
    assert {
        "vcp_leader_breakout",
        "cup_handle_breakout",
        "high_tight_flag_breakout",
    } <= hidden
