"""Build versioned generic strategy evidence and persist derived signal events."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.strategy.engine import StrategyDataContext, StrategyDef, StrategyResult

from .strategy_signal_events import StrategySignalEventRepository


def _fingerprint(value: Any, length: int = 20) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:length]


def _input_fingerprint(context: StrategyDataContext) -> str:
    frame = getattr(context, "current", None)
    if frame is None or frame.is_empty():
        return "empty"
    columns = [column for column in ("symbol", "date", "close", "volume") if column in frame.columns]
    sample = frame.select(columns).sort("symbol").to_dicts() if columns else []
    return _fingerprint(sample)


def _event_type(signal: str, default: str) -> str:
    lowered = signal.lower()
    if any(token in lowered for token in ("fail", "invalid", "broken")):
        return "failure"
    if any(token in lowered for token in ("support", "bounce", "pullback")):
        return "support"
    if any(token in lowered for token in ("retrigger", "re_break", "second_break")):
        return "retrigger"
    return default


def _row_metrics(row: dict[str, Any], params: dict[str, Any], signals: list[str]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for signal in signals:
        column = signal if signal.startswith(("signal_", "csg_")) else f"signal_{signal}"
        metrics.append({"name": column, "value": bool(row.get(column, True)), "threshold": True, "unit": "bool", "passed": bool(row.get(column, True))})
    for name, value in sorted(params.items()):
        if isinstance(value, (int, float, bool)):
            metrics.append({"name": f"param.{name}", "value": value, "threshold": value, "unit": "strategy_param", "passed": None})
    for name in ("close", "change_pct", "volume", "vol_ratio_5d", "turnover_rate", "ma5", "ma10", "ma20", "ma60", "rsi_14", "macd_dif", "macd_dea"):
        value = row.get(name)
        if value is not None and isinstance(value, (int, float, bool)):
            metrics.append({"name": name, "value": value, "threshold": None, "unit": "price" if name.startswith("ma") or name == "close" else "raw", "passed": None})
    return metrics[:32]


def enrich_and_persist_strategy_result(
    *,
    data_dir: Path,
    result: StrategyResult,
    strategy: StrategyDef,
    params: dict[str, Any],
    context: StrategyDataContext,
    provenance: str = "observed_run",
    signal_kind: str = "strategy_signal",
) -> list[dict[str, Any]]:
    strategy_version = str(strategy.meta.get("version") or "1.0.0")
    params_fingerprint = _fingerprint(params)
    input_fingerprint = _input_fingerprint(context)
    source_run_id = _fingerprint({
        "strategy_id": getattr(result, "strategy_id", None) or getattr(result, "strategy", "unknown"),
        "strategy_version": strategy_version,
        "params_fingerprint": params_fingerprint,
        "as_of": result.as_of,
        "asset_type": getattr(context, "asset_type", "stock"),
        "timeframe": getattr(context, "timeframe", "1d"),
        "input_fingerprint": input_fingerprint,
        "provenance": provenance,
    }, 24)
    strategy_id = getattr(result, "strategy_id", None) or getattr(result, "strategy", "unknown")
    row_map = {str(row.get("symbol")): row for row in result.rows if row.get("symbol")}
    events: list[dict[str, Any]] = []

    def append(symbol: str, event_type: str, signals: list[str]) -> None:
        row = row_map.get(symbol, {})
        close = row.get("close")
        levels = [] if close is None else [{"role": "signal_price", "label": "信号日收盘", "value": float(close)}]
        for name, role in (("ma20", "support"), ("boll_upper", "trigger"), ("recent_high", "trigger")):
            if row.get(name) is not None:
                levels.append({"role": role, "label": name, "value": float(row[name])})
        events.append({
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "params_fingerprint": params_fingerprint,
            "symbol": symbol,
            "asset_type": getattr(context, "asset_type", "stock"),
            "event_date": result.as_of,
            "event_type": event_type,
            "signal_kind": signal_kind,
            "score": getattr(result, "scores", {}).get(symbol, row.get("score")),
            "source_run_id": source_run_id,
            "provenance": provenance,
            "input_fingerprint": input_fingerprint,
            "reason_codes": signals or [f"strategy_{event_type}"],
            "metrics": _row_metrics(row, params, signals),
            "anchors": [{"date": result.as_of.isoformat(), "role": event_type, "ohlc": {key: row.get(key) for key in ("open", "high", "low", "close")}}],
            "levels": levels,
            "pattern_refs": [],
            "observed_at": datetime.now(),
        })

    for symbol in sorted(row_map):
        append(symbol, "candidate", [])
    for hit in getattr(result, "entry_signal_hits", []):
        symbol = str(hit.get("symbol") or "")
        if symbol:
            signals = [str(value) for value in hit.get("signals") or []]
            append(symbol, "entry", signals)
            derived = {_event_type(signal, "entry") for signal in signals} - {"entry"}
            for event_type in sorted(derived):
                append(symbol, event_type, signals)
    for hit in getattr(result, "exit_signal_hits", []):
        symbol = str(hit.get("symbol") or "")
        if symbol:
            signals = [str(value) for value in hit.get("signals") or []]
            event_type = next((_event_type(signal, "exit") for signal in signals if _event_type(signal, "exit") != "exit"), "exit")
            append(symbol, event_type, signals)

    result.strategy_version = strategy_version
    result.params_fingerprint = params_fingerprint
    result.source_run_id = source_run_id
    result.input_fingerprint = input_fingerprint
    result.evidence = events
    if events:
        StrategySignalEventRepository(data_dir).upsert(events)
    return events


def persist_backtest_fill_events(data_dir: Path, payload: dict[str, Any]) -> int:
    """Persist simulated fills with explicit backtest semantics."""
    config = payload.get("config") or {}
    strategy_info = payload.get("strategy_info") or {}
    strategy_id = str(config.get("strategy_id") or strategy_info.get("id") or "unknown")
    run_id = str(payload.get("run_id") or _fingerprint(payload, 24))
    params = config.get("params") or {}
    params_fingerprint = _fingerprint(params)
    strategy_version = str(strategy_info.get("version") or "unknown")
    events: list[dict[str, Any]] = []
    for trade_index, trade in enumerate(payload.get("trades") or []):
        symbol = str(trade.get("symbol") or "")
        if not symbol:
            continue
        for event_type, date_key, price_key, signal_key in (
            ("entry", "entry_date", "entry_price", "entry_signal_id"),
            ("exit", "exit_date", "exit_price", "exit_signal_id"),
        ):
            event_date = trade.get(date_key)
            if not event_date:
                continue
            signal_id = trade.get(signal_key)
            events.append({
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "params_fingerprint": params_fingerprint,
                "symbol": symbol,
                "asset_type": str(config.get("asset_type") or "stock"),
                "event_date": str(event_date)[:10],
                "event_type": event_type,
                "signal_kind": "backtest_fill",
                "event_sequence": trade_index,
                "score": trade.get("entry_score"),
                "source_run_id": run_id,
                "provenance": "observed_run",
                "input_fingerprint": f"backtest:{run_id}",
                "reason_codes": [str(signal_id or trade.get("exit_reason") or event_type)],
                "metrics": [
                    {"name": "fill_price", "value": trade.get(price_key), "unit": "price", "passed": None},
                    {"name": "pnl_pct", "value": trade.get("pnl_pct"), "unit": "%", "passed": None},
                ],
                "anchors": [{"date": str(event_date)[:10], "role": f"backtest_{event_type}"}],
                "levels": [{"role": f"backtest_{event_type}", "label": "回测成交价", "value": trade.get(price_key)}],
                "pattern_refs": [],
                "observed_at": datetime.now(),
            })
    return StrategySignalEventRepository(data_dir).upsert(events) if events else 0


def persist_realtime_trigger_events(
    *,
    data_dir: Path,
    strategy_id: str,
    strategy_version: str,
    params: dict[str, Any],
    as_of: date,
    asset_type: str,
    changes: dict[str, set[str]],
    rows: dict[str, dict[str, Any]],
) -> int:
    """Persist only edge-triggered monitor events, never the polling snapshots."""
    params_fingerprint = _fingerprint(params)
    source_run_id = _fingerprint({
        "strategy_id": strategy_id,
        "as_of": as_of,
        "params_fingerprint": params_fingerprint,
        "signal_kind": "realtime_trigger",
    }, 24)
    type_map = {
        "buy_signal": "entry", "sell_signal": "exit",
        "pool_entry": "candidate", "pool_exit": "failure",
    }
    events: list[dict[str, Any]] = []
    for change_type, symbols in changes.items():
        for symbol in sorted(symbols):
            row = rows.get(symbol, {})
            close = row.get("close")
            events.append({
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "params_fingerprint": params_fingerprint,
                "symbol": symbol,
                "asset_type": asset_type,
                "event_date": as_of,
                "event_type": type_map.get(change_type, "candidate"),
                "signal_kind": "realtime_trigger",
                "score": row.get("score"),
                "source_run_id": source_run_id,
                "provenance": "observed_run",
                "input_fingerprint": f"realtime:{as_of.isoformat()}",
                "reason_codes": [change_type],
                "metrics": [],
                "anchors": [{"date": as_of.isoformat(), "role": change_type}],
                "levels": [] if close is None else [{"role": "realtime_trigger", "label": "触发时最新价", "value": close}],
                "pattern_refs": [],
                "observed_at": datetime.now(),
            })
    return StrategySignalEventRepository(data_dir).upsert(events) if events else 0
