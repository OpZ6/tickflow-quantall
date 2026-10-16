// ===== 自定义模块 API 客户端 =====
// 从 lib/api.ts 拆分而来: 所有 QuantX / 股票池 / 缠论 / 财务分析等自定义版面的
// API 类型与客户端集中于此。上游仓库不存在此文件 → 未来同步零冲突。
// 共享 HTTP 层 (request/ApiError) 与上游公共类型仍由 lib/api.ts 提供。

import { request, COMPUTE_REQUEST_TIMEOUT_MS, type KlineRow, type LevelType, type PriceLevel } from '@/lib/api'

export interface ChanlunStatus {
  available: boolean
  viewer_url: string | null
  detail: string
  capabilities: {
    structures: string[]
    main_indicators: number
    sub_indicators: number
  }
}

export interface FinancialAnalysis {
  symbol: string
  as_of: string
  model: string
  score: { total: number; components: Record<string, number>; quality_flag: boolean }
  cards: Record<string, Record<string, number | null>>
  coverage: { periods: number; latest_period: string | null }
  warnings: string[]
}

export interface ResearchBacktestRunSummary {
  research_key: string
  run_id: string
  result_id?: string | null
  phase?: string | null
  started_at?: string | null
  finished_at?: string | null
  experiment: string
  purpose?: string | null
  strategy_id?: string | null
  start?: string | null
  end?: string | null
  stats: Record<string, any>
}

export type ChartInterval = '1m' | '5m' | '15m' | '30m' | '60m' | '1d' | '1w' | '1mo'
export type ChartAdjustment = 'none' | 'qfq' | 'hfq'
export type ChartRangeName = '1m' | '3m' | '6m' | '1y' | '3y' | '5y' | 'all' | 'custom'

export interface ChartDataMeta {
  indicator_metadata?: Record<string, {
    algorithm_version: string
    parameters: { h: number; gamma: number; kf: number; n: number }
    capital_basis: 'ordinary_float'
    price_basis: 'unadjusted'
    bar_basis: 'observed_stock_daily_bars'
    latest_share_basis: string
    warmup_bars: number
    available: boolean
  }>
  requested_interval: ChartInterval
  effective_interval: ChartInterval
  requested_adjustment: ChartAdjustment
  adjustment: ChartAdjustment
  requested_start: string
  requested_end: string
  required_fetch_start: string
  source: string
  coverage_start: string | null
  coverage_end: string | null
  complete: boolean
  warmup_bars: number
  warmup_complete: boolean
  required_warmup_bars: number
  actual_warmup_bars: number
  indicator_readiness: Record<string, {
    required_warmup_bars: number
    actual_warmup_bars: number
    status: 'ready' | 'partial'
  }>
  input_fingerprint: string
  warnings: string[]
}

export type ChartLayerCategory = 'pattern' | 'strategy' | 'event' | 'plan'
export type ChartLayerStatus = 'available' | 'insufficient_data' | 'unavailable' | 'error'

export interface AnnotationEvidenceMetric {
  name: string
  value: unknown
  threshold?: unknown
  unit?: string
  passed?: boolean | null
}

export interface AnnotationEvidence {
  id: string
  title: string
  summary: string
  metrics: AnnotationEvidenceMetric[]
  reason_codes: string[]
  warnings: string[]
  metadata: Record<string, unknown>
}

export interface AnnotationMarker {
  id: string
  layer_id: string
  date: string
  role: string
  price?: number | null
  label: string
  evidence_id?: string | null
  detected_at?: string | null
  confirmed_at?: string | null
  invalidated_at?: string | null
  count: number
}

export interface AnnotationLine {
  id: string
  layer_id: string
  role: string
  value: number
  start_date?: string | null
  end_date?: string | null
  end_value?: number | null
  label: string
  evidence_id?: string | null
}

export interface AnnotationZone {
  id: string
  layer_id: string
  role: string
  start_date: string
  end_date: string
  low?: number | null
  high?: number | null
  label: string
  evidence_id?: string | null
  confirmed_at?: string | null
}

export interface AnnotationSegment {
  id: string
  layer_id: string
  role: string
  points: { date: string; price: number }[]
  label: string
  evidence_id?: string | null
  confirmed_at?: string | null
}

export interface ChartAnnotationLayer {
  schema_version: 1
  id: string
  category: ChartLayerCategory
  title: string
  status: ChartLayerStatus
  algorithm_version?: string | null
  input_fingerprint?: string | null
  price_basis: ChartAdjustment
  markers: AnnotationMarker[]
  lines: AnnotationLine[]
  zones: AnnotationZone[]
  segments: AnnotationSegment[]
  evidence: AnnotationEvidence[]
  warnings: string[]
}

export interface ChartDataResponse {
  symbol: string
  asset_type: 'stock' | 'etf' | 'index'
  rows: KlineRow[]
  /** 隐藏预热 + 可见区间，仅用于分析计算，不直接绘制。 */
  analysis_rows: KlineRow[]
  /** 与 rows 同周期、同复权、同裁剪窗口计算的 11 组关键价位。 */
  levels: Record<LevelType, PriceLevel[]>
  annotation_layers?: ChartAnnotationLayer[]
  meta: ChartDataMeta
}

export interface ChartDataQuery {
  symbol: string
  assetType?: 'stock' | 'etf' | 'index'
  interval: ChartInterval
  adjustment: ChartAdjustment
  range: ChartRangeName
  startDate?: string
  endDate?: string
  layers?: ChartLayerCategory[]
  strategyIds?: string[]
  sourceRunId?: string
  paramsFingerprint?: string
  warmupBars?: number
  indicatorWarmups?: Record<string, number>
  indicatorParams?: Record<string, Record<string, unknown>>
}

export interface StrategyPreviewRequest {
  symbol: string
  assetType: 'stock' | 'etf' | 'index'
  timeframe: ChartInterval
  startDate: string
  endDate: string
  strategyIds: string[]
  paramsByStrategy?: Record<string, Record<string, unknown>>
}

export interface StrategyPreviewResponse {
  mode: 'single_asset_preview'
  symbol: string
  asset_type: 'stock' | 'etf' | 'index'
  timeframe: ChartInterval
  calculation_price_basis: 'qfq'
  layers: ChartAnnotationLayer[]
  warnings: string[]
}

export interface MarketDatasetContract {
  dataset_id: string
  description: string
  schema_version: number
  primary_key: string[]
  partition_keys: string[]
  required_columns: string[]
  field_units: Record<string, string>
  freshness: string
}

export interface MarketSourceContract {
  source_id: string
  display_name: string
  supported_datasets: string[]
  collector_type: 'provider' | 'python'
  collector: string
  credentials_ref: string | null
  credentials_configured: boolean
  dependency_available: boolean
  max_retries: number
  freshness_required: boolean
}

export interface MarketSourceHealth {
  source_id: string
  status: string
  record_count?: number
  collected_at?: string | null
  used_fallback?: boolean
  error?: string | null
}

