from __future__ import annotations

import numpy as np

from app.backtest.matrix import MarketDataMatrix, make_signal_matrix, valid_rolling_mean


def _series(market, asset, t):
    indices = np.flatnonzero(np.isfinite(market.close[: t + 1, asset]))
    return tuple(
        values[indices, asset]
        for values in (market.open, market.high, market.low, market.close, market.volume)
    )


def _cup_detect_window(high, low, close, volume, p):
    n = len(close)
    if n < int(p.get("min_bars", 15)):
        return {"valid": False, "status": "invalid", "reason": "history_too_short"}
    left_end = max(3, int(n * 0.45))
    li = int(np.nanargmax(high[:left_end]))
    lp = float(high[li])
    if li >= n - 5 or lp <= 0:
        return {"valid": False, "status": "invalid", "reason": "invalid_cup"}
    bi = li + 1 + int(np.nanargmin(low[li + 1 :]))
    bp = float(low[bi])
    depth = (lp - bp) / lp
    if depth < float(p.get("cup_min_depth_pct", 0.12)) or depth > float(
        p.get("cup_max_depth_pct", 0.45)
    ):
        return {
            "valid": False,
            "status": "invalid",
            "reason": "cup_depth_invalid",
            "cup_depth": depth,
        }
    rim = next((i for i in range(bi + 1, n) if lp * 0.95 <= high[i] <= lp * 1.05), None)
    if rim is None:
        return {
            "valid": True,
            "status": "watch",
            "setup": "watch",
            "stage": "right_side_approach",
            "quality": 3.5,
            "pivot": round(lp, 4),
            "cup_depth": depth,
        }
    middle = high[bi + 1 : rim]
    if len(middle) and (
        np.nanmax(middle) > lp * 1.05 or np.sum(close[bi + 1 : rim] > lp * 1.03) >= 2
    ):
        return {
            "valid": False,
            "status": "invalid",
            "reason": "mid_cup_breakout_invalid",
            "pivot": lp,
        }
    after = np.flatnonzero(high[rim + 1 :] > lp * 1.05)
    if len(after):
        first = rim + 1 + int(after[0])
        if np.nanmin(low[first + 1 :]) < lp * 0.9 if first + 1 < n else False:
            return {
                "valid": False,
                "status": "invalid",
                "reason": "mid_cup_breakout_invalid",
                "pivot": lp,
            }
    pivot = round(max(lp, float(high[rim])) * (1 + float(p.get("buy_point_offset_pct", 0.001))), 4)
    distance = float(close[-1]) / pivot - 1
    prior = volume[-21:-1]
    vr = float(volume[-1] / np.nanmean(prior)) if len(prior) and np.nanmean(prior) > 0 else 0
    chase = float(p.get("breakout_max_chase_pct", 0.025))
    zone_high = round(pivot * (1 + chase), 4)
    setup = "breakout"
    if close[-1] > zone_high:
        stage, status, setup = "extended_after_breakout", "extended_do_not_chase", "extended"
    elif (
        rim + 1 < n
        and np.max(high[rim + 1 :]) >= pivot
        and np.min(low[rim + 1 :]) <= lp * 1.01
        and close[-1] >= lp
    ):
        stage, status, setup = "cup_lip_support_retest", "executable", "support"
    elif high[rim] < lp:
        if close[-1] < high[rim] * 0.98:
            stage, status = "handle_tightening", "wait_breakout"
        else:
            stage, status, setup = "right_rim_under_high", "watch", "watch"
    elif close[-1] >= pivot:
        stage, status = "right_rim_breakout_without_pullback", "executable"
    else:
        stage, status = "right_rim_pullback", "wait_breakout"
    quality = 4.0 + (1.5 if 0.18 <= depth <= 0.33 else 0) + max(0, 2 - abs(high[rim] / lp - 1) * 20)
    if stage in {"cup_lip_support_retest", "right_rim_breakout_without_pullback"}:
        quality += 1
    return {
        "valid": True,
        "status": status,
        "setup": setup,
        "stage": stage,
        "quality": round(min(10, quality), 4),
        "pivot": pivot,
        "cup_depth": depth,
        "volume_ratio": vr,
        "distance": distance,
        "stop_price": round(pivot * (1 - float(p.get("breakout_stop_pct", 0.07))), 4),
    }


