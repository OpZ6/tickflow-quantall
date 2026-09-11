from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from vcp_classic_structure import represent_classic_structure


def _fixture():
    close = np.array(
        [
            8.0,
            9.0,
            10.0,
            11.0,
            12.0,
            11.5,
            10.5,
            9.5,
            9.0,
            9.5,
            10.5,
            11.2,
            11.8,
            11.5,
            11.0,
            10.6,
            10.4,
            10.8,
            11.2,
            11.4,
            11.6,
            11.4,
            11.2,
            11.0,
            10.9,
            11.1,
            11.3,
            11.4,
            11.45,
            11.5,
            12.0,
        ],
        dtype=float,
    )
    high = close + 0.1
    low = close - 0.1
    volume = np.array(
        [
            40,
            39,
            38,
            37,
            36,
            35,
            34,
            33,
            32,
            31,
            30,
            29,
            28,
            27,
            26,
            25,
            24,
            23,
            22,
            21,
            20,
            12,
            11,
            10,
            9,
            8,
            7,
            6,
            5,
            4,
            30,
        ],
        dtype=float,
    )
    dates = np.array([f"D{index:02d}" for index in range(len(close))])
    return high, low, close, volume, dates


def test_signal_bar_does_not_change_prebreakout_structure() -> None:
    high, low, close, volume, dates = _fixture()
    original = represent_classic_structure(high, low, close, volume, dates)
    high[-1], low[-1], close[-1], volume[-1] = 99, 0.1, 50, 9999
    changed = represent_classic_structure(high, low, close, volume, dates)

    for field in ("supported", "reason", "legs", "pivot", "right_edge_position", "prebreakout_supply_ratio"):
        assert changed[field] == original[field]


def test_noncontracting_latest_pullback_is_not_skipped() -> None:
    high, low, close, volume, dates = _fixture()
    baseline = represent_classic_structure(high, low, close, volume, dates)
    assert baseline["checks"]["contiguous_contracting_chain"] is True

    low[24] = 9.4
    close[24] = 9.5
    result = represent_classic_structure(high, low, close, volume, dates)

    assert result["supported"] is False
    assert result["reason"] == "latest_pullbacks_do_not_contract"
