import importlib.util
import os
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.backtest.engine import MatcherConfig

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "analyze_right_side_short_windows.py"
SPEC = importlib.util.spec_from_file_location("analyze_right_side_short_windows", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

RUNS_ROOT = Path(__file__).resolve().parents[3] / "data" / "research" / "vcp" / "runs"
ANALYSIS_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "research"
    / "right-side-short-window-autopsy-2016-2022-v1-analysis.json"
)


def test_signal_day_equal_weight_is_mean_of_daily_means_not_pooled() -> None:
    pairs = [("2020-01-02", 0.10), ("2020-01-02", -0.04), ("2020-01-03", 0.16)]
    date_ew = MODULE.signal_day_equal_weight(pairs)
    pooled = sum(value for _, value in pairs) / 3
    assert date_ew == pytest.approx(0.095)
    assert pooled == pytest.approx(0.073333, abs=1e-6)
    assert date_ew != pytest.approx(pooled)


def _session_dates(count: int = 26) -> list[date]:
    start = date(2020, 1, 2)
    return [start + timedelta(days=i) for i in range(count)]


def _flat_bars(symbols: list[str], sessions: list[date], opens: dict[tuple[str, date], float]) -> pl.DataFrame:
    rows = []
    for symbol in symbols:
        for day in sessions:
            price = opens.get((symbol, day), 100.0)
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": price,
                    "high": price * 1.01,
                    "close": price,
                }
            )
    return pl.DataFrame(rows)


def test_label_and_summarize_applies_costs_and_date_equal_weight() -> None:
    sessions = _session_dates()
    entry_ab = sessions[1]
    exit_ab = sessions[1 + 10]
    entry_c = sessions[2]
    exit_c = sessions[2 + 10]
    symbols = ["600000.SH", "600001.SH", "000001.SZ"]
    opens = {
        ("600000.SH", entry_ab): 100.0,
        ("600000.SH", exit_ab): 110.0,
        ("600001.SH", entry_ab): 100.0,
        ("600001.SH", exit_ab): 96.0,
        ("000001.SZ", entry_c): 100.0,
        ("000001.SZ", exit_c): 116.0,
    }
    trades = [
        {
            "symbol": "600000.SH",
            "entry_signal_date": sessions[0].isoformat(),
            "entry_date": entry_ab.isoformat(),
            "entry_price": 100.0,
        },
        {
            "symbol": "600001.SH",
            "entry_signal_date": sessions[0].isoformat(),
            "entry_date": entry_ab.isoformat(),
            "entry_price": 100.0,
        },
        {
            "symbol": "000001.SZ",
            "entry_signal_date": sessions[1].isoformat(),
            "entry_date": entry_c.isoformat(),
            "entry_price": 100.0,
        },
    ]
    records = MODULE.label_trades(trades, _flat_bars(symbols, sessions, opens))
    ten = [row["windows"]["10"] for row in records]
    assert all(slot["complete"] for slot in ten)
    assert ten[0]["gross"] == pytest.approx(0.10)
    assert ten[1]["gross"] == pytest.approx(-0.04)
    assert ten[2]["gross"] == pytest.approx(0.16)
    config = MatcherConfig(
        matching="open_t+1",
        commission_pct=0.0003,
        slippage_bps=10.0,
        stamp_tax_policy="a_share_historical",
    )
    buy = config.buy_cost_pct()
    sell = config.sell_cost_pct(exit_ab)
    expected_nets = [
        MODULE.net_round_trip(0.10, buy, sell),
        MODULE.net_round_trip(-0.04, buy, config.sell_cost_pct(exit_ab)),
        MODULE.net_round_trip(0.16, buy, config.sell_cost_pct(exit_c)),
    ]
    assert ten[0]["net"] == pytest.approx(expected_nets[0])
    assert ten[0]["net"] < ten[0]["gross"]
    assert ten[2]["net"] < ten[2]["gross"]
    summary = MODULE.summarize_family(records)
    date_ew = summary["windows"]["10"]["date_ew_net"]
    trade_mean = summary["windows"]["10"]["trade_mean_net"]
    expected_date_ew = ((expected_nets[0] + expected_nets[1]) / 2 + expected_nets[2]) / 2
    expected_pooled = sum(expected_nets) / 3
    assert date_ew == pytest.approx(round(expected_date_ew, 6))
    assert trade_mean == pytest.approx(round(expected_pooled, 6))
    assert date_ew != pytest.approx(trade_mean)
    assert summary["windows"]["10"]["same_day_unselected"] == MODULE.UNAVAILABLE


