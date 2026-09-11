import importlib.util
from datetime import date, timedelta
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "research_vcp_two_bar_no_demand.py"
SPEC = importlib.util.spec_from_file_location("research_vcp_two_bar_no_demand", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _bars(volumes: list[float], start: date = date(2020, 1, 2)) -> tuple[list[dict], list[date]]:
    days: list[date] = []
    cursor = start
    while len(days) < len(volumes):
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    sessions = [
        {"date": day, "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": vol}
        for day, vol in zip(days, volumes, strict=True)
    ]
    return sessions, days


def test_breakout_low_holds_prior_low_and_rejects_undercut() -> None:
    sessions, calendar = _bars([100.0] * 3)
    sessions[0]["low"] = 9.5
    sessions[1]["low"] = 9.6
    sessions[2]["low"] = 9.4
    hold = MODULE.breakout_low_holds_prior_low(
        signal_date=calendar[1], sessions=sessions, market_calendar=calendar
    )
    cut = MODULE.breakout_low_holds_prior_low(
        signal_date=calendar[2], sessions=sessions, market_calendar=calendar
    )
    assert hold["holds"] is True
    assert cut["holds"] is False
    assert cut["reason"] == "undercut_prior_low"


def test_breakout_volume_at_least_prior_20_mean_is_expanded() -> None:
    volumes = [100.0] * 20 + [100.0]
    sessions, calendar = _bars(volumes)
    got = MODULE.breakout_volume_expanded(
        signal_date=calendar[-1], sessions=sessions, market_calendar=calendar
    )
    assert got["expanded"] is True
    volumes[-1] = 99.0
    sessions, calendar = _bars(volumes)
    got = MODULE.breakout_volume_expanded(
        signal_date=calendar[-1], sessions=sessions, market_calendar=calendar
    )
    assert got["expanded"] is False
    assert got["reason"] == "quiet_breakout"


def test_prebreakout_contraction_compares_5d_mean_to_20d_mean() -> None:
    volumes = [200.0] * 15 + [50.0] * 5 + [80.0]
    sessions, calendar = _bars(volumes)
    got = MODULE.prebreakout_volume_contracted(
        signal_date=calendar[-1], sessions=sessions, market_calendar=calendar
    )
    assert got["contracted"] is True
    assert got["expanding"] is False
    volumes = [50.0] * 15 + [200.0] * 5 + [80.0]
    sessions, calendar = _bars(volumes)
    got = MODULE.prebreakout_volume_contracted(
        signal_date=calendar[-1], sessions=sessions, market_calendar=calendar
    )
    assert got["contracted"] is False
    assert got["expanding"] is True
    assert got["reason"] == "not_contracted"


def test_volume_lookback_hole_is_not_expanded() -> None:
    volumes = [100.0] * 21
    sessions, calendar = _bars(volumes)
    hole_day = calendar[10]
    stock = [row for row in sessions if row["date"] != hole_day]
    got = MODULE.breakout_volume_expanded(
        signal_date=calendar[-1], sessions=stock, market_calendar=calendar
    )
    assert got["expanded"] is False
    assert got["reason"] == "missing_prior_bar"
