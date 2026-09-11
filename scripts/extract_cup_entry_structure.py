"""Reconstruct the frozen cup baseline through its existing matrix detector."""

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.strategy.builtin._quants_legacy_patterns import LegacyPatternStrategy  # noqa: E402


def main():
    run = ROOT / "data/research/vcp/runs/20260909T133226351846Z"
    relative = "backend/app/strategy/builtin/_quants_legacy_patterns.py"
    with ZipFile(run / "source.zip") as archive:
        if archive.read(relative) != (ROOT / relative).read_bytes():
            raise ValueError("Detector differs from frozen source")
    trades = json.loads((run / "result.json").read_text(encoding="utf-8"))["trades"]
    meta = json.loads((run / "strategy.json").read_text(encoding="utf-8"))["meta"]
    params = {p["id"]: p["default"] for p in meta["params"] if "default" in p}
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    params.update(config.get("params") or {})
    last = max(t["entry_signal_date"] for t in trades)
    refs = [r for r in json.loads((run / "data-references.json").read_text(
        encoding="utf-8"
    ))["files"] if Path(r["path"]).parts[0] == "kline_daily_enriched"
        and Path(r["path"]).parent.name.removeprefix("date=") <= last]
    for ref in refs:
        stat = (ROOT / "data" / ref["path"]).stat()
        if (stat.st_size, stat.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
            raise ValueError(f"Changed source: {ref['path']}")
    fields = ("open", "high", "low", "close", "volume")
    bars = pl.scan_parquet([str(ROOT / "data" / r["path"]) for r in refs]).select(
        "symbol", "date", *fields
    ).filter(pl.col("symbol").is_in({t["symbol"] for t in trades})).collect()
    groups = bars.sort("date").partition_by("symbol", as_dict=True)
    by_symbol = {}
    for trade in trades:
        by_symbol.setdefault(trade["symbol"], []).append(trade)
    strategy = LegacyPatternStrategy("cup")
    records = []
    for symbol, events in by_symbol.items():
        frame = groups[(symbol,)]
        dates = frame["date"].to_numpy()
        market = SimpleNamespace(**{
            field: frame[field].to_numpy().astype(np.float32).reshape(-1, 1)
            for field in fields
        })
        for trade in events:
            t = int(np.searchsorted(dates, np.datetime64(trade["entry_signal_date"])))
            assert str(dates[t]) == trade["entry_signal_date"]
            candidate = strategy._detect(market, 0, t, params)
            records.append({
                **{k: trade.get(k) for k in (
                    "symbol", "entry_signal_date", "entry_date", "entry_signal_id"
                )},
                "status": candidate.get("status"), "pivot": candidate.get("pivot"),
                "planned_stop": candidate.get("stop_price"), "scale": candidate.get("scale"),
            })
    report = {
        "run_id": run.name, "scope": "entry_signal_date_causal_reconstruction",
        "status_counts": dict(Counter(r["status"] for r in records)),
        "pivot_coverage": sum(r["pivot"] is not None for r in records), "records": records,
    }
    (run / "entry-structure-evidence.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "records"}), flush=True)


if __name__ == "__main__":
    main()
