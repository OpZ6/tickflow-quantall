import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from research_vcp_breakout_volume_filter import signal_volume_ratio


def test_prior_twenty_excludes_signal_and_future():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(23)]
    rows = [{"date": d, "volume": 100.0} for d in days]
    rows[20]["volume"] = 200.0
    rows[21]["volume"] = 1e9
    assert signal_volume_ratio(rows, days, days[20]) == 2.0
    rows[20]["volume"] = 100.0
    assert signal_volume_ratio(rows, days, days[20]) == 1.0


@pytest.mark.parametrize("bad", [None, 0.0, float("nan")])
def test_missing_or_invalid_history_blocks(bad):
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(21)]
    rows = [{"date": d, "volume": 100.0} for d in days]
    if bad is None:
        rows.pop(5)
    else:
        rows[5]["volume"] = bad
    with pytest.raises(ValueError):
        signal_volume_ratio(rows, days, days[20])
