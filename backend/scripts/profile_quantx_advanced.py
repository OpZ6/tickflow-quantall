"""Profile the QuantX advanced snapshot builder without going through HTTP."""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import time
from datetime import datetime
from pathlib import Path

from app.quantx_data.advanced import build_advanced_snapshot
from app.tickflow.repository import DataStore, KlineRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20261127")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--timings", action="store_true", help="按函数统计耗时")
    args = parser.parse_args()

    timings: dict[str, list[float]] = {}
    if args.timings:
        import functools

        import app.quantx_data.advanced as adv

        for name in dir(adv):
            if not name.startswith("_") or name.startswith("__"):
                continue
            target = getattr(adv, name)
            if not callable(target) or name in {"_read_range", "_round", "_empty_card", "_card"}:
                continue

            def wrap(fn, key):
                @functools.wraps(fn)
                def inner(*fargs, **fkwargs):
                    started = time.perf_counter()
                    try:
                        return fn(*fargs, **fkwargs)
                    finally:
                        timings.setdefault(key, []).append(time.perf_counter() - started)

                return inner

            setattr(adv, name, wrap(target, name))
        build = adv.build_advanced_snapshot
    else:
        build = build_advanced_snapshot

    day = datetime.strptime(args.date, "%Y%m%d").date()
    store = DataStore()
    repo = KlineRepository(store)
    # api/quantx_data.advanced() 传的是 _root(request).parent, 也就是 data_dir 本身
    # (数据集落在 data/<dataset>/date=*/part.parquet)。
    root = Path(store.data_dir)

    for index in range(args.repeat):
        started = time.perf_counter()
        if args.profile and index == 0:
            profiler = cProfile.Profile()
            profiler.enable()
        snapshot = build(root, day, repo)
        if args.profile and index == 0:
            profiler.disable()
        elapsed = time.perf_counter() - started
        coverage = snapshot.get("coverage", {})
        print(f"run {index}: {elapsed:.2f}s coverage={coverage.get('available')}/{coverage.get('total')}")
        for key, card in snapshot.get("cards", {}).items():
            print(f"  {key:28s} status={card.get('status'):10s} rows={card.get('rows')}")

    if args.timings:
        print("\n按函数累计耗时(秒):")
        for key, values in sorted(timings.items(), key=lambda item: -sum(item[1])):
            print(f"  {key:32s} calls={len(values):4d} total={sum(values):7.2f} max={max(values):6.2f}")

    if args.profile:
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(35)
        print(stream.getvalue())


if __name__ == "__main__":
    main()