def cup_detect(high, low, close, volume, p):
    """Evaluate the same trailing scale candidates as the optimized Quants detector.

    Invalid continuity candidates are intentionally preferred: Quants uses them
    as a guard against presenting a later, apparently valid rim after the cup
    continuity has already broken.
    """
    minimum_required = int(p.get("min_bars", 15))
    scales = ((minimum_required, 45), (45, 120), (120, 260), (260, 420))
    candidates = []
    for scale, (minimum, maximum) in zip(
        ("short", "medium", "long", "extended"), scales, strict=True
    ):
        if len(close) < minimum:
            continue
        start = max(0, len(close) - maximum)
        candidate = _cup_detect_window(high[start:], low[start:], close[start:], volume[start:], p)
        candidate["scale"] = scale
        if not candidate.get("valid"):
            candidate.update(
                setup="invalid",
                quality=0.0,
                stage="mid_cup_breakout_invalid"
                if candidate.get("reason") == "mid_cup_breakout_invalid"
                else "invalid_structure",
            )
        candidates.append(candidate)
    # Optimized Quants also searches the long window for an older cup whose
    # continuity broke before the accepted right rim.
    continuity_candidate = None
    if len(close) >= 60:
        hh, ll, cc = high[-260:], low[-260:], close[-260:]
        limit = int(len(hh) * 0.65)
        for left in range(5, limit):
            lp = float(hh[left])
            if lp < float(np.max(hh[max(0, left - 5) : left + 1])):
                continue
            tail = ll[left + 5 :]
            if not len(tail):
                continue
            bottom = left + 5 + int(np.argmin(tail))
            depth = (lp - float(ll[bottom])) / lp if lp > 0 else 0.0
            if depth < float(p.get("cup_min_depth_pct", 0.12)) or depth > float(
                p.get("cup_max_depth_pct", 0.45)
            ):
                continue
            rim = next(
                (i for i in range(bottom + 1, len(hh)) if lp * 0.95 <= hh[i] <= lp * 1.05), None
            )
            if rim is None or rim - left < 20:
                continue
            middle = hh[bottom + 1 : rim]
            broken = len(middle) and (
                float(np.max(middle)) > lp * 1.05
                or int(np.sum(cc[bottom + 1 : rim] > lp * 1.03)) >= 2
            )
            if not broken:
                after = np.flatnonzero(hh[rim + 1 :] > lp * 1.05)
                if len(after):
                    first = rim + 1 + int(after[0])
                    broken = first + 1 < len(ll) and float(np.min(ll[first + 1 :])) < lp * 0.9
            if broken:
                continuity_candidate = {
                    "valid": False,
                    "status": "invalid",
                    "setup": "invalid",
                    "stage": "mid_cup_breakout_invalid",
                    "quality": 0.0,
                    "scale": "long",
                    "reason": "mid_cup_breakout_invalid",
                    "pivot": round(lp, 4),
                    "alternates": candidates[:3],
                }
                break
    if continuity_candidate is not None:
        candidates.append(continuity_candidate)
    if not candidates:
        return {
            "valid": False,
            "status": "invalid",
            "setup": "invalid",
            "stage": "invalid_structure",
            "quality": 0.0,
            "scale": "medium",
            "reason": "history_too_short",
        }
    continuity = [c for c in candidates if c.get("reason") == "mid_cup_breakout_invalid"]
    if continuity:
        primary = continuity[0]
        return {**primary, "alternates": [c for c in candidates if c is not primary][:3]}
    valid = [c for c in candidates if c.get("valid")]
    if valid:
        rank = {"executable": 0, "wait_breakout": 1, "watch": 2, "extended_do_not_chase": 3}
        best_rank = min(rank.get(c.get("status"), 9) for c in valid)
        comparable = [c for c in valid if rank.get(c.get("status"), 9) == best_rank]
        best_quality = max(c.get("quality", 0) for c in comparable)
        primary = min(
            (c for c in comparable if best_quality - c.get("quality", 0) <= 1),
            key=lambda c: {"medium": 0, "short": 1, "long": 2, "extended": 3}[c["scale"]],
        )
        return {**primary, "alternates": [c for c in candidates if c is not primary]}
    primary = min(
        candidates, key=lambda c: {"medium": 0, "short": 1, "long": 2, "extended": 3}[c["scale"]]
    )
    return {**primary, "alternates": [c for c in candidates if c is not primary][:3]}


