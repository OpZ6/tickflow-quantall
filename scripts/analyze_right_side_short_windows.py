#!/usr/bin/env python3
"""Scheduled 5/10/20-day net open-to-open labels on frozen filled trades.

Does not re-run detectors. Signal-day equal-weight is the mean of daily means.
Gross close-path early_excess_returns are not treated as a net round-trip.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backtest.engine import MatcherConfig  # noqa: E402

WINDOWS = (5, 10, 20)
TRAINING_END = date(2022, 12, 31)
COST_CONFIG = MatcherConfig(
    matching="open_t+1",
    commission_pct=0.0003,
    slippage_bps=10.0,
    stamp_tax_policy="a_share_historical",
)
CITED_TRADES = {
    "wide_vcp": ("20260909T135940874097Z", 4396),
    "leader_vcp": ("20260908T024521089151Z", 290),
    "cup_handle": ("20260909T133226351846Z", 98489),
    "high_tight_flag": ("20260909T130617820559Z", 1245),
    "launch_pullback": ("20260909T053715693165Z", 32193),
}
UNAVAILABLE = "unavailable_not_in_frozen_inputs"


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def net_round_trip(gross: float, buy_cost: float, sell_cost: float) -> float:
    return (1.0 + gross) * (1.0 - sell_cost) / (1.0 + buy_cost) - 1.0


def geometric_excess(stock: float, market: float) -> float:
    return (1.0 + stock) / (1.0 + market) - 1.0


def signal_day_equal_weight(pairs: list[tuple[str, float]]) -> float | None:
    """Mean of per-signal-day means. Skips empty days."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for day, value in pairs:
        buckets[day].append(value)
    if not buckets:
        return None
    return sum(sum(group) / len(group) for group in buckets.values()) / len(buckets)


def verify_runs(runs_root: Path) -> list[str]:
    gaps: list[str] = []
    for family, (run_id, cited) in CITED_TRADES.items():
        run_dir = runs_root / run_id
        result_path = run_dir / "result.json"
        if not run_dir.is_dir():
            gaps.append(f"{family}: missing run directory {run_id}")
            continue
        if not result_path.is_file():
            gaps.append(f"{family}: missing result.json in {run_id}")
            continue
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        n = len(payload.get("trades") or [])
        if n != cited:
            gaps.append(f"{family}: {run_id} has {n} trades, cited {cited}")
    return gaps


def build_market_open_components(bars: pl.DataFrame) -> pl.DataFrame:
    market = bars.filter(
        pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")
    )
    dates = market.select("date").unique().sort("date").with_row_index("session")
    frame = (
        market.join(dates, on="date")
        .sort(["symbol", "date"])
        .with_columns(
            pl.col("close").shift(1).over("symbol").alias("previous_close"),
            pl.col("session").shift(1).over("symbol").alias("previous_session"),
        )
        .with_columns(
            (pl.col("close") / pl.col("open") - 1.0).alias("oc"),
            pl.when(pl.col("session") == pl.col("previous_session") + 1)
            .then(pl.col("close") / pl.col("previous_close") - 1.0)
            .alias("cc"),
            pl.when(pl.col("session") == pl.col("previous_session") + 1)
            .then(pl.col("open") / pl.col("previous_close") - 1.0)
            .alias("co"),
        )
    )
    finite = lambda col: (  # noqa: E731
        pl.col(col).filter(pl.col(col).is_finite() & pl.col(col).is_between(-0.5, 0.5)).mean()
    )
    return (
        frame.group_by("date")
        .agg(finite("oc").alias("oc"), finite("cc").alias("cc"), finite("co").alias("co"))
        .sort("date")
    )


