"""Cost and dividend-availability sensitivity for the ETF research rules."""

from __future__ import annotations

import json
from pathlib import Path

from research_dividend_etf_backtest import (
    SYMBOLS,
    corporate_actions,
    load_etf_pair,
    metrics,
    public_payment_indices,
    signals,
    simulate,
    total_return_bars,
)


ROOT = Path("data/research/dividend_etf")
STRATEGIES = ("hold", "macd", "channel", "core70_macd30", "core70_channel30")
SCENARIOS = {
    "zero_cost": (0., 0),
    "5bps": (.0005, 0),
    "10bps": (.001, 0),
    "20bps": (.002, 0),
    "5bps_payment_lag_5_bars": (.0005, 5),
    "5bps_published_payment_date": (.0005, None),
}


def main() -> None:
    report = {"status": "exploratory_execution_sensitivity", "cost_unit": "fraction of traded notional per side", "payment_lag_unit": "ETF trading bars after ex-date", "symbols": {}}
    for symbol in SYMBOLS:
        raw, adjusted = load_etf_pair(ROOT, symbol)
        dividends, splits = corporate_actions(raw, adjusted, symbol)
        signal_frame = total_return_bars(raw, dividends) if symbol == "510880.SH" else adjusted
        target = signals(signal_frame)
        published_payment = public_payment_indices(raw, symbol, ROOT)
        scenarios = {}
        for scenario, (cost, lag) in SCENARIOS.items():
            results = {}
            for name in STRATEGIES:
                curve, changes, turnover = simulate(raw, target[name], 199, cost, dividends=dividends, splits=splits, dividend_lag_bars=lag or 0, payment_indices=published_payment if lag is None else None)
                results[name] = {**metrics(curve), "allocation_changes": changes, "turnover": turnover}
            baseline = results["hold"]["cagr"]
            for row in results.values():
                row["cagr_minus_hold"] = row["cagr"] - baseline
            scenarios[scenario] = results
        report["symbols"][symbol] = scenarios
    (ROOT / "execution_sensitivity.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({symbol: {scenario: {name: round(rows[name]["cagr_minus_hold"] * 100, 2) for name in STRATEGIES[1:]} for scenario, rows in scenarios.items()} for symbol, scenarios in report["symbols"].items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
