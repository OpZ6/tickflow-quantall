import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/run_vcp_research.py"
SPEC = importlib.util.spec_from_file_location("research_runner_boundary", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def check(end, cutoff="2022-12-31", holding=30):
    protocol = {"training_gate": {}, "training_data_end": cutoff,
                "analysis": {"evaluation_horizon_bars": 40}}
    config = SimpleNamespace(end=date.fromisoformat(end), overrides={},
                             holding_days=5, mode="full")
    MODULE.validate_training_boundary(protocol, config, SimpleNamespace(max_hold_days=holding))


def test_year_end_signal_does_not_mean_year_end_training():
    with pytest.raises(ValueError, match="purge"):
        check("2022-12-30")


def test_purged_signal_range_passes():
    check("2022-10-11")


def test_long_execution_window_is_checked_too():
    with pytest.raises(ValueError, match="purge"):
        check("2022-10-11", holding=100)


def test_training_gate_without_cutoff_is_rejected():
    with pytest.raises(ValueError, match="explicit"):
        MODULE.validate_training_boundary({"training_gate": {"trades": 40}}, None, None)