def pullback_detect(
    open_,
    high,
    low,
    close,
    volume,
    p,
    money_flow=None,
    pct_changes=None,
    ma10_values=None,
    vol_ma20_values=None,
):
    n = len(close)
    if n < 12:
        return {"valid": False, "status": "invalid", "reason": "history_too_short"}
    ma10 = float(ma10_values[-1]) if ma10_values is not None else np.nanmean(close[-10:])
    ma20v = (
        float(vol_ma20_values[-1])
        if vol_ma20_values is not None
        else (np.nanmean(volume[-20:]) if n >= 3 else 0)
    )
    if money_flow is None:
        return {"valid": False, "status": "invalid", "reason": "money_flow_missing"}
    mf = np.asarray(money_flow, dtype=float)
    if len(mf) != n or not np.isfinite(mf).all():
        return {"valid": False, "status": "invalid", "reason": "money_flow_missing"}
    mf5 = np.nansum(mf[-5:])
    if mf5 <= 0:
        return {"valid": False, "status": "invalid", "reason": "net_mf_5d_not_positive"}
    start = max(0, n - int(p.get("anchor_lookback_days", 10)) - 1)
    pct = (
        np.array(pct_changes, dtype=float, copy=True)
        if pct_changes is not None
        else np.diff(close, prepend=close[0]) / np.maximum(np.abs(np.roll(close, 1)), 1e-9)
    )
    pct[0] = 0.0
    anchors = [
        i
        for i in range(start, n - 1)
        if close[i] > 0
        and pct[i] >= float(p.get("anchor_min_pct_chg", 0.06))
        and volume[i]
        / (
            (
                vol_ma20_values[i]
                if vol_ma20_values is not None
                else np.nanmean(volume[max(0, i - 19) : i + 1])
                if i >= 2
                else np.nan
            )
            or 1
        )
        >= float(p.get("anchor_min_volume_ratio", 2.0))
        and (money_flow is None or float(mf[i]) > float(p.get("anchor_min_net_mf_amount", 1000.0)))
    ]
    if not anchors:
        return {"valid": False, "status": "invalid", "reason": "anchor_not_found"}
    ai = anchors[-1]
    days = n - 1 - ai
    if days < int(p.get("min_days_since_anchor", 2)):
        return {"valid": False, "status": "invalid", "reason": "too_close_to_anchor"}
    if days > int(p.get("max_days_since_anchor", 10)):
        return {"valid": False, "status": "invalid", "reason": "too_far_from_anchor"}
    mid = (open_[ai] + close[ai]) / 2
    va = volume[-1] / (volume[ai] or 1)
    vm = volume[-1] / (ma20v or 1)
    current_pct = float(pct[-1])
    checks = [
        (va > float(p.get("max_volume_to_anchor_ratio", 0.6)), "pullback_volume_not_dry"),
        (vm > float(p.get("max_volume_to_ma20_ratio", 1.2)), "pullback_volume_above_ma20"),
        (
            abs(current_pct) > float(p.get("max_abs_pullback_pct_chg", 0.02)),
            "pullback_price_not_tight",
        ),
        (close[-1] < mid, "lost_anchor_midline"),
        (close[-1] < ma10, "lost_ma10"),
    ]
    for bad, reason in checks:
        if bad:
            return {"valid": False, "status": "invalid", "reason": reason}
    return {
        "valid": True,
        "status": "watch",
        "setup": "low_absorb",
        "pivot": max(close[-1], mid),
        "anchor_index": ai,
        "days_since_anchor": days,
        "volume_to_anchor": va,
        "volume_to_ma20": vm,
        "net_mf_5d": mf5,
        "stop_price": mid * (1 - float(p.get("support_stop_pct", 0.06))),
    }


