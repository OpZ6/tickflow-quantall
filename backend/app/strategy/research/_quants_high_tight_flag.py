"""Causal matrix implementation of Quants v4 optimized high-tight flag."""

from __future__ import annotations

import numpy as np

from app.backtest.matrix import MarketDataMatrix, make_signal_matrix, valid_rolling_mean

ENTRY_IDS = ("signal_quants_high_tight_flag_breakout",)
EXIT_IDS = ("signal_quants_high_tight_flag_exit_ma20",)
SCALES = (("short", 20, 60), ("medium", 60, 120), ("long", 120, 220))


def _scan(high, low, close, volume, params):
    if len(close) < 12:
        return {"valid": False, "status": "invalid", "reason": "history_too_short"}
    start = max(8, int(len(close) * 0.58))
    pole_start = int(np.nanargmin(low[:start]))
    pole_high_i = int(np.nanargmax(high[:start]))
    if pole_high_i <= pole_start or low[pole_start] <= 0:
        return {"valid": False, "status": "invalid", "reason": "invalid_no_flagpole"}
    pole_gain = high[pole_high_i] / low[pole_start] - 1
    if pole_gain < float(params.get("pole_gain_min", 0.8)):
        return {"valid": False, "status": "invalid", "reason": "invalid_no_flagpole"}
    flag = slice(pole_high_i + 1, len(close))
    if len(close[pole_high_i + 1 :]) < 4:
        return {
            "valid": True,
            "status": "watch",
            "setup": "watch",
            "stage": "flagpole_confirmed",
            "quality": 4.5,
            "reason": "flagpole_confirmed",
            "pivot": round(float(high[pole_high_i]), 4),
            "pole_gain": float(pole_gain),
        }
    flag_high = float(
        np.nanmax(high[pole_high_i + 1 : -1] if len(close) > pole_high_i + 2 else high[flag])
    )
    flag_low = float(np.nanmin(low[flag]))
    depth = (high[pole_high_i] - flag_low) / high[pole_high_i]
    pivot = round(flag_high, 4)
    if depth > float(params.get("flag_depth_max", 0.22)):
        return {
            "valid": False,
            "status": "invalid",
            "reason": "invalid_deep_flag",
            "pivot": pivot,
            "pole_gain": float(pole_gain),
            "flag_depth": float(depth),
        }
    prior = volume[-8:-1]
    vr = (
        round(float(volume[-1] / np.nanmean(prior)), 4)
        if len(prior) and np.nanmean(prior) > 0
        else None
    )
    chase = float(params.get("max_chase", 0.025))
    distance = close[-1] / pivot - 1 if pivot > 0 else 9.0
    if close[-1] > round(pivot * (1 + chase), 4):
        status, setup = "extended_do_not_chase", "extended"
    elif distance >= 0:
        status, setup = (
            ("executable", "breakout")
            if (vr or 0) >= float(params.get("breakout_volume_ratio_min", 1.3))
            else ("wait_support", "breakout")
        )
    elif distance >= -0.04:
        status, setup = "wait_breakout", "breakout"
    else:
        status, setup = "watch", "watch"
    stage = (
        "extended_after_breakout"
        if status == "extended_do_not_chase"
        else "flag_breakout_confirmed"
        if status == "executable"
        else "flag_breakout_watch"
        if close[-1] >= pivot * 0.96
        else "flag_consolidating"
    )
    quality = round(
        min(
            10,
            3
            + min(2.5, max(0, pole_gain - 0.8) * 2)
            + max(0, 2.5 - depth * 8)
            + (1 if (vr or 0) >= 1.3 else 0),
        ),
        4,
    )
    return {
        "valid": True,
        "status": status,
        "setup": setup,
        "stage": stage,
        "quality": quality,
        "reason": status,
        "pivot": pivot,
        "pole_gain": float(pole_gain),
        "flag_depth": float(depth),
        "volume_ratio": vr,
        "distance": distance,
        "stop_price": round(pivot * (1 - float(params.get("plan_stop_pct", 0.08))), 4),
    }


