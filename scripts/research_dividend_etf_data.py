"""Freeze public ETF daily bars for the dividend ETF research experiment.

Research input only: this does not publish bars into the application's market
data repository. The Tencent endpoint is queried in two-year windows because
longer requests can return an empty or truncated response.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests


SYMBOLS = {
    "510880.SH": ("sh", 2007),
    "512890.SH": ("sh", 2019),
    "513630.SH": ("sh", 2023),
    "515080.SH": ("sh", 2019),
    "159331.SZ": ("sz", 2024),
}
ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def fetch(symbol: str, start_year: int, end: date, adjustment: str) -> pd.DataFrame:
    market = SYMBOLS[symbol][0]
    key = f"{market}{symbol[:6]}"
    rows: list[dict] = []
    with requests.Session() as session:
        session.trust_env = False
        for year in range(start_year, end.year + 1, 2):
            window_end = min(date(year + 1, 12, 31), end)
            param = f"{key},day,{year}-01-01,{window_end.isoformat()},1000,{adjustment}"
            response = session.get(ENDPOINT, params={"param": param}, timeout=20)
            response.raise_for_status()
            payload = response.json()
            node = payload.get("data", {}).get(key) if isinstance(payload.get("data"), dict) else None
            if not isinstance(node, dict):
                raise ValueError(f"missing bars: {symbol} {param}")
            bars = node.get("qfqday" if adjustment == "qfq" else "day", [])
            if not bars:
                raise ValueError(f"empty bars: {symbol} {param}")
            for bar in bars:
                rows.append({
                    "date": bar[0], "open": float(bar[1]), "close": float(bar[2]),
                    "high": float(bar[3]), "low": float(bar[4]), "volume": float(bar[5]),
                })
    frame = pd.DataFrame(rows)
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError(f"duplicate or unordered dates: {symbol} {adjustment}")
    if frame.date.iloc[-1] != end.isoformat():
        raise ValueError(f"last date mismatch: {symbol} {adjustment}: {frame.date.iloc[-1]}")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 24))
    parser.add_argument("--output", type=Path, default=Path("data/research/dividend_etf"))
    parser.add_argument("--overwrite", action="store_true", help="replace an earlier research snapshot")
    args = parser.parse_args()
    if any(args.output.glob("*_raw.csv")) and not args.overwrite:
        parser.error("research snapshot exists; pass --overwrite to replace it")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"source": ENDPOINT, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "end": args.end.isoformat(), "datasets": []}
    for symbol, (_, start_year) in SYMBOLS.items():
        for adjustment in ("raw", "qfq"):
            frame = fetch(symbol, start_year, args.end, "qfq" if adjustment == "qfq" else "")
            path = args.output / f"{symbol}_{adjustment}.csv"
            frame.to_csv(path, index=False)
            manifest["datasets"].append({"symbol": symbol, "adjustment": adjustment, "path": path.name, "rows": len(frame), "first": frame.date.iloc[0], "last": frame.date.iloc[-1]})
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True))


if __name__ == "__main__":
    main()
