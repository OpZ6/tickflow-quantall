"""SMNC (smnc.juecan.com) research material collector.

Ported from the QuantX research pipeline so the stock pool can pull its
research materials directly inside TickFlow instead of depending on an
external project. The site is a plain ASP list/info page; entries are
normalized into the same ``items.json`` contract used by the research
material index.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "http://smnc.juecan.com"
LIST_PATH = "/list.asp"
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_BEIJING = timezone(timedelta(hours=8))
_TIME_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})")


def fetch_page(url: str) -> tuple[str, str]:
    """Fetch one list page. Returns (html, status)."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.encoding = response.apparent_encoding or "utf-8"
        if response.status_code != 200:
            return "", f"http_{response.status_code}"
        if "smnc.juecan.com" not in response.url:
            return "", f"blocked_or_redirected: {response.url}"
        return response.text, "ok"
    except requests.Timeout:
        return "", "timeout"
    except requests.ConnectionError as exc:
        return "", f"connection_error: {exc}"
    except Exception as exc:
        return "", f"error: {exc}"


def _parse_time(text: str) -> str:
    match = _TIME_RE.search(text or "")
    if not match:
        return ""
    year, month, day, hour, minute, second = (int(value) for value in match.groups())
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=_BEIJING).isoformat()
    except (ValueError, OverflowError):
        return ""


def parse_html(html: str) -> list[dict[str, Any]]:
    """Parse the list page into entry dicts (id/title/content/url/created_at)."""
    if not html:
        return []
    entries: list[dict[str, Any]] = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for post in soup.select("div.post"):
            short = post.select_one("[id^=short_text_]")
            full = post.select_one("[id^=full_text_]")
            content_el = full or short
            if not content_el:
                continue
            match = re.search(r"(\d+)$", content_el.get("id", ""))
            if not match:
                continue
            content_text = content_el.get_text(separator="\n", strip=True)
            if not content_text:
                continue
            first_p = content_el.select_one("p")
            if first_p and first_p.get_text(strip=True):
                title = first_p.get_text(strip=True)[:80]
            else:
                title = (content_text.split("\n", 1)[0] or "")[:80]
            meta = post.select_one(".entry-meta, .entry-utility")
            images: list[str] = []
            for image in content_el.select("img"):
                src = image.get("src", "")
                if not src:
                    continue
                if src.startswith("http"):
                    images.append(src)
                elif src.startswith("/"):
                    images.append(BASE_URL + src)
                else:
                    images.append(BASE_URL + "/" + src)
            entries.append({
                "id": match.group(1),
                "title": title,
                "content": content_text,
                "url": f"{BASE_URL}/info.asp?id={match.group(1)}",
                "created_at": _parse_time(meta.get_text(" ", strip=True) if meta else ""),
                "images": images,
            })
    except Exception:
        logger.exception("SMNC list page parse failed")
    return entries


def _content_hash(source_id: str, content_text: str) -> str:
    return hashlib.sha256(f"smnc|{source_id}|{content_text[:2000]}".encode()).hexdigest()[:16]


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    source_id = str(entry.get("id", entry.get("url", "")))
    created = str(entry.get("created_at") or "")
    return {
        "item_id": f"smnc_{source_id}",
        "source": "smnc",
        "source_id": source_id,
        "title": str(entry.get("title", ""))[:200],
        "content_text": str(entry.get("content", "")),
        "created_at": created,
        "updated_at": created,
        "captured_at": datetime.now(UTC).isoformat(),
        "tags": [],
        "stocks": [],
        "themes": [],
        "source_url": str(entry.get("url", "")),
        "content_hash": _content_hash(source_id, str(entry.get("content", ""))),
        "status": "active",
        "images": list(entry.get("images") or []),
        "owner": "smnc",
    }


def _load_items(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    return [item for item in payload if isinstance(item, dict) and item.get("content_hash")]


def _to_epoch(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (ValueError, TypeError):
        return 0.0


def update_items(
    data_root: Path,
    *,
    max_pages: int = 50,
    allow_network: bool = True,
) -> dict[str, Any]:
    """Incrementally poll SMNC and upsert new entries into the local store.

    Pages are fetched from newest to oldest; pagination stops once a page's
    oldest entry predates the newest stored item. Network failures degrade to
    a status dict so the caller can keep using the existing local items.
    """
    data_root = Path(data_root)
    items_path = data_root / "research" / "items.json"
    existing = _load_items(items_path)
    cursor = max((str(item.get("created_at") or "") for item in existing), default="")
    cursor_epoch = _to_epoch(cursor)

    result: dict[str, Any] = {
        "status": "ok", "pages_fetched": 0, "added": 0, "updated": 0,
        "entries_found": 0, "cursor": cursor,
    }
    if not allow_network:
        result["status"] = "offline"
        return result

    fetched: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        html, status = fetch_page(f"{BASE_URL}{LIST_PATH}?page={page}")
        if status != "ok":
            result["status"] = status if not fetched else "partial"
            break
        result["pages_fetched"] += 1
        entries = parse_html(html)
        if not entries:
            break
        fetched.extend(entries)
        oldest = min((_to_epoch(entry.get("created_at")) for entry in entries), default=0.0)
        if cursor_epoch and oldest and oldest <= cursor_epoch:
            break
        time.sleep(0.5)

    if result["status"] not in {"ok", "partial"}:
        return result

    result["entries_found"] = len(fetched)
    if not fetched:
        result["status"] = "empty" if result["status"] == "ok" else result["status"]
        return result

    raw_dir = data_root / "research" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(datetime.now(UTC).timestamp())
    (raw_dir / f"smnc_{timestamp}.json").write_text(
        json.dumps({
            "status": result["status"], "pages_fetched": result["pages_fetched"],
            "entries_found": len(fetched), "cursor": cursor,
            "fetched_at": datetime.now(UTC).isoformat(),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    by_hash = {str(item["content_hash"]): item for item in existing}
    added = updated = 0
    for entry in fetched:
        item = normalize_entry(entry)
        previous = by_hash.get(item["content_hash"])
        if previous is None:
            by_hash[item["content_hash"]] = item
            added += 1
        elif item.get("updated_at") != previous.get("updated_at"):
            by_hash[item["content_hash"]] = item
            updated += 1
    if added or updated:
        items_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(by_hash.values(), key=lambda item: str(item.get("created_at") or ""))
        items_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    result["added"] = added
    result["updated"] = updated
    return result
