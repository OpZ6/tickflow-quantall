#!/usr/bin/env python3
"""Audit the frozen pivot chase boundary against actual next-open fills."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_CHASE = 0.025
ERAS = ((2016, 2018), (2019, 2022), (2023, 2026))


def _summary(rows: list[dict]) -> dict:
    count = len(rows)
    return {
        "trades": count,
        "entry_years": sorted({int(row["entry_date"][:4]) for row in rows}),
        "average_pnl": sum(float(row["pnl_pct"]) for row in rows) / count if count else None,
        "win_rate": sum(float(row["pnl_pct"]) > 0 for row in rows) / count if count else None,
        "stop_loss_share": sum(row["exit_reason"] == "stop_loss" for row in rows) / count if count else None,
        "average_entry_to_pivot": (
            sum(float(row["entry_to_pivot"]) for row in rows) / count if count else None
        ),
    }


def analyze(trades: list[dict], structures: list[dict]) -> dict:
    def keys(row: dict) -> tuple[str, str, str]:
        return (
            str(row["symbol"]),
            str(row["entry_signal_date"])[:10],
            str(row["entry_date"])[:10],
        )

    structure_by_key = {keys(row): row for row in structures}
    joined = []
    for trade in trades:
        structure = structure_by_key.get(keys(trade))
        if structure is None:
            raise RuntimeError(f"missing reconstructed structure for {keys(trade)}")
        pivot = float(structure["pivot"])
        joined.append({**trade, "pivot": pivot, "entry_to_pivot": float(trade["entry_price"]) / pivot - 1.0})
    rejected = [row for row in joined if row["entry_to_pivot"] > MAX_CHASE]
    retained = [row for row in joined if row["entry_to_pivot"] <= MAX_CHASE]
    by_era = {}
    era_direction = []
    for start, end in ERAS:
        era_rows = [row for row in joined if start <= int(row["entry_date"][:4]) <= end]
        era_rejected = [row for row in era_rows if row["entry_to_pivot"] > MAX_CHASE]
        era_retained = [row for row in era_rows if row["entry_to_pivot"] <= MAX_CHASE]
        rejected_summary, retained_summary = _summary(era_rejected), _summary(era_retained)
        direction = bool(
            era_rejected
            and era_retained
            and rejected_summary["average_pnl"] < retained_summary["average_pnl"]
        )
        by_era[f"{start}-{end}"] = {
            "rejected": rejected_summary,
            "retained": retained_summary,
            "rejected_average_pnl_below_retained": direction,
        }
        era_direction.append(direction)
    rejected_summary, retained_summary = _summary(rejected), _summary(retained)
    gates = {
        "rejected_trades_min_20": len(rejected) >= 20,
        "rejected_entry_years_min_5": len(rejected_summary["entry_years"]) >= 5,
        "rejected_average_pnl_below_retained": rejected_summary["average_pnl"] < retained_summary["average_pnl"],
        "rejected_stop_loss_share_above_retained": (
            rejected_summary["stop_loss_share"] > retained_summary["stop_loss_share"]
        ),
        "three_fixed_eras_all_directional": all(era_direction),
    }
    return {
        "analysis": "production-leader-next-open-chase-audit-2016-2026-v1",
        "actual_open_max_chase": MAX_CHASE,
        "trades": len(joined),
        "rejected": rejected_summary,
        "retained": retained_summary,
        "by_era": by_era,
        "gates": gates,
        "all_diagnostic_gates_passed": all(gates.values()),
        "decision": "register_strategy_version" if all(gates.values()) else "stop_without_variants",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    run_dir = args.data_root.resolve() / "research" / "vcp" / "runs" / args.run_id
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    evidence = json.loads((run_dir / "entry-structure-evidence.json").read_text(encoding="utf-8"))
    if evidence["reconstruction"]["mismatched_executable"]:
        raise RuntimeError("entry reconstruction contains mismatches")
    report = analyze(list(result["trades"]), list(evidence["records"]))
    output = ROOT / "data/research/vcp/analysis/production-leader-next-open-chase-audit-2016-2026-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
