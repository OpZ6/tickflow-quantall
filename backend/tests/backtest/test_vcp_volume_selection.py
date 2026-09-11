import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "vcp_volume_selection", Path(__file__).resolve().parents[3] / "scripts/research_vcp_volume_selection.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_disjoint_volume_windows_and_missing_inputs():
    prior = np.array([100.] * 30 + [50.] * 10)
    assert module.volume_ratio(prior) == .5
    assert module.volume_ratio(np.r_[999999., prior]) == .5
    assert np.isnan(module.volume_ratio(prior[:-1]))
    prior[0] = 0
    assert np.isnan(module.volume_ratio(prior))
    prior[0] = np.nan
    assert np.isnan(module.volume_ratio(prior))
    assert module.volume_ratio([50.] * 30 + [100.] * 10) == pytest.approx(2.)


def test_lower_half_is_within_date_keeps_ties_and_singletons():
    valid, selected = module.select_dry_half([.3, .7, .7, 2., np.nan])
    assert valid.tolist() == [True, True, True, True, False]
    assert selected.tolist() == [True, True, True, False, False]
    assert module.select_dry_half([.9])[1].tolist() == [True]
    assert module.select_dry_half([2., 2.])[1].tolist() == [True, True]
    assert module.select_dry_half([np.nan, 0])[1].tolist() == [False, False]
