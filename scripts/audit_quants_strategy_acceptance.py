"""Read-only, independent Quants/TickFlow migration acceptance audit.

Run with backend's Python; --source is an explicit reference checkout. Only
synthetic fixtures and optional normalized local daily history are read. No
Quants database, network, production configuration or event writes occur.
Exit 1 means semantic differences, not successful acceptance.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import runpy
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def differences(reference, target, path=""):
    """Missing fields and discrete changes never disappear into numeric tolerance."""
    if isinstance(reference, dict) and isinstance(target, dict):
        result = []
        for key in sorted(reference.keys() | target.keys()):
            child = f"{path}.{key}" if path else key
            if key not in reference or key not in target:
                result.append(
                    {
                        "field": child,
                        "reference": reference.get(key),
                        "target": target.get(key),
                        "kind": "missing_field",
                    }
                )
            else:
                result.extend(differences(reference[key], target[key], child))
        return result
    numeric = all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in (reference, target)
    )
    equal = (
        math.isclose(reference, target, rel_tol=1e-6, abs_tol=1e-4)
        if numeric
        else reference == target
    )
    return (
        []
        if equal
        else [{"field": path, "reference": reference, "target": target, "kind": "value"}]
    )


IDS = {
    "v1": "quants_vcp_legacy_v1",
    "v2": "quants_growth_trend_legacy_v1",
    "v3": "quants_cup_handle_legacy_v1",
    "v4": "quants_high_tight_flag_legacy_v1",
    "v5": "quants_pullback_low_absorb_legacy_v1",
}
MODULES = {
    "v1": ("vcp_optimized", "OptimizedVcpDetector"),
    "v2": ("vcp", "VcpDetector"),
    "v3": ("cup_with_handle_optimized", "OptimizedCupWithHandleDetector"),
    "v4": ("high_tight_flag_optimized", "OptimizedHighTightFlagDetector"),
    "v5": ("pullback_low_absorb", "PullbackLowAbsorbDetector"),
}


def canonical_reference(result):
    flat = result.flat_metrics
    primary = flat.get("primary_candidate", {})
    entry = primary.get("entry", {})
    return {
        "valid": bool(result.is_valid),
        "reason": result.invalid_reason,
        "status": flat.get("entry_status", "invalid" if not result.is_valid else None),
        "setup": flat.get("entry_setup_type", "invalid" if not result.is_valid else None),
        "scale": flat.get("pattern_scale"),
        "stage": flat.get("pattern_stage"),
        "pivot": flat.get("primary_trigger_price", flat.get("derived_pivot_price")),
        "quality": flat.get("pattern_quality_score"),
        "stop_price": entry.get("stop_price"),
        "alternates": len(flat.get("alternate_candidates", [])),
    }


def evaluate_target(key, frame, params):
    from app.strategy.builtin._quants_high_tight_flag import detect as flag
    from app.strategy.builtin._quants_legacy_patterns import cup_detect, pullback_detect
    from app.strategy.builtin._quants_vcp import detect as vcp

    arrays = [
        frame[c + "_for_factor"].to_numpy(float) for c in ("open", "high", "low", "close", "volume")
    ]
    o, h, lo, c, v = arrays
    alternate_count = 0
    if key in {"v1", "v2"}:
        if key == "v1":
            params = {**params, "legacy_semantics": True}
        raw = vcp(h, lo, c, v, frame.trade_date.astype(str).tolist(), params) or {}
        alternate_count = len(raw.get("alternates", []))
        result = raw.get("primary", {})
    elif key == "v3":
        result = cup_detect(h, lo, c, v, params)
    elif key == "v4":
        result = flag(h, lo, c, v, params) or {}
    else:
        optional = [
            frame[name].to_numpy(float) if name in frame else None
            for name in ("net_mf_amount", "pct_chg", "ma10", "vol_ma20")
        ]
        result = pullback_detect(o, h, lo, c, v, params, *optional)
    valid = bool(result.get("valid", False))
    if key not in {"v1", "v2"}:
        alternate_count = min(3, len(result.get("alternates", [])))
    return {
        "valid": valid,
        "reason": None if valid else result.get("reason"),
        "status": result.get("status"),
        "setup": result.get("setup", "invalid" if not valid else None),
        "scale": result.get("scale"),
        "stage": result.get("stage"),
        "pivot": result.get("pivot"),
        "quality": result.get("quality"),
        "stop_price": result.get("stop_price"),
        "alternates": alternate_count,
    }


def synthetic_cases(source):
    base = source / "tests/fixtures/patterns/optimized"
    specifications = [
        ("v1", "vcp_cases.py", "synthetic_three_contraction_vcp"),
        ("v2", "vcp_cases.py", "synthetic_three_contraction_vcp"),
        ("v3", "cup_with_handle_cases.py", "right_rim_under_high_then_handle"),
        ("v3", "cup_with_handle_cases.py", "breakout_then_cup_lip_support"),
        ("v4", "high_tight_flag_cases.py", "flagpole_no_flag"),
        ("v4", "high_tight_flag_cases.py", "tight_flag_breakout"),
    ]
    for key, filename, function in specifications:
        frame = runpy.run_path(str(base / filename))[function]()
        for size in sorted({1, 11, 12, 15, 20, len(frame) - 1, len(frame)}):
            if size <= len(frame):
                yield key, f"{function}/prefix-{size}", frame.head(size).copy()
        for multiple in (0.9, 0.99, 1.0, 1.025, 1.026, 1.081):
            case = frame.astype({c: float for c in frame.columns if c.endswith("_for_factor")})
            close = float(case.close_for_factor.iloc[-1]) * multiple
            case.loc[case.index[-1], "close_for_factor"] = close
            case.loc[case.index[-1], "high_for_factor"] = max(close, case.high_for_factor.iloc[-1])
            case.loc[case.index[-1], "low_for_factor"] = min(close, case.low_for_factor.iloc[-1])
            yield key, f"{function}/tail-{multiple}", case
    factory = runpy.run_path(str(source / "tests/test_v5_pullback_low_absorb_detector.py"))[
        "_history"
    ]
    for name, kwargs in [
        ("positive", {}),
        ("wet", {"current_volume": 1500.0}),
        ("lost_midline", {"current_close": 10.2}),
        ("lost_ma10", {"ma10": 10.8}),
        ("negative_flow", {"net_mf_tail": (-100,) * 5}),
        ("zero_flow", {"net_mf_tail": (0,) * 5}),
    ]:
        yield "v5", name, factory(**kwargs)
    yield "v5", "missing_flow", factory().drop(columns="net_mf_amount")


def real_cases(data, start, end, keys):
    import polars as pl

    partitions = sorted((data / "kline_daily_enriched").glob("date=*/part.parquet"))
    partitions = [p for p in partitions if p.parent.name[5:] <= end]
    end_labels = [p.parent.name[5:] for p in partitions]
    if start not in end_labels:
        raise ValueError("start must be an existing trading-date partition")
    partitions = partitions[max(0, end_labels.index(start) - 420) :]
    frame = pl.read_parquet(
        partitions, columns=["symbol", "date", "open", "high", "low", "close", "volume"]
    )
    mapping = {
        "date": "trade_date",
        **{c: c + "_for_factor" for c in ("open", "high", "low", "close", "volume")},
    }
    for (symbol,), group in (
        frame.sort(["symbol", "date"]).partition_by("symbol", as_dict=True).items()
    ):
        pdf = group.rename(mapping).to_pandas()
        labels = pdf.trade_date.astype(str)
        for index in pdf.index[(labels >= start) & (labels <= end)]:
            history = pdf.iloc[max(0, index - 419) : index + 1].copy()
            history["trade_date"] = history.trade_date.dt.date
            for key in keys:
                yield key, f"{symbol}/{labels.iloc[index]}", history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--real-strategies", default="v1,v3,v4,v5")
    args = parser.parse_args()
    if args.data and not (args.start and args.end):
        parser.error("--data requires --start and --end")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("output must be empty; previous audit evidence is immutable")
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.source.resolve()))
    from app.strategy.engine import StrategyEngine

    engine = StrategyEngine([ROOT / "backend/app/strategy/builtin"])
    params = {key: engine.resolve_params(engine.get(sid), None, None) for key, sid in IDS.items()}
    detectors = {
        key: getattr(importlib.import_module("ppgu.patterns." + module), name)()
        for key, (module, name) in MODULES.items()
    }
    source_paths = [
        args.source / "ppgu/patterns" / (module + ".py") for module, _ in MODULES.values()
    ]
    source_paths += [
        args.source / "ppgu" / name
        for name in (
            "factor_wave.py",
            "screen.py",
            "strategies.py",
            "strategy_registry.py",
            "strategy_analysis.py",
        )
    ]
    source_paths += list((args.source / "configs/strategies").glob("v[1-5]_*.yaml"))
    for path in source_paths:
        destination = output / "source" / path.relative_to(args.source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    for path in (ROOT / "backend/app/strategy/builtin").glob("*quants*.py"):
        destination = output / "target" / path.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(path, destination)
    counters = {key: Counter() for key in IDS}
    field_counts = {key: Counter() for key in IDS}
    started = time.perf_counter()
    cases = synthetic_cases(args.source)
    if args.data:
        from itertools import chain

        cases = chain(
            cases, real_cases(args.data, args.start, args.end, args.real_strategies.split(","))
        )
    fixtures = []
    with (output / "cases.jsonl").open("w", encoding="utf-8") as log:
        for index, (key, name, frame) in enumerate(cases):
            reference_raw = detectors[key].detect(
                frame, ts_code=name.split("/")[0], trade_date=frame.trade_date.iloc[-1]
            )
            reference = canonical_reference(reference_raw)
            target = evaluate_target(key, frame, params[key])
            diff = differences(reference, target)
            if not args.data:
                fixtures.append(
                    {
                        "strategy": key,
                        "case": name,
                        "params": params[key],
                        "history": frame.to_dict(orient="records"),
                        "expected": reference,
                    }
                )
            counters[key]["cases"] += 1
            counters[key]["reference_positive"] += int(reference["valid"])
            counters[key]["target_positive"] += int(target["valid"])
            counters[key]["valid_mismatch"] += int(reference["valid"] != target["valid"])
            counters[key]["any_field_mismatch"] += int(bool(diff))
            counters[key]["input_blocked"] += int(key == "v5" and "net_mf_amount" not in frame)
            field_counts[key].update(d["field"] for d in diff)
            log.write(
                json.dumps(
                    {
                        "strategy": key,
                        "case": name,
                        "bars": len(frame),
                        "reference": reference,
                        "target": target,
                        "differences": diff,
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
            if index and index % 1000 == 0:
                print(f"audited {index} cases", flush=True)
    summary = {
        "status": "failed"
        if any(c["any_field_mismatch"] for c in counters.values())
        else "detector_fields_passed",
        "scope": "independent detectors with registered target defaults; NOT full-selection acceptance",
        "python": sys.version,
        "params": params,
        "target_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.source, text=True
        ).strip(),
        "strategies": {
            key: {**counts, "different_fields": field_counts[key]}
            for key, counts in counters.items()
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "remaining_gates": [
            "full factor/filter/score/order parity",
            "full state and evidence roundtrip",
            "point-in-time input coverage",
            "reproducible final version freeze",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if fixtures:
        (output / "reference-fixtures.json").write_text(
            json.dumps(fixtures, ensure_ascii=False, default=str), encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
