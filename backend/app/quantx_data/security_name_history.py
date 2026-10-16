"""Offline namechange normalization; reconstructed evidence, not tradability."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

SCHEMA = {
    "symbol": pl.String, "name": pl.String,
    "valid_from": pl.Date, "valid_to_exclusive": pl.Date,
    "ann_date": pl.Date, "available_from": pl.Date,
    "coverage_until": pl.Date, "is_st_name": pl.Boolean,
    "source": pl.String, "source_record_id": pl.String,
    "observed_at": pl.String, "quality_level": pl.String,
}
SOURCE_SYMBOL_PATTERN = re.compile(r"\d{6}\.(SH|SZ|BJ)")


def _date(value, *, required=False) -> date | None:
    if value is None or value == "":
        if required:
            raise ValueError("missing interval start")
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise ValueError("source dates must be YYYYMMDD")
    return datetime.strptime(value, "%Y%m%d").date()


def normalize_name_pages(pages: list[dict]) -> pl.DataFrame:
    """Convert inclusive source end dates without inventing missing intervals.

    Tushare's documented example ends the old name one day before the next
    name starts. Preserve this as [start, end + 1 day). Announcement dates have
    no intraday timestamp: available_from conservatively starts the next day.
    Missing announcements remain unknown. Source coverage ends on observation,
    even when the current name has an open interval.
    """
    shadow_keys = {
        (
            item["source_symbol"], item["name"],
            date.fromisoformat(item["shadow_start"]),
            date.fromisoformat(item["ann_date"]),
        )
        for item in announcement_shadow_rows(pages)
    }
    rows = []
    seen = set()
    for page in pages:
        if page.get("status") != "ok" or page.get("request", {}).get("endpoint") != "namechange":
            raise ValueError("expected successful namechange source page")
        observed_at = page.get("scraped_at", "")
        observed = datetime.fromisoformat(observed_at)
        if observed.tzinfo is None:
            raise ValueError("observation time must have a timezone")
        coverage = observed.astimezone(ZoneInfo("Asia/Shanghai")).date()
        source = page.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError("source provenance missing")
        if not isinstance(page.get("rows"), list):
            raise ValueError("missing source rows")
        for raw in page["rows"]:
            symbol, name = raw.get("ts_code"), raw.get("name")
            if not isinstance(symbol, str) or not SOURCE_SYMBOL_PATTERN.fullmatch(symbol):
                raise ValueError(f"invalid source security code: {symbol!r}")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("missing security name")
            start = _date(raw.get("start_date"), required=True)
            end = _date(raw.get("end_date"))
            announcement = _date(raw.get("ann_date"))
            if (symbol, name, start, announcement) in shadow_keys:
                continue
            if end is not None and end < start:
                raise ValueError("name interval ends before it starts")
            key = (symbol, start)
            if key in seen:
                raise ValueError("duplicate/conflicting name interval start")
            seen.add(key)
            rows.append({
                "symbol": symbol, "name": name,
                "valid_from": start,
                "valid_to_exclusive": end + timedelta(days=1) if end else None,
                "ann_date": announcement,
                "available_from": announcement + timedelta(days=1) if announcement else None,
                "coverage_until": coverage,
                "is_st_name": bool(re.match(r"^(?:S\*ST|SST|\*ST|ST)", name.strip().upper())),
                "source": source, "source_record_id": f"{symbol}:{start.isoformat()}",
                "observed_at": observed_at, "quality_level": "reconstructed",
            })
    frame = pl.DataFrame(rows, schema=SCHEMA).sort("symbol", "valid_from")
    previous = None
    for row in frame.iter_rows(named=True):
        if previous and previous["symbol"] == row["symbol"]:
            end = previous["valid_to_exclusive"]
            if end is None or end > row["valid_from"]:
                raise ValueError(
                    "overlapping name intervals: "
                    f"{row['symbol']} {previous['valid_from']} -> {row['valid_from']}"
                )
        previous = row
    return frame


def announcement_shadow_rows(pages: list[dict]) -> list[dict]:
    """Identify proposal-date duplicates only when the effective interval is proven.

    Some provider rows repeat a future name first at the proposal announcement
    date and then at the actual exchange effective date. Collapse only the exact
    pattern where the prior different name ends on the day before that later
    effective row. Ambiguous overlaps remain fail-closed in normalization.
    """
    raw_rows = [
        raw
        for page in pages
        if isinstance(page.get("rows"), list)
        for raw in page["rows"]
        if isinstance(raw.get("ts_code"), str)
        and SOURCE_SYMBOL_PATTERN.fullmatch(raw["ts_code"])
    ]
    result = []
    for raw in raw_rows:
        symbol, name = raw["ts_code"], raw.get("name")
        start = _date(raw.get("start_date"), required=True)
        announcement = _date(raw.get("ann_date"))
        if raw.get("end_date") not in (None, "") or announcement is None or start != announcement:
            continue
        later = []
        for candidate in raw_rows:
            if (
                candidate is not raw
                and candidate.get("ts_code") == symbol
                and candidate.get("name") == name
                and candidate.get("ann_date") == raw.get("ann_date")
                and candidate.get("end_date") in (None, "")
            ):
                candidate_start = _date(candidate.get("start_date"), required=True)
                if candidate_start > start:
                    later.append(candidate_start)
        if len(later) != 1:
            continue
        effective = later[0]
        prior_boundary = effective - timedelta(days=1)
        prior = [
            candidate
            for candidate in raw_rows
            if candidate.get("ts_code") == symbol
            and candidate.get("name") != name
            and _date(candidate.get("end_date")) == prior_boundary
        ]
        if len(prior) != 1:
            continue
        result.append({
            "source_symbol": symbol,
            "name": name,
            "ann_date": announcement.isoformat(),
            "shadow_start": start.isoformat(),
            "effective_start": effective.isoformat(),
            "prior_name": prior[0]["name"],
            "prior_end": prior_boundary.isoformat(),
        })
    return result


def invalid_name_source_codes(pages: list[dict]) -> list[dict]:
    """List invalid provider identifiers without weakening fail-closed normalization."""
    counts: Counter[str] = Counter()
    for page in pages:
        rows = page.get("rows")
        if not isinstance(rows, list):
            continue
        for raw in rows:
            symbol = raw.get("ts_code")
            if not isinstance(symbol, str) or not SOURCE_SYMBOL_PATTERN.fullmatch(symbol):
                counts[symbol if isinstance(symbol, str) else repr(symbol)] += 1
    return [
        {"source_symbol": symbol, "rows": count}
        for symbol, count in sorted(counts.items())
    ]


def inspect_name_pages(pages: list[dict]) -> dict:
    """Run a complete offline audit while keeping invalid identifiers rejected."""
    invalid_codes = invalid_name_source_codes(pages)
    shadow_rows = announcement_shadow_rows(pages)
    diagnostic_pages = [
        {
            **page,
            "rows": [
                raw
                for raw in page.get("rows", [])
                if isinstance(raw.get("ts_code"), str)
                and SOURCE_SYMBOL_PATTERN.fullmatch(raw["ts_code"])
            ],
        }
        for page in pages
    ]
    try:
        remaining = summarize_name_history(normalize_name_pages(diagnostic_pages))
    except ValueError as exc:
        remaining = {
            "status": "rejected",
            "error": str(exc),
            "production_published": False,
        }
    if invalid_codes:
        return {
            "status": "rejected_invalid_source_codes",
            "invalid_source_codes": invalid_codes,
            "announcement_shadow_rows": shadow_rows,
            "valid_code_rows_diagnostic": remaining,
            "production_published": False,
        }
    remaining["announcement_shadow_rows"] = shadow_rows
    return remaining


def summarize_name_history(frame: pl.DataFrame) -> dict:
    gaps = 0
    previous = None
    for row in frame.iter_rows(named=True):
        if previous and previous["symbol"] == row["symbol"]:
            gaps += int(previous["valid_to_exclusive"] < row["valid_from"])
        previous = row
    return {
        "status": "normalized_unverified" if frame.height else "missing",
        "rows": frame.height, "symbols": frame["symbol"].n_unique(),
        "unknown_announcements": frame["ann_date"].null_count(),
        "internal_interval_gaps": gaps,
        "production_published": False,
        "coverage": "observed source intervals only; no listing or suspension inference",
    }
