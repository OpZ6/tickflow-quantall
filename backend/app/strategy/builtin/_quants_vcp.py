"""Causal Quants VCP port. Pure calculations; no external project/data dependency.

Preserves multi-scale swing/contraction/pivot semantics. The optimized detector
selects the longest contracting chain from the six most recent pullbacks.
"""

from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    make_signal_matrix,
    valid_rolling_max,
    valid_rolling_mean,
    valid_shift,
)

SCALES = (("short", 15, 45), ("medium", 45, 120), ("long", 120, 260))
ENTRY_IDS = (
    "signal_quants_vcp_breakout",
    "signal_quants_vcp_cheat",
    "signal_quants_vcp_early_recovery",
    "signal_quants_vcp_broad_advance",
)
EXPANDED_ENTRY_IDS = (*ENTRY_IDS, "signal_quants_vcp_middle_expansion")
EXIT_IDS = ("signal_quants_vcp_exit_ma20",)


def _swings(high, low, close, span=2):
    points = []
    for i in range(span, len(close) - span):
        hi = (
            high[i] >= max(high[i - span : i])
            and high[i] >= max(high[i + 1 : i + span + 1])
            and high[i] > high[i - 1]
        )
        lo = (
            low[i] <= min(low[i - span : i])
            and low[i] <= min(low[i + 1 : i + span + 1])
            and low[i] < low[i - 1]
        )
        if hi == lo:
            continue
        point = (i, "high" if hi else "low", float(high[i] if hi else low[i]))
        if points and points[-1][1] == point[1]:
            if (point[2] >= points[-1][2]) if hi else (point[2] <= points[-1][2]):
                points[-1] = point
        else:
            points.append(point)
    if len(points) <= 2:
        return points
    min_move = min(0.08, max(0.022, float(np.median((high - low) / close)) * 2.4))
    filtered = []
    for point in points:
        if not filtered:
            filtered.append(point)
        elif point[1] == filtered[-1][1]:
            if (
                (point[2] >= filtered[-1][2])
                if point[1] == "high"
                else (point[2] <= filtered[-1][2])
            ):
                filtered[-1] = point
        elif point[0] - filtered[-1][0] >= 3 and abs(point[2] / filtered[-1][2] - 1) >= min_move:
            filtered.append(point)
    return filtered