def _window_market_return(
    oc: list[float | None],
    cc: list[float | None],
    co: list[float | None],
    entry_idx: int,
    hold: int,
) -> float | None:
    exit_idx = entry_idx + hold
    if exit_idx >= len(oc):
        return None
    start = oc[entry_idx]
    finish = co[exit_idx]
    if start is None or finish is None:
        return None
    wealth = 1.0 + float(start)
    for idx in range(entry_idx + 1, exit_idx):
        step = cc[idx]
        if step is None:
            return None
        wealth *= 1.0 + float(step)
    wealth *= 1.0 + float(finish)
    return wealth - 1.0


def label_trades(
    trades: list[dict],
    bars: pl.DataFrame,
    *,
    training_end: date = TRAINING_END,
    config: MatcherConfig = COST_CONFIG,
) -> list[dict]:
    if bars.is_empty():
        raise RuntimeError("no bars supplied for scheduled-window labels")
    frame = bars.with_columns(pl.col("date").cast(pl.Date))
    opens: dict[tuple[str, date], float] = {}
    highs: dict[tuple[str, date], float] = {}
    for row in frame.select("symbol", "date", "open", "high").iter_rows(named=True):
        key = (str(row["symbol"]), row["date"])
        opens[key] = float(row["open"]) if row["open"] is not None else float("nan")
        highs[key] = float(row["high"]) if row["high"] is not None else float("nan")
    components = build_market_open_components(frame)
    calendar = [_as_date(value) for value in components["date"].to_list()]
    index = {day: i for i, day in enumerate(calendar)}
    oc = [None if v is None else float(v) for v in components["oc"].to_list()]
    cc = [None if v is None else float(v) for v in components["cc"].to_list()]
    co = [None if v is None else float(v) for v in components["co"].to_list()]
    buy_cost = config.buy_cost_pct()
    records: list[dict] = []
    for trade in trades:
        signal_day = _as_date(trade["entry_signal_date"])
        entry_day = _as_date(trade["entry_date"])
        symbol = str(trade["symbol"])
        entry_price = float(trade["entry_price"])
        entry_idx = index.get(entry_day)
        next_day = calendar[entry_idx + 1] if entry_idx is not None and entry_idx + 1 < len(calendar) else None
        high0 = highs.get((symbol, entry_day))
        high1 = highs.get((symbol, next_day)) if next_day is not None else None
        early = None
        if (
            entry_price > 0
            and high0 is not None
            and high1 is not None
            and high0 > 0
            and high1 > 0
        ):
            early = max(high0 / entry_price - 1.0, high1 / entry_price - 1.0)
        record = {
            "symbol": symbol,
            "entry_signal_date": signal_day.isoformat(),
            "entry_date": entry_day.isoformat(),
            "entry_year": signal_day.year,
            "early_two_bar_mfe": early,
            "never_plus_3pct": early is not None and early < 0.03,
            "windows": {},
        }
        for hold in WINDOWS:
            slot: dict[str, object] = {"hold_days": hold, "complete": False}
            if entry_idx is None:
                slot["reason"] = "entry_date_not_on_market_calendar"
                record["windows"][str(hold)] = slot
                continue
            exit_idx = entry_idx + hold
            if exit_idx >= len(calendar):
                slot["reason"] = "exit_beyond_calendar"
                record["windows"][str(hold)] = slot
                continue
            exit_day = calendar[exit_idx]
            if exit_day > training_end:
                slot["reason"] = "label_crosses_training_end"
                record["windows"][str(hold)] = slot
                continue
            exit_open = opens.get((symbol, exit_day))
            if exit_open is None or not (exit_open > 0):
                slot["reason"] = "missing_exit_open_no_roll"
                record["windows"][str(hold)] = slot
                continue
            market = _window_market_return(oc, cc, co, entry_idx, hold)
            if market is None:
                slot["reason"] = "incomplete_market_path"
                record["windows"][str(hold)] = slot
                continue
            gross = exit_open / entry_price - 1.0
            sell_cost = config.sell_cost_pct(exit_day)
            net = net_round_trip(gross, buy_cost, sell_cost)
            record["windows"][str(hold)] = {
                "hold_days": hold,
                "complete": True,
                "exit_date": exit_day.isoformat(),
                "gross": gross,
                "net": net,
                "market": market,
                "gross_excess": geometric_excess(gross, market),
                "net_excess": geometric_excess(net, market),
            }
        records.append(record)
    return records


