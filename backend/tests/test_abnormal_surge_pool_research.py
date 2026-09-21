import importlib.util
from pathlib import Path
import sys

import numpy as np


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/research_abnormal_surge_pool.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("research_abnormal_surge_pool", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_process_ages_reset_after_leaving_pool():
    signal = np.array([[False, True], [True, True], [True, False], [False, True], [True, True]])
    assert MODULE.process_ages(signal).tolist() == [[-1, 0], [0, 1], [1, -1], [-1, 0], [0, 1]]


def test_horizons_include_ultrashort_days():
    assert MODULE.HORIZONS == (1, 2, 3, 5, 10, 20)