def scan_window(high, low, close, volume, dates, scale, params):
    """Only already-completed bars may be supplied; all point confirmations are explicit."""
    invalid = {
        "valid": False,
        "status": "invalid",
        "reason": "invalid_structure",
        "scale": scale,
        "quality": 0.0,
        "legs": [],
        "as_of": dates[-1],
        "stage": "invalid_structure",
        "setup": "invalid",
    }
    legacy = params.get("legacy_semantics", False)
    recent_range = float((np.max(high[-10:]) - np.min(low[-10:])) / close[-1])
    if (round(recent_range, 4) if legacy else recent_range) > 0.25:
        return {
            **invalid,
            "reason": "post_surge_window_high",
            "pivot": float(np.max(high[:-1])) if legacy else None,
        }
    points = _swings(high, low, close)
    pullbacks = []
    for i in range(len(points) - 1):
        a, b = points[i : i + 2]
        depth = 1 - b[2] / a[2]
        if a[1] == "high" and b[1] == "low" and 0 < depth < 0.45:
            pullbacks.append(
                {
                    "high_date": dates[a[0]],
                    "low_date": dates[b[0]],
                    "confirmed_at": dates[b[0] + 2],
                    "high": a[2],
                    "low": b[2],
                    "depth": depth,
                }
            )
    if len(pullbacks) < 2:
        return invalid
    # Optimized Quants selects the longest strictly contracting suffix among
    # the latest six pullbacks, restarting when a candidate cannot extend it.
    recent = pullbacks[-6:]
    best = []
    ratio = float(params.get("contraction_ratio_max", 0.95))
    for start in range(len(recent)):
        sequence = [recent[start]]
        for item in recent[start + 1 :]:
            if item["depth"] <= sequence[-1]["depth"] * ratio:
                sequence.append(item)
            elif len(sequence) < 2:
                sequence = [item]
        if len(sequence) > len(best):
            best = sequence
    legs = best if len(best) >= 2 else recent[-2:]
    legs = legs[-4:]
    if len(legs) < int(params.get("min_legs", 2)):
        return {**invalid, "reason": "non_contracting_suffix"}
    depths = [leg["depth"] for leg in legs]
    improvements = [1 - depths[i + 1] / depths[i] for i in range(len(depths) - 1)]
    if legacy:
        improvements = [max(0.0, min(1.0, value)) for value in improvements]
    tightness = float(np.mean(improvements))
    tightness = min(
        1.0, tightness + (0.2 if depths[-1] <= 0.05 else 0.1 if depths[-1] <= 0.08 else 0.0)
    )
    pivot = legs[-1]["high"]
    if legacy:
        tightness = round(tightness, 4)
        pivot = round(pivot, 4)
    consistent = sum(abs(leg["high"] / pivot - 1) <= 0.04 for leg in legs) >= max(
        1, int(len(legs) * 0.5)
    )
    if legacy:
        consistent = sum(pivot * 0.96 <= leg["high"] <= pivot * 1.04 for leg in legs) >= max(
            1, int(len(legs) * 0.5)
        )
    distance = float(close[-1] / pivot - 1)
    if legacy and distance > 0.08:
        return {
            **invalid,
            "status": "extended_do_not_chase",
            "setup": "extended",
            "stage": "extended_after_breakout",
            "reason": "extended_without_base",
            "pivot": pivot,
            "stop_price": round(pivot * 0.97, 4),
            "distance": round(distance, 4),
        }
    rising = all(legs[i + 1]["low"] >= legs[i]["low"] * 0.97 for i in range(len(legs) - 1))
    if not (consistent or rising) or tightness < float(params.get("tightness_min", 0.25)):
        return {
            **invalid,
            "reason": "invalid_structure" if legacy else "insufficient_tightness",
            "pivot": pivot,
        }
    distance = float(close[-1] / pivot - 1)
    prior_volume = volume[-20:-1]
    volume_ratio = (
        float(volume[-1] / np.mean(prior_volume))
        if len(prior_volume) == 19 and np.mean(prior_volume) > 0
        else None
    )
    day_range = float(high[-1] - low[-1])
    close_location = float((close[-1] - low[-1]) / day_range) if day_range > 0 else 0.5
    # Exclude the trigger bar from dry-up evidence; a breakout must not erase its base.
    baseline = volume[max(0, len(volume) - 51) : -1]
    dry_ratio = (
        float(np.mean(volume[-11:-1]) / np.mean(baseline))
        if len(baseline) >= 19 and np.mean(baseline) > 0
        else None
    )
    if legacy:
        dry_ratio = (
            round(float(np.mean(volume[-10:]) / np.mean(volume[-50:])), 4)
            if len(volume) >= 20 and np.mean(volume[-50:]) > 0
            else None
        )
        volume_ratio = round(volume_ratio, 4) if volume_ratio is not None else None
    dry = dry_ratio is not None and dry_ratio <= float(params.get("dry_volume_ratio_max", 0.9))
    chase = float(params.get("max_chase", 0.025))
    zone_high = round(pivot * (1 + chase), 4) if legacy else pivot * (1 + chase)
    if close[-1] > zone_high:
        status, setup = "extended_do_not_chase", "extended"
    elif distance >= 0:
        status = (
            "executable"
            if volume_ratio is not None
            and volume_ratio >= float(params.get("breakout_volume_ratio_min", 1.25))
            else "wait_support"
        )
        setup = "breakout"
    elif distance >= -0.015 and tightness >= 0.65 and dry:
        status, setup = (
            ("executable" if params.get("allow_cheat", legacy) else "wait_breakout"),
            "cheat",
        )
    elif distance >= -0.035:
        status, setup = "wait_breakout", "breakout"
    else:
        status, setup = "watch", "watch"
    # Quants optimized detector treats a structurally valid contraction as
    # valid even when the latest close is below the final leg low; the latter
    # is represented by entry status/diagnostics, not a second validity gate.
    valid = distance <= 0.08
    if not valid and not legacy:
        status = "invalid"
    quality = min(
        10.0,
        min(3.0, len(legs) * 0.9)
        + min(2.2, tightness * 2.2)
        + 1.2 * consistent
        + 1.0 * rising
        + 1.2 * dry
        + 0.8 * (abs(distance) <= 0.03),
    )
    stage = (
        "extended_after_breakout"
        if distance > 0.025
        else "breakout_confirmed"
        if distance >= 0 and (volume_ratio or 0) >= 1.25
        else "breakout_watch"
        if distance >= 0
        else "tight_below_pivot"
        if distance >= -0.035
        else "contraction_2"
    )
    return {
        "valid": bool(valid),
        "status": status,
        "setup": setup,
        "reason": status
        if valid
        else "extended_without_base"
        if legacy
        else "extended_or_support_broken",
        "stage": stage,
        "scale": scale,
        "quality": (round(quality, 4) if valid else 0.0) if legacy else float(quality),
        "pivot": pivot,
        "pivot_date": legs[-1]["high_date"],
        "confirmed_at": legs[-1]["confirmed_at"],
        "as_of": dates[-1],
        "zone_low": pivot * 0.985 if setup == "cheat" else pivot,
        "zone_high": pivot if setup == "cheat" else zone_high,
        "stop_price": round(pivot * (1 - float(params.get("plan_stop_pct", 0.03))), 4)
        if legacy
        else pivot * (1 - float(params.get("plan_stop_pct", 0.03))),
        "distance": distance,
        "tightness": tightness,
        "volume_ratio": volume_ratio,
        "close_location": close_location,
        "dry_volume_ratio": dry_ratio,
        "legs": legs,
    }


def detect(high, low, close, volume, dates, params):
    candidates = []
    for scale, minimum, maximum in SCALES:
        if len(close) >= minimum:
            candidates.append(
                scan_window(
                    high[-maximum:],
                    low[-maximum:],
                    close[-maximum:],
                    volume[-maximum:],
                    dates[-maximum:],
                    scale,
                    params,
                )
            )
    if not candidates:
        if params.get("legacy_semantics"):
            return {
                "primary": {
                    "valid": False,
                    "status": "invalid",
                    "setup": "invalid",
                    "stage": "invalid_structure",
                    "reason": "history_too_short",
                    "scale": "medium",
                    "quality": 0.0,
                },
                "alternates": [],
            }
        return None
    status_rank = {
        "executable": 0,
        "wait_breakout": 1,
        "wait_support": 1,
        "watch": 2,
        "extended_do_not_chase": 3,
        "invalid": 4,
    }

    def rank(c):
        return (not c["valid"], status_rank[c["status"]])

    best_rank = min(map(rank, candidates))
    comparable = [c for c in candidates if rank(c) == best_rank]
    quality = max(c["quality"] for c in comparable)
    primary = min(
        (c for c in comparable if quality - c["quality"] <= 1.0),
        key=lambda c: (
            {"medium": 0, "short": 1, "long": 2}[c["scale"]],
            abs(c.get("distance", 99)),
            -c["quality"],
        ),
    )
    return {"primary": primary, "alternates": [c for c in candidates if c is not primary]}


