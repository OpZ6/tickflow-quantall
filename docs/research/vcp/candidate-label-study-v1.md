# Frozen VCP recall and false-breakout study v1

The source-compatible `quants_vcp_legacy_v1` detector is the frozen recall layer. Research
filters must consume its candidates and may not redefine its swing, contraction, pivot, volume
or trend-template calculations. Optional confirmation and market filters remain disabled here.

Discovery uses 2021-09-06 through 2023-12-29. A setup is de-duplicated by symbol, pivot date and
scale. Its executable price is the next tradable daily open. The primary label is whether price
reaches +10% before -7% within 20 trading bars; if both levels occur in one daily bar it is treated
as a failure. A stricter secondary label requires +20% before -7% within 40 bars.

Candidate features must be known by the signal close, except `gap_to_signal_close`, which is only
known at the following open and can only support an execution-time chase rejection. Discovery
outputs are stored under `data/research/vcp/candidate-labels/source-vcp-v1/`.

The 2024-01-01 through 2025-09-04 interval is reserved for validation until a small filtering rule
is frozen. The previously inspected 2025-09-05 onward interval cannot serve as a clean holdout.

## Discovery findings (2026-09-06)

- The frozen detector produced 1,258 de-duplicated setups: 492 in 2021-2022 and 766 in 2023.
  The primary true-breakout rate was 30.52%; median 20-day return was -3.02%.
- A theory-first sequence requiring shallower contractions, a tight right side, pre-pivot volume
  dry-up, positive 63-day momentum, rising MA50, strong-volume breakout and a fresh pivot did not
  validate. The strictest rule rose to 34.92% in 2021-2022 but fell to 25.71% in 2023.
- A regularized shallow histogram gradient model was trained only on 2021-2022 causal features.
  Its in-sample AUC was 0.9707, while 2023 AUC was 0.5381. A cutoff frozen at the development
  top 30% retained 183 validation setups, with 33.88% true breakouts and a negative mean 20-day
  return. This model is rejected as overfit.
- Board and price buckets were unstable across years. Breakout-day turnover of at least 3% was
  directionally more stable, but it did not create positive mean 20-day returns on its own. It may
  be used only as a pre-declared attention/liquidity feature in a later candidate.
- The original Quants warehouse cannot supply point-in-time fundamentals or industry ranks for
  this discovery period. `dm_daily_factor` and `dm_finance_factor` begin usable continuous coverage
  on 2025-11-18, and `dwd_quarter_finance` contains only 2026 announcements. Current classifications
  must not be backfilled into 2021-2023.

These results keep the source-compatible detector unchanged and reject both the mechanical
"classic VCP" gate and the learned classifier. The next detector-quality iteration must add causal
right-side structure information at candidate generation time, then repeat the same time split.

## Iteration 4 portfolio diagnostics (2026-09-06)

- Adding signal-day turnover as a ranking input and widening the stop from 5% to 7% improved the
  weak baseline, but the resulting 2021-2023 account still lost 60.59% with a 21.57% win rate and
  a 0.568 aggregate monetary profit factor. The change is directional evidence, not acceptance.
- A narrow early-recovery filter (MA20 breadth 30%-50%, breadth higher than five trading bars ago,
  and turnover at least 3%) paired with the frozen +10%/-7% label exits produced +4.66% total,
  38.58% winning trades, 1.77 mean-win/mean-loss payoff, and a 1.102 aggregate monetary profit
  factor across 127 trades. Average exposure was only 10.15%; 2023 returned -2.16%. It is a useful
  diagnostic but fails practical acceptance.
- Removing only the five-day breadth-improvement condition increased trades from 127 to 231 and
  average exposure from 10.15% to 17.71%, but total return fell to -13.73%, Sharpe to -0.63, and
  aggregate monetary profit factor to 0.844. Candidate supply cannot be expanded by simply
  relaxing the market gate.
- A +10% fixed take-profit is label-aligned but not a final trend-following exit. It suppresses the
  large-winner right tail and must not define the final Minervini-style strategy.

The method-level comparison and next specification are recorded in
`minervini-sepa-gap-audit-v1.md`.
