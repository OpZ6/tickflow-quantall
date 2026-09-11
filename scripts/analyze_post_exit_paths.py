"""Frozen post-exit price diagnostics; run from repository root with project Python."""

import json
from pathlib import Path
from statistics import mean, median

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def path_labels(dates, low, close, exit_price):
    recovery = np.flatnonzero(close > exit_price)
    loss = np.flatnonzero(low <= exit_price * 0.9)
    r = int(recovery[0]) if len(recovery) else None
    loss_index = int(loss[0]) if len(loss) else None
    return {
        "minimum_low_return": float(np.min(low) / exit_price - 1),
        "recovered_on_close": r is not None,
        "loss10_before_recovery": loss_index is not None and (r is None or loss_index < r),
        "loss10_same_bar_as_recovery": loss_index is not None and loss_index == r,
        "first_recovery_date": str(dates[r]) if r is not None else None,
    }


def main():
    protocol = ROOT / "docs/research/post-exit-path-diagnostic-v1.json"
    for name, run in json.loads(protocol.read_text(encoding="utf-8"))["runs"].items():
        directory = ROOT / "data/research/vcp/runs" / run
        def read(file, directory=directory):
            return json.loads((directory / file).read_text(encoding="utf-8"))
        trades = read("result.json")["trades"]
        paths = read("trade-path-analysis.json")["trades"]
        def key(row):
            return tuple(row.get(k) for k in (
                "symbol", "entry_signal_date", "entry_date", "entry_signal_id"
            ))
        index = {key(row): row for row in trades}
        assert len(index) == len(trades) == len(paths)
        assert set(index) == {key(row) for row in paths}
        selected = [r for r in paths if r["exit_reason"] == "signal"
                    and r["exit_date"] < r["evaluation_horizon_end_date"]]
        start = min(r["exit_date"] for r in selected)
        end = max(r["evaluation_horizon_end_date"] for r in selected)
        assert end <= "2022-12-31"
        refs = [r for r in read("data-references.json")["files"]
                if Path(r["path"]).parts[0] == "kline_daily_enriched"
                and start <= Path(r["path"]).parent.name.removeprefix("date=") <= end]

        def verify(refs=refs):
            for ref in refs:
                stat = (ROOT / "data" / ref["path"]).stat()
                if (stat.st_size, stat.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
                    raise ValueError(f"Changed source: {ref['path']}")

        verify()
        bars = pl.scan_parquet([str(ROOT / "data" / r["path"]) for r in refs]).select(
            "symbol", "date", "low", "close"
        ).filter(pl.col("symbol").is_in({r["symbol"] for r in selected})).collect()
        verify()
        groups = bars.sort("date").partition_by("symbol", as_dict=True)
        rows = []
        for r in selected:
            frame = groups[(r["symbol"],)]
            dates = frame["date"].to_numpy()
            left = np.searchsorted(dates, np.datetime64(r["exit_date"]), side="right")
            right = np.searchsorted(dates, np.datetime64(r["evaluation_horizon_end_date"]), side="right")
            window = frame.slice(int(left), int(right - left))
            assert window.height and str(window["date"][-1]) == r["evaluation_horizon_end_date"]
            low, close = window["low"].to_numpy(), window["close"].to_numpy()
            assert np.isfinite(low).all() and np.isfinite(close).all() and (low > 0).all()
            trade = index[key(r)]
            assert np.isclose(close[-1] / trade["entry_price"] - 1, r["horizon_close_return"])
            rows.append(path_labels(window["date"].to_numpy(), low, close, trade["exit_price"]))
        result = {
            "protocol": str(protocol.relative_to(ROOT)), "run_id": run, "n": len(rows),
            "source_metadata_verified": True, "immutable_snapshot": False,
            "median_minimum_low_return": median(r["minimum_low_return"] for r in rows),
            **{field + "_share": mean(r[field] for r in rows) for field in (
                "recovered_on_close", "loss10_before_recovery", "loss10_same_bar_as_recovery"
            )},
        }
        output = ROOT / "docs/research" / name / "post-exit-path-diagnostic-v1-analysis.json"
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
