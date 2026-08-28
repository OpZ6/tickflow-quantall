"""Explicit historical fact gaps that must never be silently backfilled."""
from __future__ import annotations

ACCEPTED_HISTORICAL_GAPS: dict[tuple[str, str], str] = {
    (
        "2026-06-25",
        "theme_member_daily",
    ): "published pywencai snapshot reports the limit-up count but contains no stock membership rows",
    (
        "2026-06-25",
        "screening_candidate_daily",
    ): "published source evidence contains no rule-candidate rows; an empty partition preserves that fact",
    (
        "2026-07-10",
        "sector_breadth_daily",
    ): "no same-day legulegu breadth payload or sidecar exists in the retained source evidence",
}
