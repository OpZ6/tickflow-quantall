"""Builtin strategy catalog origin: upstream Tick Stock Panel vs this repo."""

# Original Polars screeners shipped with Tick Stock Panel (docs/strategy.md 的 25 个).
UPSTREAM_BUILTIN_IDS = frozenset({
    "active_limit_gene",
    "boll_breakout",
    "breakout_new_high_60d",
    "broken_board_recovery",
    "bullish_alignment",
    "consecutive_limit_ups",
    "high_turnover_surge",
    "limit_up_momentum",
    "long_lower_shadow_reversal",
    "low_volatility_leader",
    "ma_convergence_breakout",
    "ma_golden_cross",
    "macd_below_zero_revival",
    "macd_golden",
    "n_day_low_reversal",
    "near_limit_up",
    "oversold_bounce",
    "oversold_reversal",
    "platform_consolidation_breakout",
    "pullback_ma20_bounce",
    "pullback_to_support",
    "rsi_midline_pullback",
    "strong_open",
    "trend_breakout",
    "volume_price_surge",
})

CATALOG_PROJECT = "project"
CATALOG_LABELS = {
    CATALOG_PROJECT: "右侧",
}


def catalog_origin(strategy_id: str, source: str | None = None) -> str | None:
    """Return origin for extra project strategies; None keeps upstream `source=builtin`."""
    if source not in (None, "builtin"):
        return None
    if strategy_id in UPSTREAM_BUILTIN_IDS:
        return None
    return CATALOG_PROJECT


def catalog_label_for(origin: str | None) -> str | None:
    if origin != CATALOG_PROJECT:
        return None
    return CATALOG_LABELS[CATALOG_PROJECT]