def _window_summary(records: list[dict], hold: int) -> dict:
    key = str(hold)
    complete = [row for row in records if row["windows"].get(key, {}).get("complete")]
    pairs_net = [(row["entry_signal_date"], float(row["windows"][key]["net"])) for row in complete]
    pairs_gross = [(row["entry_signal_date"], float(row["windows"][key]["gross"])) for row in complete]
    pairs_net_ex = [(row["entry_signal_date"], float(row["windows"][key]["net_excess"])) for row in complete]
    pairs_gross_ex = [(row["entry_signal_date"], float(row["windows"][key]["gross_excess"])) for row in complete]
    pairs_mkt = [(row["entry_signal_date"], float(row["windows"][key]["market"])) for row in complete]
    yearly: dict[str, dict] = {}
    for year in sorted({int(row["entry_year"]) for row in complete}):
        group = [row for row in complete if int(row["entry_year"]) == year]
        yearly[str(year)] = {
            "complete": len(group),
            "signal_days": len({row["entry_signal_date"] for row in group}),
            "date_ew_net_excess": _round(
                signal_day_equal_weight(
                    [(row["entry_signal_date"], float(row["windows"][key]["net_excess"])) for row in group]
                )
            ),
        }
    regimes = {"down": [], "sideways": [], "up": []}
    for row in complete:
        market = float(row["windows"][key]["market"])
        if market < -0.05:
            bucket = "down"
        elif market > 0.05:
            bucket = "up"
        else:
            bucket = "sideways"
        regimes[bucket].append(float(row["windows"][key]["net_excess"]))
    return {
        "complete": len(complete),
        "signal_days": len({row["entry_signal_date"] for row in complete}),
        "trade_mean_gross": _round(_mean([v for _, v in pairs_gross])),
        "trade_mean_net": _round(_mean([v for _, v in pairs_net])),
        "trade_mean_gross_excess": _round(_mean([v for _, v in pairs_gross_ex])),
        "trade_mean_net_excess": _round(_mean([v for _, v in pairs_net_ex])),
        "date_ew_gross": _round(signal_day_equal_weight(pairs_gross)),
        "date_ew_net": _round(signal_day_equal_weight(pairs_net)),
        "date_ew_gross_excess": _round(signal_day_equal_weight(pairs_gross_ex)),
        "date_ew_net_excess": _round(signal_day_equal_weight(pairs_net_ex)),
        "date_ew_market": _round(signal_day_equal_weight(pairs_mkt)),
        "same_day_unselected": UNAVAILABLE,
        "positive_excess_years": sum(
            1 for row in yearly.values() if (row["date_ew_net_excess"] or 0) > 0
        ),
        "years_evaluated": len(yearly),
        "yearly": yearly,
        "market_outcome_trade_mean_net_excess": {
            name: _round(_mean(values)) for name, values in regimes.items()
        },
    }


def summarize_family(records: list[dict]) -> dict:
    observed = [row for row in records if row["early_two_bar_mfe"] is not None]
    never = [row for row in observed if row["never_plus_3pct"]]
    five = [
        row
        for row in records
        if row["windows"].get("5", {}).get("complete") and row["early_two_bar_mfe"] is not None
    ]
    return {
        "trades": len(records),
        "windows": {str(hold): _window_summary(records, hold) for hold in WINDOWS},
        "early_death": {
            "first_two_bars_observed": len(observed),
            "never_plus_3pct_count": len(never),
            "never_plus_3pct_share": _round(len(never) / len(observed) if observed else None),
            "window_5_complete_with_two_bars": len(five),
            "never_plus_3pct_and_5d_net_negative_share": _round(
                (
                    sum(
                        1
                        for row in five
                        if row["never_plus_3pct"] and float(row["windows"]["5"]["net"]) < 0
                    )
                    / len(five)
                )
                if five
                else None
            ),
        },
    }


