import importlib.util
from datetime import date
from pathlib import Path

import polars as pl
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "analyze_vcp_trade_paths.py"
SPEC = importlib.util.spec_from_file_location("analyze_vcp_trade_paths", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_trade_path_analysis_labels_excursions_without_changing_trade() -> None:
    bars = pl.DataFrame({
        "symbol": ["600000.SH"] * 3,
        "date": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
        "high": [101.0, 106.0, 103.0],
        "low": [99.0, 98.0, 94.0],
    })
    trades = [{
        "symbol": "600000.SH",
        "entry_date": "2024-01-02",
        "exit_date": "2024-01-04",
        "entry_price": 100.0,
        "pnl_pct": -0.05,
        "pnl_amount": -500.0,
        "entry_signal_id": "early_recovery",
        "exit_reason": "stop_loss",
    }]

    records = MODULE.analyze_trade_paths(trades, bars)
    summary = MODULE.summarize(records)

    assert records[0]["mfe"] == pytest.approx(0.06)
    assert records[0]["mae"] == pytest.approx(-0.06)
    assert records[0]["first_plus_5_bar"] == 1
    assert records[0]["first_minus_5_bar"] == 2
    assert records[0]["gave_back_5pct_move"] is True
    assert summary["overall"]["stop_loss_share"] == 1.0
    assert summary["overall"]["gave_back_5pct_move_share_of_nonwins"] == 1.0
    assert summary["path_timing_bars"]["stop_losses"]["median_first_minus_5"] == 2.0


def test_trade_path_analysis_separates_held_path_from_post_exit_horizon() -> None:
    bars = pl.DataFrame({
        "symbol": ["600000.SH"] * 6,
        "date": [date(2024, 1, day) for day in range(2, 8)],
        "high": [101.0, 106.0, 104.0, 125.0, 151.0, 140.0],
        "low": [99.0, 98.0, 94.0, 100.0, 120.0, 130.0],
        "close": [100.0, 103.0, 95.0, 120.0, 145.0, 135.0],
    })
    trades = [{
        "symbol": "600000.SH",
        "entry_date": "2024-01-02",
        "exit_date": "2024-01-04",
        "entry_price": 100.0,
        "pnl_pct": -0.05,
        "pnl_amount": -500.0,
        "entry_signal_id": "early_recovery",
        "exit_reason": "stop_loss",
    }]

    records = MODULE.analyze_trade_paths(
        trades, bars, evaluation_horizon_bars=5, early_path_bars=(3, 5),
    )
    summary = MODULE.summarize(
        records, large_winner_thresholds=(0.2, 0.5), early_path_bars=(3, 5),
    )

    assert records[0]["mfe"] == pytest.approx(0.06)
    assert records[0]["horizon_mfe"] == pytest.approx(0.51)
    assert records[0]["evaluation_horizon_end_date"] == "2024-01-07"
    assert records[0]["early_close_returns"]["3"] == pytest.approx(0.2)
    assert records[0]["realized_capture_of_horizon_mfe"] == 0.0
    assert summary["evaluation_horizon"]["large_winner_paths"]["mfe_at_least_50pct"] == {
        "candidates": 1,
        "candidate_share": 1.0,
        "realized_at_least_threshold": 0,
        "positive_exits": 0,
        "average_exit_capture": 0.0,
        "median_exit_capture": 0.0,
    }


def test_trade_path_analysis_measures_market_relative_returns() -> None:
    dates = [date(2024, 1, day) for day in range(2, 6)]
    bars = pl.DataFrame({
        "symbol": ["600000.SH"] * 4,
        "date": dates,
        "high": [101.0, 104.0, 106.0, 111.0],
        "low": [99.0, 100.0, 102.0, 108.0],
        "close": [100.0, 103.0, 105.0, 110.0],
    })
    market = pl.DataFrame({
        "date": dates,
        "open_to_close": [0.01, 0.0, 0.0, 0.0],
        "close_to_close": [None, 0.01, 0.01, 0.01],
        "market_constituents": [100, 100, 100, 100],
    })
    trades = [{
        "symbol": "600000.SH",
        "entry_date": "2024-01-02",
        "exit_date": "2024-01-03",
        "entry_price": 100.0,
        "pnl_pct": 0.03,
        "pnl_amount": 300.0,
        "entry_signal_id": "middle_expansion",
        "exit_reason": "signal",
    }]

    records = MODULE.analyze_trade_paths(
        trades,
        bars,
        market_returns=market,
        evaluation_horizon_bars=3,
        early_path_bars=(2,),
    )
    summary = MODULE.summarize(records, early_path_bars=(2,))

    held_market = 1.01 * 1.01 - 1.0
    horizon_market = 1.01**4 - 1.0
    assert records[0]["market_return_held"] == pytest.approx(held_market)
    assert records[0]["excess_return_held"] == pytest.approx(1.03 / (1 + held_market) - 1)
    assert records[0]["market_return_horizon"] == pytest.approx(horizon_market)
    assert records[0]["excess_return_horizon"] == pytest.approx(1.10 / (1 + horizon_market) - 1)
    assert records[0]["market_outcome_horizon"] == "sideways"
    assert summary["overall"]["average_excess_return_held"] > 0
