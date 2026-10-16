import importlib.util
from pathlib import Path

import numpy as np


def test_recovery_timing_distinguishes_prior_loss_and_same_bar():
    path = Path(__file__).resolve().parents[3] / "scripts/analyze_post_exit_paths.py"
    spec = importlib.util.spec_from_file_location("post_exit_paths", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dates = np.array(["2020-01-02", "2020-01-03"], dtype="datetime64[D]")
    before = module.path_labels(dates, np.array([89., 99.]), np.array([95., 101.]), 100)
    assert before["loss10_before_recovery"]
    assert not before["loss10_same_bar_as_recovery"]
    assert before["first_recovery_date"] == "2020-01-03"
    same = module.path_labels(dates, np.array([89., 99.]), np.array([101., 101.]), 100)
    assert not same["loss10_before_recovery"]
    assert same["loss10_same_bar_as_recovery"]
    never = module.path_labels(dates, np.array([89., 90.]), np.array([95., 99.]), 100)
    assert never["loss10_before_recovery"]
    assert not never["recovered_on_close"]
