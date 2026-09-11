"""Build security-history batches explicitly, outside the daily source pipeline."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from app.market_facts.builders import FactBatch, FactValidationError
from app.market_facts.registry import DatasetId, get_dataset
from app.quantx_data.security_listing_history import normalize_listing_pages
from app.quantx_data.security_name_history import normalize_name_pages

NAME_STATE_SCHEMA = {
    "symbol": pl.String, "name": pl.String, "is_st_name": pl.Boolean,
    "knowledge_basis": pl.String, "reason": pl.String,
}
ELIGIBILITY_SCHEMA = {
    "symbol": pl.String,
    "security_id": pl.String,
    "eligibility": pl.String,
    "reasons": pl.List(pl.String),
    "listing_trade_days": pl.Int64,
    "listing_trade_days_lower_bound": pl.Int64,
    "listing_age_basis": pl.String,
    "is_st_name": pl.Boolean,
}


def listing_trade_days(
    calendar: pl.DataFrame, *, exchange: str, listed_on: date | None, day: date,
) -> int | None:
    """Count exchange open days inclusively; listing day is day one.

    Callers must resolve the security identity, listing-date availability and
    calendar vintage before calling. This arithmetic helper does not certify
    PIT knowledge or tradability. Missing closed days also invalidate coverage;
    neither observed bars nor calendar-day subtraction can replace a calendar.
    Excluding the first N trading days means accepting age > N, not age >= N.
    """
    if listed_on is None or day < listed_on:
        return None
    window = calendar.filter(
        (pl.col("exchange") == exchange)
        & pl.col("trade_date").is_between(listed_on, day, closed="both")
    ).sort("trade_date")
    if window["trade_date"].n_unique() != window.height:
        raise ValueError("duplicate calendar dates; resolve snapshot versions first")
    if window.height != (day - listed_on).days + 1 or window["is_open"].null_count():
        return None
    if not window["is_open"][0]:
        return None
    return int(window["is_open"].sum())


def _listing_trade_day_evidence(
    calendar: pl.DataFrame, *, exchange: str, listed_on: date, day: date,
) -> tuple[int | None, int | None]:
    """Return exact age when covered, otherwise a verified open-day lower bound."""
    observed = calendar.filter(
        (pl.col("exchange") == exchange) & (pl.col("trade_date") <= day)
    ).sort("trade_date")
    if observed.is_empty() or observed["is_open"].null_count():
        return None, None
    if observed["trade_date"].n_unique() != observed.height:
        raise ValueError("duplicate calendar dates; resolve snapshot versions first")
    coverage_start = observed["trade_date"][0]
    if observed.height != (day - coverage_start).days + 1:
        return None, None
    if listed_on >= coverage_start:
        exact = listing_trade_days(
            calendar,
            exchange=exchange,
            listed_on=listed_on,
            day=day,
        )
        return exact, exact
    return None, int(observed["is_open"].sum())


def resolve_security_names(
    frame: pl.DataFrame, symbols: list[str], *, cutoff: datetime,
    allow_reconstructed: bool = False,
) -> pl.DataFrame:
    """Resolve known names only; never interpret missing names as non-ST.

    Default mode requires both observation and ingestion before the cutoff.
    Reconstruction relaxes that collection constraint, not the announcement,
    effective interval or observed coverage constraints. Neither mode certifies
    official ST status, listing eligibility or execution feasibility.
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must have a timezone")
    day = cutoff.astimezone(ZoneInfo("Asia/Shanghai")).date()
    active = frame.filter(
        pl.col("symbol").is_in(symbols)
        & (pl.col("valid_from") <= day)
        & (pl.col("valid_to_exclusive").is_null() | (pl.col("valid_to_exclusive") > day))
    )
    if active["symbol"].n_unique() != active.height:
        raise FactValidationError("multiple active name intervals for one security")
    indexed = {row["symbol"]: row for row in active.iter_rows(named=True)}
    result = []
    for symbol in dict.fromkeys(symbols):
        row = indexed.get(symbol)
        reason = "no_name_interval"
        if row is not None:
            reason = ""
            if row["coverage_until"] < day:
                reason = "beyond_observed_coverage"
            elif row["available_from"] is None:
                reason = "announcement_unknown"
            elif row["available_from"] > day:
                reason = "announcement_not_available"
            elif not allow_reconstructed:
                for field in ("observed_at", "ingested_at"):
                    timestamp = datetime.fromisoformat(row[field])
                    if timestamp.tzinfo is None:
                        raise FactValidationError("fact timestamps must have timezones")
                    if timestamp > cutoff:
                        reason = "not_recorded_by_cutoff"
                        break
        known = not reason
        result.append({
            "symbol": symbol, "name": row["name"] if known else None,
            "is_st_name": row["is_st_name"] if known else None,
            "knowledge_basis": ("reconstructed" if allow_reconstructed else "recorded") if known else "unknown",
            "reason": reason or "available",
        })
    return pl.DataFrame(result, schema=NAME_STATE_SCHEMA)