def entry_allowed(pattern, previous_close, params, recent_closes=None):
    if pattern["status"] != "executable":
        return False
    if pattern["setup"] == "breakout" and pattern.get("close_location", 0.5) < float(
        params.get("breakout_close_location_min", 0.0)
    ):
        return False
    if pattern["setup"] == "breakout":
        closes = np.asarray(recent_closes if recent_closes is not None else [], dtype=float)
        max_prior_pivot_closes = int(params.get("prebreakout_pivot_closes_max", 20))
        prior_closes = closes[-21:-1]
        if (
            len(prior_closes)
            and np.count_nonzero(np.isfinite(prior_closes) & (prior_closes >= pattern["pivot"]))
            > max_prior_pivot_closes
        ):
            return False
    if pattern["setup"] != "breakout" or not params.get("require_pivot_cross", False):
        return True
    confirmation_days = max(1, int(params.get("breakout_confirmation_days", 1)))
    if confirmation_days > 1:
        closes = np.asarray(recent_closes if recent_closes is not None else [], dtype=float)
        if len(closes) <= confirmation_days:
            return False
        return bool(
            np.isfinite(closes[-confirmation_days - 1])
            and closes[-confirmation_days - 1] < pattern["pivot"]
            and np.all(np.isfinite(closes[-confirmation_days:]))
            and np.all(closes[-confirmation_days:] >= pattern["pivot"])
        )
    return bool(np.isfinite(previous_close) and previous_close < pattern["pivot"])


def market_breadth_allowed(close, ma20, params, valid_bars=None):
    """Return the same-day breadth gate used by a close signal filled next open."""
    valid = np.isfinite(close) & np.isfinite(ma20) & (close > 0)
    denominator = valid.sum(axis=1)
    breadth = np.divide(
        ((close > ma20) & valid).sum(axis=1),
        denominator,
        out=np.full(close.shape[0], np.nan),
        where=denominator > 0,
    )
    if params.get("a_share_dual_regime", False):
        prior_breadth = np.full_like(breadth, np.nan)
        prior_breadth[5:] = breadth[:-5]
        early_recovery = (
            np.isfinite(prior_breadth)
            & (breadth < 0.3)
            & (breadth > prior_breadth)
        )
        close_valid = np.isfinite(close) & (close > 0)
        prior_close = valid_shift(close, 1, close_valid, bar_index=valid_bars)
        stock_returns = np.divide(
            close,
            prior_close,
            out=np.full(close.shape, np.nan),
            where=prior_close > 0,
        ) - 1
        return_count = np.isfinite(stock_returns).sum(axis=1)
        market_daily_return = np.divide(
            np.nansum(stock_returns, axis=1),
            return_count,
            out=np.zeros(close.shape[0], dtype=float),
            where=return_count > 0,
        )
        market_index = np.cumprod(1 + market_daily_return)
        market_return_63 = np.full(close.shape[0], np.nan)
        market_return_63[63:] = market_index[63:] / market_index[:-63] - 1
        broad_advance = (
            (breadth >= 0.7)
            & np.isfinite(market_return_63)
            & (market_return_63 >= 0)
        )
        middle_expansion = (
            bool(params.get("include_middle_expansion_regime", False))
            & (breadth >= 0.3)
            & (breadth < 0.7)
            & np.isfinite(prior_breadth)
            & (breadth > prior_breadth)
            & np.isfinite(market_return_63)
            & (market_return_63 >= 0)
        )
        return early_recovery | middle_expansion | broad_advance, breadth
    lower = float(params.get("market_breadth_ma20_min", 0.0))
    upper = float(params.get("market_breadth_ma20_max", 1.0))
    allowed = np.isfinite(breadth) & (breadth >= lower) & (breadth <= upper)
    percentile_lookback = max(0, int(params.get("market_breadth_percentile_lookback", 0)))
    if percentile_lookback:
        percentile = np.full_like(breadth, np.nan)
        minimum_history = min(60, percentile_lookback)
        for t, value in enumerate(breadth):
            if not np.isfinite(value):
                continue
            history = breadth[max(0, t - percentile_lookback + 1) : t + 1]
            history = history[np.isfinite(history)]
            if len(history) >= minimum_history:
                percentile[t] = np.count_nonzero(history <= value) / len(history)
        percentile_min = float(params.get("market_breadth_percentile_min", 0.0))
        percentile_max = float(params.get("market_breadth_percentile_max", 1.0))
        allowed &= (
            np.isfinite(percentile)
            & (percentile >= percentile_min)
            & (percentile <= percentile_max)
        )
    slope_days = max(0, int(params.get("market_breadth_rising_days", 0)))
    if slope_days:
        prior = np.full_like(breadth, np.nan)
        prior[slope_days:] = breadth[:-slope_days]
        allowed &= np.isfinite(prior) & (breadth > prior)
    market_return_lookback = max(
        0, int(params.get("market_equal_weight_return_lookback", 0))
    )
    if market_return_lookback:
        close_valid = np.isfinite(close) & (close > 0)
        prior_close = valid_shift(
            close, 1, close_valid, bar_index=valid_bars
        )
        stock_returns = np.divide(
            close,
            prior_close,
            out=np.full(close.shape, np.nan),
            where=prior_close > 0,
        ) - 1
        return_count = np.isfinite(stock_returns).sum(axis=1)
        market_daily_return = np.divide(
            np.nansum(stock_returns, axis=1),
            return_count,
            out=np.zeros(close.shape[0], dtype=float),
            where=return_count > 0,
        )
        market_index = np.cumprod(1 + market_daily_return)
        market_return = np.full(close.shape[0], np.nan)
        market_return[market_return_lookback:] = (
            market_index[market_return_lookback:]
            / market_index[:-market_return_lookback]
            - 1
        )
        minimum = float(params.get("market_equal_weight_return_min", 0.0))
        allowed &= np.isfinite(market_return) & (market_return >= minimum)
    return allowed, breadth


