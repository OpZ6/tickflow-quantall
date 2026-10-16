"""Describe primary VCP and same-origin retrigger portfolio overlap without optimizing weights."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    ROOT
    / "docs/research/vcp/production-leader-retrigger-complementarity-audit-2016-2026-v1.json"
)
DEFAULT_OUTPUT = ROOT / "data/research/vcp/analysis/leader-retrigger-complementarity-2016-2026-v1.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True))
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)


def _returns(curve: list[dict]) -> list[float]:
    values = [float(row["value"]) for row in curve]
    return [0.0] + [values[index] / values[index - 1] - 1.0 for index in range(1, len(values))]


def _trade_overlap(left: dict, right: dict) -> bool:
    return max(date.fromisoformat(left["entry_date"]), date.fromisoformat(right["entry_date"])) <= min(
        date.fromisoformat(left["exit_date"]), date.fromisoformat(right["exit_date"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    protocol = _read(args.protocol)
    runs = ROOT / "data/research/vcp/runs"
    primary_id = protocol["inputs"]["primary_run"]
    secondary_id = protocol["inputs"]["secondary_run"]
    primary = _read(runs / primary_id / "result.json")
    secondary = _read(runs / secondary_id / "result.json")
    primary_audit = _read(runs / primary_id / "trade-audit.json")
    secondary_audit = _read(runs / secondary_id / "trade-audit.json")

    primary_curve = primary["equity_curve"]
    secondary_curve = secondary["equity_curve"]
    dates = [row["date"] for row in primary_curve]
    if dates != [row["date"] for row in secondary_curve]:
        raise ValueError("run equity dates do not align")
    if primary_audit["violations"] or secondary_audit["violations"]:
        raise ValueError("input run has timing violations")

    primary_returns = _returns(primary_curve)
    secondary_returns = _returns(secondary_curve)
    primary_exposed = [float(row["exposure"]) > 0 for row in primary_curve]
    secondary_exposed = [float(row["exposure"]) > 0 for row in secondary_curve]
    union_exposed = [a or b for a, b in zip(primary_exposed, secondary_exposed, strict=True)]
    both_exposed = [a and b for a, b in zip(primary_exposed, secondary_exposed, strict=True)]
    union_indices = [index for index, value in enumerate(union_exposed) if value]

    primary_drawdown = [float(row["value"]) for row in primary["drawdown_curve"]]
    secondary_drawdown = [float(row["value"]) for row in secondary["drawdown_curve"]]
    primary_deep = [value <= -0.10 for value in primary_drawdown]
    secondary_deep = [value <= -0.10 for value in secondary_drawdown]

    primary_trades = primary["trades"]
    secondary_trades = secondary["trades"]
    primary_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for trade in primary_trades:
        primary_by_symbol[trade["symbol"]].append(trade)
    date_index = {value: index for index, value in enumerate(dates)}

    same_symbol_ever = 0
    same_symbol_concurrent = 0
    prior_primary_within_60 = 0
    for trade in secondary_trades:
        related = primary_by_symbol.get(trade["symbol"], [])
        if related:
            same_symbol_ever += 1
        if any(_trade_overlap(trade, candidate) for candidate in related):
            same_symbol_concurrent += 1
        entry_index = date_index[trade["entry_date"]]
        prior_gaps = [
            entry_index - date_index[candidate["exit_date"]]
            for candidate in related
            if candidate["exit_date"] < trade["entry_date"]
        ]
        if prior_gaps and min(prior_gaps) <= 60:
            prior_primary_within_60 += 1

    primary_curve_by_date = {row["date"]: row for row in primary_curve}
    secondary_entry_primary_snapshot = [primary_curve_by_date[trade["entry_date"]] for trade in secondary_trades]
    combined_exposure = [
        float(left["exposure"]) + float(right["exposure"])
        for left, right in zip(primary_curve, secondary_curve, strict=True)
    ]
    positive_pnl = sorted(
        (float(trade["pnl_amount"]) for trade in secondary_trades if float(trade["pnl_amount"]) > 0),
        reverse=True,
    )

    result = {
        "analysis": protocol["experiment"],
        "inputs": {"primary_run": primary_id, "secondary_run": secondary_id},
        "source_classification": protocol.get(
            "source_classification", "same_origin_secondary_entry_state"
        ),
        "sample": {
            "market_days": len(dates),
            "primary_trades": len(primary_trades),
            "secondary_trades": len(secondary_trades),
            "primary_avg_exposure": primary["stats"]["avg_exposure"],
            "secondary_avg_exposure": secondary["stats"]["avg_exposure"],
        },
        "daily_path": {
            "return_correlation_all_days": _correlation(primary_returns, secondary_returns),
            "return_correlation_union_exposed_days": _correlation(
                [primary_returns[index] for index in union_indices],
                [secondary_returns[index] for index in union_indices],
            ),
            "drawdown_correlation_all_days": _correlation(primary_drawdown, secondary_drawdown),
        },
        "exposure_overlap": {
            "primary_exposed_days": sum(primary_exposed),
            "secondary_exposed_days": sum(secondary_exposed),
            "union_exposed_days": sum(union_exposed),
            "both_exposed_days": sum(both_exposed),
            "exposed_day_jaccard": sum(both_exposed) / sum(union_exposed),
            "combined_exposure_above_100pct_days": sum(value > 1.0 for value in combined_exposure),
            "maximum_combined_exposure": max(combined_exposure),
            "secondary_entries_primary_eod_four_positions": sum(
                int(row["positions"]) >= 4 for row in secondary_entry_primary_snapshot
            ),
            "secondary_entries_primary_eod_exposure_at_least_99pct": sum(
                float(row["exposure"]) >= 0.99 for row in secondary_entry_primary_snapshot
            ),
            "entry_conflict_scope": "primary end-of-day snapshot on the secondary fill date; descriptive proxy, not an execution simulation",
        },
        "trade_relationship": {
            "secondary_symbols_ever_traded_by_primary": same_symbol_ever,
            "secondary_trades_with_same_symbol_concurrent_primary_trade": same_symbol_concurrent,
            "secondary_trades_with_prior_same_symbol_primary_exit_within_60_market_sessions": prior_primary_within_60,
        },
        "drawdown_overlap": {
            "primary_days_at_or_below_minus_10pct": sum(primary_deep),
            "secondary_days_at_or_below_minus_10pct": sum(secondary_deep),
            "both_at_or_below_minus_10pct_days": sum(
                left and right for left, right in zip(primary_deep, secondary_deep, strict=True)
            ),
        },
        "secondary_concentration": {
            "positive_trades": len(positive_pnl),
            "top_five_winner_share_of_gross_positive_pnl": (
                sum(positive_pnl[:5]) / sum(positive_pnl) if positive_pnl else None
            ),
        },
        "interpretation_contract": {
            "independent_strategy": False,
            "combined_backtest_authorized": False,
            "parameter_or_weight_search_authorized": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
