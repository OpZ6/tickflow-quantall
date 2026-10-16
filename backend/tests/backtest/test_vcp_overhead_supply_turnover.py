from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from analyze_vcp_overhead_supply_turnover import cumulative_float_turnover


def test_cumulative_float_turnover_converts_lots_to_shares() -> None:
    result = cumulative_float_turnover(
        np.array([10_000.0, 20_000.0]),
        np.array([10_000_000.0, 10_000_000.0]),
    )

    assert result == pytest.approx(0.3)


def test_cumulative_float_turnover_fails_closed_on_missing_share_history() -> None:
    assert cumulative_float_turnover(np.array([10_000.0]), np.array([np.nan])) is None
