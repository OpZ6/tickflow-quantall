import importlib.util
import sys
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/analyze_abnormal_demand_shock.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("analyze_abnormal_demand_shock", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_cooldown_and_control_matching_are_deterministic() -> None:
    candidates = [
        {"symbol": "A", "position": 10, "date": date(2020, 1, 2), "return_percentile": 0.91},
        {"symbol": "A", "position": 20, "date": date(2020, 1, 3), "return_percentile": 0.92},
        {"symbol": "A", "position": 30, "date": date(2020, 1, 6), "return_percentile": 0.93},
    ]
    controls = [
        {"symbol": "C", "date": date(2020, 1, 2), "return_percentile": 0.90},
        {"symbol": "B", "date": date(2020, 1, 2), "return_percentile": 0.90},
        {"symbol": "D", "date": date(2020, 1, 6), "return_percentile": 0.94},
    ]

    kept = MODULE.retain_first_after_cooldown(candidates, 20)
    pairs = MODULE.match_controls(kept, controls)

    assert [row["position"] for row in kept] == [10, 30]
    assert [control["symbol"] for _, control in pairs] == ["B", "D"]
