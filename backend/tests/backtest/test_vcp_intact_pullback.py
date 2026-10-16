import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from app.backtest.engine import MatcherConfig
from app.backtest.matrix import build_market_data_matrix

spec = importlib.util.spec_from_file_location(
    "intact_pullback", Path(__file__).resolve().parents[3] / "scripts/research_vcp_intact_pullback.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def trigger(close, high=None, volume=None, tradable=None):
    return module.pullback_trigger(
        np.array(close), np.array(high if high is not None else close) + .1,
        np.array(volume if volume is not None else [200] + [100] * (len(close) - 1)),
        np.array(tradable if tradable is not None else [True] * len(close)), 10.,
    )


def test_actual_pullback_then_reclaim_is_prefix_causal():
    assert trigger([11, 10.5, 10.7]) == (2, "confirmed")
    assert trigger([11, 10.5]) == (None, "no_reclaim")
    assert trigger([11, 11.1, 11.2]) == (None, "no_pullback")
    assert trigger([11, 10.5, 10.7, 1, 999]) == (2, "confirmed")
    # Freeze first pullback high: a lower subsequent high cannot lower the trigger.
    assert trigger([11, 10.5, 10.2, 10.4]) == (None, "no_reclaim")


def test_pivot_failure_or_gap_cancels_and_never_restarts():
    assert trigger([11, 10.5, 9.9, 11.5]) == (None, "pivot_failed")
    assert trigger([11, 10.5, 10.7], tradable=[True, False, True]) == (None, "missing_observation")
    assert trigger([11, 10., 10.5]) == (2, "confirmed")
    assert trigger([11, 10.5, 10.7], volume=[200, 200, 300]) == (None, "no_pullback")
    assert trigger([11, 11, 11, 11, 11, 10.5, 12]) == (None, "no_reclaim")


def market_for_test():
    return build_market_data_matrix(pl.DataFrame([
        {"symbol": "600000.SH", "date": date(2016, 1, 4) + timedelta(days=i),
         **{c: float(price) for c in ("open", "high", "low", "close")}, "volume": 1000.}
        for i, price in enumerate([10, 11, 12, 13, 14, 15, 16])
    ]))


def test_delayed_costs_and_common_endpoint_and_cash():
    market = market_for_test()
    config = MatcherConfig(matching="open_t+1", commission_pct=.001, slippage_bps=0)
    baseline = module.replay_arm(market, 0, 6, config)
    delayed = module.replay_arm(market, 2, 6, config)
    assert baseline["exit_date"] == delayed["exit_date"] == "2016-01-10"
    assert baseline["net_return"] == pytest.approx(16 / 11 * .999 / 1.001 - 1)
    assert delayed["net_return"] == pytest.approx(16 / 13 * .999 / 1.001 - 1)
    assert delayed["entry_date"] == "2016-01-07"
    assert delayed["exposure_sessions"] == 3
    assert module.replay_arm(market, None, 6, config)["net_return"] == 0
    with pytest.raises(ValueError):
        module.replay_arm(market, 5, 6, config)


def test_benchmark_does_not_bridge_a_missing_market_session():
    rows = []
    for symbol in ("600000.SH", "600001.SH"):
        for i, price in enumerate([10., 10., 20.]):
            if symbol == "600001.SH" and i == 1:
                continue
            # Keep returns within the benchmark's declared +/-50% filter.
            if i == 2:
                price = 12. if symbol == "600000.SH" else 14.
            rows.append({"symbol": symbol, "date": date(2016, 1, 4) + timedelta(days=i),
                         "open": price, "close": price})
    daily = module.benchmark_daily(pl.DataFrame(rows))
    assert daily["cc"][-1] == pytest.approx(.2)
    assert daily["co"][-1] == pytest.approx(.2)
    assert daily["oc"].to_list() == [0., 0., 0.]


def test_joint_blocks_keep_cash_dates_and_paired_contrasts():
    values = np.array([[.01, .02, .03], [np.nan] * 3, [.01, .02, .03], [.01, .02, .03]])
    result = module.intervals(values, {"seed": 1, "calendar_block_sessions": 2,
                                      "replicates": 100, "local_family_size": 3})
    for row, value in zip(result, [.01, .02, .03], strict=True):
        assert row["mean"] == pytest.approx(value)
        assert row["local_adjusted_ci"] == pytest.approx([value, value])
