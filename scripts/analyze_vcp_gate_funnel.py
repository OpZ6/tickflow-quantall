#!/usr/bin/env python3
"""Audit where generic training-period breakout winners fail frozen VCP gates."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from math import prod
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _market_path_return(
    dates: list[int], open_to_close: np.ndarray, close_to_close: np.ndarray
) -> float:
    returns = [float(open_to_close[dates[0]])]
    returns.extend(float(close_to_close[t]) for t in dates[1:])
    return prod(1.0 + value for value in returns) - 1.0


def _summarize(rows: list[dict]) -> dict:
    by_gate: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_gate[row["first_failed_gate"]].append(row)
    summary = {}
    for gate, items in sorted(by_gate.items()):
        alpha_by_year: dict[int, list[float]] = defaultdict(list)
        for item in items:
            alpha_by_year[int(item["signal_year"])].append(float(item["alpha_40d"]))
        summary[gate] = {
            "opportunities": len(items),
            "mfe_20pct_count": sum(item["mfe_40d"] >= 0.2 for item in items),
            "mfe_50pct_count": sum(item["mfe_40d"] >= 0.5 for item in items),
            "mfe_100pct_count": sum(item["mfe_40d"] >= 1.0 for item in items),
            "average_40d_return": sum(item["close_return_40d"] for item in items) / len(items),
            "average_40d_alpha": sum(item["alpha_40d"] for item in items) / len(items),
            "positive_alpha_years": sum(
                sum(values) / len(values) > 0 for values in alpha_by_year.values()
            ),
            "years_present": len(alpha_by_year),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "docs/research/vcp/production-vcp-gate-funnel-train-2016-2022-v1.json",
    )
    parser.add_argument(
        "--source-run", default="20260909T034426222263Z",
        help="Completed production run whose historical-union symbols are reused.",
    )
    args = parser.parse_args()

    from app.backtest.engine import BacktestEngine
    from app.backtest.matrix import valid_rolling_mean, valid_shift
    from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
    from app.config import settings
    from app.strategy.builtin._quants_vcp import (
        detect,
        entry_allowed,
        fresh_20d_breakout_opportunity_mask,
        market_breadth_allowed,
        trend_context,
    )
    from app.strategy.engine import StrategyEngine
    from app.tickflow.repository import DataStore, KlineRepository

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    source_dir = settings.data_dir / "research/vcp/runs" / args.source_run
    source_config = json.loads((source_dir / "config.json").read_text(encoding="utf-8"))
    strategies = StrategyEngine([ROOT / "backend/app/strategy/builtin"])
    definition = strategies.get("vcp_leader_breakout")
    service = StrategyBacktestService(
        BacktestEngine(KlineRepository(DataStore(settings.data_dir))), strategies
    )
    config = StrategyBacktestConfig(
        strategy_id="vcp_leader_breakout",
        symbols=source_config["symbols"],
        start=date(2016, 1, 4),
        end=date(2023, 3, 31),
        params=None,
        mode="full",
        asset_type="stock",
    )
    params = service._normalize_params({}, definition)
    prepared = service.prepare_matrix_optimization([config])
    market = prepared.market_data
    with prepared.compute_cache.activate(market):
        diagnostics: dict[str, np.ndarray] = {}
        _, ranks = trend_context(market, params, diagnostics=diagnostics)
        valid = np.isfinite(market.close) & (market.close > 0)
        fresh_breakout = fresh_20d_breakout_opportunity_mask(market)
        ma20 = valid_rolling_mean(
            market.close, valid, 20, bar_index=market.valid_bars
        )
        regime_allowed, breadth = market_breadth_allowed(
            market.close, ma20, params, market.valid_bars
        )
        prior_close = valid_shift(
            market.close, 1, valid, bar_index=market.valid_bars
        )
        close_to_close_matrix = np.divide(
            market.close,
            prior_close,
            out=np.full(market.shape, np.nan),
            where=prior_close > 0,
        ) - 1.0
        open_to_close_matrix = np.divide(
            market.close,
            market.open,
            out=np.full(market.shape, np.nan),
            where=market.open > 0,
        ) - 1.0
        close_counts = np.isfinite(close_to_close_matrix).sum(axis=1)
        open_counts = np.isfinite(open_to_close_matrix).sum(axis=1)
        close_to_close = np.divide(
            np.nansum(close_to_close_matrix, axis=1),
            close_counts,
            out=np.zeros(market.shape[0], dtype=float),
            where=close_counts > 0,
        )
        open_to_close = np.divide(
            np.nansum(open_to_close_matrix, axis=1),
            open_counts,
            out=np.zeros(market.shape[0], dtype=float),
            where=open_counts > 0,
        )

    training_start, training_end = map(date.fromisoformat, protocol["training_period"])
    rows: list[dict] = []
    for asset, symbol in enumerate(market.symbols):
        if not (symbol.endswith(".SH") or symbol.endswith(".SZ")):
            continue
        ids = np.flatnonzero(valid[:, asset])
        last_kept_position = -1000
        for position, t in enumerate(ids):
            signal_date = date.fromisoformat(market.timestamp_labels[t][:10])
            if signal_date < training_start or signal_date > training_end:
                continue
            if position - last_kept_position < 20:
                continue
            if not fresh_breakout[t, asset]:
                continue
            future = ids[position + 1 :]
            future = future[market.tradable[future, asset].astype(bool)][:41]
            if len(future) < 41 or not np.isfinite(market.open[future[0], asset]):
                continue
            last_kept_position = position
            entry_price = float(market.open[future[0], asset])
            horizon = future[:41]
            market_return = _market_path_return(
                horizon.tolist(), open_to_close, close_to_close
            )
            stock_return = float(market.close[horizon[-1], asset] / entry_price - 1.0)
            alpha = (1.0 + stock_return) / (1.0 + market_return) - 1.0

            first_failed = "selected_by_vcp"
            for name, key in (
                ("trend_ma_alignment", "trend_ma_alignment"),
                ("positive_63_126_252_returns", "positive_returns"),
                ("near_52_week_high", "near_52_week_high"),
                ("rs_85", "rs_threshold"),
            ):
                if not bool(diagnostics[key][t, asset]):
                    first_failed = name
                    break
            else:
                if not bool(regime_allowed[t]):
                    first_failed = "dual_market_regime"
                else:
                    history = ids[max(0, position - 259) : position + 1]
                    arrays = [
                        np.asarray(field[history, asset], dtype=np.float64)
                        for field in (market.high, market.low, market.close, market.volume)
                    ]
                    if len(history) < 45 or not all(np.isfinite(v).all() for v in arrays):
                        first_failed = "valid_vcp_structure"
                    else:
                        dates = [market.timestamp_labels[i][:10] for i in history]
                        structure = detect(*arrays, dates, params)
                        pattern = structure["primary"] if structure else None
                        if not pattern or not pattern.get("valid"):
                            first_failed = "valid_vcp_structure"
                        else:
                            broad = breadth[t] >= 0.7
                            if pattern.get("scale") == "short" and (
                                not params.get("short_scale_enabled", True) or broad
                            ):
                                first_failed = "allowed_scale"
                            elif pattern.get("status") != "executable":
                                first_failed = "executable_breakout"
                            else:
                                entry_params = {
                                    **params,
                                    "prebreakout_pivot_closes_max": 20 if broad else 0,
                                }
                                if not entry_allowed(
                                    pattern, arrays[2][-2], entry_params, arrays[2]
                                ):
                                    first_failed = "first_pivot_in_recovery"

            rows.append({
                "symbol": symbol,
                "signal_date": signal_date,
                "signal_year": signal_date.year,
                "entry_date": date.fromisoformat(market.timestamp_labels[horizon[0]][:10]),
                "label_end_date": date.fromisoformat(
                    market.timestamp_labels[horizon[-1]][:10]
                ),
                "first_failed_gate": first_failed,
                "rs_percentile": float(ranks[t, asset]),
                "market_breadth_ma20": float(breadth[t]),
                "mfe_40d": float(np.max(market.high[horizon, asset]) / entry_price - 1.0),
                "close_return_40d": stock_return,
                "market_return_40d": market_return,
                "alpha_40d": alpha,
            })

    output_dir = settings.data_dir / "research/vcp/gate-funnel" / protocol["experiment"]
    output_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(output_dir / "opportunities.parquet")
    summary = {
        "protocol": str(args.protocol.relative_to(ROOT)),
        "source_run": args.source_run,
        "opportunities": len(rows),
        "by_first_failed_gate": _summarize(rows),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
