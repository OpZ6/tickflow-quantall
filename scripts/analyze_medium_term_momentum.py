#!/usr/bin/env python3
"""Build a purged monthly 12-1 momentum candidate and control ledger."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import polars as pl
from analyze_vcp_trade_paths import (
    _geometric_excess,
    _market_outcome_regime,
    _market_return,
    build_equal_weight_market_returns,
)

ROOT = Path(__file__).resolve().parents[1]


def _summarize(rows: list[dict]) -> dict:
    by_year: dict[int, list[dict]] = defaultdict(list)
    by_market: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_year[int(row["signal_date"][:4])].append(row)
        by_market[str(row["market_outcome_40d"])].append(row)

    def stats(items: list[dict]) -> dict:
        return {
            "candidates": len(items),
            "average_40d_return": sum(row["return_40d"] for row in items) / len(items),
            "average_40d_alpha": sum(row["alpha_40d"] for row in items) / len(items),
            "mfe_20pct_rate": sum(row["mfe_40d"] >= 0.2 for row in items) / len(items),
            "mfe_50pct_count": sum(row["mfe_40d"] >= 0.5 for row in items),
            "mfe_100pct_count": sum(row["mfe_40d"] >= 1.0 for row in items),
        }

    return {
        **stats(rows),
        "positive_alpha_years": sum(
            stats(items)["average_40d_alpha"] > 0 for items in by_year.values()
        ),
        "by_signal_year": {
            str(year): stats(items) for year, items in sorted(by_year.items())
        },
        "by_future_market_outcome": {
            regime: stats(items) for regime, items in sorted(by_market.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "docs/research/momentum/medium-term-skip-month-momentum-train-2016-2022-v1.json",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    data_start, data_end = protocol["training_data_period"]
    signal_start, signal_end = protocol["training_signal_period"]
    horizon = int(protocol["label_horizon_bars"])
    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={data_start}" <= path.parent.name <= f"date={data_end}"
    ]
    panel = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "date", "open", "high", "low", "close", "amount")
        .sort(["symbol", "date"])
        .collect()
    )
    calendar = (
        panel.select("date").unique().sort("date")
        .with_columns(pl.col("date").shift(-1).alias("next_market_date"))
        .with_columns(
            (
                pl.col("next_market_date").is_null()
                | (pl.col("date").dt.month() != pl.col("next_market_date").dt.month())
            ).alias("month_end")
        )
    )
    selection = protocol["selection"]
    events = (
        panel.with_columns(
            pl.col("close").shift(21).over("symbol").alias("close_t_minus_21"),
            pl.col("close").shift(252).over("symbol").alias("close_t_minus_252"),
            pl.col("date").shift(-1).over("symbol").alias("entry_date"),
            pl.col("open").shift(-1).over("symbol").alias("entry_open"),
        )
        .with_columns(
            (pl.col("close_t_minus_21") / pl.col("close_t_minus_252") - 1.0)
            .alias("skip_month_momentum")
        )
        .join(calendar, on="date", how="left")
        .filter(
            pl.col("month_end")
            & pl.col("date").is_between(date.fromisoformat(signal_start), date.fromisoformat(signal_end))
            & pl.col("close").is_between(*selection["eligible_signal_close"])
            & (pl.col("amount") >= float(selection["minimum_signal_amount_cny"]))
            & pl.col("skip_month_momentum").is_finite()
            & (pl.col("entry_date") == pl.col("next_market_date"))
            & (pl.col("entry_date") <= date.fromisoformat(data_end))
            & pl.col("entry_open").is_finite()
            & (pl.col("entry_open") > 0)
        )
        .with_columns(
            (
                pl.col("skip_month_momentum").rank("average").over("date")
                / pl.len().over("date")
            ).alias("momentum_percentile")
        )
        .filter(
            (pl.col("momentum_percentile") >= float(selection["candidate_percentile_min"]))
            | (pl.col("momentum_percentile") <= float(selection["control_percentile_max"]))
        )
    )
    grouped = {}
    for key, frame in panel.partition_by("symbol", as_dict=True).items():
        symbol = key[0] if isinstance(key, tuple) else key
        frame = frame.sort("date")
        grouped[symbol] = (
            frame,
            {value: index for index, value in enumerate(frame["date"].to_list())},
        )
    market_returns = build_equal_weight_market_returns(
        panel.select("symbol", "date", "open", "close")
    )
    market_by_date = {row["date"]: row for row in market_returns.to_dicts()}
    rows = []
    excluded_incomplete_labels = {"candidate": 0, "control": 0}
    for event in events.to_dicts():
        symbol = str(event["symbol"])
        entry_date = event["entry_date"]
        frame, indexes = grouped[symbol]
        entry_index = indexes[entry_date]
        evaluated = frame.slice(entry_index, horizon + 1)
        percentile = float(event["momentum_percentile"])
        cohort = (
            "candidate"
            if percentile >= float(selection["candidate_percentile_min"])
            else "control"
        )
        if evaluated.height < horizon + 1:
            excluded_incomplete_labels[cohort] += 1
            continue
        evaluated_dates = evaluated["date"].to_list()
        if evaluated_dates[-1] > date.fromisoformat(data_end):
            excluded_incomplete_labels[cohort] += 1
            continue
        entry_open = float(event["entry_open"])
        stock_return = float(evaluated["close"][-1]) / entry_open - 1.0
        market_return = _market_return(evaluated_dates, market_by_date)
        rows.append({
            "symbol": symbol,
            "signal_date": event["date"].isoformat(),
            "entry_date": entry_date.isoformat(),
            "label_end_date": evaluated_dates[-1].isoformat(),
            "cohort": cohort,
            "skip_month_momentum": float(event["skip_month_momentum"]),
            "momentum_percentile": percentile,
            "return_40d": stock_return,
            "market_return_40d": market_return,
            "alpha_40d": _geometric_excess(stock_return, market_return),
            "mfe_40d": max((evaluated["high"] / entry_open - 1.0).to_list()),
            "mae_40d": min((evaluated["low"] / entry_open - 1.0).to_list()),
            "market_outcome_40d": _market_outcome_regime(market_return),
        })
    candidates = [row for row in rows if row["cohort"] == "candidate"]
    controls = [row for row in rows if row["cohort"] == "control"]
    candidate_summary, control_summary = _summarize(candidates), _summarize(controls)
    spread = candidate_summary["average_40d_alpha"] - control_summary["average_40d_alpha"]
    gates = protocol["training_gate"]
    checks = {
        "minimum_candidates": candidate_summary["candidates"] >= gates["minimum_candidates"],
        "minimum_average_40d_alpha": candidate_summary["average_40d_alpha"] >= gates["minimum_average_40d_alpha"],
        "minimum_top_minus_bottom_40d_alpha": spread >= gates["minimum_top_minus_bottom_40d_alpha"],
        "minimum_positive_alpha_years": candidate_summary["positive_alpha_years"] >= gates["minimum_positive_alpha_years"],
        "minimum_mfe_20pct_rate": candidate_summary["mfe_20pct_rate"] >= gates["minimum_mfe_20pct_rate"],
        "minimum_mfe_50pct_count": candidate_summary["mfe_50pct_count"] >= gates["minimum_mfe_50pct_count"],
    }
    result = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "candidate": candidate_summary,
        "control": control_summary,
        "candidate_minus_control_40d_alpha": spread,
        "training_checks": checks,
        "passed_training": all(checks.values()),
        "excluded_incomplete_labels": excluded_incomplete_labels,
        "maximum_label_end_date": max(row["label_end_date"] for row in rows),
        "temporal_test_inspected": False,
    }
    output_dir = args.data_root / "research/momentum" / protocol["experiment"]
    output_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(output_dir / "candidate-control-ledger.parquet")
    (output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    decision_path = args.protocol.with_name(f"{protocol['experiment']}-decision.json")
    decision_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
