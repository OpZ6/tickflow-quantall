"""Archive and run a VCP experiment through TickFlow's existing backtest service.

Run from backend: uv run --no-sync python ../scripts/run_vcp_research.py
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import traceback
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def merged(base, overlay):
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = value
    return result


def load_protocol(path: Path, seen: tuple[Path, ...] = ()):
    path = path.resolve()
    if path in seen:
        chain = " -> ".join(str(item) for item in (*seen, path))
        raise ValueError(f"Circular base_protocol chain: {chain}")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    base_protocol = protocol.pop("base_protocol", None)
    if not base_protocol:
        return protocol
    base_path = path.parent / base_protocol
    return merged(load_protocol(base_path, (*seen, path)), protocol)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", type=Path, default=ROOT / "docs/research/vcp/five-year-v1.json"
    )
    parser.add_argument("--phase", choices=["train", "validation", "holdout", "baseline"])
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    protocol = load_protocol(args.protocol)

    from app.backtest.engine import BacktestEngine
    from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
    from app.config import settings
    from app.strategy.engine import StrategyEngine
    from app.tickflow.repository import DataStore, KlineRepository

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = settings.data_dir / "research" / "vcp" / "runs" / run_id
    output.mkdir(parents=True, exist_ok=False)
    print(f"RUN_DIR={output}", flush=True)
    state = {"run_id": run_id, "status": "running", "started_at": datetime.now(UTC).isoformat()}
    write_json(output / "status.json", state)
    write_json(output / "protocol.json", protocol)
    store = None
    try:
        # Capture actual dirty/untracked Python sources, not only the Git HEAD label.
        with zipfile.ZipFile(output / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((ROOT / "backend/app").rglob("*.py")):
                archive.write(path, path.relative_to(ROOT))
            for path in [Path(__file__), ROOT / "backend/uv.lock", ROOT / "backend/pyproject.toml"]:
                archive.write(path, path.relative_to(ROOT))
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        write_json(
            output / "environment.json",
            {"head": head, "python": sys.version, "platform": platform.platform()},
        )
        data_dir = settings.data_dir / protocol.get("data_directory", "")
        if protocol.get("data_directory"):
            build = json.loads((data_dir / "build-status.json").read_text(encoding="utf-8"))
            if build.get("status") != "completed_with_limitations":
                raise ValueError("Research dataset build has not completed")
        store = DataStore(data_dir)
        repo = KlineRepository(store)
        engine = BacktestEngine(repo)
        # No user override loader: this run consumes only builtin defaults + frozen protocol.
        strategies = StrategyEngine([ROOT / "backend/app/strategy/builtin"])
        cfg = dict(protocol["backtest"])
        if protocol.get("phases"):
            phase = args.phase or "train"
            cfg.update(protocol["phases"][phase])
            state["phase"] = phase
        elif args.phase:
            raise ValueError("This engineering protocol does not define phases")
        cfg["start"] = date.fromisoformat(cfg["start"])
        cfg["end"] = date.fromisoformat(cfg["end"])
        universe_date = date.fromisoformat(protocol["universe_date"])
        if universe_date >= cfg["start"]:
            raise ValueError("universe_date must precede the experiment")
        universe_end = (
            cfg["end"] if protocol.get("universe_mode") == "historical_union" else universe_date
        )
        universe = engine.load_panel(None, universe_date, universe_end, columns=["symbol", "date"])
        symbols = sorted(set(universe["symbol"].to_list())) if not universe.is_empty() else []
        if protocol.get("data_directory"):
            quality = json.loads((data_dir / "quality-summary.json").read_text(encoding="utf-8"))
            excluded = set(quality.get("excluded_symbols", []))
            symbols = [symbol for symbol in symbols if symbol not in excluded]
            write_json(output / "data-quality.json", quality)
        if not symbols:
            raise ValueError("No historical universe data on universe_date")
        count = int(protocol["sample_size"])
        if count < 0:
            raise ValueError("sample_size must be non-negative (0 means full universe)")
        selected = (
            symbols
            if count == 0 or count >= len(symbols)
            else [symbols[i * len(symbols) // count] for i in range(count)]
        )
        cfg["symbols"] = selected
        write_json(
            output / "universe.json",
            {
                "date": universe_date,
                "end": universe_end,
                "mode": protocol.get("universe_mode", "snapshot"),
                "available": len(symbols),
                "method": "sorted_symbol_even_spacing",
                "symbols": selected,
                "rs_scope": "selected_universe",
            },
        )
        config = StrategyBacktestConfig(**cfg)
        write_json(output / "config.json", asdict(config))
        definition = strategies.get(config.strategy_id)
        write_json(
            output / "strategy.json",
            {
                "meta": definition.meta,
                "entry_signals": definition.entry_signals,
                "exit_signals": definition.exit_signals,
            },
        )
        history = engine.load_panel(
            selected,
            config.start - timedelta(days=416),
            config.end,
            columns=["symbol", "date", "close"],
        )
        import polars as pl

        coverage = (
            history.filter(pl.col("close").is_not_null())
            .group_by("symbol")
            .agg(
                (pl.col("date") < config.start).sum().alias("warmup_bars"),
                (pl.col("date") >= config.start).sum().alias("experiment_bars"),
                pl.col("date").min().alias("first_date"),
                pl.col("date").max().alias("last_date"),
            )
            .sort("symbol")
        )
        write_json(output / "coverage.json", coverage.to_dicts())
        eligible_history = sum(
            row["warmup_bars"] + row["experiment_bars"] >= 253 for row in coverage.to_dicts()
        )
        write_json(
            output / "coverage-summary.json",
            {
                "selected": len(selected),
                "with_253_bars_by_end": eligible_history,
                "required_for_default_rs": 253,
            },
        )
        if eligible_history == 0:
            state["failure_stage"] = "data_preflight"
            raise ValueError(
                "No selected stock has 253 bars by experiment end; default VCP annual return/RS cannot be calculated"
            )
        # Record input references; this does not pretend to freeze mutable market data.
        inputs = []
        for directory in (
            "kline_daily_enriched",
            "kline_daily",
            "adj_factor",
            "instruments",
            "kline_index_daily",
        ):
            for path in sorted((data_dir / directory).rglob("*.parquet")):
                stat = path.stat()
                inputs.append(
                    {
                        "path": str(path.relative_to(data_dir)),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
        write_json(
            output / "data-references.json",
            {"data_directory": str(data_dir), "immutable_snapshot": False, "files": inputs},
        )
        if args.preflight_only:
            state["status"] = "preflight_completed"
            print(
                json.dumps(
                    {
                        "preflight": "completed",
                        "symbols": len(selected),
                        "with_253_bars": eligible_history,
                    }
                ),
                flush=True,
            )
            return

        def progress(message):
            with (output / "progress.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
            print(json.dumps(message, ensure_ascii=True, default=str), flush=True)

        result = asdict(StrategyBacktestService(engine, strategies).run(config, progress))
        write_json(output / "result.json", result)
        if result.get("error"):
            raise RuntimeError(result["error"])
        trades = result["trades"]
        violations = []
        for trade in trades:
            if str(trade["exit_date"]) <= str(trade["entry_date"]):
                violations.append("non_T1_trade")
            if trade.get("entry_signal_date") and str(trade["entry_signal_date"]) >= str(
                trade["entry_date"]
            ):
                violations.append("entry_not_after_signal")
            if (
                trade.get("exit_reason") == "signal"
                and trade.get("exit_signal_date")
                and str(trade["exit_signal_date"]) >= str(trade["exit_date"])
            ):
                violations.append("exit_not_after_signal")
        audit = {
            "trade_count": len(trades),
            "exit_reasons": dict(Counter(t["exit_reason"] for t in trades)),
            "violations": violations,
            "nonzero_trades": bool(trades),
            "purpose": protocol["purpose"],
        }
        write_json(output / "trade-audit.json", audit)
        if violations:
            raise RuntimeError(f"Trade timing audit failed: {violations[:5]}")
        store.db.close()
        store = None
        state["status"] = "completed" if trades else "completed_no_trades"
        print(json.dumps(audit, ensure_ascii=True), flush=True)
    except BaseException as exc:
        state["status"] = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        state["error"] = str(exc)
        (output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        state["finished_at"] = datetime.now(UTC).isoformat()
        write_json(output / "status.json", state)
        if store is not None:
            store.db.close()


if __name__ == "__main__":
    main()