export interface MarketDataFoundation {
  datasets: MarketDatasetContract[]
  sources: MarketSourceContract[]
  routes: Array<{ dataset_id: string; sources: string[] }>
  health: {
    latest_trade_date: string | null
    run_id: string | null
    status: string
    sources: MarketSourceHealth[]
    datasets: Array<{
      dataset_id: string
      partition_count: number
      latest_partition: string | null
    }>
    snapshot_retention: {
      status?: string
      dry_run?: boolean
      retention_days?: number
      cutoff_date?: string
      metadata_count?: number
      blob_count?: number
      bytes_reclaimable?: number
      error?: string
    }
  }
}

// ===== Chanlun (缠论原生分析) =====
export interface ChanlunBi {
  start_time: number
  start_price: number
  end_time: number
  end_price: number
  direction: 'up' | 'down'
  start_index: number | null
  end_index: number | null
  is_sure: boolean
  confirm_index: number | null
}

export interface ChanlunSegment {
  start_time: number
  start_price: number
  end_time: number
  end_price: number
  direction: 'up' | 'down'
  is_sure: boolean
}

export interface ChanlunZhongshu {
  start_time: number
  end_time: number
  low: number
  high: number
}

export interface ChanlunBsp {
  time: number
  direction: 'buy' | 'sell'
  type: string
  price: number
  level: 'bi' | 'seg'
  fx_confirmed: boolean
}

export interface ChanlunAnalysis {
  merged_klines: { start_time: number; end_time: number; high: number; low: number; dir: string; n: number }[]
  fenxing: { time: number; type: 'bottom' | 'top'; value: number }[]
  bi: ChanlunBi[]
  segments: ChanlunSegment[]
  zhongshu: ChanlunZhongshu[]
  macd: { time: number; dif: number; dea: number; histogram: number }[]
  bsp: ChanlunBsp[]
  _meta?: {
    algorithm: string
    version: string
    data_fingerprint: string
    final_confirmed: boolean
  }
}

