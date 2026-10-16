import importlib.util
from pathlib import Path
import sys
import numpy as np

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/research_failed_limit_repair_pool.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("research_failed_limit_repair_pool", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


def test_board_limit_rates_follow_launch_dates():
    symbols = np.array(["300001.SZ", "300001.SZ", "688001.SH", "830001.BJ", "600001.SH"])
    dates = np.array(["2020-08-21", "2020-08-24", "2019-07-22", "2022-01-01", "2022-01-01"], dtype="datetime64[D]")
    assert np.allclose(MODULE.limit_rates(symbols, dates), [.1, .2, .2, .3, .1])


def test_fixed_horizons():
    assert MODULE.HORIZONS == (1, 2, 3, 5, 10, 20)
