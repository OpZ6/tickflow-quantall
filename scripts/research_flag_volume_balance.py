"""Frozen high-tight-flag selection experiment with exact detector prechecks."""
import json
import sys
from dataclasses import replace
from datetime import date
from io import BytesIO
from pathlib import Path
from types import ModuleType
from zipfile import ZipFile

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from extract_vcp_entry_structure import _defaults  # noqa: E402
from research_vcp_volume_selection import evaluate_selection  # noqa: E402

from app.backtest.matrix import _limit_lock_matrices, build_market_data_matrix  # noqa: E402
from app.strategy.builtin._quants_high_tight_flag import SCALES  # noqa: E402


def possible_poles(high, low, minimum_gain=.8):
    """A necessary condition only; the unchanged detector makes every decision."""
    high, low = np.asarray(high, dtype=float), np.asarray(low, dtype=float)
    possible = np.zeros(len(high), dtype=bool)
    for scale, minimum, maximum in SCALES:
        first = 12 if scale == "short" else minimum
        for length in range(first, min(len(high) + 1, maximum)):
            end = max(8, int(length * .58))
            bottom = np.min(low[:end])
            possible[length - 1] |= bottom > 0 and np.max(high[:end]) / bottom - 1 >= minimum_gain
        if len(high) >= maximum:
            end = max(8, int(maximum * .58))
            highs = np.lib.stride_tricks.sliding_window_view(high, maximum)[:, :end].max(axis=1)
            lows = np.lib.stride_tricks.sliding_window_view(low, maximum)[:, :end].min(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                possible[maximum - 1:] |= (lows > 0) & (highs / lows - 1 >= minimum_gain)
    return possible


def flag_balance(high, close, volume, scale):
    maximum = next(maximum for name, _, maximum in SCALES if name == scale)
    high, close, volume = (np.asarray(x[-maximum:], dtype=float) for x in (high, close, volume))
    prefix = max(8, int(len(close) * .58))
    pole = int(np.argmax(high[:prefix]))
    # Original detector's flag starts immediately after pole high; exclude signal.
    v = volume[pole + 1:-1]
    direction = np.sign(close[pole + 1:-1] - close[pole:-2])
    if not len(v) or not (np.isfinite(v) & (v > 0)).all() or not np.isfinite(direction).all():
        return np.nan, len(v)
    return float(np.sum(v * direction) / np.sum(v)), len(v)


def main():
    path = ROOT / "docs/research/high-tight-flag/flag-volume-balance-selection-train-v1.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    output = ROOT / "data/research/high-tight-flag" / protocol["experiment"]
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_bytes(path.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    source = ROOT / "data/research/vcp/runs" / protocol["baseline_run"]
    params = _defaults(source)
    symbols = set(json.loads((source / "config.json").read_text(encoding="utf-8"))["symbols"])
    relative = "backend/app/strategy/builtin/_quants_high_tight_flag.py"
    with ZipFile(source / "source.zip") as z:
        detector_source = z.read(relative)
    frozen = ModuleType("frozen_flag")
    exec(compile(detector_source, str(source / "source.zip") + "/" + relative, "exec"), frozen.__dict__)
    assert frozen.SCALES == SCALES
    detector = frozen.QuantsHighTightFlagStrategy()
    frames = []
    with ZipFile(ROOT / protocol["data_archive"]) as z:
        for n in z.namelist():
            if (n.startswith("data/kline_daily_enriched/date=") and n.endswith("/part.parquet")
                    and n.split("date=")[1][:10] <= protocol["training_data_end"]):
                frames.append(pl.read_parquet(BytesIO(z.read(n)), columns=[
                    "symbol", "date", "open", "high", "low", "close", "volume", "raw_close"
                ]).filter(pl.col("symbol").is_in(symbols)))
    market = build_market_data_matrix(pl.concat(frames), field_columns={"raw_close"})
    del frames
    dates = [d[:10] for d in market.timestamp_labels]
    old = json.loads((source / "result.json").read_text(encoding="utf-8"))["trades"]
    known_names = {r["symbol"]: r["name"] for r in old}
    names = tuple(known_names.get(s, "") for s in market.symbols)
    up, down = _limit_lock_matrices(market.close, market.fields["raw_close"], np.isfinite(market.close),
                                   [date.fromisoformat(d) for d in dates], list(market.symbols),
                                   list(names), {}, apply_latest_limits=False)
    market = replace(market, names=names, limit_up_locked=up, limit_down_locked=down)
    candidates = []
    exact_calls = 0
    for a, symbol in enumerate(market.symbols):
        ids = np.flatnonzero(np.isfinite(market.close[:, a]))
        possible = possible_poles(market.high[ids, a], market.low[ids, a], params["pole_gain_min"])
        for position in np.flatnonzero(possible):
            t = int(ids[position])
            if not protocol["signal_period"][0] <= dates[t] <= protocol["signal_period"][1]:
                continue
            c = detector._detect(market, a, t, params)
            exact_calls += 1
            if not c or c.get("status") != "executable":
                continue
            history = ids[max(0, position - 219):position + 1]
            score, length = flag_balance(market.high[history, a], market.close[history, a],
                                         market.volume[history, a], c["scale"])
            candidates.append({"symbol": symbol, "signal_date": dates[t], "t": t, "asset": a,
                               "flag_volume_balance": score, "flag_observations": length,
                               "primary_scale": c["scale"], "pivot": c["pivot"]})
        if (a + 1) % 500 == 0:
            print(f"assets={a + 1}/{market.shape[1]} exact_calls={exact_calls} candidates={len(candidates)}", flush=True)
    by_date = {}
    for r in candidates:
        by_date.setdefault(r["signal_date"], []).append(r)
    for rows in by_date.values():
        finite = [r["flag_volume_balance"] for r in rows if np.isfinite(r["flag_volume_balance"])]
        median = np.median(finite) if finite else np.nan
        for r in rows:
            r.update(feature_valid=bool(np.isfinite(r["flag_volume_balance"])),
                     selected=bool(r["flag_volume_balance"] >= median))
    pl.DataFrame(candidates).write_parquet(output / "frozen-candidates.parquet")
    old_keys = {(r["symbol"], r["entry_signal_date"]) for r in old}
    new_keys = {(r["symbol"], r["signal_date"]) for r in candidates}
    (output / "candidate-reconciliation.json").write_text(json.dumps({
        "original_trades": len(old_keys), "original_keys_recovered": len(old_keys & new_keys),
        "missing_original_keys": sorted(old_keys - new_keys),
        "additional_keys": sorted(new_keys - old_keys), "exact_detector_calls": exact_calls,
        "frozen_detector_source_used": True,
    }, indent=2), encoding="utf-8")
    print(f"frozen_candidates={len(candidates)} signal_dates={len(by_date)}", flush=True)
    evaluate_selection(market, candidates, protocol, output, "flag_volume_balance", 1)


if __name__ == "__main__":
    main()