export interface ChanlunCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export interface ChanlunCandleRow {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export interface ChanlunOfficialResponse {
  available: boolean
  detail?: string
  source?: 'pro' | 'free'
  name?: string | null
  /** ZenChart 窗口只用于时间戳严格对齐审计，不替换本地 K 线。 */
  candles?: ChanlunCandle[]
  counts?: { bi: number; segments: number; zhongshu: number; bsp: number }
  official?: {
    bi: ChanlunBi[]
    segments: ChanlunSegment[]
    zhongshu: ChanlunZhongshu[]
    bsp: ChanlunBsp[]
  }
}

export interface EtfMomentumRow {
  rank: number
  previous_rank: number | null
  rank_change: number | null
  symbol: string
  name: string
  as_of: string
  return_1d_pct: number
  return_5d_pct: number
  return_20d_pct: number
  return_50d_pct: number
  weighted_momentum_pct: number
  slope_momentum_pct: number | null
  volume_ratio_5_20: number | null
  momentum_change_pct: number | null
  previous_metrics: Record<string, number | null>
}

export interface EtfMomentumResponse {
  available: boolean
  detail?: string | null
  unit: 'percent'
  formula?: string
  rows: EtfMomentumRow[]
  requested_count?: number
  excluded_count?: number
}

export interface SectorResearchStat {
  sample_count: number; date_count: number; mean_excess_pct: number | null
  median_return_pct: number | null; outperform_pct: number | null
}
export interface SectorResearchResponse {
  available: boolean; detail: string; trade_date?: string; dimension?: string; horizon?: number
  phase: Array<{ sector: string; x: number | null; y: number | null; previous_x: number | null; previous_y: number | null
    breadth_pct: number | null; amount_yi: number; member_count: number; breadth_members: number; pressure_members: number }>
  outcomes: null | { cells: Array<SectorResearchStat & { band: number; expanding: boolean }>
    sectors: Array<SectorResearchStat & { sector: string; breadth_pct: number | null; breadth_change_5d_pp: number | null }>
    pending_count: number; missing_count: number; matured_count: number; first_date: string | null; last_date: string | null }
}
export interface ConceptOverlapResponse {
  available: boolean; detail: string; concepts: string[]; sector: string; member_count: number; related_count: number
  rows: Array<{ sector: string; member_count: number; common_count: number; jaccard_pct: number
    coverage_pct: number; other_coverage_pct: number; common_codes: string[]; common_members: Array<{ code: string; name: string }> }>
  edges: Array<{ source: string; target: string; common_count: number; jaccard_pct: number }>
}

export interface SectorFlowResponse {
  available: boolean
  quality: 'observed' | 'proxy' | 'unavailable'
  basis?: string
  unit?: 'CNY'
  detail?: string | null
  dates?: string[]
  rows: { sector: string; total_flow_yuan: number; points: { date: string; flow_yuan: number }[] }[]
}

export interface SectorRadarRow {
  rank: number
  sector: string
  as_of: string
  score: number
  return_pct: number
  flow_yuan: number
  flow_ratio_pct: number
  ema_swing_pct: number
  positive_days_30: number
  swing_ratio_pct: number
  swing_amount_yuan: number
  swing_rank: number
  swing_rank_pct: number
  swing_score: number
  swing_rank_change_1d: number
  swing_rank_change_3d: number
  swing_rank_change_5d: number
  swing_top_30d: number
  swing_bottom_30d: number
  ratio_rank: number
  ratio_rank_pct: number
  ratio_score: number
  ratio_rank_change_1d: number
  ratio_rank_change_3d: number
  ratio_rank_change_5d: number
  ratio_top_30d: number
  ratio_bottom_30d: number
  amount_rank: number
  amount_rank_pct: number
  amount_score: number
  amount_rank_change_1d: number
  amount_rank_change_3d: number
  amount_rank_change_5d: number
  amount_top_30d: number
  amount_bottom_30d: number
}

export interface SectorRadarResponse {
  available: boolean
  quality: 'observed' | 'proxy' | 'unavailable'
  basis?: string
  detail?: string | null
  as_of?: string
  available_dates?: string[]
  universe_size?: number
  unit?: 'CNY'
  rows: SectorRadarRow[]
  rank_history?: Record<string, { date: string; swing_rank: number; ratio_rank: number; amount_rank: number; swing_rank_pct: number; ratio_rank_pct: number; amount_rank_pct: number }[]>
}

export interface SectorMemberRow {
  symbol: string
  name: string
  return_pct: number | null
  main_net_amount: number | null
  active_buy_net_amount: number | null
}

export interface SectorMembersResponse {
  available: boolean
  detail?: string
  as_of?: string
  sector?: string
  member_count?: number
  flow_quality?: 'observed' | 'proxy' | 'unavailable'
  active_quality?: 'observed' | 'unavailable'
  metrics: Record<'return_pct' | 'main_net_amount' | 'active_buy_net_amount', { top: SectorMemberRow[]; bottom: SectorMemberRow[] }>
}

export interface MacroContributionRow {
  name: string
  return_pct?: number
  signed_deviation?: number
  share?: number
  direction?: number
  state: string
  contribution_pct?: number
}

export interface MacroDispersionResponse {
  available: boolean
  window: string
  unit: 'percent'
  as_of?: string
  basis?: string
  detail?: string
  mean_pct: number
  dispersion: number
  ma3: number
  percentile: number | null
  ma3_percentile: number | null
  change_1d: number
  change_5d: number
  zone: string
  industry_count: number
  industry_level?: number
  history: { date: string; dispersion: number; ma3: number; mean_pct?: number; industry_count?: number }[]
  indices: { symbol: string; label: string; name: string; points: { date: string; normalized: number }[] }[]
  contributions: MacroContributionRow[]
  contribution_windows: Record<'1' | '3' | '5' | '10', { high: MacroContributionRow[]; low: MacroContributionRow[] }>
}

export interface PositionResult {
  shares: number
  market_value: number
  risk_budget: number
  planned_loss: number
  capital_usage_pct: number
  reward_risk: number
  target_price: number
  target_r: number
  breakeven_price: number
  breakeven_r: number
  projected_profit: number
  actual_risk_pct: number
  stop_pct: number
  target_upside_pct: number
  risk_level: string
  cash_limited: boolean
  warnings: string[]
}

export interface PitResult { target: number; depth_pct: number; upside_pct: number }
export interface DrawdownResult {
  actual_r: number; draw_amount: number; exit_price: number
  max_profit_pct: number; locked_profit_pct: number; target_achieved: boolean
}

export interface SimulationResult {
  paths: number
  trades: number
  kelly_pct: number
  half_kelly_pct: number
  expectancy_r: number
  break_even_pct: number
  p10_final: number
  p50_final: number
  p90_final: number
  p50_max_drawdown_pct: number
  p95_max_drawdown_pct: number
  loss_probability_pct: number
  sample_paths: number[][]
  reverse: {
    recommended_risk_pct: number; test_risk_pct: number; target_required_risk_pct: number | null
    drawdown_risk_pct: number; limiting_factor: string; target_reachable: boolean; target_return_pct: number
  }
  strategies: {
    id: string; name: string; basis: 'decision' | 'theory'; risk_pct: number
    p10_final: number; p50_final: number; p90_final: number; p80_drawdown_pct: number
    p50_drawdown_pct: number; p95_drawdown_pct: number; ruin_probability_pct: number
    halve_probability_pct: number; p10_path: number[]; median_path: number[]; p90_path: number[]; sample_paths: number[][]
  }[]
  distribution: { bins: { from: number; to: number; count: number; density: number }[] }
}

export interface CatalogRecord {
  trade_date: string
  stage: string
  metrics: Record<string, number | string | boolean | null>
  themes: Array<{ name: string; count: number }>
  change_summary?: string
  deltas?: Record<string, number>
  multiday_available?: boolean
}

export interface CatalogData {
  schema_version: number
  generated_at: string
  stats: { total_dates: number; complete: number; degraded?: number; failed?: number; data_only?: number; draft_only?: number }
  records: CatalogRecord[]
  theme_events?: Array<{ trade_date: string; name: string; count: number; lifecycle: string }>
}

export interface QuantXDataTables {
  trade_date: string
  market_overview?: any
  market_breadth?: any
  market_liquidity?: any
  limit_summary?: any
  limit_ladder?: any
  limit_stocks?: any
  promotion_stats?: any
  premium_stats?: any
  theme_snapshot?: any
  theme_rankings?: any
  theme_history?: any
  theme_stocks?: any
  sentiment_state?: any
  risk_signals?: any
  participation?: any
  sector_fund_flow?: any
  sector_rotation?: any
  screening_candidates?: any
  trend_history?: any
  trend_pool?: any
  _computed?: any
  quality?: any
  manifest?: any
}

export interface QuantXReviewIndexRow {
  code: string
  name: string
  close: number | null
  pct_chg: number | null
}

export interface QuantXRiskRadar {
  headline: string
  summary: string
  counter_evidence: string
  coverage: { complete: number; total: number }
  algorithm_version: string
  missing: string[]
  dimensions: Array<{
    key: string
    title: string
    tone: 'red' | 'amber' | 'green' | null
    status: string
    metrics: Array<{ label: string; value: string; tone: 'red' | 'amber' | 'green' | null; judgement: string | null }>
    explanation: string
    details: Array<{ label: string; value: string; tone: 'red' | 'amber' | 'green' | null; judgement: string | null }>
    series: Array<{
      kind: 'ordinary' | 'sentiment'
      code: string
      name: string
      deviation_pct: number
      change_pct: number | null
      close: number | null
      ma10: number | null
      zone: string
      tone: 'red' | 'amber' | 'green'
    }>
    source: string
  }>
}

export interface QuantXReviewDataV2 {
  trade_date: string
  metric_strip: {
    indexes: QuantXReviewIndexRow[]
    up_count: number | null
    down_count: number | null
    flat_count: number | null
    total_amount_yi: number | null
    advance_rate: number | null
  }
  emotion: {
    market_heat: { score: number | null; zone: string }
    short_term_sentiment: { score: number | null; zone: string }
    trend_sentiment: { score: number | null; zone: string }
    loss_effect: { severity: string; limit_down_count: number | null }
    height_trend: {
      days: Array<{ date: string; max_board: number }>
      latest_max_board: number
      previous_high_5d: number | null
      height_compressed: boolean
      evidence: string
    }
    daily_summary: string
  }
  sections: {
    s0: {
      diagnosis: Array<{ name: string; value: string; zone: string }>
      risks: Array<{ name: string; triggered: boolean; status?: string; evidence?: string }>
    }
    s1: {
      indexes: QuantXReviewIndexRow[]
      kline_history: Array<Record<string, number | string | null>>
      up_count_history: Array<{ date: string; up_count: number; down_count: number; total_amount_yi: number | null }>
      width_heat: Array<{ code: string; name: string; ma5: number | null; ma10: number | null; ma20: number | null; ma60: number | null }>
      width_heat_level2: Array<{ code: string; name: string; ma5: number | null; ma10: number | null; ma20: number | null; ma60: number | null }>
      margin: { date: string; rzye_yi: number | null; rz_net_buy_yi: number | null } | null
      margin_history: Array<{ date: string; rzye_yi: number | null; rz_net_buy_yi: number | null }>
      congestion: {
        latest: { date: string; close: number | null; top5_amount: number | null; total_amount: number | null; congestion_pct: number | null }
        table: Array<[string, number | null, number | null, number | null, number | null]>
      } | null
    }
    s2: {
      participation: { conditions: Array<{ name: string; value: unknown; ok: boolean | null; available: boolean | null }>; verdict: string; satisfied: number; total: number } | null
      risk_radar: QuantXRiskRadar | null
      ebb_risk: { verdict: string; signal_count: number } | null
      themes_pywencai: Array<{ name: string; count: number | null; rank: number | null }>
      themes_ths: Array<{ tag: string; count: number | null; rank: number | null }>
      new_high: {
        status: string
        stocks: Array<{ code: string; name: string; pct_chg: number | null }>
        total_stocks?: number
        coverage_pct?: Partial<Record<'concept' | 'attribute' | 'industry_level1' | 'industry_level2', number>>
        mapping_semantics?: 'latest_ext_snapshot_proxy'
        windows?: Partial<Record<'1' | '5' | '10' | '20', {
          valid_days: number
          date_range: string[]
          dimensions: Record<'concept' | 'attribute' | 'industry_level1' | 'industry_level2', Array<{
            name: string
            current_count: number
            unique_count: number
            active_days: number
            average_share_pct: number
            current_share_pct: number
            weighted_share_pct: number
            change_pct: number
            status: string
          }>>
        }>>
      } | null
    }
    s3: {
      emotion_scores: { market_heat?: number | null; short_term?: number | null; trend?: number | null }
      emotion_zones: { market_heat?: string; short_term?: string; trend?: string }
      advance: { advance_rate?: number | null; premium_rate?: number | null }
      advance_history: Array<{ date: string; advance_rate: number | null; premium_rate: number | null; limit_up_count: number | null; max_board: number | null; seal_rate: number | null }>
      ebb_signals: Array<{ name: string; triggered: boolean | null; available: boolean | null; value?: unknown; baseline?: unknown }>
      crash_signals: Array<{ name: string; triggered: boolean | null; status: string; evidence: string }>
      ladder_grid: Array<{ level: string; count: number; names: string[] }>
      ladder_detail: Array<{
        code: string
        name: string
        limit_times: number
        theme_name: string
        turnover_pct: number | null
        amount_yi: number | null
        first_seal_time: string | null
        last_seal_time: string | null
        broken_count: number | null
        seal_amount_yi: number | null
      }>
      seal_quality: {
        total_limit_up_count: number
        process_coverage_count: number
        process_coverage_pct: number | null
        broken_count_coverage_count: number
        no_break_count: number
        no_break_ratio_pct: number | null
        repeat_break_count: number
        repeat_break_ratio_pct: number | null
        first_seal_coverage_count: number
        early_seal_ratio_pct: number | null
        last_seal_coverage_count: number
        late_final_seal_ratio_pct: number | null
        seal_amount_coverage_count: number
        median_seal_amount_yi: number | null
      }
      height_history: Array<{ date: string; height: number; name: string; names: string[]; second_height: number; second_names: string[]; turnover_pct: number | null; amount_yi: number | null }>
    }
    s4: {
      sector_flow: {
        top_in: Array<Record<string, unknown>>
        top_out: Array<Record<string, unknown>>
        gross_inflow_yi?: number
        gross_outflow_yi?: number
        net_inflow_yi?: number
        inflow_count?: number
        outflow_count?: number
        sector_count?: number
      }
      sector_treemap: Array<{ name: string; value: number | null; pct_chg: number | null }>
    }
    s5: {
      candidates: QuantXCandidate[]
      candidate_funnel: {
        algorithm_version: string
        regime: {
          key: 'strong_attack' | 'strong_divergence' | 'neutral_rotation' | 'weak_defense'
          label: string
          policy: string
          weights: Record<'logic' | 'strength' | 'setup' | 'execution', number>
          evidence: Record<string, number | boolean>
        }
        universe_count: number
        stages: Array<{ key: string; label: string; input_count: number; passed_count: number; eliminated_count: number }>
        branch_counts: Record<string, number>
        audit_rows: QuantXCandidate[]
      } | null
      market_anchors: QuantXCandidate[]
    }
    s6: {
      position: { band: string; action: string } | null
      scenes: Array<{ name: string; condition: string; tone: 'positive' | 'neutral' | 'negative' }>
    }
  }
  data_foundation: {
    schema_version: 'quantx-review.v2'
    read_mode: 'canonical_view_v2'
    cache_artifact: null
    source_json_read: false
    presentation_cache_read: false
    canonical_fields: string[]
    derived_fields: string[]
    view_algorithm_version: string
    derived_field_status: Record<string, {
      status: 'available' | 'missing_inputs'
      inputs: string[]
      missing_inputs: string[]
      algorithm_version: string
    }>
    presentation_fields: string[]
    presentation_cache_fields: string[]
    deprecated_fields: string[]
    fallback_fields: string[]
    implicit_cache_fields: string[]
  }
}

export interface QuantXCandidate {
  code: string
  name: string
  theme: string
  setup_type: 'momentum_leader' | 'divergence_acceptance' | 'healthy_pullback' | 'early_breakout' | null
  setup_label: string
  score: number | null
  component_scores: Record<'logic' | 'strength' | 'setup' | 'execution', number> | null
  action_status: 'focus' | 'wait_confirmation' | 'wait_divergence' | 'context_only'
  reason: string
  confirmation: string
  invalidation: string
  risk_tags: string[]
  source_signals: string[]
  board_height: number
  limit_class_pct: number
  pct_chg: number | null
  active_days: number
  stage: string
  eliminated_reason: string
  stage_path: string[]
}

export type QuantXReviewData = QuantXReviewDataV2

export interface QuantXWindowComponent {
  key: 'heat' | 'breadth' | 'relay' | 'risk'
  first: number | null
  last: number | null
  delta: number | null
  arrow: 'up' | 'down' | 'flat' | 'missing'
}

export interface QuantXWindowSignal {
  window: number
  date_range: string[]
  valid_days: number
  confidence: 'high' | 'medium' | 'low'
  market: { direction: string; tone: string; components: QuantXWindowComponent[] }
  themes: {
    observed_days: number
    mainline: QuantXWindowTheme[]
    warming: QuantXWindowTheme[]
    cooling: QuantXWindowTheme[]
  }
  sector_flow: any
}

export interface QuantXWindowTheme {
  name: string
  active_days: number
  persistence_pct: number
  average_strength: number
  strength_change: number
  latest_strength: number
  source_count: number
  leaders: Array<{ code: string; name: string }>
}

export interface QuantXSectorFlowContinuity {
  semantics: string
  basis: string
  available: boolean
  coverage: number
  direction: string
  industries: any[]
  rule_candidates: any[]
}

export interface QuantXOpportunityWindow {
  window: 5 | 20
  valid_days: number
  date_range: string[]
  coverage_confidence: Record<'themes' | 'sectors' | 'stocks', number>
  themes: Array<{
    name: string
    score: number
    active_days: number
    last_seen: string
    lifecycle?: string
  }>
  sectors: Array<{
    name: string
    score: number
    active_days: number
    last_seen: string
    net_inflow_sum_yi: number
    last_net_inflow_yi?: number | null
    last_pct_chg?: number | null
  }>
  stocks: Array<{
    code: string
    name?: string
    score: number
    active_days: number
    last_seen: string
    priority?: string
    source?: string
  }>
}

export interface QuantXOpportunityRadar {
  schema_version: 'opportunity-radar-v2'
  default_window: 5
  windows: Record<'5' | '20', QuantXOpportunityWindow>
  coverage_confidence: Record<string, number>
  themes: QuantXOpportunityWindow['themes']
  sectors: QuantXOpportunityWindow['sectors']
  stocks: QuantXOpportunityWindow['stocks']
}

export interface QuantXMultidaySnapshot {
  schema_version: string
  generated_at: string
  trade_date: string
  llm: false
  window_signals: Record<'5' | '10' | '20', QuantXWindowSignal>
  calendar: Array<Record<string, any> & { trade_date: string }>
  window_statistics: Record<'5' | '10' | '20', Record<string, any>>
  theme_lifecycle: { current: any[]; events: any[]; exited: any[]; heatmap: { dates: string[]; rows: Array<{ name: string; values: Array<number | null> }> } }
  factor_attribution: Array<{ name: string; count: number }>
  opportunity_radar: QuantXOpportunityRadar
  sector_flow_continuity: QuantXSectorFlowContinuity
  data_coverage: { theme_days: number; sector_flow_days: number; window_days: number }
}

export interface QuantXAdvancedCard {
  status: 'ok' | 'unavailable'
  rows?: number
  reason?: string
  note?: string
  data: Record<string, any>
}

export interface QuantXAdvancedSnapshot {
  schema_version: 'tickflow-quantx-advanced-v1'
  trade_date: string
  generated_at: string
  coverage: { available: number; total: number; history_start?: string; history_end?: string }
  cards: Record<string, QuantXAdvancedCard>
}

export interface QuantXObservability {
  trade_date: string
  pipeline_job_id: string | null
  quantx_run_id: string | null
  status: string
  published_at: string | null
  sources: Array<{
    source_id: string
    display_name: string
    required: boolean
    status: string
    freshness: 'fresh' | 'reused'
    record_count: number
    credential_readiness: string
    dependency_readiness: string
    manifest_health: string
    live_probe: string
    error: string | null
    error_kind: string | null
  }>
  facts: Array<{
    dataset_id: string
    path: string
    status: string
    row_count: number | null
    coverage: number
    quality_level: string
    sha256: string | null
  }>
  fact_summary: { expected_partition_count: number; present_partition_count: number; gap_partition_count: number }
  view: { schema_version: string | null; canonical_count: number; derived_count: number; cache_count: number; fallback_count: number; implicit_cache_count: number }
  reconciliation: { status: string; gap_count: number; fingerprint: string | null }
  multiday: { published: boolean; schema_version: string | null; generated_at: string | null }
  catalog: { published: boolean; stage: string | null; generated_at: string | null }
  metrics: { field_drift: number; stale_snapshot: number; empty_result: number; rate_limit: number }
  warnings: string[]
  errors: string[]
  refreshed_at: string
}

export interface QuantXNewHighClusterMembers {
  trade_date: string
  dimension: 'concept' | 'industry_level1' | 'industry_level2'
  window: 1 | 5 | 10 | 20
  cluster_name: string
  valid_days: number
  current_count: number
  window_count: number
  mapping_semantics: 'latest_ext_snapshot_proxy'
  members: Array<{
    code: string
    name: string
    pct_chg: number | null
    current: boolean
    active_days: number
    first_seen: string
    last_seen: string
  }>
}

export interface QuantXNewHighMemberBundle {
  trade_date: string
  mapping_semantics: 'latest_ext_snapshot_proxy'
  datasets: Record<string, QuantXNewHighClusterMembers>
}

export const quantxApi = {
  getCatalog: () =>
    request<CatalogData>(`/api/quantx-data/catalog`),

  buildCatalog: (date?: string) =>
    request<{ status: string; rebuilt: number; trade_date?: string; stats: CatalogData['stats'] }>(`/api/quantx-data/catalog/rebuild${date ? `?trade_date=${encodeURIComponent(date)}` : ''}`, { method: 'POST' }),

  getMultiday: (date: string) =>
    request<QuantXMultidaySnapshot>(`/api/quantx-data/multiday/${encodeURIComponent(date)}`),

  getAdvanced: (date: string) =>
    request<QuantXAdvancedSnapshot>(`/api/quantx-data/advanced/${encodeURIComponent(date)}`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),

  getReviewData: (date: string) =>
    request<QuantXReviewData>(`/api/quantx/review/${encodeURIComponent(date)}/data`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),

  getNewHighClusterMembers: (date: string, dimension: 'concept' | 'attribute' | 'industry_level1' | 'industry_level2', window: 1 | 5 | 10 | 20, name: string) =>
    request<QuantXNewHighClusterMembers>(`/api/quantx-data/new-high/${encodeURIComponent(date)}/members?dimension=${encodeURIComponent(dimension)}&window=${window}&name=${encodeURIComponent(name)}`),

  getNewHighMemberBundle: (date: string) =>
    request<QuantXNewHighMemberBundle>(`/api/quantx-data/new-high/${encodeURIComponent(date)}/member-bundle`),

  getTables: (date: string) =>
    request<QuantXDataTables>(`/api/quantx-data/${date}/tables`),

  runData: (tradeDate: string, options?: { force?: boolean; recompute?: boolean; sources?: string[] }) =>
    request<any>(`/api/quantx-data/runs`, {
      method: 'POST',
      body: JSON.stringify({ trade_date: tradeDate, ...options }),
    }),

  recomputeData: (date: string) =>
    request<any>(`/api/quantx-data/runs/${date}/recompute`, { method: 'POST' }),

  resumeData: (date: string) =>
    request<any>(`/api/quantx-data/runs/${date}/resume`, { method: 'POST' }),

  retrySource: (date: string, source: string) =>
    request<any>(`/api/quantx-data/runs/${date}/sources/${encodeURIComponent(source)}/retry`, { method: 'POST' }),

  getObservability: (date: string, pipelineJobId?: string | null) =>
    request<QuantXObservability>(`/api/quantx-data/observability/${encodeURIComponent(date)}${pipelineJobId ? `?pipeline_job_id=${encodeURIComponent(pipelineJobId)}` : ''}`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),
}

export interface StockPoolSourceStat {
  id: string
  label: string
  stage: string
  expiry: string
  count: number
  overlap_count: number
  status: string
}

export interface StockPoolSubgroup {
  name: string
  count: number
  symbols: string[]
}

export interface StockPoolCluster {
  name: string
  dimension?: string
  count: number
  event_count: number
  up_count: number
  mean_pct_chg: number
  stage_counts: Record<string, number>
  symbols: string[]
  catalysts?: string[]
  subgroups?: StockPoolSubgroup[]
  research_background?: Array<Record<string, unknown>>
  research_count?: number
}

export interface StockPoolThemeContext {
  basis: 'dated_logic' | 'latest_static_proxy'
  window_start: string | null
  sources: Array<{
    source: string
    status: 'ranked' | 'not_ranked' | 'unavailable' | 'ambiguous'
    rank: number | null
    list_size: number | null
    previous_date: string | null
    previous_rank: number | null
    seen_days: number
    available_days: number
    raw_name: string | null
    match_basis: 'name' | 'dated_term' | null
    observed_at: string | null
    quality_level: string | null
    related_narrower?: Array<{ name: string; rank: number | null }>
  }>
}

export interface StockPoolSummary {
  trade_date: string
  published_at?: string | null
  first_published_available?: boolean
  rule_version: string
  status: 'complete' | 'degraded'
  degraded_sources: string[]
  input_generation: string
  instrument_generation?: string
  market_count?: number
  eligible_count: number
  exchange_coverage?: Record<string, { listed: number; market: number; eligible: number }>
  candidate_count: number
  raw_hit_count: number
  overlap_count: number
  event_count: number
  source_stats: StockPoolSourceStat[]
  stage_stats: Array<{ stage: string; count: number }>
  tier_stats: Record<string, number>
  clusters: StockPoolCluster[]
  daily_changes: { status: string; topic_status?: string; previous_date: string | null; counts: Record<string, number>; exits: unknown[] }
  source_quality: Record<string, string>
  theme_context_version?: string
  theme_contexts?: Record<string, StockPoolThemeContext>
}

export interface StockPoolMemberships {
  concept: string[]
  industry_level1: string[]
  industry_level2: string[]
  attribute: string[]
}

export interface StockPoolCandidate {
  symbol: string
  code: string
  name: string
  exchange: string
  price: number
  pct_chg: number
  amount_yi: number
  market_cap_yi: number
  turnover_pct: number
  volume_ratio: number
  source_ids: string[]
  sources: string[]
  primary_stage: string
  tier: 'core' | 'focus' | 'all'
  freshness: string
  topics: string[]
  logic_evidence_count?: number
  unclustered_terms?: string[]
  industry: string
  memberships?: StockPoolMemberships
  primary_concept?: string | null
  evidence?: string
  observation_window?: string
  price_context?: {
    ma10_distance_pct: number | null
    ma20_distance_pct: number | null
    high20_drawdown_pct: number | null
    return10_pct: number | null
  }
  change_types: string[]
  research_count?: number
  research_breakdown?: { smnc_focused: number; audited_primary: number; counter: number }
  research_focus?: {
    title: string | null; excerpt: string | null; available_at: string | null; source_url: string | null
    source_date?: string | null; age_days?: number | null
    topic_mentions?: Array<{ label: string; surface: string; location: 'title' | 'excerpt' }>
    counter?: { title: string | null; source_url: string | null } | null
  } | null
}

export interface StockPoolCandidateDetail extends StockPoolCandidate {
  source_events: Array<{
    source_id: string
    source: string
    stage: string
    event_date: string
    event_age: number
    anchor_price: number | null
    expires: string
    evidence: string
    details: Record<string, unknown>
  }>
  topic_evidence: Array<Record<string, unknown>>
  research: Array<Record<string, unknown>>
}

export interface StockPoolEvolution {
  trade_date: string
  previous_date: string | null
  mode: 'hot' | 'low'
  topic: string
  basis: 'daily_membership' | 'current_cohort'
  comparison_status: 'complete' | 'limited' | 'incompatible' | 'unavailable'
  current_count: number
  previous_count: number | null
  counts: Record<'retained' | 'entered_topic' | 'entered_pool' | 'left_topic' | 'left_pool' | 'stage_changed' | 'source_changed', number>
  stages: Array<{ stage: string; current: number; previous: number | null }>
  flows: Array<{ key: string; kind: string; from_stage: string; to_stage: string; count: number; symbols: string[] }>
  members: Array<{
    symbol: string; name: string; kind: string; previous_stage: string | null; current_stage: string
    added_sources: string[]; removed_sources: string[]; flow_key: string
    pct_chg: number | null; price_context?: StockPoolCandidate['price_context']
    research_count: number; freshness?: string; reentry: boolean
  }>
  exits: Array<{ symbol: string; name: string; kind: string; previous_stage: string; current_stage: string | null; flow_key: string }>
  history: Array<{ date: string; count: number | null; event_count: number | null; stage_counts: Record<string, number> }>
}

export interface StockPoolCandidateHistory {
  trade_date: string
  symbol: string
  timeline: Array<{
    date: string; available: boolean; present: boolean; stage: string | null
    sources: string[]; topics: string[]; pct_chg: number | null
    price_context?: StockPoolCandidate['price_context']; research_count: number
  }>
}

export interface StockPoolReviewRow {
  date: string
  symbol: string
  name: string
  labels: string[]
  stage: string
  previous_stage: string | null
  source_ids: string[]
  added_source_ids: string[]
  removed_source_ids: string[]
  research_count: number
  research_breakdown: { smnc_focused?: number; audited_primary?: number; counter?: number }
  research_breakdown_available: boolean
  sources: string[]
  added_sources: string[]
  removed_sources: string[]
  topics: string[]
  price: number | null
  snapshot_basis: 'first_published' | 'replay'
  snapshot_status: 'recorded' | 'late' | 'early' | 'replay' | 'unknown'
  prior_snapshot_status?: 'recorded' | 'late' | 'early' | 'replay' | 'unknown'
  published_at: string | null
  entry_date: string | null
  target_date: string | null
  target_stage: string | null
  outcome_status: 'mature' | 'pending' | 'unavailable'
  path: Array<{ date: string; stage: string | null; present: boolean }>
  return_pct: number | null
  open_proxy_pct: number | null
  open_proxy_net_pct: number | null
  max_adverse_pct: number | null
  max_favorable_pct: number | null
}

export interface StockPoolReviewStats {
  sample_count: number; matured_count: number; matured_dates: number; priced_count: number; unique_symbols: number; retained_count: number; recorded_count: number; recorded_transition_count?: number
  pending_count: number; unavailable_count: number; up_count: number
  up_rate_pct: number | null; priced_dates: number; mean_adverse_pct: number | null; adverse_count: number
  mean_return_pct: number | null; median_return_pct: number | null; peer_diff_pct: number | null; peer_days: number
  open_proxy_count: number; mean_open_proxy_pct: number | null; median_open_proxy_pct: number | null
  mean_open_proxy_net_pct: number | null; median_open_proxy_net_pct: number | null
  peer_open_diff_pct: number | null; peer_open_days: number
  eligible_diff_pct: number | null; eligible_days: number
  target_stages: Record<string, number>
}

export interface StockPoolReview {
  as_of_date: string
  window: number
  horizon: 1 | 3 | 5
  return_basis: 'adjusted_close_to_close'
  open_proxy_basis: 'next_trading_day_adjusted_open_to_target_close'
  cost_bps: number
  audit_counts: Record<string, number>
  eligible_baseline_days: number
  research_breakdown_observations: number
  anchor_dates: string[]
  skipped_dates: Array<{ date: string; reason: string }>
  groups: Record<string, StockPoolReviewStats>
  attribution: Record<'sources' | 'added_sources' | 'transitions' | 'research' | 'combinations', Record<string, StockPoolReviewStats & { label?: string }>>
  rows: StockPoolReviewRow[]
}

export const stockPoolApi = {
  getCatalog: () => request<{ dates: string[]; latest_date: string | null }>('/api/stock-pools'),
  getSummary: (date: string) => request<StockPoolSummary>(`/api/stock-pools/${encodeURIComponent(date)}`),
  getCandidates: (date: string) => request<{ trade_date: string; total: number; rows: StockPoolCandidate[] }>(`/api/stock-pools/${encodeURIComponent(date)}/candidates`),
  getCandidate: (date: string, symbol: string, snapshot: 'current' | 'first' = 'current') => request<StockPoolCandidateDetail>(`/api/stock-pools/${encodeURIComponent(date)}/candidates/${encodeURIComponent(symbol)}?snapshot=${snapshot}`),
  getEvolution: (date: string, mode: 'hot' | 'low', topic: string, window: number) =>
    request<StockPoolEvolution>(`/api/stock-pools/${encodeURIComponent(date)}/evolution?${new URLSearchParams({ mode, topic, window: String(window) })}`),
  getCandidateHistory: (date: string, symbol: string, window: number) =>
    request<StockPoolCandidateHistory>(`/api/stock-pools/${encodeURIComponent(date)}/candidates/${encodeURIComponent(symbol)}/history?window=${window}`),
  getReview: (date: string, window: number, horizon: 1 | 3 | 5, costBps: number) =>
    request<StockPoolReview>(`/api/stock-pools/${encodeURIComponent(date)}/review?${new URLSearchParams({ window: String(window), horizon: String(horizon), cost_bps: String(costBps) })}`),
  rebuild: (tradeDate?: string) => request<Record<string, unknown>>('/api/stock-pools/runs', {
    method: 'POST', body: JSON.stringify({ trade_date: tradeDate ?? null }),
  }),
}

export type AmvDimension = 'concept' | 'industry_level1' | 'industry_level2'
export type AmvProfile = 'research' | 'reconstructed'

export interface AmvPoint {
  date: string
  amv_yi: number
  float_mv_yi: number
  active_share_pct: number
  amount_proxy_yi: number
  price_index: number | null
  relative_ma10_pct?: number | null
}

export interface AmvMember {
  symbol: string
  name: string
  amv_yi: number
  amv_share_pct: number | null
  amv_change_yi: number
  float_mv_yi: number
  active_share_pct: number
  amount_proxy_yi: number
  share_basis: string
  amv_change_pct: number | null
  amv_change_5d_pct: number | null
  active_share_change_5d_pp: number
  price_change_5d_pct: number | null
  percentile_250: number | null
}

export interface AmvAnalysis {
  trade_date: string
  algorithm_version: string
  parameter_profile: AmvProfile
  official_0amv_verified: false
  capital_basis: 'ordinary_float'
  status: 'complete' | 'partial' | 'unavailable'
  scope: 'selected_members' | 'sector_latest_mapping'
  sector: string | null
  dimension: string | null
  membership_basis: string
  calendar_basis: string
  requested_members: number
  covered_members: number
  unmapped_members: number
  market_cap_coverage_pct: number | null
  unknown_capital_members: number
  diagnosis: string
  notes: string[]
  parameters: { half_life_sessions: number; exponent: number; turnover_factor: number; warmup_sessions: number }
  series: AmvPoint[]
  members: AmvMember[]
  excluded: Array<{ symbol: string; reason: string }>
  latest: (AmvPoint & {
    amv_change_pct: number | null
    amv_change_5d_pct: number | null
    active_share_change_5d_pp: number
    price_change_5d_pct: number | null
    expanding_members_5d: number
    expanding_members_5d_pct: number
    top3_amv_share_pct: number | null
    latest_float_proxy_members: number
    percentile_250: number | null
  }) | null
}

export type AmvSectorRow = Pick<AmvAnalysis, 'sector' | 'status' | 'requested_members' | 'covered_members' | 'unmapped_members' | 'market_cap_coverage_pct' | 'unknown_capital_members' | 'latest' | 'diagnosis'>
export interface AmvSectorResponse {
  available: boolean
  trade_date: string | null
  dimension: AmvDimension
  algorithm_version?: string
  parameter_profile?: AmvProfile
  parameters?: { half_life_sessions: number; exponent: number; turnover_factor: number }
  rows: AmvSectorRow[]
  available_dates: string[]
  detail: string
}

export const amvApi = {
  sectors: (dimension: AmvDimension = 'concept', date?: string, profile: AmvProfile = 'research') =>
    request<AmvSectorResponse>(`/api/amv/sectors?dimension=${dimension}&profile=${profile}${date ? `&trade_date=${encodeURIComponent(date)}` : ''}`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),
  analyze: (date: string, symbols: string[], sector = '', dimension: AmvDimension = 'concept', profile: AmvProfile = 'research') =>
    request<AmvAnalysis>('/api/amv/analyze', {
      method: 'POST', body: JSON.stringify({ trade_date: date, symbols, sector, dimension, profile }),
      timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS,
    }),
}

// ===== 自定义模块 API 客户端 (从原 lib/api.ts 抽出, 避免与上游核心声明交错冲突) =====

/** 抽取自核心 api 对象的自定义模块客户端。 */

const customApiClients = {

  chanlunAnalyze: (candles: ChanlunCandle[]) =>
    request<ChanlunAnalysis>('/api/chanlun/analyze', {
      method: 'POST',
      body: JSON.stringify({ candles }),
    }),
  /** 窗口补全的日 K OHLCV (本地不足时后端实时拉取补齐, 不落盘) */
  chanlunCandles: (symbol: string, days = 500) =>
    request<{ symbol: string; source: string; provider: string; rows: ChanlunCandleRow[] }>(
      `/api/chanlun/candles?symbol=${encodeURIComponent(symbol)}&days=${days}`,
    ),
  /** ZenChart 官方分析图层 (叠加对比; Pro 需服务端配置 token) */
  chanlunOfficial: (symbol: string, level = 'D1', limit = 300) =>
    request<ChanlunOfficialResponse>(
      `/api/chanlun/official?symbol=${encodeURIComponent(symbol)}&level=${level}&limit=${limit}`,
      { quiet: true },
    ),
  chanlunStatus: () => request<ChanlunStatus>('/api/chanlun/status', { quiet: true }),
  /** 对给定 K 线运行缠论分析 (包含处理/分型/笔/线段/中枢/买卖点) */
  extDataPresetFetch: (id: string) =>
    request<{ status: string; rows: number }>(
      `/api/ext-data/presets/${id}/fetch`,
      { method: 'POST' },
    ),
  financialAnalysis: (symbol: string) =>
    request<FinancialAnalysis>(`/api/financials/analysis/${encodeURIComponent(symbol)}`),

  /** AI 分析报告 CRUD */
  financialSyncScope: (
    scope: 'market_overview' | 'market_history' | 'stock' | 'market_detail',
    symbol?: string,
    startYear = 2012,
  ) =>
    request<{ status: string; synced: { started: boolean; reason?: string } }>(
      '/api/financials/sync', {
        method: 'POST',
        body: JSON.stringify({ scope, symbol, start_year: startYear }),
      },
    ),
  klineChart: (query: ChartDataQuery) => {
    const params = new URLSearchParams({
      symbol: query.symbol,
      interval: query.interval,
      adjustment: query.adjustment,
      range: query.range,
    })
    if (query.assetType) params.set('asset_type', query.assetType)
    if (query.startDate) params.set('start_date', query.startDate)
    if (query.endDate) params.set('end_date', query.endDate)
    if (query.layers?.length) params.set('layers', query.layers.join(','))
    if (query.strategyIds?.length) params.set('strategy_ids', query.strategyIds.join(','))
    if (query.sourceRunId) params.set('source_run_id', query.sourceRunId)
    if (query.paramsFingerprint) params.set('params_fingerprint', query.paramsFingerprint)
    if (query.warmupBars != null) params.set('warmup_bars', String(query.warmupBars))
    if (query.indicatorWarmups && Object.keys(query.indicatorWarmups).length) {
      params.set('indicator_warmups', Object.entries(query.indicatorWarmups).sort(([left], [right]) => left.localeCompare(right)).map(([id, bars]) => `${id}:${bars}`).join(','))
    }
    if (query.indicatorParams && Object.keys(query.indicatorParams).length) params.set('indicator_params', JSON.stringify(query.indicatorParams))
    return request<ChartDataResponse>(`/api/kline/chart?${params.toString()}`)
  },
  marketDataFoundation: async (): Promise<MarketDataFoundation> => {
    const [datasets, sources, routes, health] = await Promise.all([
      request<{ datasets: MarketDatasetContract[] }>('/api/data-sources/datasets'),
      request<{ sources: MarketSourceContract[] }>('/api/data-sources/sources'),
      request<{ routes: Array<{ dataset_id: string; sources: string[] }> }>('/api/data-sources/routes'),
      request<MarketDataFoundation['health']>('/api/data-sources/health'),
    ])
    return { datasets: datasets.datasets, sources: sources.sources, routes: routes.routes, health }
  },
  marketLabConceptOverlap: (sector?: string) =>
    request<ConceptOverlapResponse>(`/api/market-lab/concept-overlap?${new URLSearchParams(sector ? { sector } : {})}`),
  marketLabDrawdown: (payload: { entry: number; stop: number; high: number; target_r: number; drawdown_pct: number }) =>
    request<DrawdownResult>('/api/market-lab/drawdown', { method: 'POST', body: JSON.stringify(payload) }),
  marketLabEtfMomentum: (limit = 40, symbols?: string) =>
    request<EtfMomentumResponse>(`/api/market-lab/etf-momentum?${new URLSearchParams({ limit: String(limit), ...(symbols ? { symbols } : {}) })}`),
  marketLabMacroDispersion: () =>
    request<MacroDispersionResponse>('/api/market-lab/macro-dispersion', { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),
  marketLabPit: (payload: { top: number; bottom: number; current: number }) =>
    request<PitResult>('/api/market-lab/pit', { method: 'POST', body: JSON.stringify(payload) }),
  marketLabPosition: (payload: { balance: number; risk_pct: number; entry: number; stop: number; target?: number; mode: 'brave' | 'sensitive'; trade_type: 'B1' | 'B2' }) =>
    request<PositionResult>('/api/market-lab/position', { method: 'POST', body: JSON.stringify(payload) }),
  marketLabSectorFlow: (dimension: 'industry' | 'concept' = 'industry', taxonomy: 'ths' | 'source' = 'ths') =>
    request<SectorFlowResponse>(`/api/market-lab/sector-flow?dimension=${dimension}&taxonomy=${taxonomy}`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),
  marketLabSectorMembers: (sector: string, dimension: 'industry' | 'concept' = 'industry', asOf?: string) =>
    request<SectorMembersResponse>(`/api/market-lab/sector-members?sector=${encodeURIComponent(sector)}&dimension=${dimension}${asOf ? `&as_of=${encodeURIComponent(asOf)}` : ''}`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),
  marketLabSectorRadar: (dimension: 'industry' | 'concept' = 'industry', asOf?: string, taxonomy: 'ths' | 'source' = 'ths') =>
    request<SectorRadarResponse>(`/api/market-lab/sector-radar?dimension=${dimension}&taxonomy=${taxonomy}${asOf ? `&as_of=${encodeURIComponent(asOf)}` : ''}`, { timeoutMs: COMPUTE_REQUEST_TIMEOUT_MS }),
  marketLabSectorResearch: (dimension: string, horizon: number, asOf?: string) =>
    request<SectorResearchResponse>(`/api/market-lab/sector-research?${new URLSearchParams({ dimension, horizon: String(horizon), ...(asOf ? { as_of: asOf } : {}) })}`),
  marketLabSimulate: (payload: {
    balance: number; win_rate: number; win_r: number; loss_r: number
    risk_pct: number; trades: number; paths: number; seed?: number
    target_return_pct?: number; max_drawdown_pct?: number; annual_trades?: number
  }) => request<SimulationResult>('/api/market-lab/simulate', { method: 'POST', body: JSON.stringify(payload) }),

  // ===== Auth (访问认证) =====
  researchBacktestRun: (researchKey: string, runId: string) =>
    request<StrategyBacktestResult>(
      `/api/backtest/strategy/research-runs/${encodeURIComponent(researchKey)}/${encodeURIComponent(runId)}`,
    ),
  researchBacktestRuns: (strategyId?: string | null, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (strategyId) params.set('strategy_id', strategyId)
    return request<{ items: ResearchBacktestRunSummary[] }>(
      `/api/backtest/strategy/research-runs?${params}`,
    )
  },
  strategyPreview: (payload: StrategyPreviewRequest) =>
    request<StrategyPreviewResponse>('/api/strategies/preview', {
      method: 'POST',
      body: JSON.stringify({
        symbol: payload.symbol,
        asset_type: payload.assetType,
        timeframe: payload.timeframe,
        start_date: payload.startDate,
        end_date: payload.endDate,
        strategy_ids: payload.strategyIds,
        params_by_strategy: payload.paramsByStrategy ?? {},
      }),
    }),
  syncDailySingle: (symbol: string, startDate: string, endDate: string) =>
    request<{ status: string; symbol: string; rows: number; factor_rows: number; warning?: string | null }>(
      '/api/kline/sync_daily_single', {
        method: 'POST',
        body: JSON.stringify({ symbol, start_date: startDate, end_date: endDate }),
      },
    ),

}



/** 汇总暴露给核心 api 对象展开的自定义客户端集合。 */

export const customApi = {

  ...quantxApi,

  ...stockPoolApi,

  ...amvApi,

  ...customApiClients,

}
