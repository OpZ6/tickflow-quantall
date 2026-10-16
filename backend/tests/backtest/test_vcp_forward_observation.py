from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest


def _module():
    path = Path(__file__).resolve().parents[3] / "scripts/observe_vcp_forward.py"
    spec = importlib.util.spec_from_file_location("observe_vcp_forward", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paper_ledger_keeps_terminal_marks_open_and_builds_next_open_queue() -> None:
    module = _module()
    backtest = SimpleNamespace(
        config={"start": "2026-09-07", "end": "2026-09-08"},
        trades=[
            {
                "symbol": "CLOSED",
                "exit_reason": "stop_loss",
                "exit_date": "2026-09-08",
            },
            {
                "symbol": "OPEN",
                "name": "open position",
                "entry_date": "2026-09-07",
                "entry_signal_date": "2026-09-06",
                "entry_signal_id": "signal_vcp",
                "entry_price": 10.0,
                "entry_value": 10_000.0,
                "shares": 1_000.0,
                "lots": 10.0,
                "entry_score": 80.0,
                "exit_reason": "end",
                "exit_date": "2026-09-08",
            },
        ],
        equity_curve=[{"date": "2026-09-08", "value": 1_001_000.0}],
        stats={
            "execution": {"buy_no_slot": 2},
            "execution_rejections": [{"symbol": "BLOCKED", "date": "2026-09-08", "reason": "buy_no_slot"}],
            "execution_rejection_scope": "portfolio_matrix_attempts",
        },
    )
    screen = SimpleNamespace(
        entry_signal_hits=[
            {"symbol": "OPEN", "signals": ["signal_vcp"]},
            {"symbol": "CLOSED", "signals": ["signal_vcp"]},
            {"symbol": "NEW", "signals": ["signal_vcp"]},
        ],
        exit_signal_hits=[{"symbol": "OPEN", "signals": ["signal_ma20"]}],
        rows=[
            {
                "symbol": "NEW",
                "name": "new candidate",
                "vcp_status": "breakout",
                "vcp_setup": "pivot",
                "vcp_pivot": 19.5,
                "strategy_evidence": {"reason_codes": ["breakout"]},
            },
            {
                "symbol": "WATCH",
                "name": "watch candidate",
                "vcp_status": "near_pivot",
                "strategy_evidence": {"reason_codes": ["near_pivot"]},
            },
        ],
        scores={"NEW": 91.0, "OPEN": 80.0, "CLOSED": 70.0},
    )
    ledger = module._paper_ledger(
        backtest,
        pl.DataFrame({"symbol": ["OPEN", "NEW"], "close": [11.0, 20.0]}),
        screen,
        date(2026, 9, 8),
        max_positions=2,
    )

    assert [row["symbol"] for row in ledger["closed_trades"]] == ["CLOSED"]
    assert [row["symbol"] for row in ledger["open_positions"]] == ["OPEN"]
    assert ledger["open_positions"][0]["unrealized_return_before_exit_cost"] == pytest.approx(0.1)
    assert [row["symbol"] for row in ledger["pending_entries"]] == ["NEW"]
    assert [row["symbol"] for row in ledger["pending_signal_exits"]] == ["OPEN"]
    assert ledger["execution_rejection_counts"] == {"buy_no_slot": 2}
    assert ledger["execution_rejections"] == backtest.stats["execution_rejections"]
    assert ledger["execution_rejection_scope"] == "portfolio_matrix_attempts"

    decisions = module._candidate_decisions(screen)
    assert decisions[0]["decision"] == "entry_signal_only"
    assert decisions[0]["reason_codes"] == ["breakout"]
    assert decisions[1]["decision"] == "observe_only"
    assert decisions[1]["reason_codes"] == ["near_pivot"]


def test_candidate_decisions_respect_paper_queue_and_exclusions() -> None:
    module = _module()
    symbols = ["HELD", "POLICY", "QUEUED", "NO_SLOT", "WATCH"]
    screen = SimpleNamespace(
        rows=[{"symbol": symbol} for symbol in symbols],
        scores={},
        entry_signal_hits=[{"symbol": symbol} for symbol in symbols[:-1]],
    )
    ledger = {
        "pending_entries": [{"symbol": "QUEUED"}],
        "entry_signals_without_available_slot": [{"symbol": "NO_SLOT"}],
        "entry_signal_exclusions": [
            {"symbol": "HELD", "reason": "already_held"},
            {"symbol": "POLICY", "reason": "policy_exclusion"},
        ],
    }
    decisions = module._candidate_decisions(screen, ledger)
    assert [row["decision"] for row in decisions] == [
        "already_held", "policy_exclusion", "pending_next_open", "no_available_slot", "observe_only"
    ]
    assert all(row["is_simulated_fill"] is False for row in decisions)


def test_paper_ledger_records_excluded_signals_and_capacity() -> None:
    module = _module()
    backtest = SimpleNamespace(
        config={},
        trades=[
            {"symbol": "HELD", "exit_reason": "end"},
            {"symbol": "EXITED", "exit_reason": "signal", "exit_date": "2026-09-08"},
        ],
        equity_curve=[], stats={},
    )
    screen = SimpleNamespace(
        rows=[], scores={"A": 90, "B": 80}, exit_signal_hits=[],
        entry_signal_hits=[{"symbol": symbol} for symbol in ["HELD", "EXITED", "B", "A"]],
    )
    ledger = module._paper_ledger(backtest, None, screen, date(2026, 9, 8), max_positions=2)
    assert ledger["entry_signal_exclusions"] == [
        {"symbol": "HELD", "reason": "already_held"},
    ]
    assert [row["symbol"] for row in ledger["pending_entries"]] == ["A"]
    assert [row["symbol"] for row in ledger["entry_signals_without_available_slot"]] == ["B", "EXITED"]
    assert ledger["pending_entries"][0]["intended_fill"] == "next_market_open"


def test_exit_today_does_not_block_a_new_signal_for_tomorrow() -> None:
    module = _module()
    backtest = SimpleNamespace(
        config={},
        trades=[{"symbol": "A", "exit_reason": "signal", "exit_date": "2026-09-08"}],
        equity_curve=[], stats={},
    )
    screen = SimpleNamespace(
        rows=[{"symbol": "A"}], scores={"A": 90}, exit_signal_hits=[],
        entry_signal_hits=[{"symbol": "A", "signals": ["signal_vcp"]}],
    )
    ledger = module._paper_ledger(backtest, None, screen, date(2026, 9, 8), max_positions=1)
    assert ledger["entry_signal_exclusions"] == []
    assert [row["symbol"] for row in ledger["pending_entries"]] == ["A"]
    assert module._candidate_decisions(screen, ledger)[0]["decision"] == "pending_next_open"


def test_rejection_ledger_completion_requires_screening_and_execution_scope() -> None:
    module = _module()
    trace = {
        "scope": "matrix_snapshot_candidate_pipeline",
        "detector_subreasons_available": True,
    }
    assert module._rejection_ledger_complete(
        trace, {"status": "empty_before_first_entry_signal"}
    )
    assert module._rejection_ledger_complete(
        trace,
        {
            "status": "deterministic_replay",
            "execution_rejection_scope": "portfolio_matrix_attempts",
        },
    )
    assert not module._rejection_ledger_complete(
        trace, {"status": "deterministic_replay"}
    )
    assert not module._rejection_ledger_complete(
        {"scope": "unavailable"}, {"status": "empty_before_first_entry_signal"}
    )


def test_version_manifest_reference_is_pinned_and_version_checked(tmp_path) -> None:
    module = _module()
    module.ROOT = tmp_path
    manifest = tmp_path / "version.json"
    manifest.write_text(
        json.dumps({
            "manifest_id": "forward-v1-test",
            "strategy_version": "forward-v1",
            "status": "frozen_reference_with_limitations",
        }),
        encoding="utf-8",
    )

    reference = module._version_manifest_reference(manifest, "forward-v1")
    assert reference["manifest_id"] == "forward-v1-test"
    assert reference["status"] == "frozen_reference_with_limitations"
    assert len(reference["sha256"]) == 64

    with pytest.raises(RuntimeError, match="version manifest strategy"):
        module._version_manifest_reference(manifest, "forward-v2")
