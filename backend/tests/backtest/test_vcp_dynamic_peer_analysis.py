import importlib.util
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "analyze_vcp_dynamic_peers.py"
SPEC = importlib.util.spec_from_file_location("analyze_vcp_dynamic_peers", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_peer_selection_does_not_use_candidate_signal_day_close() -> None:
    days = np.arange(65, dtype=float)
    close = np.column_stack([
        100 + days,
        50 + days * 0.5,
        80 + days * 0.2 + np.sin(days),
        120 - days * 0.1,
    ])

    baseline = MODULE._peer_features(close, 64, 0)
    changed = close.copy()
    changed[64, 0] *= 5

    assert MODULE._peer_features(changed, 64, 0) == baseline
