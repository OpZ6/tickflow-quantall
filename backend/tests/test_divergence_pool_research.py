import importlib.util
from pathlib import Path
import sys

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/research_divergence_pool.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("research_divergence_pool", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_fixed_ultrashort_horizons():
    assert MODULE.HORIZONS == (1, 2, 3, 5, 10, 20)