class LegacyPatternStrategy:
    def __init__(self, kind, entry_id=None, exit_id=None):
        self.kind = kind
        self.entry_id = entry_id or "signal_quants_legacy_entry"
        self.exit_id = exit_id or "signal_quants_legacy_exit"

    def required_fields(self):
        fields = {"open", "high", "low", "close", "volume"}
        if self.kind == "pullback":
            fields.add("net_mf_amount")
        return frozenset(fields)

    def required_warmup_bars(self, params):
        return 30 if self.kind == "pullback" else 420

    def _detect(self, market, asset, t, params):
        if not np.isfinite(market.close[t, asset]):
            return {"valid": False, "status": "invalid", "reason": "missing_current_bar"}
        o, h, low, c, v = _series(market, asset, t)
        if (
            any(not np.isfinite(values).all() for values in (o, h, low, c, v))
            or np.any(low <= 0)
            or np.any(v <= 0)
        ):
            return {"valid": False, "status": "invalid", "reason": "invalid_history"}
        indices = np.flatnonzero(np.isfinite(market.close[: t + 1, asset]))
        mf = None
        if self.kind == "pullback" and "net_mf_amount" not in market.fields:
            raise ValueError(
                "回调低吸需要真实 net_mf_amount(万元);当前行情未提供资金流,不能计算原版候选"
            )
        if self.kind == "pullback" and "net_mf_amount" in market.fields:
            mf = market.fields["net_mf_amount"][indices, asset]
        pct = (
            market.fields["pct_chg"][indices, asset]
            if self.kind == "pullback" and "pct_chg" in market.fields
            else None
        )
        ma10 = (
            market.fields["ma10"][indices, asset]
            if self.kind == "pullback" and "ma10" in market.fields
            else None
        )
        vm20 = (
            market.fields["vol_ma20"][indices, asset]
            if self.kind == "pullback" and "vol_ma20" in market.fields
            else None
        )
        return (
            pullback_detect(o, h, low, c, v, params, mf, pct, ma10, vm20)
            if self.kind == "pullback"
            else cup_detect(h, low, c, v, params)
        )

    def compute_signals(self, market: MarketDataMatrix, params):
        entry = np.zeros(market.shape, dtype=bool)
        for a in range(market.shape[1]):
            for t in range(market.shape[0]):
                d = self._detect(market, a, t, params)
                entry[t, a] = d.get("status") == "executable"
        ma = valid_rolling_mean(
            market.close, np.isfinite(market.close), 20, bar_index=market.valid_bars
        )
        return make_signal_matrix(
            market.shape,
            entry=entry,
            exit=np.isfinite(ma) & (market.close < ma),
            entry_signal_ids=(self.entry_id,),
            exit_signal_ids=(self.exit_id,),
        )

    def screen_snapshot(self, market, params, time_index):
        entry = np.zeros(market.shape, dtype=bool)
        rows = {}
        for a, symbol in enumerate(market.symbols):
            d = self._detect(market, a, time_index, params)
            if d.get("status") == "executable":
                entry[time_index, a] = True
            if d and d.get("valid"):
                rows[symbol] = {
                    "symbol": symbol,
                    "pattern_stage": d.get("stage", d.get("setup")),
                    "entry_status": d.get("status"),
                    "primary_trigger_price": d.get("pivot"),
                    "metrics": d,
                    "levels": {"pivot": d.get("pivot"), "stop_price": d.get("stop_price")},
                }
        return make_signal_matrix(
            market.shape,
            entry=entry,
            exit=np.zeros(market.shape, dtype=bool),
            entry_signal_ids=(self.entry_id,),
            exit_signal_ids=(self.exit_id,),
        ), rows
