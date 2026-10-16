#!/usr/bin/env python3
"""Build a causal abnormal-demand candidate and matched-control ledger."""

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


def retain_first_after_cooldown(rows: list[dict], cooldown: int) -> list[dict]:
    kept: list[dict] = []
    last_position: dict[str, int] = {}
    for row in sorted(rows, key=lambda item: (item["symbol"], item["position"])):
        symbol = str(row["symbol"])
        position = int(row["position"])
        if position - last_position.get(symbol, -10_000) < cooldown:
            continue
        kept.append(row)
        last_position[symbol] = position
    return kept


def match_controls(candidates: list[dict], controls: list[dict]) -> list[tuple[dict, dict]]:
    by_date: dict[date, list[dict]] = defaultdict(list)
    for row in controls:
        by_date[row["date"]].append(row)
    pairs = []
    for candidate in sorted(candidates, key=lambda item: (item["date"], item["symbol"])):
        available = by_date.get(candidate["date"], [])
        if not available:
            continue
        control = min(
            available,
            key=lambda item: (
                abs(float(item["return_percentile"]) - float(candidate["return_percentile"])),
                str(item["symbol"]),
            ),
        )
        pairs.append((candidate, control))
    return pairs


def _cohort_summary(rows: list[dict], horizons: list[int], primary: int) -> dict:
    by_year: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_year[int(row["signal_date"][:4])].append(row)

    def mean(key: str, items: list[dict] = rows) -> float:
        return sum(float(row[key]) for row in items) / len(items)

    return {
        "candidates": len(rows),
        "horizons": {
            str(horizon): {
                "average_return": mean(f"return_{horizon}d"),
                "average_alpha": mean(f"alpha_{horizon}d"),
            }
            for horizon in horizons
        },
        "positive_primary_alpha_years": sum(
            mean(f"alpha_{primary}d", items) > 0 for items in by_year.values()
        ),
        "years_present": len(by_year),
        "mfe_40d_20pct_rate": sum(row["mfe_40d"] >= 0.2 for row in rows) / len(rows),
        "mfe_40d_50pct_count": sum(row["mfe_40d"] >= 0.5 for row in rows),
        "mfe_40d_100pct_count": sum(row["mfe_40d"] >= 1.0 for row in rows),
        "by_signal_year": {
            str(year): {
                "candidates": len(items),
                f"average_{primary}d_alpha": mean(f"alpha_{primary}d", items),
            }
            for year, items in sorted(by_year.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "docs/research/demand-shock/abnormal-demand-shock-train-2016-2022-v1.json",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    data_start, data_end = protocol["data_period"]
    signal_start, signal_end = map(date.fromisoformat, protocol["signal_period"])
    horizons = [int(value) for value in protocol["reported_horizon_bars"]]
    primary = int(protocol["primary_horizon_bars"])
    maximum_horizon = max(horizons)

    files = [
        str(path)
        for path in sorted((args.data_root / "kline_daily_enriched").glob("date=*/part.parquet"))
        if f"date={data_start}" <= path.parent.name <= f"date={data_end}"
    ]
    panel = (
        pl.scan_parquet(files, missing_columns="insert", extra_columns="ignore")
        .filter(pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ"))
        .select("symbol", "date", "open", "high", "low", "close", "volume", "amount")
        .sort(["symbol", "date"])
        .collect()
    )
    calendar = (
        panel.select("date")
        .unique()
        .sort("date")
        .with_columns(pl.col("date").shift(-1).alias("next_market_date"))
    )
    features = (
        panel.with_columns(
            pl.int_range(pl.len()).over("symbol").alias("position"),
            pl.col("close").shift(1).over("symbol").alias("previous_close"),
            pl.col("volume")
            .rolling_median(window_size=20, min_samples=20)
            .shift(1)
            .over("symbol")
            .alias("prior_volume_median_20"),
            pl.col("date").shift(-1).over("symbol").alias("entry_date"),
            pl.col("open").shift(-1).over("symbol").alias("entry_open"),
        )
        .with_columns(
            (pl.col("close") / pl.col("previous_close") - 1.0).alias("daily_return"),
            (pl.col("volume") / pl.col("prior_volume_median_20")).alias("volume_shock"),
            pl.when(pl.col("high") > pl.col("low"))
            .then((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low")))
            .otherwise(None)
            .alias("close_location"),
        )
        .join(calendar, on="date", how="left")
        .filter(
            pl.col("date").is_between(signal_start, signal_end)
            & pl.col("close").is_between(3.0, 300.0)
            & (pl.col("amount") >= 20_000_000.0)
            & pl.col("daily_return").is_finite()
            & pl.col("volume_shock").is_finite()
            & (pl.col("entry_date") == pl.col("next_market_date"))
            & pl.col("entry_open").is_finite()
            & (pl.col("entry_open") > 0)
        )
        .with_columns(
            (pl.col("daily_return").rank("average").over("date") / pl.len().over("date")).alias(
                "return_percentile"
            ),
            (pl.col("volume_shock").rank("average").over("date") / pl.len().over("date")).alias(
                "volume_shock_percentile"
            ),
        )
    )
    price_confirmed = features.filter(
        (pl.col("daily_return") > 0)
        & (pl.col("close_location") >= 0.7)
        & (pl.col("return_percentile") >= 0.8)
    )
    candidate_rows = retain_first_after_cooldown(
        price_confirmed.filter(pl.col("volume_shock_percentile") >= 0.9).to_dicts(), 20
    )
    control_rows = price_confirmed.filter(
        pl.col("volume_shock_percentile").is_between(0.4, 0.6)
    ).to_dicts()
    pairs = match_controls(candidate_rows, control_rows)

    grouped = {}
    for key, frame in panel.partition_by("symbol", as_dict=True).items():
        symbol = key[0] if isinstance(key, tuple) else key
        grouped[symbol] = (
            frame,
            {value: index for index, value in enumerate(frame["date"].to_list())},
        )
    market_by_date = {
        row["date"]: row
        for row in build_equal_weight_market_returns(
            panel.select("symbol", "date", "open", "close")
        ).to_dicts()
    }

    def label(row: dict, cohort: str, pair_id: int) -> dict | None:
        frame, indexes = grouped[str(row["symbol"])]
        entry_index = indexes.get(row["entry_date"])
        if entry_index is None:
            return None
        evaluated = frame.slice(entry_index, maximum_horizon + 1)
        if evaluated.height < maximum_horizon + 1:
            return None
        dates = evaluated["date"].to_list()
        if dates[-1] > date.fromisoformat(data_end):
            return None
        entry_open = float(row["entry_open"])
        result = {
            "pair_id": pair_id,
            "cohort": cohort,
            "symbol": str(row["symbol"]),
            "signal_date": row["date"].isoformat(),
            "entry_date": row["entry_date"].isoformat(),
            "label_end_date": dates[-1].isoformat(),
            "daily_return": float(row["daily_return"]),
            "return_percentile": float(row["return_percentile"]),
            "volume_shock": float(row["volume_shock"]),
            "volume_shock_percentile": float(row["volume_shock_percentile"]),
            "mfe_40d": max((evaluated["high"] / entry_open - 1.0).to_list()),
            "mae_40d": min((evaluated["low"] / entry_open - 1.0).to_list()),
        }
        for horizon in horizons:
            observed = evaluated.slice(0, horizon + 1)
            observed_dates = observed["date"].to_list()
            stock_return = float(observed["close"][-1]) / entry_open - 1.0
            market_return = _market_return(observed_dates, market_by_date)
            result[f"return_{horizon}d"] = stock_return
            result[f"market_return_{horizon}d"] = market_return
            result[f"alpha_{horizon}d"] = _geometric_excess(stock_return, market_return)
        result["market_outcome_20d"] = _market_outcome_regime(result["market_return_20d"])
        return result

    records = []
    excluded_incomplete_pairs = 0
    for pair_id, (candidate, control) in enumerate(pairs):
        candidate_record = label(candidate, "candidate", pair_id)
        control_record = label(control, "matched_control", pair_id)
        if candidate_record is None or control_record is None:
            excluded_incomplete_pairs += 1
            continue
        records.extend([candidate_record, control_record])

    candidates = [row for row in records if row["cohort"] == "candidate"]
    controls = [row for row in records if row["cohort"] == "matched_control"]
    candidate_summary = _cohort_summary(candidates, horizons, primary)
    control_summary = _cohort_summary(controls, horizons, primary)
    pair_spreads = [
        {
            "year": int(candidate["signal_date"][:4]),
            "spread": candidate[f"alpha_{primary}d"] - control[f"alpha_{primary}d"],
        }
        for candidate, control in zip(candidates, controls, strict=True)
    ]
    spread_by_year: dict[int, list[float]] = defaultdict(list)
    for row in pair_spreads:
        spread_by_year[row["year"]].append(row["spread"])
    average_spread = sum(row["spread"] for row in pair_spreads) / len(pair_spreads)
    mfe_enrichment = candidate_summary["mfe_40d_20pct_rate"] / control_summary["mfe_40d_20pct_rate"]
    gates = protocol["training_gate"]
    checks = {
        "minimum_matched_candidates": len(candidates) >= gates["minimum_matched_candidates"],
        "minimum_average_20d_alpha": candidate_summary["horizons"][str(primary)]["average_alpha"]
        >= gates["minimum_average_20d_alpha"],
        "minimum_candidate_minus_control_20d_alpha": average_spread
        >= gates["minimum_candidate_minus_control_20d_alpha"],
        "minimum_positive_candidate_alpha_years": candidate_summary["positive_primary_alpha_years"]
        >= gates["minimum_positive_candidate_alpha_years"],
        "minimum_positive_pair_spread_years": sum(
            sum(values) / len(values) > 0 for values in spread_by_year.values()
        )
        >= gates["minimum_positive_pair_spread_years"],
        "minimum_40d_mfe_20pct_rate": candidate_summary["mfe_40d_20pct_rate"]
        >= gates["minimum_40d_mfe_20pct_rate"],
        "minimum_40d_mfe_20pct_enrichment_vs_control": mfe_enrichment
        >= gates["minimum_40d_mfe_20pct_enrichment_vs_control"],
    }
    result = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "candidate": candidate_summary,
        "matched_control": control_summary,
        "candidate_minus_control_20d_alpha": average_spread,
        "positive_pair_spread_years": sum(
            sum(values) / len(values) > 0 for values in spread_by_year.values()
        ),
        "pair_spread_by_signal_year": {
            str(year): sum(values) / len(values) for year, values in sorted(spread_by_year.items())
        },
        "mfe_40d_20pct_enrichment_vs_control": mfe_enrichment,
        "candidate_events_before_matching": len(candidate_rows),
        "excluded_incomplete_pairs": excluded_incomplete_pairs,
        "maximum_label_end_date": max(row["label_end_date"] for row in records),
        "training_checks": checks,
        "passed_training": all(checks.values()),
        "temporal_test_inspected": False,
    }
    output_dir = args.data_root / "research/demand-shock" / protocol["experiment"]
    output_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(records).write_parquet(output_dir / "candidate-control-ledger.parquet")
    (output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    decision = {
        **result,
        "decision": "freeze_for_time_test" if result["passed_training"] else "reject_training",
        "next_action": (
            protocol["success_action"] if result["passed_training"] else protocol["failure_action"]
        ),
    }
    args.protocol.with_name(f"{protocol['experiment']}-decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
