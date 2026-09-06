# Minervini SEPA / VCP gap audit v1

Date: 2026-09-06

## Conclusion

`quants_vcp_legacy_v1` is a source-compatible migration of the original Quants V1 detector, but
the source detector is a technical VCP approximation rather than a complete implementation of
Mark Minervini's SEPA process. Migration parity therefore does not establish strategy fidelity.

The current detector remains the frozen high-recall candidate layer. It must not be promoted as a
live-trading strategy until a separate research strategy supplies point-in-time leadership and
fundamental evidence, more faithful setup grading, and a complete risk/exit model.

## What is already represented

- Daily trend alignment: close above MA50, MA50 above MA150, and MA150 above MA200.
- Positive 63-, 126-, and 252-trading-bar returns.
- Cross-sectional relative-strength percentile, with a default minimum of 85.
- Price within 12% of its rolling 252-bar high.
- Multi-scale swing scanning and at least two pullbacks.
- Contracting pullback depth, clustered highs or rising lows, right-side tightness, volume dry-up,
  a pivot, maximum chase distance, breakout volume, and breakout close location.
- A separate next-open execution engine with A-share trading constraints, costs, portfolio slots,
  stop loss, take profit, trailing exits, and a strategy MA exit.

## Material gaps from the complete method

1. **Trend template fidelity.** The detector does not explicitly require a rising MA200 over a
   prior interval or a minimum distance above the 52-week low. Positive fixed-horizon returns are
   only an approximation.
2. **Point-in-time fundamentals.** Earnings and sales acceleration, earnings surprises or estimate
   revisions, and margin improvement are absent from the VCP backtest. The local metrics file has
   broad 2026 coverage, but only one symbol has announcements during 2021-2023; it cannot support
   the discovery interval.
3. **Industry leadership.** The migrated detector ranks stock RS but does not apply the original
   Quants industry-strength and industry-leader components. Historical membership and ranks must
   be point-in-time before use.
4. **Setup quality.** Swing depth contraction is useful recall logic, but it does not fully encode
   base stage/count, prior advance, duration and symmetry of each contraction, overhead supply,
   natural versus abnormal reactions, constructive shakeouts, or discretionary chart context.
5. **Entry quality.** The source configuration supports pivot, cheat, pullback, and retrigger ideas,
   while the migrated backtest currently exercises a smaller subset. It does not yet grade risk
   from the actual setup low and entry distance as a single trade plan.
6. **Exit and portfolio management.** A generic MA20 cross plus one account-level fixed stop is not
   the complete Minervini sell process. There is no progressive exposure, position sizing from
   stop distance, add-on/pyramiding logic, break-even tightening, abnormal-action exit, or rule for
   retaining exceptional winners.

## Why published Minervini performance is not a VCP-only benchmark

Published performance refers to the complete SEPA decision and portfolio process in selected U.S.
growth stocks. It cannot be used as an expected return for every mechanical VCP scan, for an equal
weight A-share portfolio, or for the 2021-2023 market regime. The relevant engineering target is
stable positive expectancy and benchmark-relative return across isolated periods, not reproducing
a trader's best historical return.

## Research implication

The +10% before -7% within 20 bars label is useful for studying false breakouts. A fixed +10%
portfolio take-profit is only a diagnostic exit: it converts that label into realized PnL but also
removes the right tail that a trend-following strategy needs. Future work should retain separate
outcomes for early failure, ordinary follow-through, and large-winner continuation, then build a
two-stage model:

1. preserve the frozen detector for candidate recall;
2. grade causal setup quality, fundamental acceleration, industry/stock leadership, and market
   context;
3. size each position from entry-to-technical-stop risk;
4. exit failed breakouts quickly while allowing confirmed leaders to compound through a trailing
   or structure-based sell rule.

The 2024-01-01 through 2025-09-04 validation interval remains sealed until this revised specification
and its thresholds are frozen.
