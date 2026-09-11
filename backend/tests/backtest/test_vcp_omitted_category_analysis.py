import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "analyze_vcp_omitted_categories.py"
SPEC = importlib.util.spec_from_file_location("analyze_vcp_omitted_categories", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_structure_categories_are_mutually_exclusive() -> None:
    assert MODULE.classify_structure(
        range_contracting=True, higher_low=True, volume_dry=True
    ) == "contracting_shelf"
    assert MODULE.classify_structure(
        range_contracting=True, higher_low=True, volume_dry=False
    ) == "contraction_without_dry_up"
    assert MODULE.classify_structure(
        range_contracting=False, higher_low=False, volume_dry=True
    ) == "volume_dry_base"
    assert MODULE.classify_structure(
        range_contracting=False, higher_low=True, volume_dry=False
    ) == "ascending_base"
    assert MODULE.classify_structure(
        range_contracting=True, higher_low=False, volume_dry=False
    ) == "range_compression_only"
    assert MODULE.classify_structure(
        range_contracting=False, higher_low=False, volume_dry=False
    ) == "loose_breakout"


def test_matched_expectation_uses_same_year_and_market_outcome() -> None:
    rows = [
        {"signal_year": 2020, "market_regime_at_signal": "broad_bull", "structure_category": "contracting_shelf", "leader_50": True, "leader_100": False, "failed_control": False, "alpha_40d": 0.2},
        {"signal_year": 2020, "market_regime_at_signal": "broad_bull", "structure_category": "contracting_shelf", "leader_50": False, "leader_100": False, "failed_control": True, "alpha_40d": -0.1},
        {"signal_year": 2020, "market_regime_at_signal": "broad_bull", "structure_category": "loose_breakout", "leader_50": False, "leader_100": False, "failed_control": True, "alpha_40d": -0.2},
        {"signal_year": 2021, "market_regime_at_signal": "weak_bear", "structure_category": "loose_breakout", "leader_50": True, "leader_100": False, "failed_control": False, "alpha_40d": 0.1},
        {"signal_year": 2021, "market_regime_at_signal": "weak_bear", "structure_category": "loose_breakout", "leader_50": False, "leader_100": False, "failed_control": True, "alpha_40d": -0.1},
    ]

    observed, expected = MODULE._matched_expected(rows, "contracting_shelf")

    assert observed == 1
    assert expected == 2 / 8 + 1 / 7
