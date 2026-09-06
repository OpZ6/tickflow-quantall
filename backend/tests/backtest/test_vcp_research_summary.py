import importlib.util
from pathlib import Path

import pytest


def test_research_summary_uses_money_pnl_and_carries_year_end_equity():
    path = Path(__file__).resolve().parents[3] / "scripts/summarize_vcp_run.py"
    spec = importlib.util.spec_from_file_location("vcp_summary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {
        "run_id": "test",
        "config": {"initial_capital": 1000},
        "stats": {"final_equity": 900, "profit_factor": 2.0},
        "equity_curve": [
            {"date": "2022-12-30", "value": 1100},
            {"date": "2023-01-03", "value": 900, "positions": 0},
        ],
        "trades": [
            {"pnl_amount": 100, "pnl_pct": 0.10, "duration": 5, "exit_reason": "signal"},
            {"pnl_amount": -200, "pnl_pct": -0.05, "duration": 1, "exit_reason": "stop_loss"},
        ],
    }
    summary = module.summarize(result)
    assert summary["monetary_profit_factor"] == 0.5
    assert summary["equity_minus_realized_pnl"] == 0
    assert summary["calendar_years"]["2023"]["return"] == pytest.approx(900 / 1100 - 1)
    assert summary["exit_reasons"]["stop_loss"]["net_pnl_amount"] == -200


def test_protocol_overlay_keeps_nested_base_values():
    path = Path(__file__).resolve().parents[3] / "scripts/run_vcp_research.py"
    spec = importlib.util.spec_from_file_location("vcp_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = {"backtest": {"params": {"rs_min": 85}, "overrides": {"stop_loss": -0.05}}}
    overlay = {"backtest": {"overrides": {"score_min": 80}}}
    assert module.merged(base, overlay) == {
        "backtest": {
            "params": {"rs_min": 85},
            "overrides": {"stop_loss": -0.05, "score_min": 80},
        }
    }


def test_protocol_loader_resolves_multiple_inheritance_levels(tmp_path):
    path = Path(__file__).resolve().parents[3] / "scripts/run_vcp_research.py"
    spec = importlib.util.spec_from_file_location("vcp_runner_recursive", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "base.json").write_text(
        '{"backtest":{"start":"2021-01-01","overrides":{"stop_loss":-0.05}}}',
        encoding="utf-8",
    )
    (tmp_path / "middle.json").write_text(
        '{"base_protocol":"base.json","backtest":{"overrides":{"score_min":80}}}',
        encoding="utf-8",
    )
    leaf = tmp_path / "leaf.json"
    leaf.write_text(
        '{"base_protocol":"middle.json","backtest":{"overrides":{"score_min":78}}}',
        encoding="utf-8",
    )

    assert module.load_protocol(leaf) == {
        "backtest": {
            "start": "2021-01-01",
            "overrides": {"stop_loss": -0.05, "score_min": 78},
        }
    }


def test_protocol_loader_rejects_cycles(tmp_path):
    path = Path(__file__).resolve().parents[3] / "scripts/run_vcp_research.py"
    spec = importlib.util.spec_from_file_location("vcp_runner_cycle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "a.json").write_text('{"base_protocol":"b.json"}', encoding="utf-8")
    (tmp_path / "b.json").write_text('{"base_protocol":"a.json"}', encoding="utf-8")

    with pytest.raises(ValueError, match="Circular base_protocol chain"):
        module.load_protocol(tmp_path / "a.json")
