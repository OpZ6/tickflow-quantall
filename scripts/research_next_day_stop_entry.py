"""One-session buy-stop transform for an already delayed research matrix."""
from dataclasses import replace

import numpy as np


def next_day_stop_entry(matrix):
    """Trigger above signal high; missing/untriggered orders expire, never fall back."""
    entry = matrix.entry.copy()
    times = matrix.entry_signal_time.copy()
    codes = matrix.entry_signal_code.copy()
    prices = np.full(matrix.shape, np.nan, dtype=np.float32)
    stats = {"orders": int(np.count_nonzero(entry)), "triggered": 0,
             "untriggered": 0, "invalid": 0, "gap_open": 0, "intraday": 0}
    for t, a in zip(*np.nonzero(entry), strict=True):
        signal = int(times[t, a])
        if signal != t - 1 or signal < 0:
            raise ValueError("Buy-stop requires exactly next-market-session delayed orders")
        trigger, opening, high = matrix.high[signal, a], matrix.open[t, a], matrix.high[t, a]
        valid = all(np.isfinite(x) and x > 0 for x in (trigger, opening, high)) and high >= opening
        if not valid or high <= trigger:
            stats["untriggered" if valid else "invalid"] += 1
            entry[t, a], times[t, a], codes[t, a] = 0, -1, -1
            continue
        prices[t, a] = max(opening, trigger)
        stats["triggered"] += 1
        stats["gap_open" if opening > trigger else "intraday"] += 1
    # Keep all OHLC and sell constraints intact. These experiments have no
    # intraday trailing/profit activation; entry-day selling is forbidden by T+1.
    return replace(matrix, entry=entry, entry_signal_time=times,
                   entry_signal_code=codes, entry_price=prices), stats