def technical_score(pattern, rs, params):
    score = pattern["quality"] * 8 + (rs or 0) * 0.2
    if pattern.get("scale") == "short":
        score -= max(0.0, float(params.get("short_scale_score_penalty", 0.0)))
    volume_ratio = pattern.get("volume_ratio")
    if volume_ratio is not None:
        excess_volume = min(1.75, max(0.0, float(volume_ratio) - 1.25))
        score += excess_volume * float(params.get("breakout_volume_score_weight", 0.0))
    return min(100.0, score)


def apply_candidate_rankings(score, entry, weighted_fields):
    """Blend causal signal-day field percentiles into crowded-date ranking."""
    fields = [
        (values, max(0.0, float(weight)))
        for values, weight in weighted_fields
        if float(weight) > 0
    ]
    total_weight = sum(weight for _, weight in fields)
    if total_weight <= 0:
        return score
    if total_weight > 1:
        fields = [(values, weight / total_weight) for values, weight in fields]
        total_weight = 1.0
    for t in range(entry.shape[0]):
        candidates = entry[t].astype(bool)
        base = score[t].copy()
        score[t, candidates] = (1 - total_weight) * base[candidates]
        applied = np.zeros(score.shape[1], dtype=float)
        for matrix, weight in fields:
            ids = np.flatnonzero(candidates & np.isfinite(matrix[t]))
            if not len(ids):
                continue
            values = matrix[t, ids]
            ordered = np.sort(values)
            ranks = (
                np.searchsorted(ordered, values, "left")
                + np.searchsorted(ordered, values, "right")
                + 1
            ) * 50.0 / len(ids)
            score[t, ids] += weight * ranks
            applied[ids] += weight
        missing_weight = total_weight - applied[candidates]
        score[t, candidates] += missing_weight * base[candidates]
    return score


def apply_turnover_ranking(score, entry, turnover, weight):
    """Backward-compatible single-field candidate ranking helper."""
    return apply_candidate_rankings(score, entry, [(turnover, weight)])


def cross_sectional_percentile_ranks(values, valid=None):
    """Return average-tie percentile ranks for every date without future data."""
    finite = np.isfinite(values)
    if valid is not None:
        finite &= valid
    ranks = np.full(values.shape, np.nan)
    for t, row in enumerate(values):
        ids = np.flatnonzero(finite[t])
        if not len(ids):
            continue
        ordered = np.sort(row[ids])
        ranks[t, ids] = (
            np.searchsorted(ordered, row[ids], "left")
            + np.searchsorted(ordered, row[ids], "right")
            + 1
        ) * 50.0 / len(ids)
    return ranks


def market_outperformance_allowed(close, valid_bars=None):
    """Return stocks whose causal close-to-close return beat the same-day market."""
    valid = np.isfinite(close) & (close > 0)
    prior = valid_shift(close, 1, valid, bar_index=valid_bars)
    returns = np.divide(
        close, prior, out=np.full(close.shape, np.nan), where=prior > 0
    ) - 1.0
    counts = np.isfinite(returns).sum(axis=1)
    market_return = np.divide(
        np.nansum(returns, axis=1),
        counts,
        out=np.full(close.shape[0], np.nan),
        where=counts > 0,
    )
    return np.isfinite(returns) & (returns > market_return[:, None])


def trend_context(market, params, *, diagnostics=None):
    close = market.close
    valid = np.isfinite(close) & (close > 0)
    returns = []
    for period in (63, 126, 252):
        prev = valid_shift(close, period, valid, bar_index=market.valid_bars)
        returns.append(np.divide(close, prev, out=np.full(close.shape, np.nan), where=prev > 0) - 1)
    raw = 0.4 * returns[0] + 0.2 * returns[1] + 0.4 * returns[2]
    # Average-tie percentile ranks, computed independently for every date.
    ranks = np.full(close.shape, np.nan)
    for t, values in enumerate(raw):
        ids = np.flatnonzero(np.isfinite(values) & valid[t])
        if not len(ids):
            continue
        ordered = np.sort(values[ids])
        ranks[t, ids] = (
            (
                np.searchsorted(ordered, values[ids], "left")
                + np.searchsorted(ordered, values[ids], "right")
                + 1
            )
            * 50.0
            / len(ids)
        )
    mask = valid.copy()
    if diagnostics is not None:
        diagnostics["valid_close"] = valid
    if params.get("trend_filter", True):
        means = [
            valid_rolling_mean(close, valid, n, bar_index=market.valid_bars) for n in (50, 150, 200)
        ]
        high252 = valid_rolling_max(market.high, valid, 252, bar_index=market.valid_bars)
        ma_alignment = (close > means[0]) & (means[0] > means[1]) & (means[1] > means[2])
        positive_returns = np.logical_and.reduce([r > 0 for r in returns])
        near_high = close >= high252 * (1 - float(params.get("distance_high_max", 0.12)))
        mask &= ma_alignment
        mask &= positive_returns
        mask &= near_high
        if diagnostics is not None:
            diagnostics.update(
                trend_ma_alignment=ma_alignment,
                positive_returns=positive_returns,
                near_52_week_high=near_high,
            )
    if float(params.get("rs_min", 85)) > 0:
        rs_threshold = ranks >= float(params.get("rs_min", 85))
        mask &= rs_threshold
        if diagnostics is not None:
            diagnostics["rs_threshold"] = rs_threshold
    return mask, ranks


