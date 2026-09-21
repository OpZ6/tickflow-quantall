"""Cache today's multi-source research ranking using the existing Quantall adapter."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests


def collect(day: str, quantall_dir: Path, output: Path) -> dict:
    source_dir = quantall_dir / "apps/quantx/src"
    if not (source_dir / "scrapers/institution_trend_scraper.py").exists():
        raise FileNotFoundError("Quantall ranking adapter not found")
    sys.path.insert(0, str(source_dir.resolve()))
    from scrapers.institution_trend_scraper import collect_hot_rank_snapshot

    snapshot = collect_hot_rank_snapshot(day)
    # Quantall's quicktiny fallback can fail while Eastmoney's official API works.
    if day == dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d"):
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.post(
                "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
                json={"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "marketType": "", "pageNo": 1, "pageSize": 100},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://emappdata.eastmoney.com/"}, timeout=15,
            )
            response.raise_for_status()
            raw = response.json().get("data") or []
            if raw:
                observed = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
                records = [{"source_root": "eastmoney", "source_adapter": "official", "list_type": "normal", "trade_date": day, "code": row["sc"][2:], "rank": int(row["rk"]), "rank_change": row.get("hisRc"), "observed_at": observed, "freshness": "fresh"} for row in raw]
                snapshot["records"] = [row for row in snapshot["records"] if row["source_root"] != "eastmoney"] + records
                snapshot["source_status"]["eastmoney"] = {"status": "ok", "adapter": "official", "count": len(records), "observed_at": observed}
            else:
                snapshot["source_status"]["eastmoney"]["official_probe"] = "empty"
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            snapshot["source_status"]["eastmoney"]["official_probe"] = type(exc).__name__
    # The panel consumes source records, not the adapter's pre-merge consensus.
    snapshot.pop("consensus", None)
    snapshot["degraded"] = any(snapshot["source_status"].get(root, {}).get("status") != "ok" for root in ("ths", "xueqiu", "baidu", "eastmoney"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--quantall-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.date.replace("-", ""), args.quantall_dir, args.output)
    print(json.dumps(result["source_status"], ensure_ascii=False, indent=2))
