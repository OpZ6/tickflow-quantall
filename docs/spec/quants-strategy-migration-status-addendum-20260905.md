# Quants Strategy Migration Status Addendum

Historical snapshot, superseded by [core acceptance](quants-strategy-core-acceptance-20260905.md). The price-volume money-flow fallback described below has since been removed: V5 requires real `net_mf_amount` and remains observation-only. Earlier audit/build counts below are not the current acceptance results.

The current checkout now contains independently loadable versioned migration IDs:

- `quants_vcp_legacy_v1`
- `quants_growth_trend_legacy_v1`
- `quants_cup_handle_legacy_v1`
- `quants_high_tight_flag_legacy_v1`
- `quants_pullback_low_absorb_legacy_v1`

The migration smoke audit confirms all five IDs load through `StrategyEngine` with no loader errors. TickFlow targeted migration tests, matrix backtest tests, source V1/V3/V5 detector tests, contract validation, and the frontend production build pass.

The current real-cache reconciliation is still an alignment diagnostic, not a final strategy-return acceptance gate: V1, V3, and V4 each have 0/242 valid mismatches after porting the optimized contraction and continuity-candidate semantics; V5 has 3/242. V5's remaining cases are explained by the real cache not carrying Quants' original `net_mf_5d` field, so TickFlow uses its documented fallback price-volume estimate. No strategy-return or full-selection acceptance is claimed from this read-only audit.