def fresh_20d_breakout_opportunity_mask(market):
    """Mark the first liquid 20-session-high breakout after a 20-bar cooldown."""
    valid = np.isfinite(market.close) & (market.close > 0)
    prior_high = valid_shift(
        valid_rolling_max(market.high, valid, 20, bar_index=market.valid_bars),
        1,
        valid,
        bar_index=market.valid_bars,
    )
    amount = market.fields.get("amount")
    if amount is None:
        raise ValueError("require_fresh_20d_breakout requires amount")
    result = np.zeros(market.shape, dtype=bool)
    for asset in range(market.shape[1]):
        ids = np.flatnonzero(valid[:, asset])
        last_kept_position = -1000
        for position, t in enumerate(ids):
            if position - last_kept_position < 20:
                continue
            if (
                np.isfinite(prior_high[t, asset])
                and market.close[t, asset] > prior_high[t, asset]
                and 3.0 <= market.close[t, asset] <= 300.0
                and np.isfinite(amount[t, asset])
                and amount[t, asset] >= 20_000_000.0
            ):
                result[t, asset] = True
                last_kept_position = position
    return result


class QuantsVcpStrategy:
    def required_fields(self):
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params):
        return 260

    def required_fields_for_params(self, params):
        fields = set()
        if params.get("require_fresh_20d_breakout", False):
            fields.add("amount")
        if (
            float(params.get("turnover_rank_weight", 0.0)) > 0
            or float(params.get("turnover_market_percentile_min", 0.0)) > 0
        ):
            fields.add("turnover_rate")
        if float(params.get("roe_rank_weight", 0.0)) > 0:
            fields.add("roe_latest")
        return frozenset(fields)

    def compute_signals(self, market: MarketDataMatrix, params):
        return self._evaluate(market, params, None)[0]

    def screen_snapshot(self, market: MarketDataMatrix, params, time_index):
        return self._evaluate(market, params, time_index)

    def screen_snapshot_with_trace(self, market, params, time_index, trace):
        return self._evaluate(market, params, time_index, trace=trace)

    def _evaluate(self, market, params, time_index, trace=None):
        trend_diagnostics = {} if trace is not None and time_index is not None else None
        eligible, ranks = trend_context(market, params, diagnostics=trend_diagnostics)
        if params.get("require_fresh_20d_breakout", False):
            fresh_breakout = fresh_20d_breakout_opportunity_mask(market)
            eligible &= fresh_breakout
            if trend_diagnostics is not None:
                trend_diagnostics["fresh_20d_breakout"] = fresh_breakout
        if params.get("require_signal_day_market_outperformance", False):
            eligible &= market_outperformance_allowed(
                market.close, market.valid_bars
            )
        if time_index is not None:
            current_universe = int(np.count_nonzero(np.isfinite(market.close[time_index])))
            ranked_universe = int(np.count_nonzero(np.isfinite(ranks[time_index])))
            minimum_ranked = max(100, int(current_universe * 0.5))
            if current_universe >= 500 and ranked_universe < minimum_ranked:
                raise ValueError(
                    "VCP 历史覆盖不足：当前股票数 "
                    f"{current_universe}，可计算 252 日 RS 的股票仅 {ranked_universe}；"
                    "请先补全至少 252 个有效交易日的全市场日 K。"
                )
        turnover_percentile_min = float(
            params.get("turnover_market_percentile_min", 0.0)
        )
        if turnover_percentile_min > 0:
            turnover_ranks = cross_sectional_percentile_ranks(
                market.field("turnover_rate"), np.isfinite(market.close)
            )
            turnover_allowed = turnover_ranks >= turnover_percentile_min
            eligible &= turnover_allowed
            if trend_diagnostics is not None:
                trend_diagnostics["turnover_percentile"] = turnover_allowed
        entry = np.zeros(market.shape, np.uint8)
        score = np.zeros(market.shape, np.float32)
        contraction_strength = np.full(market.shape, np.nan, np.float32)
        codes = np.full(market.shape, -1, np.int16)
        valid = np.isfinite(market.close)
        ma20 = valid_rolling_mean(market.close, valid, 20, bar_index=market.valid_bars)
        breadth_allowed, breadth = market_breadth_allowed(
            market.close, ma20, params, market.valid_bars
        )
        eligible &= breadth_allowed[:, None]
        detector_reasons = {}
        if trend_diagnostics is not None:
            ordered_gates = [
                ("invalid_close", trend_diagnostics.get("valid_close")),
                ("trend_ma_alignment", trend_diagnostics.get("trend_ma_alignment")),
                ("positive_returns", trend_diagnostics.get("positive_returns")),
                ("near_52_week_high", trend_diagnostics.get("near_52_week_high")),
                ("rs_threshold", trend_diagnostics.get("rs_threshold")),
                ("turnover_percentile", trend_diagnostics.get("turnover_percentile")),
                ("fresh_20d_breakout", trend_diagnostics.get("fresh_20d_breakout")),
            ]
            for asset, symbol in enumerate(market.symbols):
                reason = "market_regime"
                for gate_name, gate in ordered_gates:
                    if gate is not None and not bool(gate[time_index, asset]):
                        reason = gate_name
                        break
                else:
                    if bool(breadth_allowed[time_index]):
                        reason = "vcp_structure"
                detector_reasons[symbol] = reason
            trace.clear()
            trace.update(
                scope="vcp_snapshot_detector",
                reason_semantics="first_failed_gate",
                detector_reasons=detector_reasons,
            )
        exit_ma_days = int(params.get("exit_ma_days", 20))
        exit_ma = (
            ma20
            if exit_ma_days == 20
            else valid_rolling_mean(
                market.close, valid, exit_ma_days, bar_index=market.valid_bars
            )
        )
        prev = valid_shift(market.close, 1, valid, bar_index=market.valid_bars)
        prev_ma = valid_shift(exit_ma, 1, valid, bar_index=market.valid_bars)
        exit_ = (market.close < exit_ma) & (prev >= prev_ma)
        if params.get("disable_signal_exit", False):
            exit_ = np.zeros(market.shape, dtype=bool)
        rows = {}
        for asset, symbol in enumerate(market.symbols):
            seen_setups = set()
            ids = np.flatnonzero(valid[:, asset])
            times = (
                ids[eligible[ids, asset]]
                if time_index is None
                else [time_index]
                if eligible[time_index, asset]
                else []
            )
            for t in times:
                history_ids = ids[
                    max(0, np.searchsorted(ids, t, side="right") - 260) : np.searchsorted(
                        ids, t, side="right"
                    )
                ]
                high, low, close, volume = [
                    np.asarray(v[history_ids, asset], dtype=np.float64)
                    for v in (market.high, market.low, market.close, market.volume)
                ]
                if (
                    not len(close)
                    or not all(np.isfinite(v).all() for v in (high, low, close, volume))
                    or np.any(volume <= 0)
                    or np.any(low <= 0)
                ):
                    if trace is not None:
                        detector_reasons[symbol] = "invalid_history_window"
                    continue
                dates = [market.timestamp_labels[i][:10] for i in history_ids]
                structure = detect(high, low, close, volume, dates, params)
                if structure is None or not structure["primary"]["valid"]:
                    if trace is not None:
                        detector_reasons[symbol] = "vcp_structure"
                    continue
                p = structure["primary"]
                dual_regime = bool(params.get("a_share_dual_regime", False))
                broad_advance = dual_regime and breadth[t] >= 0.7
                middle_expansion = (
                    dual_regime
                    and bool(params.get("include_middle_expansion_regime", False))
                    and 0.3 <= breadth[t] < 0.7
                )
                if p.get("scale") == "short" and (
                    not params.get("short_scale_enabled", True)
                    or broad_advance
                    or middle_expansion
                ):
                    if trace is not None:
                        detector_reasons[symbol] = "short_scale_excluded"
                    continue
                if trace is not None:
                    detector_reasons[symbol] = "candidate"
                rs = float(ranks[t, asset]) if np.isfinite(ranks[t, asset]) else None
                # 0..100 technical score, not Quants' legacy finance/industry score.
                quality_score = technical_score(p, rs, params)
                score[t, asset] = quality_score
                leg_depths = [float(leg["depth"]) for leg in p["legs"]]
                if leg_depths and leg_depths[0] > 0:
                    contraction_strength[t, asset] = float(
                        1.0 - np.clip(leg_depths[-1] / leg_depths[0], 0.0, 1.0)
                    )
                previous_close = close[-2] if len(close) >= 2 else np.nan
                entry_params = params
                if dual_regime:
                    entry_params = {
                        **params,
                        "prebreakout_pivot_closes_max": 20 if broad_advance else 0,
                    }
                if entry_allowed(p, previous_close, entry_params, close):
                    setup_key = (str(p.get("pivot_date")), str(p.get("scale")))
                    duplicate = (
                        time_index is None
                        and bool(params.get("deduplicate_setups", False))
                        and setup_key in seen_setups
                    )
                    if not duplicate:
                        entry[t, asset] = 1
                        codes[t, asset] = (
                            4
                            if middle_expansion
                            else 3
                            if broad_advance
                            else 2
                            if dual_regime
                            else 1
                            if p["setup"] == "cheat"
                            else 0
                        )
                        if time_index is None and params.get("deduplicate_setups", False):
                            seen_setups.add(setup_key)
                if time_index is not None:
                    levels = [
                        {"role": role, "label": label, "value": p[key]}
                        for role, label, key in (
                            ("trigger", "末段收缩枢轴", "pivot"),
                            ("support", "计划失效价(非成交保证)", "stop_price"),
                            ("zone_high", "追价上限", "zone_high"),
                        )
                    ]
                    anchors = [
                        {
                            "date": leg[k],
                            "role": role,
                            "price": leg[value],
                            "confirmed_at": leg["confirmed_at"],
                        }
                        for leg in p["legs"]
                        for k, role, value in [
                            ("high_date", "contraction_high", "high"),
                            ("low_date", "contraction_low", "low"),
                        ]
                    ]
                    metrics = [
                        {"name": name, "value": value, "unit": unit, "passed": None}
                        for name, value, unit in (
                            ("vcp_tightness", p["tightness"], "ratio"),
                            ("vcp_volume_ratio", p["volume_ratio"], "ratio"),
                            ("vcp_breakout_close_location", p["close_location"], "ratio"),
                            ("vcp_dry_volume_ratio", p["dry_volume_ratio"], "ratio"),
                            ("rs_percentile", rs, "percentile"),
                            ("market_breadth_ma20", breadth[time_index], "ratio"),
                        )
                    ]
                    rows[symbol] = {
                        "vcp_status": p["status"],
                        "vcp_setup": p["setup"],
                        "vcp_pivot": p["pivot"],
                        "vcp_leg_count": len(p["legs"]),
                        "vcp_scale": p["scale"],
                        "vcp_structure": structure,
                        "vcp_rs": rs,
                        "score": quality_score,
                        "strategy_evidence": {
                            "reason_codes": [p["status"]],
                            "metrics": metrics,
                            "anchors": anchors,
                            "levels": levels,
                            "pattern_refs": [structure],
                        },
                    }
        turnover_weight = float(params.get("turnover_rank_weight", 0.0))
        roe_weight = float(params.get("roe_rank_weight", 0.0))
        contraction_weight = float(
            params.get("contraction_strength_rank_weight", 0.0)
        )
        if turnover_weight > 0 or roe_weight > 0 or contraction_weight > 0:
            weighted_fields = []
            if turnover_weight > 0:
                weighted_fields.append((market.field("turnover_rate"), turnover_weight))
            if roe_weight > 0:
                weighted_fields.append((market.field("roe_latest"), roe_weight))
            if contraction_weight > 0:
                weighted_fields.append((contraction_strength, contraction_weight))
            apply_candidate_rankings(
                score,
                entry,
                weighted_fields,
            )
        return make_signal_matrix(
            market.shape,
            entry=entry,
            exit=exit_.astype(np.uint8),
            score=score,
            entry_signal_code=codes,
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=(
                EXPANDED_ENTRY_IDS
                if params.get("include_middle_expansion_regime", False)
                else ENTRY_IDS
            ),
            exit_signal_ids=EXIT_IDS,
        ), rows


