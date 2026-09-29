"""Snapshot public fund distribution tables for research account simulation."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from research_dividend_etf_backtest import SYMBOLS, corporate_actions, load_etf_pair


ROOT = Path("data/research/dividend_etf")
URL = "https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJFH.php"


def main() -> None:
    result = {"source": URL, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "symbols": {}}
    session = requests.Session()
    session.trust_env = False
    for symbol in SYMBOLS:
        raw, adjusted = load_etf_pair(ROOT, symbol)
        inferred, _ = corporate_actions(raw, adjusted, symbol)
        response = session.get(URL, params={"symbol": symbol[:6]}, timeout=20)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        tables = pd.read_html(io.StringIO(response.text))
        payouts = {}
        for _, row in tables[8].iloc[1:, :3].iterrows():
            try:
                record_date = pd.Timestamp(row.iloc[0])
                payment_date = pd.Timestamp(row.iloc[1])
                amount = float(row.iloc[2])
            except (TypeError, ValueError):
                continue
            if not 0 < amount < 1:
                continue
            following = raw.date[raw.date > record_date]
            if len(following):
                ex_date = str(following.iloc[0].date())
                payouts[ex_date] = {"record_date": str(record_date.date()), "payment_date": str(payment_date.date()), "amount": amount}
        errors = []
        for i, amount in enumerate(inferred):
            if amount > 0 and str(raw.date.iloc[i].date()) not in payouts:
                errors.append(f"missing public record {raw.date.iloc[i].date()}")
        for day, payout in payouts.items():
            i = raw.index[raw.date == day]
            observed = float(inferred.iloc[i[0]])
            if symbol != "159331.SZ" and abs(observed - payout["amount"]) > .00051:
                errors.append(f"amount mismatch {day}: {observed} vs {payout['amount']}")
            if symbol == "159331.SZ" and abs(observed - payout["amount"]) > .00101:
                errors.append(f"large amount mismatch {day}: {observed} vs {payout['amount']}")
        if errors:
            raise ValueError(f"{symbol}: {errors}")
        result["symbols"][symbol] = payouts
        print(symbol, len(payouts), "verified")
    (ROOT / "public_payouts.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
