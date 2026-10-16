"""Check adjusted-price proxy against raw ETF trades plus cash distributions.

Distribution amounts are inferred from raw minus Tencent qfq price and must be
verified against fund notices before live use. Cash is credited on ex-date as
an equity receivable; actual cash payment can occur several days later.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_dividend_etf_backtest import (
    ROUND_TRIP_SIDE_COST,
    corporate_actions,
    load_etf_pair,
    metrics,
    signals,
    simulate,
    total_return_bars,
)


ROOT = Path("data/research/dividend_etf")
SYMBOLS = ("510880.SH", "512890.SH", "513630.SH", "515080.SH", "159331.SZ")


def main() -> None:
    report = {"status": "corporate_actions_inferred_from_qfq_not_fully_notice_verified", "cash_credit": "ex-date receivable", "symbols": {}}
    for symbol in SYMBOLS:
        raw, adjusted = load_etf_pair(ROOT, symbol)
        dividends, splits = corporate_actions(raw, adjusted, symbol)
        signal_frame = total_return_bars(raw, dividends) if symbol == "510880.SH" else adjusted
        targets = signals(signal_frame)
        first = 199
        item = {"inferred_dividend_events": int((dividends > 0).sum()), "inferred_dividend_per_share_sum": float(dividends.sum()), "split_events": int((splits != 1).sum()), "first_trade": raw.date.iloc[first + 1].date().isoformat(), "strategies": {}}
        for name in ("hold", "ma200", "macd", "channel"):
            cash_curve, changes, _ = simulate(raw, targets[name], first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits)
            cash_result = metrics(cash_curve)
            item["strategies"][name] = {"cash_ledger": cash_result, "allocation_changes": changes}
            if symbol != "510880.SH":
                proxy_curve, _, _ = simulate(signal_frame, targets[name], first, ROUND_TRIP_SIDE_COST)
                item["strategies"][name]["qfq_proxy"] = metrics(proxy_curve)
                item["strategies"][name]["cagr_difference_cash_minus_proxy"] = cash_result["cagr"] - metrics(proxy_curve)["cagr"]
        reinvested, _, _ = simulate(raw, targets["hold"], first, ROUND_TRIP_SIDE_COST, dividends=dividends, splits=splits, reinvest_dividends=True)
        item["hold_exdate_reinvestment_upper_proxy"] = metrics(reinvested)
        report["symbols"][symbol] = item
    (ROOT / "cash_ledger_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({symbol: item["strategies"]["hold"] for symbol, item in report["symbols"].items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