class QuantsLegacyVcpStrategy(QuantsVcpStrategy):
    """Preserve source dry-up/cheat semantics separately from the research variant."""

    def _evaluate(self, market, params, time_index, trace=None):
        return super()._evaluate(
            market, {**params, "legacy_semantics": True}, time_index, trace=trace
        )


FAILED_RETRIGGER_ENTRY_IDS = ("signal_vcp_failed_breakout_retrigger",)


def build_failed_breakout_retriggers(
    market: MarketDataMatrix,
    breakout_entry: np.ndarray,
    breakout_score: np.ndarray,
    breakout_pivot: np.ndarray,
):
    """Build causal close-time retriggers from frozen VCP breakout events."""
    entry = np.zeros(market.shape, dtype=np.uint8)
    score = np.zeros(market.shape, dtype=np.float32)
    valid = (
        np.isfinite(market.high)
        & np.isfinite(market.low)
        & np.isfinite(market.close)
        & np.isfinite(market.volume)
        & (market.low > 0)
        & (market.volume > 0)
    )
    for asset in range(market.shape[1]):
        ids = np.flatnonzero(valid[:, asset])
        pending = None
        for pos, t_value in enumerate(ids):
            t = int(t_value)
            if breakout_entry[t, asset] and np.isfinite(breakout_pivot[t, asset]):
                pivot = float(breakout_pivot[t, asset])
                # A different frozen setup supersedes an older unresolved one.
                if pending is None or round(pending["pivot"], 4) != round(pivot, 4):
                    pending = {
                        "pivot": pivot,
                        "breakout_pos": pos,
                        "failure_pos": None,
                        "score": float(breakout_score[t, asset]),
                    }
                continue
            if pending is None:
                continue
            pivot = pending["pivot"]
            failure_pos = pending["failure_pos"]
            if failure_pos is None:
                # The source detector only treats the latest eighteen bars as
                # belonging to an observed breakout episode.
                if pos - pending["breakout_pos"] > 18:
                    pending = None
                    continue
                if market.low[t, asset] < pivot * 0.975 or market.close[t, asset] < pivot * 0.992:
                    pending["failure_pos"] = pos
                continue
            bars_since_failure = pos - failure_pos
            if bars_since_failure > 30:
                pending = None
                continue
            if bars_since_failure < 3:
                continue
            recovery_start = failure_pos + 1
            window_start = max(recovery_start, pos - 5)
            window_ids = ids[window_start : pos + 1]
            if len(window_ids) < 3:
                continue
            recent_close = market.close[window_ids, asset]
            recent_high = market.high[window_ids, asset]
            recent_low = market.low[window_ids, asset]
            recent_volume = market.volume[window_ids, asset]
            latest_close = float(recent_close[-1])
            low_value = float(np.min(recent_low))
            high_value = float(np.max(recent_high))
            recent_range = high_value / low_value - 1.0
            volume_history = market.volume[ids[max(0, pos - 19) : pos + 1], asset]
            volume_avg_20 = float(np.mean(volume_history)) if len(volume_history) >= 5 else np.nan
            volume_dry = np.isfinite(volume_avg_20) and float(np.mean(recent_volume)) <= volume_avg_20 * 1.08
            near_pivot_days = int(
                np.count_nonzero(
                    (recent_close >= pivot * 0.985) & (recent_close <= pivot * 1.02)
                )
            )
            ready = (
                pivot * 0.985 <= latest_close <= pivot * 1.02
                and high_value >= pivot * 0.995
                and low_value >= pivot * 0.972
                and recent_range <= 0.07
                and volume_dry
                and near_pivot_days >= 2
            )
            if ready:
                entry[t, asset] = 1
                score[t, asset] = pending["score"]
                pending = None
    return entry, score


