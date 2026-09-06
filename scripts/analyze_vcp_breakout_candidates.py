"""Build causal labels for every frozen Quants VCP breakout candidate.

This is a research dataset, not a portfolio backtest.  It keeps the legacy
detector unchanged, de-duplicates repeated daily signals for the same pivot,
and measures the path after the next tradable open.

Run from backend:
  uv run --no-sync python ../scripts/analyze_vcp_breakout_candidates.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _first_hit(values: np.ndarray, threshold: float, *, above: bool) -> int | None:
    ids = np.flatnonzero(values >= threshold if above else values <= threshold)
    return int(ids[0]) if len(ids) else None


def _wins_before(highs: np.ndarray, lows: np.ndarray, gain: float, loss: float) -> bool:
    win = _first_hit(highs, 1 + gain, above=True)
    fail = _first_hit(lows, 1 - loss, above=False)
    # Daily OHLC cannot resolve the order when both levels trade on one bar.
    return win is not None and (fail is None or win < fail)


def _hit_day(values: np.ndarray, threshold: float, *, above: bool) -> int | None:
    """Return a one-based tradable-bar hit day for research diagnostics."""
    hit = _first_hit(values, threshold, above=above)
    return hit + 1 if hit is not None else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2021, 9, 6))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2023, 12, 29))
    parser.add_argument(
        "--data-directory",
        default="research/vcp/datasets/five-year-20260904-v1",
    )
    parser.add_argument("--output-version", default="source-vcp-v2")
    parser.add_argument("--market-breadth-min", type=float, default=0.0)
    parser.add_argument("--market-breadth-max", type=float, default=1.0)
    parser.add_argument("--market-breadth-rising-days", type=int, default=0)
    parser.add_argument("--market-return-lookback", type=int, default=0)
    parser.add_argument("--market-return-min", type=float, default=0.0)
    args = parser.parse_args()

    from app.backtest.engine import BacktestEngine
    from app.backtest.matrix import valid_rolling_mean, valid_shift
    from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
    from app.config import settings
    from app.strategy.builtin._quants_vcp import (
        _swings,
        detect,
        market_breadth_allowed,
        trend_context,
    )
    from app.strategy.engine import StrategyEngine
    from app.tickflow.repository import DataStore, KlineRepository

    data_dir = settings.data_dir / args.data_directory
    output_dir = settings.data_dir / "research/vcp/candidate-labels" / args.output_version
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = json.loads((data_dir / "universe.json").read_text(encoding="utf-8"))["symbols"]
    params = {
        "trend_filter": True,
        "rs_min": 85.0,
        "distance_high_max": 0.12,
        "min_legs": 2,
        "plan_stop_pct": 0.03,
        "allow_cheat": False,
        "require_pivot_cross": False,
        "market_breadth_ma20_min": args.market_breadth_min,
        "market_breadth_ma20_max": args.market_breadth_max,
        "market_breadth_rising_days": args.market_breadth_rising_days,
        "market_equal_weight_return_lookback": args.market_return_lookback,
        "market_equal_weight_return_min": args.market_return_min,
    }
    config = StrategyBacktestConfig(
        strategy_id="quants_vcp_legacy_v1",
        symbols=symbols,
        start=args.start,
        end=args.end,
        params=params,
        overrides={
            "basic_filter": {
                "enabled": True,
                "price_min": 3.0,
                "amount_min": 20_000_000.0,
                # Zero keeps the recall set unchanged while loading the
                # point-in-time field for second-stage universe research.
                "turnover_min": 0.0,
                "exclude_st": False,
                "exclude_new_days": 0,
            },
            "max_hold_days": 40,
        },
        mode="full",
        asset_type="stock",
    )
    store = DataStore(data_dir)
    try:
        engine = BacktestEngine(KlineRepository(store))
        strategies = StrategyEngine([ROOT / "backend/app/strategy/builtin"])
        service = StrategyBacktestService(engine, strategies)
        prepared = service.prepare_matrix_optimization([config])
        market = prepared.market_data
        definition = strategies.get(config.strategy_id)
        normalized = service._normalize_params(params, definition)
        with prepared.compute_cache.activate(market):
            signals = definition.matrix_strategy.compute_signals(market, normalized)
            eligible, ranks = trend_context(market, normalized)
            valid = np.isfinite(market.close) & (market.close > 0)
            ma20 = valid_rolling_mean(
                market.close, valid, 20, bar_index=market.valid_bars
            )
            ma50 = valid_rolling_mean(
                market.close, valid, 50, bar_index=market.valid_bars
            )
            ma200 = valid_rolling_mean(
                market.close, valid, 200, bar_index=market.valid_bars
            )
            _, breadth = market_breadth_allowed(
                market.close, ma20, normalized, market.valid_bars
            )
            breadth50 = np.divide(
                ((market.close > ma50) & valid & np.isfinite(ma50)).sum(axis=1),
                (valid & np.isfinite(ma50)).sum(axis=1),
                out=np.full(market.shape[0], np.nan),
                where=(valid & np.isfinite(ma50)).sum(axis=1) > 0,
            )
            breadth200 = np.divide(
                ((market.close > ma200) & valid & np.isfinite(ma200)).sum(axis=1),
                (valid & np.isfinite(ma200)).sum(axis=1),
                out=np.full(market.shape[0], np.nan),
                where=(valid & np.isfinite(ma200)).sum(axis=1) > 0,
            )
            prior_market_close = valid_shift(
                market.close, 1, valid, bar_index=market.valid_bars
            )
            stock_returns = np.divide(
                market.close,
                prior_market_close,
                out=np.full(market.shape, np.nan),
                where=prior_market_close > 0,
            ) - 1
            return_counts = np.isfinite(stock_returns).sum(axis=1)
            equal_weight_return = np.divide(
                np.nansum(stock_returns, axis=1),
                return_counts,
                out=np.zeros(stock_returns.shape[0], dtype=float),
                where=return_counts > 0,
            )
            equal_weight_index = np.cumprod(1 + equal_weight_return)

        amount = market.fields.get("amount")
        if amount is None:
            raise RuntimeError("point-in-time amount field was not loaded")
        formal = np.fromiter(
            (str(config.start) <= label[:10] <= str(config.end) for label in market.timestamp_labels),
            dtype=bool,
            count=market.shape[0],
        )
        candidate_mask = (
            signals.entry.astype(bool)
            & formal[:, None]
            & eligible
            & (market.close >= 3.0)
            & (amount >= 20_000_000.0)
        )
        times, assets = np.nonzero(candidate_mask)
        rows: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for number, (t, asset) in enumerate(zip(times, assets, strict=True), 1):
            ids = np.flatnonzero(valid[:, asset])
            end_pos = int(np.searchsorted(ids, t, side="right"))
            hist_ids = ids[max(0, end_pos - 260) : end_pos]
            arrays = [
                np.asarray(values[hist_ids, asset], dtype=np.float64)
                for values in (market.high, market.low, market.close, market.volume)
            ]
            if not hist_ids.size or not all(np.isfinite(values).all() for values in arrays):
                continue
            dates = [market.timestamp_labels[i][:10] for i in hist_ids]
            structure = detect(*arrays, dates, normalized)
            if not structure or not structure["primary"].get("valid"):
                continue
            pattern = structure["primary"]
            if pattern.get("setup") != "breakout" or pattern.get("status") != "executable":
                continue
            key = (market.symbols[asset], str(pattern.get("pivot_date")), pattern["scale"])
            if key in seen:
                continue
            seen.add(key)
            future = ids[end_pos : end_pos + 42]
            # ``tradable`` is uint8.  Cast explicitly; otherwise NumPy treats
            # the values as positional integer indexes and repeats bar 0/1.
            future = future[market.tradable[future, asset].astype(bool)]
            if len(future) < 41:
                continue
            entry_t = int(future[0])
            entry = float(market.open[entry_t, asset])
            if not np.isfinite(entry) or entry <= 0:
                continue
            rel_high = market.high[future[:40], asset] / entry
            rel_low = market.low[future[:40], asset] / entry
            rel_close = market.close[future[:40], asset] / entry
            confirm_t = int(future[0])
            confirmed_entry_t = int(future[1])
            confirmed_entry = float(market.open[confirmed_entry_t, asset])
            confirmed_future = future[1:41]
            confirmed_high = market.high[confirmed_future, asset] / confirmed_entry
            confirmed_low = market.low[confirmed_future, asset] / confirmed_entry
            confirmed_close = market.close[confirmed_future, asset] / confirmed_entry
            confirm_range = float(market.high[confirm_t, asset] - market.low[confirm_t, asset])
            legs = pattern["legs"]
            depths = [float(leg["depth"]) for leg in legs]
            close_hist = arrays[2]
            high_hist = arrays[0]
            low_hist = arrays[1]
            volume_hist = arrays[3]
            true_ranges = (high_hist[-14:] - low_hist[-14:]) / close_hist[-14:]
            swing_points = _swings(high_hist, low_hist, close_hist)
            raw_pullbacks = []
            for left, right in pairwise(swing_points):
                if left[1] == "high" and right[1] == "low" and 0 < 1 - right[2] / left[2] < 0.45:
                    raw_pullbacks.append((dates[left[0]], dates[right[0]], left[0], right[0]))
            leg_keys = [(leg["high_date"], leg["low_date"]) for leg in legs]
            raw_positions = [
                i
                for i, item in enumerate(raw_pullbacks)
                if (item[0], item[1]) in leg_keys
            ]
            skipped_pullbacks = (
                raw_positions[-1] - raw_positions[0] + 1 - len(raw_positions)
                if len(raw_positions) == len(legs)
                else np.nan
            )
            pullbacks_after_selected = (
                len(raw_pullbacks) - raw_positions[-1] - 1
                if len(raw_positions) == len(legs)
                else np.nan
            )
            leg_volumes = []
            leg_durations = []
            for leg in legs:
                left = dates.index(leg["high_date"])
                right = dates.index(leg["low_date"])
                leg_volumes.append(float(np.mean(volume_hist[left : right + 1])))
                leg_durations.append(right - left + 1)
            first_high_pos = dates.index(legs[0]["high_date"])
            last_low_pos = dates.index(legs[-1]["low_date"])
            right_close = close_hist[last_low_pos:]
            right_returns = np.diff(right_close) / right_close[:-1]
            right_path = float(np.abs(right_returns).sum()) if len(right_returns) else 0.0
            right_net = float(close_hist[-1] / close_hist[last_low_pos] - 1)
            pre_pivot_close = close_hist[-21:-1]
            pre_pivot_volume = volume_hist[-21:-1]
            pivot_crosses = int(np.sum(pre_pivot_close >= pattern["pivot"]))
            near_pivot_days = int(np.sum(close_hist[-11:-1] >= pattern["pivot"] * 0.97))
            base_low = float(np.min(low_hist[first_high_pos:]))
            base_high = float(np.max(high_hist[first_high_pos:]))
            prior_base_pos = max(0, first_high_pos - 63)
            prior_base_close = float(close_hist[prior_base_pos])
            pre_volume = volume_hist[-51:-1]
            pre_short_volume = volume_hist[-11:-1]
            pre_dry = (
                float(np.mean(pre_short_volume) / np.mean(pre_volume))
                if len(pre_volume) >= 19 and np.mean(pre_volume) > 0
                else np.nan
            )
            prior_close = close_hist[-2]
            ma50_now = float(np.mean(close_hist[-50:]))
            ma50_prior = float(np.mean(close_hist[-70:-20])) if len(close_hist) >= 70 else np.nan
            high252 = float(np.max(high_hist[-252:-1]))
            rows.append(
                {
                    "symbol": market.symbols[asset],
                    "signal_date": market.timestamp_labels[t][:10],
                    "entry_date": market.timestamp_labels[entry_t][:10],
                    "scale": pattern["scale"],
                    "pivot_date": pattern.get("pivot_date"),
                    "pivot": pattern["pivot"],
                    "leg_count": len(legs),
                    "first_depth": depths[0],
                    "last_depth": depths[-1],
                    "last_to_first_depth": depths[-1] / depths[0],
                    "skipped_pullbacks": skipped_pullbacks,
                    "pullbacks_after_selected": pullbacks_after_selected,
                    "ends_at_latest_pullback": pullbacks_after_selected == 0,
                    "leg_volume_last_to_first": leg_volumes[-1] / leg_volumes[0],
                    "leg_volume_monotonic_share": float(
                        np.mean(np.diff(leg_volumes) <= 0) if len(leg_volumes) > 1 else 0.0
                    ),
                    "last_leg_duration_bars": leg_durations[-1],
                    "leg_duration_last_to_first": leg_durations[-1] / leg_durations[0],
                    "tightness": pattern["tightness"],
                    "dry_volume_ratio": pattern.get("dry_volume_ratio"),
                    "prebreakout_dry_volume_ratio": pre_dry,
                    "breakout_volume_ratio": pattern.get("volume_ratio"),
                    "breakout_close_location": pattern.get("close_location"),
                    "breakout_distance": pattern.get("distance"),
                    "prebreakout_distance_to_pivot": prior_close / pattern["pivot"] - 1,
                    "breakout_day_return": close_hist[-1] / prior_close - 1,
                    "signal_raw_close": float(market.fields.get("raw_close", market.close)[t, asset]),
                    "signal_amount": float(amount[t, asset]),
                    "signal_turnover_rate": float(
                        market.fields.get("turnover_rate", np.full(market.shape, np.nan))[t, asset]
                    ),
                    "rs_percentile": float(ranks[t, asset]),
                    "market_breadth_ma20": float(breadth[t]),
                    "market_breadth_ma50": float(breadth50[t]),
                    "market_breadth_ma200": float(breadth200[t]),
                    "market_breadth_change_5d": (
                        float(breadth[t] - breadth[t - 5]) if t >= 5 else np.nan
                    ),
                    "market_breadth_change_20d": (
                        float(breadth[t] - breadth[t - 20]) if t >= 20 else np.nan
                    ),
                    "market_equal_weight_return_20d": (
                        float(equal_weight_index[t] / equal_weight_index[t - 20] - 1)
                        if t >= 20
                        else np.nan
                    ),
                    "market_equal_weight_return_63d": (
                        float(equal_weight_index[t] / equal_weight_index[t - 63] - 1)
                        if t >= 63
                        else np.nan
                    ),
                    "base_days": (pd.Timestamp(dates[-1]) - pd.Timestamp(legs[0]["high_date"])).days,
                    "pivot_age_days": (
                        pd.Timestamp(dates[-1]) - pd.Timestamp(pattern["pivot_date"])
                    ).days,
                    "last_low_age_days": (
                        pd.Timestamp(dates[-1]) - pd.Timestamp(legs[-1]["low_date"])
                    ).days,
                    "last_contraction_days": (
                        pd.Timestamp(legs[-1]["low_date"])
                        - pd.Timestamp(legs[-1]["high_date"])
                    ).days,
                    "atr14_pct": float(np.mean(true_ranges)),
                    "range5_pct": float((np.max(high_hist[-5:]) - np.min(low_hist[-5:])) / close_hist[-1]),
                    "prebreakout_range5_pct": float(
                        (np.max(high_hist[-6:-1]) - np.min(low_hist[-6:-1])) / prior_close
                    ),
                    "base_depth": 1 - base_low / base_high,
                    "prior_runup_63_before_base": (
                        float(close_hist[first_high_pos] / prior_base_close - 1)
                        if prior_base_close > 0 and first_high_pos > 0
                        else np.nan
                    ),
                    "right_side_bars": len(right_close),
                    "right_side_return": right_net,
                    "right_side_efficiency": right_net / right_path if right_path > 0 else 0.0,
                    "right_side_up_day_share": float(
                        np.mean(right_returns > 0) if len(right_returns) else 0.0
                    ),
                    "prebreakout_pivot_crosses_20": pivot_crosses,
                    "prebreakout_near_pivot_days_10": near_pivot_days,
                    "prebreakout_near_pivot_volume_ratio": (
                        float(
                            np.mean(pre_pivot_volume[pre_pivot_close >= pattern["pivot"] * 0.97])
                            / np.mean(pre_volume)
                        )
                        if np.any(pre_pivot_close >= pattern["pivot"] * 0.97)
                        and np.mean(pre_volume) > 0
                        else np.nan
                    ),
                    "prebreakout_range10_pct": float(
                        (np.max(high_hist[-11:-1]) - np.min(low_hist[-11:-1])) / prior_close
                    ),
                    "prebreakout_close_cv10": float(
                        np.std(close_hist[-11:-1]) / np.mean(close_hist[-11:-1])
                    ),
                    "price_to_ma50": float(close_hist[-1] / ma50_now - 1),
                    "ma50_slope_20d": float(ma50_now / ma50_prior - 1),
                    "distance_to_252d_high": float(close_hist[-1] / high252 - 1),
                    "prior_return_20d": float(close_hist[-1] / close_hist[-21] - 1),
                    "prior_return_63d": float(close_hist[-1] / close_hist[-64] - 1),
                    "prior_return_126d": float(close_hist[-1] / close_hist[-127] - 1),
                    "gap_to_signal_close": entry / close_hist[-1] - 1,
                    "confirmation_date": market.timestamp_labels[confirm_t][:10],
                    "confirmation_close_vs_pivot": float(
                        market.close[confirm_t, asset] / pattern["pivot"] - 1
                    ),
                    "confirmation_low_vs_pivot": float(
                        market.low[confirm_t, asset] / pattern["pivot"] - 1
                    ),
                    "confirmation_close_location": (
                        float(
                            (market.close[confirm_t, asset] - market.low[confirm_t, asset])
                            / confirm_range
                        )
                        if confirm_range > 0
                        else 0.5
                    ),
                    "confirmation_return_from_signal_close": float(
                        market.close[confirm_t, asset] / close_hist[-1] - 1
                    ),
                    "confirmation_volume_to_signal": float(
                        market.volume[confirm_t, asset] / volume_hist[-1]
                    ),
                    "confirmed_entry_date": market.timestamp_labels[confirmed_entry_t][:10],
                    "confirmed_entry_gap_to_pivot": confirmed_entry / pattern["pivot"] - 1,
                    "return_5d": float(rel_close[4] - 1),
                    "return_10d": float(rel_close[9] - 1),
                    "return_20d": float(rel_close[19] - 1),
                    "return_40d": float(rel_close[min(39, len(rel_close) - 1)] - 1),
                    "mfe_5d": float(np.max(rel_high[:5]) - 1),
                    "mae_5d": float(np.min(rel_low[:5]) - 1),
                    "mfe_10d": float(np.max(rel_high[:10]) - 1),
                    "mae_10d": float(np.min(rel_low[:10]) - 1),
                    "mfe_20d": float(np.max(rel_high[:20]) - 1),
                    "mae_20d": float(np.min(rel_low[:20]) - 1),
                    "mfe_40d": float(np.max(rel_high) - 1),
                    "mae_40d": float(np.min(rel_low) - 1),
                    "target_8_before_stop_5_10": _wins_before(
                        rel_high[:10], rel_low[:10], 0.08, 0.05
                    ),
                    "target_10_before_stop_5_15": _wins_before(
                        rel_high[:15], rel_low[:15], 0.10, 0.05
                    ),
                    "true_breakout_10_7_20": _wins_before(rel_high[:20], rel_low[:20], 0.10, 0.07),
                    "target_15_before_stop_7_30": _wins_before(
                        rel_high[:30], rel_low[:30], 0.15, 0.07
                    ),
                    "true_breakout_20_7_40": _wins_before(rel_high, rel_low, 0.20, 0.07),
                    "target_30_before_stop_7_40": _wins_before(
                        rel_high, rel_low, 0.30, 0.07
                    ),
                    "target_8_hit_day": _hit_day(rel_high[:10], 1.08, above=True),
                    "target_10_hit_day": _hit_day(rel_high[:20], 1.10, above=True),
                    "target_20_hit_day": _hit_day(rel_high, 1.20, above=True),
                    "stop_5_hit_day": _hit_day(rel_low[:20], 0.95, above=False),
                    "stop_7_hit_day": _hit_day(rel_low, 0.93, above=False),
                    "confirmed_return_20d": float(confirmed_close[19] - 1),
                    "confirmed_mfe_20d": float(np.max(confirmed_high[:20]) - 1),
                    "confirmed_mae_20d": float(np.min(confirmed_low[:20]) - 1),
                    "confirmed_true_breakout_10_7_20": _wins_before(
                        confirmed_high[:20], confirmed_low[:20], 0.10, 0.07
                    ),
                }
            )
            if number % 250 == 0:
                print(json.dumps({"processed_signals": number, "deduped": len(rows)}), flush=True)
        frame = pd.DataFrame(rows).sort_values(["signal_date", "symbol"])
        frame.to_parquet(output_dir / "discovery-candidates.parquet", index=False)
        frame.to_csv(output_dir / "discovery-candidates.csv", index=False, encoding="utf-8-sig")
        report = {
            "range": [str(config.start), str(config.end)],
            "strategy_id": config.strategy_id,
            "feature_version": args.output_version,
            "params": normalized,
            "config": asdict(config),
            "raw_daily_breakout_signals": int(candidate_mask.sum()),
            "deduplicated_setups": len(frame),
            "true_breakout_10_7_20_rate": float(frame["true_breakout_10_7_20"].mean()),
            "true_breakout_20_7_40_rate": float(frame["true_breakout_20_7_40"].mean()),
            "a_share_fast_breakout_8_5_10_rate": float(
                frame["target_8_before_stop_5_10"].mean()
            ),
            "large_winner_30_7_40_rate": float(
                frame["target_30_before_stop_7_40"].mean()
            ),
            "median_return_20d": float(frame["return_20d"].median()),
            "median_mfe_20d": float(frame["mfe_20d"].median()),
            "daily_ohlc_tie_policy": "same-bar target and failure is classified as failure",
        }
        (output_dir / "discovery-summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(
            json.dumps(
                {key: value for key, value in report.items() if key != "config"},
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )
    finally:
        store.db.close()


if __name__ == "__main__":
    main()
