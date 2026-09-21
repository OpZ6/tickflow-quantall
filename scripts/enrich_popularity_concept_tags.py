"""Enrich an existing normalized security_popularity snapshot with concept_tags
from the current hot-stock-list endpoint (reflects the last session's close).

Usage: python enrich_popularity_concept_tags.py --date 20260915 --data-dir data
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
URL = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"


def _code(value: str) -> str:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits[-6:] if len(digits) >= 6 else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    compact = args.date.replace("-", "")
    iso_date = f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"

    # Fetch current hot list (reflects last session's close)
    session = requests.Session()
    session.trust_env = False
    r = session.get(URL, params={"stock_type": "a", "type": "day", "list_type": "normal"},
                    headers={"User-Agent": UA, "Referer": URL}, timeout=18)
    r.raise_for_status()
    rows = r.json().get("data", {}).get("stock_list", []) or r.json().get("data", {}).get("list", [])
    tag_map: dict[str, str] = {}
    for row in rows:
        code = _code(row.get("code"))
        tag_data = row.get("tag")
        concept_tags = tag_data.get("concept_tag") if isinstance(tag_data, dict) else None
        if code and isinstance(concept_tags, list) and concept_tags:
            tag_map[code] = ";".join(concept_tags)
    print(f"fetched {len(rows)} hot stocks, {len(tag_map)} with concept_tags")

    # Enrich the existing normalized snapshot
    target = args.data_dir / "quantx" / compact / "normalized" / "security_popularity.json"
    if not target.is_file():
        print(f"ERROR: {target} not found")
        sys.exit(1)
    payload = json.loads(target.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    enriched = 0
    for record in records:
        if str(record.get("source_root") or record.get("source_name") or "") != "ths":
            continue
        code = _code(record.get("code"))
        if code in tag_map:
            record["concept_tags"] = tag_map[code]
            enriched += 1
        elif "concept_tags" not in record:
            record["concept_tags"] = ""
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"enriched {enriched} ths records with concept_tags in {target}")


if __name__ == "__main__":
    main()
