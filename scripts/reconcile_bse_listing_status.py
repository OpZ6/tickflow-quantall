#!/usr/bin/env python3
"""Record immutable BSE listed-company search evidence for suspect symbols.

This is rendered-page inspection and intentionally uses standalone Playwright
with the installed Edge channel, as required by the repository automation
contract.  It performs read-only searches and never modifies the website.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPAIR_ROOT = (ROOT / "data" / "repair").resolve()
URL = "https://www.bse.cn/nq/listedcompany.html"


def _symbol(value: str) -> str:
    text = value.strip().upper()
    code, separator, exchange = text.partition(".")
    if not separator or exchange != "BJ" or len(code) != 6 or not code.isdigit():
        raise argparse.ArgumentTypeError("symbols must use six-digit CODE.BJ form")
    return text


def _output_path(value: str) -> Path:
    path = (REPAIR_ROOT / value).resolve()
    if not path.is_relative_to(REPAIR_ROOT) or path == REPAIR_ROOT:
        raise argparse.ArgumentTypeError("output directory must be below data/repair")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", type=_symbol, required=True)
    parser.add_argument("--output-dir", type=_output_path, required=True)
    args = parser.parse_args()
    output = args.output_dir
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing evidence: {output}")

    symbols = list(dict.fromkeys(args.symbol))
    observed_at = datetime.now(UTC).isoformat()
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            for symbol in symbols:
                page = browser.new_page()
                try:
                    response = page.goto(URL, wait_until="networkidle", timeout=60_000)
                    page.get_by_placeholder("公司简称/拼音/代码").fill(symbol.split(".")[0])
                    page.get_by_role("button", name="查询").click()
                    page.wait_for_timeout(1_500)
                    body = page.locator("body").inner_text()
                    code = symbol.split(".")[0]
                    no_data = "暂无数据" in body
                    listed = code in body and not no_data
                    records.append({
                        "symbol": symbol,
                        "http_status": response.status if response else None,
                        "page_title": page.title(),
                        "listed": listed,
                        "no_data": no_data,
                        "result": "not_listed" if no_data and not listed else "listed",
                        "rendered_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    })
                finally:
                    page.close()
        finally:
            browser.close()

    valid = all(
        item["http_status"] == 200
        and item["page_title"] == "股票列表 - 北京证券交易所"
        and (item["listed"] or item["no_data"])
        for item in records
    )
    evidence = {
        "schema_version": 1,
        "status": "pass" if valid else "fail",
        "source": "beijing_stock_exchange_listed_company_search",
        "source_url": URL,
        "automation": "standalone_playwright_msedge_headless",
        "observed_at": observed_at,
        "semantics": (
            "not_listed means absent from the BSE listed-company result as observed; "
            "it does not identify a pending issue code"
        ),
        "records": records,
    }

    staging = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    staging.mkdir(parents=True)
    try:
        (staging / "reconciliation.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        staging.replace(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps({"output": str(output), **evidence}, ensure_ascii=False, indent=2))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
