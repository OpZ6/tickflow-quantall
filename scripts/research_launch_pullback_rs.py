#!/usr/bin/env python3
"""Filter launch_pullback fills to RS>=85 using frozen vcp_leader_breakout ranks."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from research_leader_universe_market_gate import (  # noqa: E402
    DATA_START,
    load_training_market,
    rs_universe_mask,
)
from research_vcp_period_slice import slice_trades  # noqa: E402
from research_vcp_two_bar_no_demand import (  # noqa: E402
    independent_trade_stats,
    training_trades,
    verdict,
    _as_date,
    _round,
)

PULLBACK_RUN = "20260909T053715693165Z"
RS_MIN = 85.0
DEFAULT_PROTOCOL = ROOT / "docs/research/pullback/launch-pullback-rs85-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/pullback/launch-pullback-rs85-v1-analysis.json"


def lookup_rs(symbol: str, signal_date: date, symbols: list[str], dates: list[date], ranks: np.ndarray) -> float | None:
    try:
        asset = symbols.index(symbol)
        time = dates.index(signal_date)
    except ValueError:
        return None
    value = ranks[time, asset]
    if not np.isfinite(value):
        return None
    return float(value)


def filter_rs(trades: list[dict], symbols: list[str], dates: list[date], ranks: np.ndarray, rs_min: float = RS_MIN):
    kept, skipped = [], 0
    for trade in trades:
        rank = lookup_rs(
            str(trade["symbol"]),
            _as_date(trade["entry_signal_date"]),
            symbols,
            dates,
            ranks,
        )
        if rank is not None and rank >= rs_min:
            kept.append(trade)
        else:
            skipped += 1
    return kept, skipped


def pack(trades: list[dict]) -> dict:
    return independent_trade_stats([float(t["pnl_pct"]) for t in trades])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--runs-root", default=str(ROOT / "data/research/vcp/runs"))
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    protocol_path = Path(args.protocol)
    if not protocol_path.is_file():
        raise SystemExit(f"protocol missing: {protocol_path}")
    payload = json.loads((Path(args.runs_root) / PULLBACK_RUN / "result.json").read_text(encoding="utf-8"))
    all_trades = payload.get("trades") or []
    train = training_trades(all_trades)
    val, val_open = slice_trades(all_trades, date(2023, 1, 1), date(2026, 12, 31), date(2026, 12, 31))
    print("loading market for RS ranks", flush=True)
    market, _listing, _names = load_training_market(Path(args.data_root), DATA_START, date(2026, 12, 31))
    _mask, ranks = rs_universe_mask(market, RS_MIN)
    symbols = list(market.symbols)
    dates = [_as_date(label) for label in market.timestamp_labels]
    train_kept, train_skip = filter_rs(train, symbols, dates, ranks)
    train_report = {
        "skipped": train_skip,
        "baseline": pack(train),
        "variant": pack(train_kept),
    }
    train_report["delta"] = {
        "avg_pnl": _round((train_report["variant"]["avg_pnl"] or 0) - (train_report["baseline"]["avg_pnl"] or 0))
        if train_report["variant"]["avg_pnl"] is not None and train_report["baseline"]["avg_pnl"] is not None
        else None,
        "win_rate": _round((train_report["variant"]["win_rate"] or 0) - (train_report["baseline"]["win_rate"] or 0))
        if train_report["variant"]["win_rate"] is not None and train_report["baseline"]["win_rate"] is not None
        else None,
        "profit_factor": None
        if train_report["variant"]["profit_factor"] is None or train_report["baseline"]["profit_factor"] is None
        else round(train_report["variant"]["profit_factor"] - train_report["baseline"]["profit_factor"], 2),
    }
    train_report["rule"] = verdict(train_report["variant"], train_report["baseline"])
    report = {
        "experiment": "launch-pullback-rs85-v1",
        "baseline_run": PULLBACK_RUN,
        "protocol": str(protocol_path),
        "training_2016_2022": train_report,
        "rule": train_report["rule"],
        "gaps": [],
    }
    if train_report["rule"] == "keep":
        val_kept, val_skip = filter_rs(val, symbols, dates, ranks)
        val_report = {
            "skipped": val_skip,
            "baseline": pack(val),
            "variant": pack(val_kept),
            "incomplete_excluded": len(val_open),
        }
        val_report["delta"] = {
            "avg_pnl": _round((val_report["variant"]["avg_pnl"] or 0) - (val_report["baseline"]["avg_pnl"] or 0))
            if val_report["variant"]["avg_pnl"] is not None and val_report["baseline"]["avg_pnl"] is not None
            else None,
            "win_rate": _round((val_report["variant"]["win_rate"] or 0) - (val_report["baseline"]["win_rate"] or 0))
            if val_report["variant"]["win_rate"] is not None and val_report["baseline"]["win_rate"] is not None
            else None,
            "profit_factor": None
            if val_report["variant"]["profit_factor"] is None or val_report["baseline"]["profit_factor"] is None
            else round(val_report["variant"]["profit_factor"] - val_report["baseline"]["profit_factor"], 2),
        }
        val_report["rule"] = verdict(val_report["variant"], val_report["baseline"])
        report["validation_2023_2026"] = val_report
        report["validation_note"] = "exposure, not a clean holdout"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "rule": report["rule"], "training": train_report, "validation": report.get("validation_2023_2026")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