def test_verify_runs_matches_cited_counts_or_writes_gaps() -> None:
    if not RUNS_ROOT.is_dir():
        pytest.skip(f"frozen run ledgers absent at {RUNS_ROOT}")
    assert MODULE.verify_runs(RUNS_ROOT) == []


def test_frozen_analysis_ledger_counts_match_committed_figures() -> None:
    """Ledger sizes stay verifiable from the run artefacts alone.

    The return figures in the archive also depend on the market bars under
    data/, and .gitignore excludes that tree wholesale, so the snapshot behind
    those numbers cannot be pinned or reproduced. The ledger counts can: they
    come straight from each run's result.json, so they are checked here.
    """
    import json

    if not RUNS_ROOT.is_dir():
        pytest.skip(f"frozen run ledgers absent at {RUNS_ROOT}")
    assert MODULE.verify_runs(RUNS_ROOT) == [], "cited trade counts must match the ledgers"
    if not ANALYSIS_PATH.is_file():
        pytest.skip(f"committed analysis absent at {ANALYSIS_PATH}")

    committed = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    for family, row in committed["families"].items():
        assert family in MODULE.CITED_TRADES, f"{family} is no longer a tracked experiment"
        run_id, cited = MODULE.CITED_TRADES[family]
        assert row["run_id"] == run_id, f"{family} archive points at a different run"
        assert row["cited_ledger_trades"] == cited, f"{family} cited count drifted from CITED_TRADES"
        assert row["ledger_trades"] == cited, f"{family} ledger count disagrees with the cited count"


def test_frozen_analysis_tables_match_shipped_transform() -> None:
    """Opt-in check of the archived return figures.

    Skipped by default because data/ is gitignored: the market bars the archive
    was scored against are not version controlled, so a machine either holds a
    different snapshot than the one behind the committed numbers or has no
    snapshot at all. Run it only where those exact inputs still exist, e.g.

        TICKFLOW_VERIFY_FROZEN_ANALYSIS=1 pytest tests/backtest/test_right_side_short_windows.py
    """
    import json

    if os.environ.get("TICKFLOW_VERIFY_FROZEN_ANALYSIS") != "1":
        pytest.skip("set TICKFLOW_VERIFY_FROZEN_ANALYSIS=1 with the frozen data/ snapshot to verify return figures")
    if not RUNS_ROOT.is_dir():
        pytest.skip(f"frozen run ledgers absent at {RUNS_ROOT}")
    assert ANALYSIS_PATH.is_file(), "committed analysis is required once frozen runs exist"

    committed = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    data_root = Path(__file__).resolve().parents[3] / "data"
    recomputed = MODULE.autopsy_families(RUNS_ROOT, data_root)
    assert recomputed["gaps"] == []
    for family, row in committed["families"].items():
        got = recomputed["families"][family]
        assert got["ledger_trades"] == row["ledger_trades"]
        assert got["training_trades"] == row["training_trades"]
        for hold in ("5", "10", "20"):
            left = row["windows"][hold]
            right = got["windows"][hold]
            assert left["complete"] == right["complete"]
            assert left["signal_days"] == right["signal_days"]
            assert left["date_ew_net_excess"] == pytest.approx(right["date_ew_net_excess"])
            assert left["trade_mean_net_excess"] == pytest.approx(right["trade_mean_net_excess"])
            assert left["date_ew_net"] == pytest.approx(right["date_ew_net"])
            assert left["same_day_unselected"] == MODULE.UNAVAILABLE
