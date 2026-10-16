"""Partitioned authority for derived strategy signal events.

This store is deliberately separate from Market Facts and the page cache.  A repeated
observed run replaces rows with the same versioned primary key, while a recomputation is
kept distinguishable through ``provenance``.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

SCHEMA_VERSION = 2
PRIMARY_KEY = [
    "strategy_id", "strategy_version", "params_fingerprint", "symbol",
    "event_date", "event_type", "source_run_id", "event_sequence",
]
_LOCK = threading.RLock()
_SCHEMA = {
    "schema_version": pl.Int32,
    "strategy_id": pl.Utf8,
    "strategy_version": pl.Utf8,
    "params_fingerprint": pl.Utf8,
    "symbol": pl.Utf8,
    "asset_type": pl.Utf8,
    "event_date": pl.Date,
    "event_type": pl.Utf8,
    "signal_kind": pl.Utf8,
    "event_sequence": pl.Int32,
    "score": pl.Float64,
    "source_run_id": pl.Utf8,
    "provenance": pl.Utf8,
    "input_fingerprint": pl.Utf8,
    "reason_codes_json": pl.Utf8,
    "metrics_json": pl.Utf8,
    "anchors_json": pl.Utf8,
    "levels_json": pl.Utf8,
    "pattern_refs_json": pl.Utf8,
    "observed_at": pl.Datetime("us"),
}


def _root(data_dir: Path) -> Path:
    return data_dir / "strategy_signal_events"


def _partition(data_dir: Path, event_date: date) -> Path:
    return _root(data_dir) / f"date={event_date.isoformat()}" / "part.parquet"


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize(events: Iterable[dict[str, Any]]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events:
        event_date = event.get("event_date")
        if isinstance(event_date, str):
            event_date = date.fromisoformat(event_date[:10])
        row = {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": str(event.get("strategy_id") or ""),
            "strategy_version": str(event.get("strategy_version") or "unknown"),
            "params_fingerprint": str(event.get("params_fingerprint") or "unknown"),
            "symbol": str(event.get("symbol") or ""),
            "asset_type": str(event.get("asset_type") or "stock"),
            "event_date": event_date,
            "event_type": str(event.get("event_type") or "candidate"),
            "signal_kind": str(event.get("signal_kind") or "strategy_signal"),
            "event_sequence": int(event.get("event_sequence") or 0),
            "score": float(event["score"]) if event.get("score") is not None else None,
            "source_run_id": str(event.get("source_run_id") or "unknown"),
            "provenance": str(event.get("provenance") or "observed_run"),
            "input_fingerprint": str(event.get("input_fingerprint") or "unknown"),
            "reason_codes_json": _json(event.get("reason_codes")),
            "metrics_json": _json(event.get("metrics")),
            "anchors_json": _json(event.get("anchors")),
            "levels_json": _json(event.get("levels")),
            "pattern_refs_json": _json(event.get("pattern_refs")),
            "observed_at": event.get("observed_at"),
        }
        if not row["strategy_id"] or not row["symbol"] or not isinstance(row["event_date"], date):
            raise ValueError("strategy event requires strategy_id, symbol and event_date")
        rows.append(row)
    return pl.DataFrame(rows, schema=_SCHEMA) if rows else pl.DataFrame(schema=_SCHEMA)


class StrategySignalEventRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def upsert(self, events: Iterable[dict[str, Any]]) -> int:
        frame = _normalize(events)
        if frame.is_empty():
            return 0
        with _LOCK:
            for event_date in frame["event_date"].unique().to_list():
                path = _partition(self.data_dir, event_date)
                part = frame.filter(pl.col("event_date") == event_date)
                if path.exists():
                    old = self._read_path(path)
                    part = pl.concat([old, part], how="diagonal_relaxed").unique(PRIMARY_KEY, keep="last")
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name("part.parquet.tmp")
                part.sort(PRIMARY_KEY).write_parquet(tmp)
                os.replace(tmp, path)
            self._bump_generation()
        return frame.height

    def query(
        self,
        *,
        symbol: str | None = None,
        strategy_ids: Iterable[str] = (),
        start_date: date | None = None,
        end_date: date | None = None,
        event_types: Iterable[str] = (),
        source_run_id: str | None = None,
        params_fingerprint: str | None = None,
    ) -> list[dict[str, Any]]:
        root = _root(self.data_dir)
        if not root.exists():
            return []
        frames: list[pl.DataFrame] = []
        for path in sorted(root.glob("date=*/part.parquet")):
            try:
                partition_date = date.fromisoformat(path.parent.name.removeprefix("date="))
            except ValueError:
                continue
            if start_date and partition_date < start_date:
                continue
            if end_date and partition_date > end_date:
                continue
            frames.append(self._read_path(path))
        if not frames:
            return []
        frame = pl.concat(frames, how="diagonal_relaxed")
        if symbol:
            frame = frame.filter(pl.col("symbol") == symbol)
        selected = list(strategy_ids)
        if selected:
            frame = frame.filter(pl.col("strategy_id").is_in(selected))
        types = list(event_types)
        if types:
            frame = frame.filter(pl.col("event_type").is_in(types))
        if source_run_id:
            frame = frame.filter(pl.col("source_run_id") == source_run_id)
        if params_fingerprint:
            frame = frame.filter(pl.col("params_fingerprint") == params_fingerprint)
        rows = frame.sort(["event_date", "strategy_id", "event_type"]).to_dicts()
        for row in rows:
            row["event_date"] = row["event_date"].isoformat()
            if row.get("observed_at") is not None:
                row["observed_at"] = row["observed_at"].isoformat()
            for key in ("reason_codes", "metrics", "anchors", "levels", "pattern_refs"):
                row[key] = json.loads(row.pop(f"{key}_json", "[]") or "[]")
        return rows

    def generation(self) -> int:
        path = _root(self.data_dir) / "generation.json"
        try:
            return int(json.loads(path.read_text(encoding="utf-8")).get("generation") or 0)
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            return 0

    def _bump_generation(self) -> None:
        root = _root(self.data_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "generation.json"
        tmp = root / "generation.json.tmp"
        tmp.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "generation": self.generation() + 1}), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _read_path(path: Path) -> pl.DataFrame:
        frame = pl.read_parquet(path)
        missing = [name for name in _SCHEMA if name not in frame.columns]
        if missing:
            frame = frame.with_columns([
                pl.lit(0 if name == "event_sequence" else None, dtype=_SCHEMA[name]).alias(name)
                for name in missing
            ])
        return frame.select([pl.col(name).cast(dtype, strict=False).alias(name) for name, dtype in _SCHEMA.items()])
