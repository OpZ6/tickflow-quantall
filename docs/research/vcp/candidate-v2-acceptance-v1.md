# VCP candidate v2 frozen acceptance protocol

## Isolation

- Development and debugging data: 2021-09-06 through 2025-09-04.
- Final holdout: 2025-09-05 through 2026-06-30. The July-August 2026 engineering pilot disclosed by `five-year-v1.json` is excluded.
- The final holdout must not be run until every pre-holdout gate below passes.
- The candidate parameters and gates are frozen before the holdout is opened.
- The holdout may be run once. No parameter, universe, score, or exit adjustment may be selected from its result. A failed holdout rejects this candidate and retires that period from future final-test use.

## Frozen candidate

- Production identity: `vcp_recovery_breakout` (“VCP 复苏突破”). The frozen backtest used the same `_quants_vcp` implementation through migration ID `quants_vcp_legacy_v1`; production parity is verified separately.
- Entry: formal breakout only, first close crossing above the current pivot, executed at the next tradable open.
- Regime: the point-in-time universe breadth (share above each stock's MA20) must be from 30% through 35% on the signal close.
- Exit: 3% hard stop, close below MA20 signal executed at the next tradable open, or 40 trading-day maximum hold.
- Portfolio: full historical-union universe, equal 10% slots, at most 10 positions. The effective engine filter used price 3–300 yuan, total market capitalization at least 1 billion yuan, signal-day turnover amount at least 20 million yuan, all supported A-share boards, and current-name ST exclusion. The turnover floor is derived from a 100,000 yuan target slot and a 0.5% participation cap, rather than selected by a parameter sweep.
- Standard costs: 3 bp commission on each side, 5 bp sell stamp tax, and 10 bp slippage on each side.

## Pre-holdout gates

All gates must pass on archived runs:

1. Main development run: total return above 0%, monetary profit factor at least 1.20, maximum drawdown no worse than -15%, at least 80 closed trades, and at least four of five calendar segments positive.
2. Boundary stability: both 28%-36% and 32%-37% neighboring breadth bands remain profitable, have monetary profit factor above 1.05, and maximum drawdown no worse than -18%.
3. Concentration: subtracting the largest realized winner leaves positive net PnL, and the top five winners contribute no more than 70% of gross profit.
4. Cost stress: with 5 bp commission on each side, 10 bp sell stamp tax, and 20 bp slippage on each side, return remains positive, monetary profit factor is at least 1.05, and maximum drawdown is no worse than -18%.
5. Execution audit: no same-day round trips, entries occur after their signals, and signal exits occur after their signals.

## One-time final holdout gates

The frozen candidate is accepted for paper/live shadow execution only if the untouched holdout has at least 15 closed trades, positive total return, monetary profit factor at least 1.10, maximum drawdown no worse than -12%, and zero execution-timing violations. Failure of any gate rejects the candidate.

## Freeze record

The first draft was written before the investability check. The capacity-derived price/turnover rule, the resulting 90-trade minimum-sample adjustment, the 70% concentration ceiling, and removal of the disclosed July-August 2026 pilot were incorporated before any clean holdout run. This revision is the freeze point; subsequent changes require a new candidate identifier and may not use the holdout for selection.

The engine normalizes partial basic-filter overrides with its global stock defaults. This made current-name ST exclusion and current-total-share market capitalization part of the frozen run even though the initial research overlay listed only price and turnover amount. A development-only audit removing those two non-point-in-time fields was defined after the holdout and is reported as sensitivity evidence, not as a second independent candidate.

## Post-holdout acceptance defect

The frozen gates above omitted a market benchmark, exposure-matched benchmark, capital-utilization floor, and statistical Alpha test. They therefore establish only positive absolute return under the recorded simulator. The later benchmark audit invalidated the live-readiness decision: the candidate underperformed every tested fully invested broad index and the all-stock equal-weight return, while its estimated Alpha was not statistically distinguishable from zero. Candidate v2 remains a research strategy only.