class VcpFailedBreakoutRetriggerStrategy:
    """Change only the entry event while retaining the frozen VCP context."""

    def __init__(self):
        self._base = QuantsLegacyVcpStrategy()

    def required_fields(self):
        return self._base.required_fields()

    def required_warmup_bars(self, params):
        return self._base.required_warmup_bars(params)

    def required_fields_for_params(self, params):
        return self._base.required_fields_for_params(params)

    def compute_signals(self, market: MarketDataMatrix, params):
        base = self._base.compute_signals(market, params)
        pivots = self._reconstruct_breakout_pivots(market, params, base.entry)
        entry, score = build_failed_breakout_retriggers(
            market, base.entry, base.score, pivots
        )
        return make_signal_matrix(
            market.shape,
            entry=entry,
            exit=base.exit,
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=base.exit_signal_code,
            entry_signal_ids=FAILED_RETRIGGER_ENTRY_IDS,
            exit_signal_ids=base.exit_signal_ids,
        )

    @staticmethod
    def _reconstruct_breakout_pivots(market, params, breakout_entry):
        pivots = np.full(market.shape, np.nan, dtype=np.float32)
        valid = np.isfinite(market.close)
        for asset in range(market.shape[1]):
            ids = np.flatnonzero(valid[:, asset])
            for t_value in np.flatnonzero(breakout_entry[:, asset]):
                t = int(t_value)
                stop = int(np.searchsorted(ids, t, side="right"))
                history_ids = ids[max(0, stop - 260) : stop]
                high, low, close, volume = [
                    np.asarray(values[history_ids, asset], dtype=np.float64)
                    for values in (market.high, market.low, market.close, market.volume)
                ]
                if not len(close) or not all(
                    np.isfinite(values).all() for values in (high, low, close, volume)
                ):
                    continue
                dates = [market.timestamp_labels[i][:10] for i in history_ids]
                structure = detect(
                    high,
                    low,
                    close,
                    volume,
                    dates,
                    {**params, "legacy_semantics": True},
                )
                if structure and structure["primary"].get("valid"):
                    pivots[t, asset] = float(structure["primary"]["pivot"])
        return pivots


