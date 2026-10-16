"""Normalize stock_basic evidence without interpreting current status as history."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from app.quantx_data.security_snapshots import STATUSES

SCHEMA = {
    "source_symbol": pl.String, "security_id": pl.String,
    "symbol": pl.String, "name": pl.String, "exchange": pl.String,
    "list_date": pl.Date, "delist_date": pl.Date, "source_status": pl.String,
    "as_of_date": pl.Date, "observed_at": pl.String, "source": pl.String,
    "quality_level": pl.String,
}
EXCHANGES = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}


def _date(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise ValueError("listing dates must be YYYYMMDD")
    return datetime.strptime(value, "%Y%m%d").date()


def normalize_listing_pages(pages: list[dict]) -> pl.DataFrame:
    rows, seen, statuses = [], set(), set()
    for page in pages:
        request = page.get("request", {})
        status = request.get("params", {}).get("list_status")
        if page.get("status") != "ok" or request.get("endpoint") != "stock_basic" or status not in STATUSES:
            raise ValueError("expected successful stock_basic status response")
        if status in statuses:
            raise ValueError("duplicate status snapshot")
        statuses.add(status)
        observed_at = page.get("scraped_at", "")
        observed = datetime.fromisoformat(observed_at)
        if observed.tzinfo is None:
            raise ValueError("observation time must have a timezone")
        as_of = observed.astimezone(ZoneInfo("Asia/Shanghai")).date()
        source = page.get("source")
        if not isinstance(source, str) or not source or not isinstance(page.get("rows"), list):
            raise ValueError("missing source provenance or rows")
        for raw in page["rows"]:
            source_symbol = raw.get("ts_code")
            symbol = source_symbol
            # Exact reviewed lifecycle, not a general vendor-prefix removal rule.
            # Evidence: quant-development-plan.md, P0-B identity decision.
            if source_symbol == "T600018.SH":
                if (source != "tushare_client_chain" or status != "D"
                    or raw.get("name") != "上港集箱(退)"
                    or raw.get("list_date") != "20000719"
                    or raw.get("delist_date") != "20061020"):
                    raise ValueError("unverified listing alias lifecycle")
                symbol = "600018.SH"
            if not isinstance(symbol, str) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
                raise ValueError("invalid listing security code")
            if raw.get("exchange") != EXCHANGES[symbol[-2:]] or raw.get("symbol") != source_symbol.rsplit(".", 1)[0]:
                raise ValueError("security code/exchange mismatch")
            if raw.get("list_status") != status:
                raise ValueError("source ignored listing status filter")
            if source_symbol in seen:
                raise ValueError("duplicate/conflicting security listing")
            seen.add(source_symbol)
            listing, delisting = _date(raw.get("list_date")), _date(raw.get("delist_date"))
            if listing and delisting and delisting < listing:
                raise ValueError("delisting precedes listing")
            if not isinstance(raw.get("name"), str) or not raw["name"].strip():
                raise ValueError("missing security name")
            rows.append({
                "source_symbol": source_symbol, "security_id": f"tushare:{source_symbol}",
                "symbol": symbol, "name": raw["name"], "exchange": raw["exchange"],
                "list_date": listing, "delist_date": delisting, "source_status": status,
                "as_of_date": as_of, "observed_at": observed_at, "source": source,
                "quality_level": "reconstructed",
            })
    frame = pl.DataFrame(rows, schema=SCHEMA).sort("symbol", "list_date")
    previous = {}
    for row in frame.iter_rows(named=True):
        old = previous.get(row["symbol"])
        if old is not None and (
            old["list_date"] is None or old["delist_date"] is None
            or row["list_date"] is None or row["list_date"] <= old["delist_date"]
        ):
            raise ValueError("unknown or overlapping listing lifecycles for trading code")
        previous[row["symbol"]] = row
    return frame


def summarize_listing_history(pages: list[dict]) -> dict:
    frame = normalize_listing_pages(pages)
    statuses = {page["request"]["params"]["list_status"] for page in pages}
    return {
        "status": "normalized_unverified" if frame.height else "missing",
        "rows": frame.height, "symbols": frame["symbol"].n_unique(),
        "security_identities": frame["security_id"].n_unique(),
        "missing_status_queries": [status for status in STATUSES if status not in statuses],
        "by_exchange": frame.group_by("exchange").len().sort("exchange").to_dicts(),
        "missing_listing_dates": frame["list_date"].null_count(),
        "retired_without_delisting_date": frame.filter(
            (pl.col("source_status") == "D") & pl.col("delist_date").is_null()
        ).height,
        "listed_with_future_listing_date": frame.filter(
            (pl.col("source_status") == "L") & (pl.col("list_date") > pl.col("as_of_date"))
        ).height,
        "production_published": False,
        "coverage": "listing events and observed status only; no historical tradability inference",
    }
