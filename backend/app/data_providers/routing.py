"""Runtime provider-chain health, failover and source lineage."""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from app.services import preferences

T = TypeVar("T")
_COOLDOWN_S = 60.0
_lock = threading.RLock()


@dataclass
class _Health:
    healthy: bool = True
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error: str | None = None
    cooldown_until: float = 0.0


_health: dict[tuple[str, str], _Health] = {}
_effective: dict[str, str] = {}
_publication_written_at: dict[str, float] = {}


class ProviderChainExhaustedError(RuntimeError):
    """Raised when every provider in a dataset priority chain fails."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _lineage_path() -> Path:
    from app.config import settings

    return settings.data_dir / "user_data" / "data_source_lineage.json"


def _persist_lineage() -> None:
    path = _lineage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    datasets: dict[str, dict] = {}
    for (dataset, provider), state in _health.items():
        entry = datasets.setdefault(dataset, {
            "effective_provider": _effective.get(dataset),
            "updated_at": _utc_now(),
            "providers": {},
        })
        payload = asdict(state)
        payload["cooldown_remaining_s"] = round(
            max(0.0, state.cooldown_until - now), 1,
        )
        payload.pop("cooldown_until", None)
        entry["providers"][provider] = payload
    payload = {"version": 1, "datasets": datasets}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def reset_health() -> None:
    with _lock:
        _health.clear()
        _effective.clear()
        _publication_written_at.clear()


def is_healthy(dataset: str, provider: str) -> bool:
    with _lock:
        state = _health.get((dataset, provider))
        return state is None or state.healthy or time.monotonic() >= state.cooldown_until


def record_success(dataset: str, provider: str) -> None:
    with _lock:
        state = _health.setdefault((dataset, provider), _Health())
        changed = not state.healthy or _effective.get(dataset) != provider
        state.healthy = True
        state.last_success_at = _utc_now()
        state.last_error = None
        state.cooldown_until = 0.0
        _effective[dataset] = provider
        if changed:
            _persist_lineage()


def record_failure(dataset: str, provider: str, error: str) -> None:
    with _lock:
        state = _health.setdefault((dataset, provider), _Health())
        state.healthy = False
        state.last_failure_at = _utc_now()
        state.last_error = str(error)
        state.cooldown_until = time.monotonic() + _COOLDOWN_S
        _persist_lineage()


def record_publication(
    dataset: str,
    provider: str,
    *,
    rows: int | None = None,
    scope: str | None = None,
) -> None:
    """Persist the source marker for a successful canonical publication."""
    record_success(dataset, provider)
    with _lock:
        now = time.monotonic()
        if now - _publication_written_at.get(dataset, 0.0) < 300.0:
            return
        _publication_written_at[dataset] = now
        path = _lineage_path()
        payload = json.loads(path.read_text(encoding="utf-8"))
        entry = payload["datasets"][dataset]
        entry["last_publication"] = {
            "provider": provider,
            "rows": rows,
            "scope": scope,
            "published_at": _utc_now(),
        }
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def health_snapshot(dataset: str | None = None) -> dict:
    with _lock:
        now = time.monotonic()
        result: dict[str, dict] = {}
        for (item_dataset, provider), state in _health.items():
            if dataset is not None and item_dataset != dataset:
                continue
            payload = asdict(state)
            payload["cooldown_remaining_s"] = round(
                max(0.0, state.cooldown_until - now), 1,
            )
            payload.pop("cooldown_until", None)
            result[provider] = payload
        return result


def run_with_failover(
    dataset: str,
    call: Callable[[str], T],
    *,
    is_success: Callable[[T], bool],
) -> tuple[T, str]:
    """Try the configured chain in order, cooling down failed providers."""
    chain = preferences.get_data_provider_chain(dataset)
    errors: list[str] = []
    for provider in chain:
        if not is_healthy(dataset, provider):
            errors.append(f"{provider}: cooling down")
            continue
        try:
            result = call(provider)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            record_failure(dataset, provider, message)
            errors.append(f"{provider}: {message}")
            continue
        if is_success(result):
            record_success(dataset, provider)
            return result, provider
        record_failure(dataset, provider, "empty result")
        errors.append(f"{provider}: empty result")
    raise ProviderChainExhaustedError(
        f"{dataset} provider chain exhausted ({'; '.join(errors)})",
    )
