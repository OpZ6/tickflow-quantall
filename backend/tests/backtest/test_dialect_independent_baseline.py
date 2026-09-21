import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_dialect_independent_baseline.py"
SPEC = importlib.util.spec_from_file_location("research_dialect_independent_baseline", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_dialect_defaults_point_at_cited_frozen_runs() -> None:
    assert MODULE.DEFAULTS["cup"]["run"] == "20260909T133226351846Z"
    assert MODULE.DEFAULTS["cup"]["strategy_id"] == "quants_cup_handle_legacy_v1"
    assert MODULE.DEFAULTS["htf"]["run"] == "20260909T130617820559Z"
    assert MODULE.DEFAULTS["htf"]["strategy_id"] == "quants_high_tight_flag_legacy_v1"
    from research_vcp_two_bar_no_demand import independent_trade_stats, training_trades

    trades = [
        {"entry_date": "2019-01-02", "exit_date": "2019-01-10", "pnl_pct": 0.02},
        {"entry_date": "2023-01-04", "exit_date": "2023-01-10", "pnl_pct": 0.50},
    ]
    train = training_trades(trades)
    stats = independent_trade_stats([float(t["pnl_pct"]) for t in train])
    assert stats["n_trades"] == 1
    assert stats["avg_pnl"] == 0.02