def _load_training_trades(result_path: Path, *, slice_training: bool) -> tuple[list[dict], int]:
    trades = json.loads(result_path.read_text(encoding="utf-8"))["trades"]
    ledger = len(trades)
    if not slice_training:
        return trades, ledger
    kept = [
        trade
        for trade in trades
        if _as_date(trade["entry_signal_date"]) <= TRAINING_END
        and _as_date(trade["entry_date"]) <= TRAINING_END
    ]
    return kept, ledger


def load_training_bars(data_root: Path, start: date, end: date) -> pl.DataFrame:
    files = [
        path
        for path in sorted((data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={start.isoformat()}" <= path.parent.name <= f"date={end.isoformat()}"
    ]
    if not files:
        raise RuntimeError(f"no kline_daily_enriched partitions between {start} and {end}")
    return (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "date", "open", "high", "close")
        .with_columns(pl.col("date").cast(pl.Date))
        .collect()
    )


def autopsy_families(
    runs_root: Path,
    data_root: Path,
    *,
    protocol_path: Path | None = None,
) -> dict:
    gaps = verify_runs(runs_root)
    report: dict = {
        "experiment": "right-side-short-window-autopsy-2016-2022-v1",
        "protocol": str(protocol_path) if protocol_path else None,
        "training_end": TRAINING_END.isoformat(),
        "windows": list(WINDOWS),
        "cost": {
            "commission_pct": 0.0003,
            "slippage_bps": 10.0,
            "stamp_tax_policy": "a_share_historical",
        },
        "gaps": gaps,
        "families": {},
    }
    if gaps:
        return report
    bars = load_training_bars(data_root, date(2015, 12, 1), TRAINING_END)
    if bars.is_empty():
        report["gaps"] = ["kline_daily_enriched produced an empty SH/SZ frame"]
        return report
    for family, (run_id, cited) in CITED_TRADES.items():
        trades, ledger = _load_training_trades(
            runs_root / run_id / "result.json",
            slice_training=True,
        )
        records = label_trades(trades, bars)
        summary = summarize_family(records)
        summary.update(
            {
                "run_id": run_id,
                "cited_ledger_trades": cited,
                "ledger_trades": ledger,
                "training_trades": len(trades),
                "exposure_trades_after_training": ledger - len(trades),
            }
        )
        report["families"][family] = summary
    return report


def verdict_for(summary: dict) -> str:
    ten = summary["windows"]["10"]["date_ew_net_excess"]
    twenty = summary["windows"]["20"]["date_ew_net_excess"]
    five = summary["windows"]["5"]["date_ew_net_excess"]
    if ten is None or twenty is None:
        return "blocked_incomplete_labels"
    if ten < 0 and twenty < 0 and (five is None or five < 0):
        return "stop_as_selector"
    if ten < 0 or twenty < 0:
        return "demote_to_observation_pool"
    return "keep_as_tradable_seed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        default=str(ROOT / "docs/research/right-side-short-window-autopsy-2016-2022-v1.json"),
    )
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs/research/right-side-short-window-autopsy-2016-2022-v1-analysis.json"),
    )
    args = parser.parse_args()
    report = autopsy_families(
        Path(args.runs_root),
        Path(args.data_root),
        protocol_path=Path(args.protocol),
    )
    for summary in report.get("families", {}).values():
        summary["rule"] = verdict_for(summary)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "gaps": report["gaps"], "families": {
        name: {
            "ledger": row["ledger_trades"],
            "training": row["training_trades"],
            "rule": row["rule"],
            "date_ew_net_excess": {
                hold: row["windows"][hold]["date_ew_net_excess"] for hold in ("5", "10", "20")
            },
        }
        for name, row in report.get("families", {}).items()
    }}, ensure_ascii=False, indent=2))
    return 1 if report["gaps"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