def detect(high, low, close, volume, params):
    candidates = []
    for scale, minimum, maximum in SCALES:
        if scale == "short" or len(close) >= minimum:
            c = _scan(high[-maximum:], low[-maximum:], close[-maximum:], volume[-maximum:], params)
            c["scale"] = scale
            if not c.get("valid"):
                c.update(
                    setup="invalid",
                    quality=0.0,
                    stage="invalid_deep_flag"
                    if c.get("reason") == "invalid_deep_flag"
                    else "invalid_no_flagpole",
                )
            candidates.append(c)
    if not candidates:
        return None
    rank = {
        "executable": 0,
        "wait_support": 1,
        "wait_breakout": 1,
        "watch": 2,
        "extended_do_not_chase": 3,
        "invalid": 4,
    }
    best = min((not c.get("valid", False), rank.get(c["status"], 9)) for c in candidates)
    comparable = [
        c for c in candidates if (not c.get("valid", False), rank.get(c["status"], 9)) == best
    ]
    quality = max(c.get("quality", 0) for c in comparable)
    primary = min(
        (c for c in comparable if quality - c.get("quality", 0) <= 1),
        key=lambda c: {"medium": 0, "short": 1, "long": 2}[c["scale"]],
    )
    return {**primary, "alternates": [c for c in candidates if c is not primary]}


class QuantsHighTightFlagStrategy:
    def required_fields(self):
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params):
        return 220

    def _detect(self, market, asset, time_index, params):
        if not np.isfinite(market.close[time_index, asset]):
            return None
        indices = np.flatnonzero(np.isfinite(market.close[: time_index + 1, asset]))[-220:]
        values = [
            np.asarray(field[indices, asset], dtype=float)
            for field in (market.high, market.low, market.close, market.volume)
        ]
        if (
            any(not np.isfinite(value).all() for value in values)
            or np.any(values[1] <= 0)
            or np.any(values[3] <= 0)
        ):
            return None
        candidate = detect(*values, params)
        if (
            candidate
            and params.get("exclude_short_scale", False)
            and candidate.get("scale") == "short"
            and candidate.get("status") == "executable"
        ):
            # Filter the original primary; choosing an alternate changes the hypothesis.
            candidate = {**candidate, "status": "watch", "reason": "short_scale_excluded"}
        return candidate

    def compute_signals(self, market: MarketDataMatrix, params):
        entry = np.zeros(market.shape, dtype=bool)
        for asset in range(market.shape[1]):
            for t in range(market.shape[0]):
                c = self._detect(market, asset, t, params)
                entry[t, asset] = bool(c and c.get("status") == "executable")
        ma20 = valid_rolling_mean(
            market.close, np.isfinite(market.close), 20, bar_index=market.valid_bars
        )
        exit_ = np.isfinite(ma20) & (market.close < ma20)
        return make_signal_matrix(
            market.shape,
            entry=entry,
            exit=exit_,
            entry_signal_ids=ENTRY_IDS,
            exit_signal_ids=EXIT_IDS,
        )

    def screen_snapshot(self, market, params, time_index):
        entry = np.zeros(market.shape, dtype=bool)
        rows = {}
        for asset, symbol in enumerate(market.symbols):
            c = self._detect(market, asset, time_index, params)
            if c and c.get("status") == "executable":
                entry[time_index, asset] = True
            if c and c.get("valid"):
                rows[symbol] = {
                    "symbol": symbol,
                    "pattern_scale": c.get("scale"),
                    "pattern_stage": c.get("stage"),
                    "pattern_quality_score": c.get("quality"),
                    "entry_setup_type": c.get("setup"),
                    "entry_status": c.get("status"),
                    "primary_trigger_price": c.get("pivot"),
                    "metrics": c,
                    "levels": {"pivot": c.get("pivot"), "stop_price": c.get("stop_price")},
                }
        return make_signal_matrix(
            market.shape,
            entry=entry,
            exit=np.zeros(market.shape, dtype=bool),
            entry_signal_ids=ENTRY_IDS,
            exit_signal_ids=EXIT_IDS,
        ), rows