PIVOT_FAILURE_EXIT_IDS = (*EXIT_IDS, "signal_vcp_pivot_failure_exit")


def build_pivot_failure_exits(market, breakout_entry, breakout_pivot, base_exit):
    """Exit next open after a completed post-breakout close loses its pivot."""
    pivot_exit = np.zeros(market.shape, dtype=np.uint8)
    valid = np.isfinite(market.close) & (market.close > 0)
    for asset in range(market.shape[1]):
        ids = np.flatnonzero(valid[:, asset])
        active = None
        for pos, t_value in enumerate(ids):
            t = int(t_value)
            if active is None and breakout_entry[t, asset] and np.isfinite(
                breakout_pivot[t, asset]
            ):
                active = {
                    "pivot": float(breakout_pivot[t, asset]),
                    "breakout_pos": pos,
                }
                continue
            if active is None:
                continue
            if pos - active["breakout_pos"] > 40:
                active = None
                continue
            if market.close[t, asset] < active["pivot"]:
                pivot_exit[t, asset] = 1
                active = None
                continue
            if base_exit[t, asset]:
                active = None
    return pivot_exit


class VcpPivotFailureExitStrategy:
    """Frozen leader entry with a thesis-level pivot-loss exit."""

    def __init__(self):
        self._base = QuantsLegacyVcpStrategy()

    def required_fields(self):
        return self._base.required_fields()

    def required_warmup_bars(self, params):
        return self._base.required_warmup_bars(params)

    def required_fields_for_params(self, params):
        return self._base.required_fields_for_params(params)

    def compute_signals(self, market: MarketDataMatrix, params):
        base = self._base.compute_signals(market, params)
        pivots = VcpFailedBreakoutRetriggerStrategy._reconstruct_breakout_pivots(
            market, params, base.entry
        )
        pivot_exit = build_pivot_failure_exits(
            market, base.entry, pivots, base.exit
        )
        exit_ = base.exit | pivot_exit
        exit_codes = np.where(
            pivot_exit,
            len(EXIT_IDS),
            np.where(base.exit, base.exit_signal_code, -1),
        ).astype(np.int16)
        return make_signal_matrix(
            market.shape,
            entry=base.entry,
            exit=exit_,
            score=base.score,
            entry_signal_code=base.entry_signal_code,
            exit_signal_code=exit_codes,
            entry_signal_ids=base.entry_signal_ids,
            exit_signal_ids=PIVOT_FAILURE_EXIT_IDS,
        )


BREAKOUT_BAR_FAILURE_EXIT_IDS = (*EXIT_IDS, "signal_vcp_breakout_bar_failure_exit")


def build_breakout_bar_failure_exits(market, breakout_entry, base_exit):
    """Exit next open after a later completed close loses the breakout-bar low."""
    failure_exit = np.zeros(market.shape, dtype=np.uint8)
    valid = np.isfinite(market.close) & np.isfinite(market.low) & (market.close > 0)
    for asset in range(market.shape[1]):
        ids = np.flatnonzero(valid[:, asset])
        active = None
        for pos, t_value in enumerate(ids):
            t = int(t_value)
            if active is None and breakout_entry[t, asset]:
                active = {
                    "breakout_low": float(market.low[t, asset]),
                    "breakout_pos": pos,
                }
                continue
            if active is None:
                continue
            if pos - active["breakout_pos"] > 40:
                active = None
                continue
            if market.close[t, asset] < active["breakout_low"]:
                failure_exit[t, asset] = 1
                active = None
                continue
            if base_exit[t, asset]:
                active = None
    return failure_exit


class VcpBreakoutBarFailureExitStrategy:
    """Frozen leader entry with completed breakout-bar-low invalidation."""

    def __init__(self):
        self._base = QuantsLegacyVcpStrategy()

    def required_fields(self):
        return self._base.required_fields()

    def required_warmup_bars(self, params):
        return self._base.required_warmup_bars(params)

    def required_fields_for_params(self, params):
        return self._base.required_fields_for_params(params)

    def compute_signals(self, market: MarketDataMatrix, params):
        base = self._base.compute_signals(market, params)
        failure_exit = build_breakout_bar_failure_exits(market, base.entry, base.exit)
        exit_ = base.exit | failure_exit
        exit_codes = np.where(
            failure_exit,
            len(EXIT_IDS),
            np.where(base.exit, base.exit_signal_code, -1),
        ).astype(np.int16)
        return make_signal_matrix(
            market.shape,
            entry=base.entry,
            exit=exit_,
            score=base.score,
            entry_signal_code=base.entry_signal_code,
            exit_signal_code=exit_codes,
            entry_signal_ids=base.entry_signal_ids,
            exit_signal_ids=BREAKOUT_BAR_FAILURE_EXIT_IDS,
        )
