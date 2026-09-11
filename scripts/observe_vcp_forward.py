"""Append one completed-day snapshot for the frozen VCP forward version.

The first version records the strategy's causal candidate evidence and signal
hits through the existing production screener path.  It deliberately labels
the output candidate-only until the persistent paper portfolio and remaining
P0 execution facts are complete.

Run from ``backend``::

    uv run --no-sync python ../scripts/observe_vcp_forward.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
PROTOCOL_PATH = ROOT / "docs/research/vcp/forward-observation-v2.json"
VERSION_MANIFEST_PATH = ROOT / "docs/research/vcp/forward-v2-version-manifest.json"


def _file_reference(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "exists": False}
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _version_manifest_reference(path: Path, strategy_version: str) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("strategy_version") != strategy_version:
        raise RuntimeError(
            f"version manifest strategy {manifest.get('strategy_version')!r} != {strategy_version!r}"
        )
    reference = _file_reference(path)
    reference.update({
        "manifest_id": manifest["manifest_id"],
        "status": manifest["status"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    return reference


def _paper_ledger(
    backtest: Any,
    current: Any,
    screen_result: Any,
    as_of: date,
    *,
    max_positions: int,
) -> dict:
    """Translate the engine's terminal marks into a forward paper ledger.

    The normal backtest realizes still-open positions with ``exit_reason=end``.
    For an as-of snapshot those records are positions, not closed trades.
    """
    closed = [trade for trade in backtest.trades if trade.get("exit_reason") != "end"]
    terminal = [trade for trade in backtest.trades if trade.get("exit_reason") == "end"]
    close_by_symbol: dict[str, float] = {}
    if current is not None and not current.is_empty() and "close" in current.columns:
        close_by_symbol = {
            str(row["symbol"]): float(row["close"])
            for row in current.select("symbol", "close").drop_nulls("close").iter_rows(named=True)
        }
    open_positions = []
    for trade in terminal:
        symbol = str(trade["symbol"])
        current_close = close_by_symbol.get(symbol)
        shares = float(trade.get("shares") or 0.0)
        entry_value = float(trade.get("entry_value") or 0.0)
        market_value = shares * current_close if current_close is not None else None
        open_positions.append(
            {
                "symbol": symbol,
                "name": trade.get("name"),
                "entry_date": trade.get("entry_date"),
                "entry_signal_date": trade.get("entry_signal_date"),
                "entry_signal_id": trade.get("entry_signal_id"),
                "entry_price": trade.get("entry_price"),
                "entry_value": entry_value,
                "shares": shares,
                "lots": trade.get("lots"),
                "entry_score": trade.get("entry_score"),
                "mark_date": as_of.isoformat(),
                "mark_close": current_close,
                "market_value": market_value,
                "unrealized_return_before_exit_cost": (
                    market_value / entry_value - 1
                    if market_value is not None and entry_value > 0
                    else None
                ),
            }
        )

    open_symbols = {row["symbol"] for row in open_positions}
    entry_symbols = {
        str(hit["symbol"]): hit.get("signals", [])
        for hit in screen_result.entry_signal_hits
    }
    row_by_symbol = {str(row["symbol"]): row for row in screen_result.rows}
    pending_candidates = []
    entry_signal_exclusions = []
    for symbol, signals in entry_symbols.items():
        if symbol in open_symbols:
            entry_signal_exclusions.append({
                "symbol": symbol,
                "reason": "already_held",
            })
            continue
        row = row_by_symbol.get(symbol, {})
        pending_candidates.append(
            {
                "symbol": symbol,
                "name": row.get("name"),
                "score": float(screen_result.scores.get(symbol, 0.0)),
                "signals": signals,
                "signal_date": as_of.isoformat(),
                "intended_fill": "next_market_open",
            }
        )
    pending_candidates.sort(key=lambda row: row["score"], reverse=True)
    slots = max(max_positions - len(open_positions), 0)
    pending_entries = pending_candidates[:slots]
    pending_exit_symbols = {
        str(hit["symbol"]): hit.get("signals", [])
        for hit in screen_result.exit_signal_hits
        if str(hit["symbol"]) in open_symbols
    }
    latest_equity = backtest.equity_curve[-1] if backtest.equity_curve else None
    return {
        "replay_start": backtest.config.get("start"),
        "replay_end": backtest.config.get("end"),
        "closed_trades": closed,
        "open_positions": open_positions,
        "pending_entries": pending_entries,
        "entry_signals_without_available_slot": pending_candidates[slots:],
        "entry_signal_exclusions": entry_signal_exclusions,
        "pending_signal_exits": [
            {"symbol": symbol, "signals": signals, "signal_date": as_of.isoformat()}
            for symbol, signals in sorted(pending_exit_symbols.items())
        ],
        "latest_equity": latest_equity,
        "execution_rejection_counts": backtest.stats.get("execution", {}),
        "execution_rejections": backtest.stats.get("execution_rejections", []),
        "execution_rejection_scope": backtest.stats.get("execution_rejection_scope", "unavailable"),
        "terminal_end_records_reclassified_as_open": len(terminal),
    }


def _candidate_decisions(screen_result: Any, paper_ledger: dict | None = None) -> list[dict]:
    """Describe the close-time queue, not next-day execution rejections or fills."""
    entry_symbols = {str(hit["symbol"]) for hit in screen_result.entry_signal_hits}
    ledger = paper_ledger or {}
    queue_decisions = {
        str(row["symbol"]): "pending_next_open"
        for row in ledger.get("pending_entries", [])
    }
    queue_decisions.update({
        str(row["symbol"]): "no_available_slot"
        for row in ledger.get("entry_signals_without_available_slot", [])
    })
    queue_decisions.update({
        str(row["symbol"]): row["reason"]
        for row in ledger.get("entry_signal_exclusions", [])
    })
    decisions = []
    for row in screen_result.rows:
        symbol = str(row["symbol"])
        evidence = row.get("strategy_evidence") or {}
        reason_codes = list(evidence.get("reason_codes") or [])
        if not reason_codes and row.get("vcp_status"):
            reason_codes = [str(row["vcp_status"])]
        decisions.append(
            {
                "symbol": symbol,
                "name": row.get("name"),
                "score": float(screen_result.scores.get(symbol, 0.0)),
                "decision": queue_decisions.get(symbol, "entry_signal_only")
                if symbol in entry_symbols else "observe_only",
                "decision_scope": "close_snapshot_queue",
                "is_simulated_fill": False,
                "reason_codes": reason_codes,
                "vcp_status": row.get("vcp_status"),
                "vcp_setup": row.get("vcp_setup"),
                "vcp_pivot": row.get("vcp_pivot"),
            }
        )
    return decisions


def _rejection_ledger_complete(screening_trace: dict, paper_ledger: dict) -> bool:
    screening_complete = (
        screening_trace.get("scope") == "matrix_snapshot_candidate_pipeline"
        and screening_trace.get("detector_subreasons_available") is True
    )
    execution_complete = (
        paper_ledger.get("status") == "empty_before_first_entry_signal"
        or paper_ledger.get("execution_rejection_scope") == "portfolio_matrix_attempts"
    )
    return screening_complete and execution_complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args()

    from app.backtest.engine import BacktestEngine
    from app.backtest.strategy import (
        BacktestResultPolicy,
        StrategyBacktestConfig,
        StrategyBacktestService,
    )
    from app.config import settings
    from app.services.screener import ScreenerService
    from app.strategy.engine import StrategyEngine
    from app.tickflow.repository import DataStore, KlineRepository

    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    store = DataStore(settings.data_dir)
    try:
        repo = KlineRepository(store)
        screener = ScreenerService(repo)
        latest = screener.latest_date()
        if latest is None:
            raise RuntimeError("production enriched daily store is empty")
        as_of = args.as_of or latest
        if as_of > latest:
            raise RuntimeError(f"requested {as_of} is later than latest completed data {latest}")
        observation_start = date.fromisoformat(protocol["observation_start"])
        if as_of < observation_start:
            raise RuntimeError(f"requested {as_of} predates observation start {observation_start}")

        strategy_id = str(protocol["strategy_id"])
        expected_version = str(protocol["strategy_version"])
        output_dir = settings.data_dir / "research/vcp/forward" / expected_version
        output = output_dir / f"{as_of.isoformat()}.json"
        if output.exists():
            raise FileExistsError(
                f"forward snapshot already exists and is append-only: {output}"
            )

        engine = StrategyEngine([ROOT / "backend/app/strategy/builtin"])
        definition = engine.get(strategy_id)
        actual_version = str(definition.meta.get("version") or "")
        if actual_version != expected_version:
            raise RuntimeError(
                f"registered strategy version {actual_version!r} != frozen {expected_version!r}"
            )
        version_manifest = _version_manifest_reference(VERSION_MANIFEST_PATH, expected_version)

        context = screener.build_strategy_context(engine, as_of, [strategy_id])
        context.screening_trace = {}
        result = engine.run(strategy_id, context)
        prior_entry_signals = 0
        for prior_path in output_dir.glob("*.json"):
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            prior_entry_signals += int((prior.get("counts") or {}).get("entry_signal_hits", 0))
        paper_ledger = {
            "status": "empty_before_first_entry_signal",
            "closed_trades": [],
            "open_positions": [],
            "pending_entries": [],
            "execution_rejection_counts": {},
        }
        if prior_entry_signals or result.entry_signal_hits:
            symbols = sorted(
                set(context.history["symbol"].to_list())
                if context.history is not None and not context.history.is_empty()
                else set(context.current["symbol"].to_list())
            )
            config = StrategyBacktestConfig(
                strategy_id=strategy_id,
                symbols=symbols,
                start=observation_start,
                end=as_of,
                params=None,
                overrides={},
                matching="open_t+1",
                entry_fill="open_t+1",
                exit_fill="open_t+1",
                commission_pct=0.0003,
                stamp_tax_pct=0.0005,
                slippage_bps=10.0,
                max_positions=int(protocol["execution"]["max_positions"]),
                max_exposure_pct=float(protocol["execution"]["max_exposure_pct"]),
                initial_capital=1_000_000.0,
                position_sizing=str(protocol["execution"]["position_sizing"]),
                mode="position",
                asset_type="stock",
                minute_fill=False,
                regime_filter=None,
            )
            replay = StrategyBacktestService(BacktestEngine(repo), engine).run(
                config, result_policy=BacktestResultPolicy(include_execution_rejections=True),
            )
            if replay.error:
                raise RuntimeError(f"forward paper replay failed: {replay.error}")
            paper_ledger = {
                "status": "deterministic_replay",
                **_paper_ledger(
                    replay,
                    context.current,
                    result,
                    as_of,
                    max_positions=config.max_positions,
                ),
            }
        output_dir.mkdir(parents=True, exist_ok=True)

        partition = settings.data_dir / "kline_daily_enriched" / f"date={as_of}" / "part.parquet"
        snapshot = {
            "observation_protocol": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"),
            "strategy_id": strategy_id,
            "strategy_version": expected_version,
            "version_manifest": version_manifest,
            "as_of": as_of.isoformat(),
            "observed_at": datetime.now(UTC).isoformat(),
            "latest_completed_data_date": latest.isoformat(),
            "collection_level": "candidate_signal_only",
            "counts": {
                "candidates": result.total,
                "entry_signal_hits": len(result.entry_signal_hits),
                "exit_signal_hits": len(result.exit_signal_hits),
            },
            "candidates": result.rows,
            "candidate_decisions": _candidate_decisions(result, paper_ledger),
            "screening_trace": context.screening_trace,
            "entry_signal_hits": result.entry_signal_hits,
            "exit_signal_hits": result.exit_signal_hits,
            "paper_ledger": paper_ledger,
            "elapsed_ms": result.elapsed_ms,
            "input_references": [
                _file_reference(partition),
                _file_reference(settings.data_dir / "instruments/instruments.parquet"),
                _file_reference(settings.data_dir / "financials/shares/part.parquet"),
                _file_reference(PROTOCOL_PATH),
            ],
            "quality_state": {
                "p0_complete": False,
                "persistent_paper_portfolio": paper_ledger["status"] == "deterministic_replay",
                "rejection_ledger_complete": _rejection_ledger_complete(
                    context.screening_trace, paper_ledger
                ),
                "known_degradations": [
                    "historical ST/name state is not yet consumed by the strategy path",
                    "exclude_new_days is declared but not yet effective",
                    "intraday partial-suspension timing and live fill evidence remain incomplete",
                ],
                "qualification_use": "does_not_count_as_complete_P4_execution_evidence",
            },
        }
        output.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps({"output": str(output), **snapshot["counts"]}, ensure_ascii=False))
    finally:
        store.db.close()


if __name__ == "__main__":
    main()
