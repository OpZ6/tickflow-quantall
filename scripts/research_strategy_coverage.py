"""Compare completed training-entry coverage without changing strategy rules."""
import json
from itertools import combinations
from pathlib import Path
from statistics import mean

import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def summarize(book):
    return {"trades": len(book), "signal_days": len({t["entry_signal_date"] for t in book}),
            "avg_net": mean(t["pnl_pct"] for t in book) if book else None}


def longest_gap(calendar, active):
    best = run = 0
    for day in calendar:
        run = 0 if day in active else run + 1
        best = max(best, run)
    return best


def main():
    books = {
        "vcp": read("data/research/vcp/runs/20260913T020510923171Z/result.json")["trades"],
        "cup": [r["baseline"] for r in read("data/research/cup-handle/cup-armed-ma20-exit-v1-chronology-rebase/ledger.json")],
        "pullback": [r["baseline"] for r in read("data/research/pullback/launch-fixed-support-exit-v1-chronology-rebase/ledger.json")],
    }
    books = {k: [t for t in v if "2016-01-01" <= t["entry_signal_date"][:10]
                 and t["exit_date"][:10] <= "2022-12-31"] for k, v in books.items()}
    assert {k: len(v) for k, v in books.items()} == {"vcp": 180, "cup": 2034, "pullback": 1421}
    days = {k: {t["entry_signal_date"][:10] for t in v} for k, v in books.items()}
    events = {k: {(t["symbol"], t["entry_signal_date"][:10]) for t in v} for k, v in books.items()}
    calendar_source = "data/research/calendar-20150101-20260907.json"
    cal = read(calendar_source)["payload"]["trade_calendar"]["records"]
    calendar = sorted({f'{r["cal_date"][:4]}-{r["cal_date"][4:6]}-{r["cal_date"][6:]}'
                       for r in cal if r["exchange"] == "SSE" and r["is_open"] == 1
                       and "20160101" <= r["cal_date"] <= "20221231"})
    if not calendar or set.union(*days.values()) - set(calendar):
        raise ValueError("Trading calendar missing completed signal dates")
    files = [p for p in (ROOT / "data/kline_index_daily").glob("date=*/part.parquet")
             if p.parent.name <= "date=2022-12-31"]
    index = (pl.scan_parquet(files).filter(pl.col("symbol") == "000300.SH")
             .select("date", "close").sort("date").collect()
             .with_columns(pl.col("close").rolling_mean(20).alias("ma")))
    if index["date"].n_unique() != index.height or set(calendar) - {str(d) for d in index["date"]}:
        raise ValueError("Index dates duplicated or missing calendar sessions")
    states = {}
    previous = None
    for row in index.to_dicts():
        ma = row["ma"]
        state = "missing" if ma is None or previous is None else (
            "rising" if row["close"] >= ma and ma > previous else
            "falling" if row["close"] <= ma and ma < previous else "mixed")
        states[str(row["date"])] = state
        previous = ma
    report = {
        "scope": "Completed training trades only; executed-event coverage, not all generated signals. Descriptive CSI300 contemporaneous MA20 state, not a new filter.",
        "market_sessions": len(calendar),
        "calendar_source": calendar_source,
        "source_signal_windows": {"cup": ["2016-01-04", "2022-10-11"],
                                  "pullback": ["2016-01-04", "2022-12-30"]},
        "coverage_caveat": "Cup source stops on 2022-10-11; later zero events are unobserved, not strategy inactivity. Common full-year denominator describes archived books only.",
        "strategies": {}, "pairs": {},
        "union_execution_days": len(set.union(*days.values())),
        "union_execution_day_fraction": len(set.union(*days.values())) / len(calendar),
        "union_longest_gap": longest_gap(calendar, set.union(*days.values())),
        "union_symbol_signal_day_events": len(set.union(*events.values())),
    }
    for name, book in books.items():
        report["strategies"][name] = {
            **summarize(book),
            "execution_day_fraction": len(days[name]) / len(calendar),
            "longest_execution_day_gap": longest_gap(calendar, days[name]),
            "environments": {state: {**summarize([t for t in book if states.get(t["entry_signal_date"][:10], "missing") == state]),
                                      "market_sessions": sum(states.get(d, "missing") == state for d in calendar)}
                             for state in ("rising", "falling", "mixed", "missing")},
            "months": {m: summarize([t for t in book if t["entry_signal_date"].startswith(m)])
                       for m in sorted({d[:7] for d in calendar})},
            "on_days_without_vcp_execution": summarize([t for t in book if t["entry_signal_date"][:10] not in days["vcp"]]),
        }
    for a, b in combinations(books, 2):
        report["pairs"][f"{a}/{b}"] = {
            "shared_execution_signal_days": len(days[a] & days[b]),
            "day_jaccard": len(days[a] & days[b]) / len(days[a] | days[b]),
            "shared_symbol_signal_day_events": len(events[a] & events[b]),
            "shared_negative_signal_months": [m for m, values in report["strategies"][a]["months"].items()
                                               if values["avg_net"] is not None and values["avg_net"] < 0
                                               and report["strategies"][b]["months"][m]["avg_net"] is not None
                                               and report["strategies"][b]["months"][m]["avg_net"] < 0],
        }
    path = ROOT / "docs/research/multi-strategy-training-coverage-v1-analysis.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "strategies": {k: {a: b for a, b in v.items() if a != "months"}
                                               for k, v in report["strategies"].items()}}, indent=2))


if __name__ == "__main__":
    main()