def resolve_daily_security_eligibility(
    listings: pl.DataFrame,
    name_states: pl.DataFrame,
    calendar: pl.DataFrame,
    symbols: list[str],
    *,
    day: date,
    exclude_new_days: int = 0,
    exclude_st: bool = True,
) -> pl.DataFrame:
    """Classify a research universe without treating missing facts as eligible.

    ``listings`` must be a complete, explicitly selected listing snapshot and
    ``name_states`` must already be resolved for ``day`` with the intended
    recorded/reconstructed cutoff. Delisting dates are treated as inclusive.
    This classifies universe membership only; it does not infer suspension or
    order execution feasibility from missing price bars.
    """
    if exclude_new_days < 0:
        raise ValueError("exclude_new_days must be non-negative")
    requested = list(dict.fromkeys(symbols))
    if not requested:
        return pl.DataFrame(schema=ELIGIBILITY_SCHEMA)
    listing_columns = {
        "symbol", "security_id", "exchange", "list_date", "delist_date",
        "source_status",
    }
    missing_listing = listing_columns - set(listings.columns)
    if missing_listing:
        raise FactValidationError(
            f"listing snapshot missing columns: {sorted(missing_listing)}"
        )
    name_columns = {"symbol", "is_st_name", "reason"}
    missing_names = name_columns - set(name_states.columns)
    if missing_names:
        raise FactValidationError(f"name states missing columns: {sorted(missing_names)}")
    if name_states["symbol"].n_unique() != name_states.height:
        raise FactValidationError("multiple name states for one security")
    names = {row["symbol"]: row for row in name_states.iter_rows(named=True)}
    result = []
    for symbol in requested:
        lifecycles = listings.filter(pl.col("symbol") == symbol)
        active = lifecycles.filter(
            pl.col("list_date").is_not_null()
            & (pl.col("list_date") <= day)
            & (pl.col("delist_date").is_null() | (pl.col("delist_date") >= day))
        )
        if active.height > 1:
            raise FactValidationError(f"multiple active listing lifecycles: {symbol}")

        reasons: list[str] = []
        unknown: list[str] = []
        age = None
        age_lower_bound = None
        age_basis = "not_required" if exclude_new_days == 0 else "unknown"
        security_id = None
        if lifecycles.is_empty():
            unknown.append("missing_listing_identity")
        elif active.is_empty():
            if lifecycles["list_date"].null_count() or (
                lifecycles.filter(pl.col("source_status") == "D")["delist_date"].null_count()
            ):
                unknown.append("incomplete_listing_lifecycle")
            else:
                reasons.append("outside_listing_lifecycle")
        else:
            listing = active.row(0, named=True)
            security_id = listing["security_id"]
            if exclude_new_days > 0:
                age, age_lower_bound = _listing_trade_day_evidence(
                    calendar,
                    exchange=listing["exchange"],
                    listed_on=listing["list_date"],
                    day=day,
                )
                if age is not None:
                    age_basis = "exact"
                elif age_lower_bound is not None:
                    age_basis = "lower_bound"
                if age is not None and age <= exclude_new_days:
                    reasons.append("new_listing")
                elif age is None and (
                    age_lower_bound is None or age_lower_bound <= exclude_new_days
                ):
                    unknown.append("unknown_listing_trade_days")

        name_state = names.get(symbol)
        is_st_name = None if name_state is None else name_state.get("is_st_name")
        if exclude_st:
            if name_state is None or is_st_name is None:
                detail = "missing" if name_state is None else name_state.get("reason", "unknown")
                unknown.append(f"unknown_name_state:{detail}")
            elif is_st_name:
                reasons.append("st_name")

        eligibility = "ineligible" if reasons else "unknown" if unknown else "eligible"
        result.append({
            "symbol": symbol,
            "security_id": security_id,
            "eligibility": eligibility,
            "reasons": [*reasons, *unknown],
            "listing_trade_days": age,
            "listing_trade_days_lower_bound": age_lower_bound,
            "listing_age_basis": age_basis,
            "is_st_name": is_st_name,
        })
    return pl.DataFrame(result, schema=ELIGIBILITY_SCHEMA)


def build_security_history_batch(
    endpoint: str, pages: list[dict], *, snapshot_date: date, run_id: str,
) -> FactBatch:
    """Build a structural fact batch; this does not certify universe coverage.

    Missing source groups/intervals remain absent. Consumers must validate source
    manifests before deriving a complete universe. Never backdate an observation
    snapshot to the historical event date.
    """
    if not run_id.strip():
        raise FactValidationError("run_id required")
    if endpoint == "stock_basic":
        dataset_id = DatasetId.SECURITY_LISTING_HISTORY
        frame = normalize_listing_pages(pages)
    elif endpoint == "namechange":
        dataset_id = DatasetId.SECURITY_NAME_HISTORY
        frame = normalize_name_pages(pages)
    else:
        raise FactValidationError("unsupported security history endpoint")
    if frame.is_empty():
        raise FactValidationError("empty security history cannot replace a published snapshot")
    observations = [
        datetime.fromisoformat(page["scraped_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date()
        for page in pages
    ]
    if snapshot_date != max(observations):
        raise FactValidationError("snapshot_date must equal latest source observation date")
    spec = get_dataset(dataset_id)
    frame = frame.with_columns(
        pl.lit(snapshot_date).alias("as_of_date"),
        pl.lit(datetime.now(UTC).isoformat()).alias("ingested_at"),
        pl.lit(run_id).alias("run_id"),
        pl.lit(spec.schema_version, dtype=pl.UInt32).alias("schema_version"),
        pl.lit(False).alias("is_fallback"),
    )
    if "source_record_id" not in frame.columns:
        frame = frame.with_columns(pl.col("source_symbol").alias("source_record_id"))
    frame = frame.select(list(spec.storage_schema)).cast(dict(spec.storage_schema), strict=True)
    if frame.select(list(spec.primary_key)).n_unique() != frame.height:
        raise FactValidationError("duplicate security fact key")
    return FactBatch(dataset_id, snapshot_date, frame)
