#!/usr/bin/env python3
"""Build and evaluate blind candidates from an independent causal VCP state machine."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from build_vcp_blind_casebook import OUTPUT as FIRST_PACKET
from build_vcp_blind_casebook import PAGE_SIZE, _draw_case, _font
from build_vcp_classic_structure_blind_casebook import OUTPUT as SECOND_PACKET
from build_vcp_supply_wave_v3_blind_casebook import OUTPUT as THIRD_PACKET
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/research/vcp/casebooks/independent-state-machine-v3-blind"
ANALYSIS_OUTPUT = ROOT / "data/research/vcp/analysis/independent-state-machine-v3-semantic-v1.json"
YEARS = tuple(range(2018, 2026))
PER_STATUS_PER_YEAR = 2


def _mean_down_volume(close: np.ndarray, volume: np.ndarray, start: int, trough: int) -> float | None:
    segment_close = close[start : trough + 1]
    segment_volume = volume[start : trough + 1]
    if len(segment_close) < 2:
        return None
    down = np.r_[False, np.diff(segment_close) < 0]
    values = segment_volume[down]
    return float(np.mean(values)) if len(values) else None


def represent_independent_vcp(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    dates: np.ndarray,
) -> dict[str, Any]:
    """Return the fixed v3 state-machine representation through one signal close."""
    high, low, close, volume = [np.asarray(values, dtype=float) for values in (high, low, close, volume)]
    dates = np.asarray(dates)
    if len(close) < 130 or any(len(values) != len(close) for values in (high, low, volume, dates)):
        return {"supported": False, "reason": "history_too_short", "waves": []}
    if any(not np.all(np.isfinite(values)) for values in (high, low, close, volume)) or np.any(low <= 0) or np.any(volume <= 0):
        return {"supported": False, "reason": "invalid_input", "waves": []}

    pattern_high, pattern_low, pattern_close, pattern_volume = high[:-1], low[:-1], close[:-1], volume[:-1]
    search_start = len(pattern_close) - 120
    pivot_local = int(np.argmax(pattern_high[search_start:-10]))
    pivot_index = search_start + pivot_local
    pivot = float(pattern_high[pivot_index])
    prior_start = max(0, pivot_index - 63)
    prior_low_local = int(np.argmin(pattern_low[prior_start : pivot_index + 1]))
    prior_low_index = prior_start + prior_low_local
    prior_advance = pivot / float(pattern_low[prior_low_index]) - 1.0
    if prior_advance < 0.30 or pivot_index - prior_low_index < 20:
        return {"supported": False, "reason": "no_orderly_prior_advance", "waves": [], "pivot": pivot,
                "pivot_date": str(dates[pivot_index])}

    base_low = float(np.min(pattern_low[pivot_index:]))
    if 1.0 - base_low / pivot > 0.35:
        return {"supported": False, "reason": "base_too_deep", "waves": [], "pivot": pivot,
                "pivot_date": str(dates[pivot_index])}
    normalized_range = (pattern_high[pivot_index:] - pattern_low[pivot_index:]) / pattern_close[pivot_index:]
    reversal = min(0.12, max(0.03, 2.0 * float(np.median(normalized_range))))

    waves: list[dict[str, Any]] = []
    state = "falling"
    peak_index, peak = pivot_index, pivot
    trough_index, trough = pivot_index, pivot
    for index in range(pivot_index + 1, len(pattern_close)):
        if state == "falling":
            if pattern_low[index] < trough:
                trough_index, trough = index, float(pattern_low[index])
            if pattern_high[index] >= trough * (1.0 + reversal):
                depth = 1.0 - trough / peak
                down_volume = _mean_down_volume(pattern_close, pattern_volume, peak_index, trough_index)
                if depth > 0 and down_volume is not None:
                    waves.append(
                        {"peak_index": peak_index, "trough_index": trough_index, "recovery_index": index,
                         "peak_date": str(dates[peak_index]), "trough_date": str(dates[trough_index]),
                         "confirmed_at": str(dates[index]), "peak": peak, "trough": trough,
                         "depth": float(depth), "mean_down_volume": down_volume}
                    )
                state = "rising"
                peak_index, peak = index, float(pattern_high[index])
        else:
            if pattern_high[index] > peak:
                peak_index, peak = index, float(pattern_high[index])
            if pattern_low[index] <= peak * (1.0 - reversal):
                state = "falling"
                trough_index, trough = index, float(pattern_low[index])

    if len(waves) < 2:
        return {"supported": False, "reason": "fewer_than_two_completed_waves", "waves": waves,
                "pivot": pivot, "pivot_date": str(dates[pivot_index]), "reversal": reversal}
    first, final = waves[-2:]
    checks = {
        "contracting_depth": final["depth"] < first["depth"],
        "contracting_down_volume": final["mean_down_volume"] < first["mean_down_volume"],
        "pivot_integrity": bool(np.all(pattern_close[pivot_index + 1 :] <= pivot)),
        "right_edge": bool(pattern_close[-1] >= (pivot + final["trough"]) / 2.0),
        "first_close_breakout": bool(close[-2] <= pivot < close[-1]),
        "breakout_close_location": bool((close[-1] - low[-1]) >= (high[-1] - low[-1]) / 2.0),
        "breakout_volume": bool(volume[-1] > np.median(pattern_volume[-20:])),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "supported": not failed,
        "reason": "supported" if not failed else "+".join(failed),
        "pivot": pivot,
        "pivot_date": str(dates[pivot_index]),
        "prior_advance": prior_advance,
        "base_depth": 1.0 - base_low / pivot,
        "reversal": reversal,
        "waves": [first, final],
        "checks": checks,
    }


def _excluded_cases() -> set[tuple[str, str]]:
    files = (FIRST_PACKET / "outcomes.json", SECOND_PACKET / "sealed.json", THIRD_PACKET / "sealed.json")
    rows = [row for path in files for row in json.loads(path.read_text(encoding="utf-8"))]
    return {(row["symbol"], row["signal_date"]) for row in rows}


def _selection_hash(symbol: str, signal_date: str, supported: bool) -> str:
    return hashlib.sha256(f"{symbol}|{signal_date}|{supported}".encode()).hexdigest()


def _case_bars(market, asset: int, signal_t: int) -> pl.DataFrame:
    ids = np.flatnonzero(np.isfinite(market.close[:, asset]))
    end = int(np.searchsorted(ids, signal_t, side="right"))
    chosen = ids[max(0, end - 160) : end]
    return pl.DataFrame(
        {"date": [market.timestamp_labels[t][:10] for t in chosen], "open": market.open[chosen, asset],
         "high": market.high[chosen, asset], "low": market.low[chosen, asset],
         "close": market.close[chosen, asset], "volume": market.volume[chosen, asset]}
    ).with_columns(pl.col("date").str.to_date())


def build() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.backtest.matrix import (
        load_market_data_matrix_from_parquet,
        valid_rolling_max,
        valid_shift,
    )
    from app.strategy.builtin._quants_vcp import trend_context

    market = load_market_data_matrix_from_parquet(
        ROOT / "data/kline_daily_enriched", date(2017, 1, 1), date(2025, 12, 31), field_columns=set()
    )
    valid = np.isfinite(market.close) & (market.close > 0)
    eligible, _ = trend_context(market, {"trend_filter": True, "rs_min": 85.0, "distance_high_max": 0.12})
    rolling_high = valid_rolling_max(market.high, valid, 120, bar_index=market.valid_bars)
    prior_high = valid_shift(rolling_high, 1, valid, bar_index=market.valid_bars)
    breakout = eligible & np.isfinite(prior_high) & (market.close > prior_high)
    formal = np.fromiter((2018 <= int(label[:4]) <= 2025 for label in market.timestamp_labels), bool, market.shape[0])
    sh_sz = np.fromiter((symbol.endswith((".SH", ".SZ")) for symbol in market.symbols), bool, market.shape[1])
    times, assets = np.nonzero(breakout & formal[:, None] & sh_sz[None, :])
    excluded = _excluded_cases()
    represented, seen = [], set()
    for signal_t, asset in zip(times, assets, strict=True):
        signal_date = market.timestamp_labels[signal_t][:10]
        symbol = market.symbols[asset]
        if (symbol, signal_date) in excluded:
            continue
        bars = _case_bars(market, asset, signal_t)
        if bars.height < 130:
            continue
        representation = represent_independent_vcp(
            bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy(),
            bars["volume"].to_numpy(), bars["date"].to_numpy()
        )
        pivot_date = representation.get("pivot_date")
        setup_key = (symbol, pivot_date)
        if setup_key in seen:
            continue
        seen.add(setup_key)
        supported = representation["supported"]
        represented.append({"symbol": symbol, "signal_date": signal_date, "signal_t": int(signal_t),
                            "asset": int(asset), "representation": representation,
                            "selection_hash": _selection_hash(symbol, signal_date, supported)})

    selected, availability, shortages = [], {}, []
    for year in YEARS:
        availability[str(year)] = {}
        for supported in (True, False):
            status = "supported" if supported else "unsupported"
            group = [row for row in represented if row["signal_date"].startswith(str(year))
                     and row["representation"]["supported"] is supported]
            group.sort(key=lambda row: row["selection_hash"])
            availability[str(year)][status] = len(group)
            if len(group) < PER_STATUS_PER_YEAR:
                shortages.append({"year": year, "status": status, "available": len(group)})
            else:
                selected.extend(group[:PER_STATUS_PER_YEAR])
    if shortages:
        print(json.dumps({"decision": "insufficient_blind_packet_coverage", "trend_breakout_events": len(represented),
                          "availability": availability, "shortages": shortages}, ensure_ascii=False, indent=2))
        return 2
    selected.sort(key=lambda row: (row["signal_date"][:4], row["selection_hash"]))

    OUTPUT.mkdir(parents=True, exist_ok=False)
    manifest, sealed, labels = [], [], []
    for offset in range(0, len(selected), 6):
        page = offset // 6 + 1
        image = Image.new("RGB", PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        draw.text((55, 20), "Independent VCP v3 blind validation - status, identity and date hidden", fill="#111827", font=_font(30))
        draw.text((55, 58), "black: completed signal day | no forward-v2 candidate input", fill="#374151", font=_font(18))
        for local_index, row in enumerate(selected[offset : offset + 6]):
            case_id = f"I{offset + local_index + 1:02d}"
            bars = _case_bars(market, row["asset"], row["signal_t"])
            draw_row = {"bars": bars, "scale": "v3"}
            column, panel_row = local_index % 2, local_index // 2
            panel_left, panel_top = 55 + column * 1165, 105 + panel_row * 605
            _draw_case(draw, (panel_left, panel_top, panel_left + 1125, panel_top + 575), case_id, draw_row, show_structure=False)
            manifest.append({"case_id": case_id, "visible_bars": bars.height, "page": f"page-{page}.png",
                             "panel": local_index + 1, "selection_hash": row["selection_hash"]})
            sealed.append({"case_id": case_id, "symbol": row["symbol"], "signal_date": row["signal_date"],
                           "representation": row["representation"]})
            labels.append({"case_id": case_id, "classification": None, "confidence": None,
                           "present": [], "missing_or_contrary": [], "note": None})
        image.save(OUTPUT / f"page-{page}.png")
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUTPUT / "sealed.json").write_text(json.dumps(sealed, indent=2), encoding="utf-8")
    (OUTPUT / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "trend_breakout_events": len(represented), "cases": len(selected),
                      "pages": (len(selected) + 5) // 6, "availability": availability,
                      "sealed_opened": False}, ensure_ascii=False, indent=2))
    return 0


def analyze() -> int:
    freeze = json.loads((OUTPUT / "label-freeze.json").read_text(encoding="utf-8"))
    labels_path = OUTPUT / freeze["labels_file"]
    actual_hash = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    if actual_hash != freeze["labels_sha256"]:
        raise RuntimeError("reviewed labels changed after freeze")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    sealed = json.loads((OUTPUT / "sealed.json").read_text(encoding="utf-8"))
    label_ids = [row["case_id"] for row in labels]
    sealed_ids = [row["case_id"] for row in sealed]
    if len(labels) != freeze["cases"] or len(label_ids) != len(set(label_ids)):
        raise RuntimeError("reviewed label count or case IDs do not match the freeze")
    if set(label_ids) != set(sealed_ids):
        raise RuntimeError("reviewed and sealed case IDs differ")
    if Counter(row["classification"] for row in labels) != freeze["classification_counts"]:
        raise RuntimeError("reviewed classification counts do not match the freeze")
    sealed_by_id = {row["case_id"]: row for row in sealed}
    joined = [{**label, **sealed_by_id[label["case_id"]]} for label in labels]
    supported = [row for row in joined if row["representation"]["supported"]]
    unsupported = [row for row in joined if not row["representation"]["supported"]]

    def summary(rows: list[dict]) -> dict:
        accepted = sum(row["classification"] in {"classic", "partial"} for row in rows)
        return {"cases": len(rows), "classic": sum(row["classification"] == "classic" for row in rows),
                "partial": sum(row["classification"] == "partial" for row in rows),
                "nonclassic": sum(row["classification"] == "nonclassic" for row in rows),
                "classic_or_partial_rate": accepted / len(rows), "nonclassic_rate": 1.0 - accepted / len(rows)}

    supported_summary, unsupported_summary = summary(supported), summary(unsupported)
    gap = supported_summary["classic_or_partial_rate"] - unsupported_summary["classic_or_partial_rate"]
    gates = {"supported_classic_or_partial_rate_min_0_75": supported_summary["classic_or_partial_rate"] >= 0.75,
             "supported_nonclassic_rate_max_0_25": supported_summary["nonclassic_rate"] <= 0.25,
             "supported_minus_unsupported_classic_or_partial_min_0_30": gap >= 0.30}
    result = {"experiment": "independent-state-machine-v3-semantic-v1", "label_freeze_verified": True,
              "labels_sha256": actual_hash, "cases": len(joined), "supported": supported_summary,
              "unsupported": unsupported_summary, "supported_minus_unsupported_classic_or_partial": gap,
              "semantic_gates": gates, "all_semantic_gates_passed": all(gates.values()),
              "decision": "register_v3_for_time_split" if all(gates.values()) else "stop_without_variants"}
    ANALYSIS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "analyze"))
    args = parser.parse_args()
    return build() if args.action == "build" else analyze()


if __name__ == "__main__":
    raise SystemExit(main())
