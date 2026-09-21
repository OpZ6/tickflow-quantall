"""A crossing is a signal-day event, not merely standing above resistance."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_cup_fresh_pivot_cross import crosses_pivot


@pytest.mark.parametrize("before,close,pivot,expected", [
    (9, 11, 10, True), (10, 11, 10, True), (9, 10, 10, False),
    (11, 12, 10, False), (11, 9, 10, False),
    (None, 11, 10, None), (9, 11, None, None),
    (float("nan"), 11, 10, None), (9, 11, 0, None),
])
def test_crossing_boundary(before, close, pivot, expected):
    assert crosses_pivot(before, close, pivot) is expected
