"""Resumable research-only Tushare security evidence, never production facts."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.quantx_data.io import write_json_atomic
from app.quantx_data.schemas import SourceSpec
from app.quantx_data.source_manager import SourceManager

FIELDS = {
    "namechange": "ts_code,name,start_date,end_date,ann_date,change_reason",
    "stock_basic": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
}
STATUSES = ("L", "D", "P", "G", "UN")
PAGE_SIZE = 10000


def retry_delay(error: str, baseline: int) -> int:
    """Use the actual account quota window, not the public permission table."""
    windows = {"分钟": 65, "小时": 3605, "天": 86405}
    return max([baseline, *(windows[unit] for unit in re.findall(r"次/(分钟|小时|天)", error))])


def request_for(endpoint: str, page: int) -> dict:
    if endpoint not in FIELDS or page < 0:
        raise ValueError("invalid security snapshot request")
    params = {"fields": FIELDS[endpoint]}
    if endpoint == "namechange":
        params.update(offset=page * PAGE_SIZE, limit=PAGE_SIZE)
    else:
        params.update(exchange="", list_status=STATUSES[page])
    return {"endpoint": endpoint, "params": params}


def run(_trade_date: str, output_dir: str) -> dict:
    """SourceManager subprocess entry; credentials stay in the existing client."""
    from app.config import settings  # noqa: F401 - load configured environment
    from app.plugins.tushare.client import build_tushare_client

    request = json.loads((Path(output_dir) / "request.json").read_text(encoding="utf-8"))
    endpoint = request["endpoint"]
    expected = {**request_for(endpoint, request["page"]), "page": request["page"]}
    if request != expected:
        raise ValueError("unexpected security snapshot request")
    frame = getattr(build_tushare_client(timeout=20), endpoint)(**request["params"])
    if frame is None:
        raise ValueError("source returned None, not a successful empty frame")
    if not set(FIELDS[endpoint].split(",")).issubset(frame.columns):
        raise ValueError("security snapshot response missing requested columns")
    # pandas conversion preserves nulls as JSON null rather than NaN/NaT.
    return {
        "status": "ok", "source": "tushare_client_chain",
        "scraped_at": datetime.now(UTC).isoformat(),
        "request": request, "rows": json.loads(frame.to_json(orient="records")),
    }


def snapshot_manager() -> SourceManager:
    manager = SourceManager()
    spec = SourceSpec(
        name="security_history_snapshot", required=True,
        collector="module:app.quantx_data.security_snapshots", role="security_history",
        dependency_modules=("tushare",), max_retries=0, timeout_seconds=100,
    )
    manager.register(spec, lambda day, directory: run(day, str(directory)))
    return manager


def collect_step(root: Path, endpoint: str, *, allow_network: bool = False,
                 manager: SourceManager | None = None, now: datetime | None = None) -> dict:
    """Inspect saved pages, then optionally fetch one next page. Single writer only.

    Short namechange pages merely suggest exhaustion: offset ordering and source
    coverage still require independent verification before canonical publication.
    """
    request_for(endpoint, 0)
    now = now or datetime.now(UTC)
    root = Path(root)
    if not allow_network and not root.exists():
        return {"status": "pending", "endpoint": endpoint, "next_page": 0, "rows": 0}
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".writer.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(now))
    try:
        return _collect_step(root, endpoint, allow_network, manager, now)
    finally:
        lock.unlink()


def _collect_step(root, endpoint, allow_network, manager, now):
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["endpoint"] != endpoint:
            raise ValueError("snapshot directory belongs to another endpoint")
    else:
        previous = {}
    seen = set()
    total = 0
    terminal = False
    paths = sorted(root.glob("page-*.json"))
    if len(paths) < previous.get("pages", 0):
        raise ValueError("previously committed page is missing")
    for page, path in enumerate(paths):
        if path.name != f"page-{page:06d}.json" or terminal:
            raise ValueError("non-contiguous pages or data after terminal page")
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = _validate_page(payload, endpoint, page, seen)
        total += len(rows)
        terminal = len(rows) < PAGE_SIZE if endpoint == "namechange" else page == 4
    state = {
        "schema_version": 1, "endpoint": endpoint, "pages": len(paths), "rows": total,
        "next_page": None if terminal else len(paths),
        "status": "collected_unverified" if terminal else "incomplete",
        "production_published": False,
        "coverage": "source responses only; not a point-in-time security master",
    }
    if terminal or not allow_network:
        return state
    if previous.get("next_attempt_at") and now < datetime.fromisoformat(previous["next_attempt_at"]):
        return {**state, "status": "cooldown", "next_attempt_at": previous["next_attempt_at"]}
    page = len(paths)
    request = {**request_for(endpoint, page), "page": page}
    directory = root / f"request-{page:06d}"
    if (directory / "rejected.json").exists():
        return {
            **state,
            "status": "invalid_page",
            "error_kind": "invalid_page",
            "requires_resolution": True,
        }
    write_json_atomic(directory / "raw" / "request.json", request)
    # Persist before networking: interruption must not immediately consume quota again.
    delay = max(previous.get("retry_delay_seconds", 0), 65 if endpoint == "namechange" else 3605)
    state["retry_delay_seconds"] = delay
    state["next_attempt_at"] = (now + timedelta(seconds=delay)).isoformat()
    write_json_atomic(manifest_path, state)
    result = (manager or snapshot_manager()).collect(
        "security_history_snapshot", now.strftime("%Y%m%d"), directory, force=True,
    )
    if not result.ok:
        state.update(status="incomplete", error_kind=result.error_kind or "source_error")
        if result.error_kind == "rate_limit":
            delay = retry_delay(result.error or "", delay)
            state["retry_delay_seconds"] = delay
            state["next_attempt_at"] = (now + timedelta(seconds=delay)).isoformat()
        # Source exceptions may embed remote credentials; persist categories only.
        write_json_atomic(manifest_path, state)
        return state
    payload = result.payload
    try:
        rows = _validate_page(payload, endpoint, page, seen)
    except ValueError:
        write_json_atomic(directory / "rejected.json", payload)
        state.update(status="incomplete", error_kind="invalid_page")
        write_json_atomic(manifest_path, state)
        return state
    write_json_atomic(root / f"page-{page:06d}.json", payload)
    terminal = len(rows) < PAGE_SIZE if endpoint == "namechange" else page == 4
    state.update(pages=page + 1, rows=total + len(rows), next_page=None if terminal else page + 1,
                 status="collected_unverified" if terminal else "incomplete")
    write_json_atomic(manifest_path, state)
    return state


def _validate_page(payload: dict, endpoint: str, page: int, seen: set) -> list:
    expected = {**request_for(endpoint, page), "page": page}
    if payload.get("request") != expected or payload.get("status") != "ok":
        raise ValueError("page request/status mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not payload.get("scraped_at"):
        raise ValueError("missing rows or observation timestamp")
    cap = PAGE_SIZE if endpoint == "namechange" else 6000
    if len(rows) > cap or (endpoint == "stock_basic" and len(rows) == cap):
        raise ValueError("response may be truncated or limit ignored")
    for row in rows:
        if not isinstance(row, dict) or not set(FIELDS[endpoint].split(",")).issubset(row):
            raise ValueError("missing fields")
        if not row["ts_code"]:
            raise ValueError("missing security code")
        if endpoint == "stock_basic" and row["list_status"] != STATUSES[page]:
            raise ValueError("source ignored status filter")
        key = (row["ts_code"], row.get("start_date"), row.get("name")) if endpoint == "namechange" else row["ts_code"]
        if key in seen:
            raise ValueError("duplicate security record across or within pages")
        seen.add(key)
    return rows
