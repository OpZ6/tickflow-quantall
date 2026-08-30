import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  Gauge,
  Layers3,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { toast } from '@/components/Toast'
import { DatePicker } from '@/components/DatePicker'
import {
  FactorAttribution,
  OpportunityRadar,
  SectorFlowContinuity,
  ThemeLifecyclePanel,
  TradingCalendarGrid,
  WindowSignalMatrix,
  type CalendarScoreKey,
  type WindowSize,
} from '@/components/quantx/MultidayPanels'
import { AdvancedPanels, type AdvancedCardLayout } from '@/components/quantx/AdvancedPanels'
import { quantxApi, type QuantXMultidaySnapshot, type QuantXReviewData } from '@/lib/api'
import { cn } from '@/lib/cn'
import { downloadQuantXStaticHtml } from '@/lib/exportStaticHtml'
import { QK } from '@/lib/queryKeys'
import {
  AdvanceRateChart,
  CongestionGauge,
  EmotionTrendChart,
  HeightChart,
  IndexChart,
  KlineChart,
  MarginChart,
  SectorBreadthHeatmap,
  SectorFlowChart,
  SectorScatterChart,
  SectorTreemapChart,
  UpCountChart,
} from './QuantXReview'

type DeepTab = 'market' | 'themes' | 'emotion' | 'flow' | 'watch' | 'data' | 'quality'

const DOMAIN_ADVANCED_LAYOUTS: Record<string, Record<string, AdvancedCardLayout>> = {
  market: {
    sentiment_phase: { span: 8, height: 400 },
    state_transition: { span: 8, height: 320 },
    anomaly_calendar: { span: 8, height: 390 },
    advance_decline: { span: 8, height: 365 },
  },
  industry: {
    sector_diffusion: { span: 16, height: 620 },
    industry_correlation: { span: 16, height: 580 },
    rps_rotation_clock: { span: 16, height: 420 },
  },
  themes: {
    theme_river: { span: 10, height: 430 },
    mainline_waterfall: { span: 6, height: 310 },
  },
  limitBoard: {
    promotion_funnel: { span: 9 },
    theme_ladder_sunburst: { span: 7, height: 500 },
  },
  liquidity: {
    liquidity_participation: { span: 8, height: 390 },
    return_distribution: { span: 8, height: 390 },
    turnover_return_density: { span: 8, height: 380 },
    turnover_lorenz: { span: 8, height: 340 },
  },
}

function Panel({ title, hint, icon, actions, className, children, testId }: {
  title: string
  hint?: string
  icon?: ReactNode
  actions?: ReactNode
  className?: string
  children: ReactNode
  testId?: string
}) {
  return (
    <section data-testid={testId} className={cn('min-w-0 overflow-hidden rounded-lg border border-border bg-elevated/25', className)}>
      <header className="flex min-h-9 items-center gap-2 border-b border-border/70 px-3 py-1.5">
        {icon && <span className="text-accent">{icon}</span>}
        <h2 className="text-xs font-semibold">{title}</h2>
        {hint && <span className="truncate text-[10px] text-muted">{hint}</span>}
        {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
      </header>
      <div className="p-2.5">{children}</div>
    </section>
  )
}

function AnalysisDomainSection({ title, hint, sequence, icon, children, testId }: {
  title: string
  hint: string
  sequence: string
  icon: ReactNode
  children: ReactNode
  testId: string
}) {
  return <section data-testid={testId} className="space-y-3 rounded-lg border border-border bg-elevated/20 p-3">
    <header className="flex flex-wrap items-center gap-2 border-b border-border pb-2">
      <span className="text-accent">{icon}</span>
      <div><h2 className="text-sm font-semibold">{title}</h2><p className="text-[10px] text-muted">{hint}</p></div>
      <span className="ml-auto rounded border border-border bg-base px-2 py-1 text-[9px] text-muted">{sequence}</span>
    </header>
    {children}
  </section>
}

function SmallTabs<T extends string | number>({ values, active, onChange, label }: {
  values: Array<[T, string]>
  active: T
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div className="flex rounded border border-border bg-base p-0.5" role="tablist" aria-label={label}>
      {values.map(([value, text]) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={active === value}
          onClick={() => onChange(value)}
          className={cn('cursor-pointer rounded px-2 py-1 text-[10px] transition-colors', active === value ? 'bg-accent/15 text-accent' : 'text-muted hover:text-foreground')}
        >
          {text}
        </button>
      ))}
    </div>
  )
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function MetricRibbon({ data }: { data: QuantXReviewData }) {
  const ms = data.metric_strip
  const items = [
    ...ms.indexes.map(index => ({ label: index.name, value: index.pct_chg, suffix: '%', tone: (index.pct_chg ?? 0) >= 0 ? 'up' : 'down' })),
    { label: '涨跌平', text: `${ms.up_count ?? '--'}/${ms.down_count ?? '--'}/${ms.flat_count ?? '--'}` },
    { label: '成交额', text: ms.total_amount_yi == null ? '--' : `${ms.total_amount_yi.toFixed(0)}亿` },
    { label: '晋级率', text: ms.advance_rate == null ? '--' : `${ms.advance_rate}%` },
    { label: '最高板', text: `${data.emotion.height_trend.latest_max_board ?? '--'}板` },
    { label: '市场热度', text: `${data.emotion.market_heat.score ?? '--'} ${data.emotion.market_heat.zone || ''}` },
  ]
  return (
    <div data-testid="quantx-metric-ribbon" className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-10">
      {items.map((item, index) => {
        const value = 'value' in item ? item.value : null
        const text = 'text' in item ? item.text : value == null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}${item.suffix}`
        return (
          <div key={`${item.label}-${index}`} className="rounded-md border border-border bg-elevated/35 px-2.5 py-1.5">
            <div className="truncate text-[9px] text-muted">{item.label}</div>
            <div className={cn('mt-0.5 truncate font-mono text-sm font-bold', 'tone' in item && item.tone === 'up' ? 'text-red-400' : 'tone' in item && item.tone === 'down' ? 'text-green-400' : '')}>{text}</div>
          </div>
        )
      })}
    </div>
  )
}

function DashboardHeader({ date, dates, refreshing, exporting, coverage, onDate, onRefresh, onExport }: {
  date: string
  dates: string[]
  refreshing: boolean
  exporting?: boolean
  coverage?: string
  onDate: (date: string) => void
  onRefresh: () => void
  onExport?: () => void
}) {
  const index = dates.indexOf(date)
  const previous = index > 0 ? dates[index - 1] : null
  const next = index >= 0 && index < dates.length - 1 ? dates[index + 1] : null
  const latest = dates.at(-1)
  const pickerDates = dates.map(value => `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`)
  const pickerDate = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}`
  return (
    <header data-testid="quantx-dashboard-header" className="sticky top-0 z-20 -mx-3 flex flex-wrap items-center gap-2 border-b border-border bg-base/95 px-3 py-2 backdrop-blur md:-mx-4 md:px-4">
      <div className="mr-2 flex items-center gap-2"><Zap className="h-4 w-4 text-accent" /><h1 className="text-base font-bold text-foreground">QuantX 市场驾驶舱</h1></div>
      <button aria-label="前一交易日" data-static-export-remove="true" disabled={!previous} onClick={() => previous && onDate(previous)} className="cursor-pointer rounded border border-border p-1.5 disabled:cursor-not-allowed disabled:opacity-30"><ChevronLeft className="h-3.5 w-3.5" /></button>
      <DatePicker ariaLabel="QuantX交易日" value={pickerDate} allowedDates={pickerDates} min={pickerDates[0]} max={pickerDates.at(-1)} onChange={value => onDate(value.replaceAll('-', ''))} align="left" buttonClassName="font-semibold" />
      <button aria-label="后一交易日" data-static-export-remove="true" disabled={!next} onClick={() => next && onDate(next)} className="cursor-pointer rounded border border-border p-1.5 disabled:cursor-not-allowed disabled:opacity-30"><ChevronRight className="h-3.5 w-3.5" /></button>
      <button type="button" data-static-export-remove="true" disabled={!latest || latest === date} onClick={() => latest && onDate(latest)} className="cursor-pointer rounded border border-border px-2 py-1.5 text-[10px] text-muted disabled:cursor-not-allowed disabled:opacity-40">最新</button>
      <div className="ml-auto flex items-center gap-2 text-[10px] text-muted">
        <span className="hidden items-center gap-1 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-green-400" />{coverage || '覆盖待确认'}</span>
        {onExport && <button
          type="button"
          data-testid="quantx-export-html"
          data-static-export-remove="true"
          onClick={onExport}
          disabled={exporting}
          title="导出当前日期为可离线分享的单文件 HTML"
          className="inline-flex cursor-pointer items-center gap-1 rounded border border-accent/45 bg-accent/10 px-2 py-1.5 font-medium text-accent transition-colors hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}{exporting ? '导出中' : '导出 HTML'}
        </button>}
        <button type="button" data-static-export-remove="true" onClick={onRefresh} disabled={refreshing} className="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-2 py-1.5 text-foreground disabled:cursor-not-allowed disabled:opacity-50">
          {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}刷新
        </button>
      </div>
    </header>
  )
}

function ThemeMainline({ review, multiday }: { review: QuantXReviewData; multiday?: QuantXMultidaySnapshot }) {
  const rows = [...(multiday?.theme_lifecycle.current || [])]
    .sort((left: any, right: any) => (
      Number(right.rank_strength || 0) - Number(left.rank_strength || 0)
      || Number(right.source_count || 0) - Number(left.source_count || 0)
      || String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN')
    ))
    .slice(0, 8)
  if (!rows.length) {
    const fallback = review.sections.s2.themes_pywencai.slice(0, 8)
    return <div className="space-y-1">{fallback.map((row, index) => <div key={`${row.name}-${index}`} className="flex items-center justify-between rounded bg-base/40 px-2 py-1.5 text-xs"><span>{index + 1}. {row.name}</span><span className="font-mono text-muted">{row.count ?? '--'}</span></div>)}</div>
  }
  return (
    <div className="space-y-1">
      <div className="grid grid-cols-[24px_1fr_52px_52px_68px] items-center gap-1 px-1.5 text-[9px] text-muted">
        <span>排名</span><span>题材</span><span className="text-right">强度</span><span className="text-right">连续</span><span className="text-right">状态</span>
      </div>
      {rows.map((row: any, index: number) => (
        <div key={`${row.name}-${index}`} data-testid="quantx-theme-mainline-row" data-score={row.rank_strength ?? ''} className="grid grid-cols-[24px_1fr_52px_52px_68px] items-center gap-1 rounded bg-base/40 px-1.5 py-1.5 text-[10px] hover:bg-elevated">
          <span className="text-muted">{index + 1}</span><span className="truncate text-xs font-medium">{row.name}</span><span className="text-right font-mono text-red-400">{row.rank_strength ?? '--'}</span><span className="text-right">{row.streak ?? '--'}日</span><span className="truncate text-right text-muted">{row.lifecycle ?? '--'}</span>
        </div>
      ))}
    </div>
  )
}

function DecisionRail({ data }: { data: QuantXReviewData }) {
  const { s6 } = data.sections
  return (
    <div className="space-y-2">
      <div className="rounded border border-orange-500/30 bg-orange-500/5 p-2"><div className="text-[9px] text-muted">仓位与动作</div><div className="mt-0.5 font-semibold text-orange-300">{s6.position?.band || '--'}</div><div className="mt-1 text-[10px] text-muted">{s6.position?.action || '--'}</div></div>
      <div className="space-y-1.5">{s6.scenes.map((scene, index) => <div key={`${scene.name}-${index}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded border border-border/60 bg-base/35 px-2 py-1.5 text-[10px]"><b>{scene.name}</b><span className="truncate text-muted" title={scene.condition}>{scene.condition}</span><span className={cn(scene.tone === 'positive' ? 'text-red-300' : scene.tone === 'negative' ? 'text-green-300' : 'text-muted')}>{VALUE_LABELS[String(scene.tone)] || scene.tone || '--'}</span></div>)}</div>
      <p className="rounded border border-border/60 bg-base/25 p-2 text-[10px] leading-5 text-muted">{data.emotion.daily_summary}</p>
    </div>
  )
}

function EmotionCalendar({ data, records, multiday, date }: { data: QuantXReviewData; records: Array<{ trade_date: string; metrics: Record<string, number | string | boolean | null> }>; multiday?: QuantXMultidaySnapshot; date: string }) {
  const [calendarScore, setCalendarScore] = useState<CalendarScoreKey>('market_heat_score')
  const dates = records.slice(-20).map(row => row.trade_date)
  const scores = {
    heat: records.slice(-20).map(row => num(row.metrics.market_heat_score) ?? 0),
    short: records.slice(-20).map(row => num(row.metrics.short_term_sentiment_score) ?? 0),
    trend: records.slice(-20).map(row => num(row.metrics.trend_sentiment_score) ?? 0),
  }
  return (
    <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,.9fr)]">
      <div className="min-w-0">
        <div className="grid grid-cols-5 gap-1.5">
          {[
            ['市场热度', data.emotion.market_heat.score, 'text-red-400'],
            ['短线情绪', data.emotion.short_term_sentiment.score, ''],
            ['趋势情绪', data.emotion.trend_sentiment.score, ''],
            ['最高板', data.emotion.height_trend.latest_max_board, ''],
            ['晋级率', `${data.sections.s3.advance.advance_rate ?? '--'}%`, ''],
          ].map(([label, value, tone]) => <div key={String(label)} className="rounded border border-border bg-base/40 px-2 py-1.5"><div className="truncate text-[9px] text-muted">{label}</div><div className={cn('font-mono text-sm font-bold', String(tone))}>{value ?? '--'}</div></div>)}
        </div>
        <EmotionTrendChart dates={dates} scores={scores} height={220} />
      </div>
      <div className="min-w-0 border-t border-border pt-2 xl:border-l xl:border-t-0 xl:pl-3 xl:pt-0">
        <div className="mb-2 flex flex-wrap items-center gap-2"><div className="mr-auto"><h3 className="text-xs font-semibold">交易日情绪分数</h3><p className="text-[10px] text-muted">日期只读 · 颜色和数值对应当前情绪口径</p></div><SmallTabs values={[["market_heat_score", '总情绪'], ["trend_sentiment_score", '波段情绪'], ["short_term_sentiment_score", '短线情绪']]} active={calendarScore} onChange={setCalendarScore} label="交易日情绪口径" /><CalendarDays className="h-4 w-4 text-accent" /></div>
        {multiday ? <TradingCalendarGrid rows={multiday.calendar} selectedDate={date} scoreKey={calendarScore} compact /> : <div className="py-16 text-center text-xs text-muted">该日期无交易日历快照</div>}
      </div>
    </div>
  )
}

const COLUMN_LABELS: Record<string, string> = {
  trade_date: '交易日', date: '日期', code: '代码', name: '名称', source: '来源', source_count: '来源数',
  count: '数量', rank: '排名', score: '评分', priority: '优先级', status: '状态', available: '可用', ok: '达标',
  value: '当前值', baseline: '基线', evidence: '证据', reason: '触发原因', condition: '条件', tone: '情景',
  limit_times: '连板数', theme_name: '题材', turnover_pct: '换手率(%)', amount_yi: '成交额(亿)', pct_chg: '涨跌幅(%)',
  congestion_pct: '拥挤度(%)', close: '全A收盘', top5_amount: '前5%成交额(亿)', total_amount: '全市场成交额(亿)',
  concepts: '概念', lifecycle: '生命周期', streak: '连续日', rank_strength: '强度', active_days: '活跃日', last_seen: '最近出现',
  net_inflow_yi: '净流入(亿)', net_inflow_sum_yi: '累计净流入(亿)', last_pct_chg: '最新涨跌(%)', direction: '方向',
  candidate_type: '候选类型', display_name: '显示名称', collector_type: '采集器类型', collector: '采集器', credentials_ref: '凭据引用',
  source_id: '数据源 ID', credentials_configured: '凭据已配置', credential_readiness: '凭据状态', dependency_available: '依赖可用', dependency_status: '依赖状态',
  dataset_id: '数据集', path: '分区路径', partition_path: '分区路径', row_count: '行数', schema_version: 'Schema', quality_level: '质量等级',
  source_counts: '来源分布', quality_counts: '质量分布', coverage: '覆盖率', observed_count: '观测数', expected_count: '应有数',
}

const VALUE_LABELS: Record<string, string> = {
  true: '是', false: '否', new: '新生', strengthening: '增强', continuing: '延续', weakening: '转弱', exited: '退出',
  positive: '积极', neutral: '中性', negative: '谨慎', rule: '规则', signal: '信号', limit_up: '涨停', new_high_100d: '百日新高',
  ready: '就绪', missing: '缺失', present: '已存在', degraded: '降级', fallback: '回退', limit_up_consecutive_limit_up: '连续涨停',
}

function displayCell(value: unknown): string {
  if (value == null || value === '') return '--'
  if (Array.isArray(value)) return value.map(displayCell).join('；') || '--'
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${COLUMN_LABELS[key] || key}: ${displayCell(item)}`).join('，') || '--'
  return VALUE_LABELS[String(value)] || String(value)
}

function GenericRows({ rows, columns: preferredColumns, maxHeight = 520 }: { rows: any[]; columns?: string[]; maxHeight?: number }) {
  if (!rows.length) return <div className="py-8 text-center text-xs text-muted">当前数据集无记录</div>
  const columns = preferredColumns || Array.from(new Set(rows.slice(0, 20).flatMap(row => row && typeof row === 'object' ? Object.keys(row) : []))).slice(0, 12)
  if (!columns.length) return <pre className="max-h-96 overflow-auto text-[10px]">{JSON.stringify(rows, null, 2)}</pre>
  return <div data-testid="quantx-adaptive-table" className="overflow-auto" style={{ maxHeight }}><table className="w-max min-w-full table-auto text-[10px]"><thead className="sticky top-0 z-[1] bg-elevated"><tr>{columns.map(column => <th key={column} className="whitespace-nowrap border-b border-border px-2 py-1.5 text-left font-medium text-muted first:pl-0">{COLUMN_LABELS[column] || column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-b border-border/50 hover:bg-base/40">{columns.map(column => { const value = displayCell(row[column]); return <td key={column} className={cn('max-w-64 truncate whitespace-nowrap px-2 py-1.5 first:pl-0', typeof row[column] === 'number' && 'text-right font-mono tabular-nums')} title={value}>{value}</td> })}</tr>)}</tbody></table></div>
}

function CongestionOverview({ data }: { data: any }) {
  const latest = data?.latest || {}
  const rows = (data?.table || []).map((row: any[]) => ({ date: row[0], close: row[1], top5_amount: row[2], total_amount: row[3], congestion_pct: row[4] }))
  return <div data-testid="quantx-congestion-combined" className="grid items-center gap-4 xl:grid-cols-[minmax(260px,.72fr)_minmax(0,1.28fr)]">
    <div className="min-w-0 border-b border-border pb-3 xl:border-b-0 xl:border-r xl:pb-0 xl:pr-4">
      <CongestionGauge pct={latest.congestion_pct ?? 0} height={230} />
      <div className="grid grid-cols-3 gap-1.5 text-center text-[10px]"><div className="rounded bg-base/50 p-2"><span className="text-muted">全A收盘</span><b className="mt-0.5 block font-mono">{latest.close?.toFixed?.(2) ?? '--'}</b></div><div className="rounded bg-base/50 p-2"><span className="text-muted">前5%成交额</span><b className="mt-0.5 block font-mono">{latest.top5_amount?.toFixed?.(0) ?? '--'}亿</b></div><div className="rounded bg-base/50 p-2"><span className="text-muted">全市场成交额</span><b className="mt-0.5 block font-mono">{latest.total_amount?.toFixed?.(0) ?? '--'}亿</b></div></div>
    </div>
    <div className="min-w-0"><div className="mb-2 flex items-end justify-between"><div><h3 className="text-xs font-semibold">近十日拥挤度历史</h3><p className="text-[10px] text-muted">前 5% 活跃股票成交额占全市场比例</p></div><span className="rounded bg-accent/10 px-2 py-1 font-mono text-xs text-accent">最新 {latest.congestion_pct?.toFixed?.(2) ?? '--'}%</span></div><GenericRows rows={rows} columns={['date', 'close', 'top5_amount', 'total_amount', 'congestion_pct']} maxHeight={340} /></div>
  </div>
}

const EBB_LABELS: Record<string, string> = {
  ladder_compressed: '梯队压缩',
  loss_effect_expanding: '亏钱效应扩散',
  relay_payoff_weak: '接力收益转弱',
  seal_quality_weak: '封板质量转弱',
}

const PARTICIPATION_LABELS: Record<string, string> = {
  direction_aligned: '趋势方向一致',
  height_ge_4: '最高连板达到 4 板',
  ladder_complete: '连板梯队完整',
  volume_stable: '成交额保持稳定',
}

function signalDetail(signal: any): string {
  if (signal.evidence) return String(signal.evidence)
  const value = signal.value == null ? '' : typeof signal.value === 'object' ? JSON.stringify(signal.value) : `当前 ${signal.value}`
  const baseline = signal.baseline == null ? '' : typeof signal.baseline === 'object' ? JSON.stringify(signal.baseline) : `基准 ${signal.baseline}`
  return [value, baseline].filter(Boolean).join(' · ') || '等待更多样本'
}

function RiskSignalBoard({ ebb, crash, participation }: { ebb: any[]; crash: any[]; participation: any[] }) {
  const groups = [
    { key: 'ebb', title: '退潮信号', rows: ebb, tone: 'orange' },
    { key: 'crash', title: '崩塌信号', rows: crash, tone: 'red' },
  ] as const
  return (
    <section data-testid="quantx-risk-signals" className="xl:[grid-column:span_16/span_16] overflow-hidden rounded-lg border border-border bg-elevated/25">
      <header className="flex items-center gap-2 border-b border-border/70 px-3 py-2"><ShieldAlert className="h-4 w-4 text-orange-400" /><h2 className="text-xs font-semibold">情绪风险与参与度雷达</h2><span className="text-[10px] text-muted">退潮、崩塌与行情参与条件统一监控</span></header>
      <div className="grid gap-2 p-2.5 xl:grid-cols-3">
        {groups.map(group => <section key={group.key} className="min-w-0 rounded-md border border-border/60 bg-base/20 p-2"><h3 className="mb-1.5 text-[10px] font-semibold text-muted">{group.title}</h3><div className="grid min-w-0 gap-1.5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          {group.rows.map((signal, index) => {
            const active = Boolean(signal.triggered)
            return <article key={`${signal.name}-${index}`} className={cn('min-w-0 rounded-md border px-2.5 py-2', active ? group.tone === 'red' ? 'border-red-500/45 bg-red-500/10' : 'border-orange-500/45 bg-orange-500/10' : 'border-border/70 bg-base/35')}>
              <div className="flex items-center gap-1.5">{active ? <AlertTriangle className={cn('h-3.5 w-3.5 shrink-0', group.tone === 'red' ? 'text-red-400' : 'text-orange-400')} /> : <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-400" />}<span className="truncate text-[11px] font-semibold">{EBB_LABELS[signal.name] || signal.name || group.title}</span><span className={cn('ml-auto shrink-0 rounded px-1.5 py-0.5 text-[9px]', active ? group.tone === 'red' ? 'bg-red-500/20 text-red-300' : 'bg-orange-500/20 text-orange-300' : 'bg-green-500/15 text-green-300')}>{active ? '已触发' : signal.status || '正常'}</span></div>
              <p className="mt-1 truncate text-[9px] text-muted" title={signalDetail(signal)}>{signalDetail(signal)}</p>
            </article>
          })}
          {!group.rows.length && <div className="rounded border border-border/70 bg-base/35 px-3 py-4 text-center text-[10px] text-muted">{group.title}暂无可用规则</div>}
        </div></section>)}
        <section data-testid="quantx-participation-signals" className="min-w-0 rounded-md border border-border/60 bg-base/20 p-2"><h3 className="mb-1.5 text-[10px] font-semibold text-muted">参与度条件</h3><div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">{participation.map((item, index) => {
          const available = item.available !== false
          const passed = available && Boolean(item.ok)
          return <article key={`${item.name}-${index}`} className={cn('rounded-md border px-2.5 py-2', !available ? 'border-border/70 bg-base/35' : passed ? 'border-green-500/40 bg-green-500/10' : 'border-orange-500/40 bg-orange-500/10')}><div className="flex items-center gap-1.5"><span className="truncate text-[11px] font-semibold">{PARTICIPATION_LABELS[item.name] || item.name || `条件 ${index + 1}`}</span><span className={cn('ml-auto shrink-0 rounded px-1.5 py-0.5 text-[9px]', !available ? 'bg-elevated text-muted' : passed ? 'bg-green-500/15 text-green-300' : 'bg-orange-500/15 text-orange-300')}>{!available ? '不可用' : passed ? '达标' : '未达标'}</span></div><p className="mt-1 truncate font-mono text-[9px] text-muted" title={displayCell(item.value)}>当前 {displayCell(item.value)}</p></article>
        })}{!participation.length && <div className="rounded border border-border/70 bg-base/35 px-3 py-4 text-center text-[10px] text-muted">参与度暂无可用条件</div>}</div></section>
      </div>
    </section>
  )
}

function NewHighPanel({ date, data }: { date: string; data: QuantXReviewData['sections']['s2']['new_high'] }) {
  const [dimension, setDimension] = useState<'concept' | 'industry_level1' | 'industry_level2'>('concept')
  const [window, setWindow] = useState<1 | 5 | 10 | 20>(5)
  const [expandedName, setExpandedName] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const memberQuery = useQuery({
    queryKey: QK.quantxNewHighMembers(date, dimension, window, expandedName || ''),
    queryFn: () => quantxApi.getNewHighClusterMembers(date, dimension, window, expandedName || ''),
    enabled: Boolean(expandedName),
    staleTime: 30_000,
    retry: false,
  })
  useEffect(() => { setExpandedName(null); setShowAll(false) }, [dimension, window])
  if (!data) return <div data-testid="quantx-new-high-unavailable" className="rounded border border-orange-500/30 bg-orange-500/5 px-3 py-8 text-center text-xs text-orange-300">本日百日新高事实尚未发布，请刷新数据后重试</div>
  if (data.status !== 'ok') return <div data-testid="quantx-new-high-unavailable" className="rounded border border-orange-500/30 bg-orange-500/5 px-3 py-8 text-center text-xs text-orange-300">百日新高来源暂不可用，未用零值替代</div>
  const total = data.total_stocks ?? data.stocks.length
  if (!total) return <div className="py-8 text-center text-xs text-muted">数据已发布，本日无百日新高个股</div>
  const selected = data.windows?.[String(window) as '1' | '5' | '10' | '20']
  const rows = selected?.dimensions[dimension] || []
  const coverage = data.coverage_pct?.[dimension] ?? 0
  const top = rows[0]
  const dimensionLabels = { concept: '题材概念', industry_level1: '申万一级', industry_level2: '申万二级' }
  const statusTone: Record<string, string> = {
    新生: 'bg-red-500/15 text-red-300',
    扩散: 'bg-orange-500/15 text-orange-300',
    持续: 'bg-accent/15 text-accent',
    收缩: 'bg-green-500/15 text-green-300',
    轮动: 'bg-blue-500/15 text-blue-300',
    当日集中: 'bg-purple-500/15 text-purple-300',
  }
  return <div data-testid="quantx-new-high-clusters" className="space-y-2.5">
    <div className="flex flex-wrap items-center gap-2">
      <SmallTabs values={[["concept", '题材概念'], ["industry_level1", '申万一级'], ["industry_level2", '申万二级']]} active={dimension} onChange={setDimension} label="百日新高聚类维度" />
      <SmallTabs values={[[1, '当日'], [5, '5日'], [10, '10日'], [20, '20日']]} active={window} onChange={setWindow} label="百日新高观察窗口" />
      <span className="ml-auto text-[9px] text-muted">{selected?.date_range?.join('—') || '--'} · {selected?.valid_days ?? 0} 个有效交易日</span>
    </div>
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
      <div className="rounded border border-border/70 bg-base/35 px-2.5 py-2"><span className="text-[9px] text-muted">当日新高</span><b className="mt-0.5 block font-mono text-base text-foreground">{total}<small className="ml-1 text-[9px] font-normal text-muted">只</small></b></div>
      <div className="rounded border border-border/70 bg-base/35 px-2.5 py-2"><span className="text-[9px] text-muted">{dimensionLabels[dimension]}覆盖</span><b className="mt-0.5 block font-mono text-base text-foreground">{coverage.toFixed(1)}%</b></div>
      <div className="rounded border border-border/70 bg-base/35 px-2.5 py-2"><span className="text-[9px] text-muted">最强聚类</span><b className="mt-0.5 block truncate text-sm text-foreground" title={top?.name}>{top?.name || '--'}</b></div>
      <div className="rounded border border-border/70 bg-base/35 px-2.5 py-2"><span className="text-[9px] text-muted">窗口活跃</span><b className="mt-0.5 block font-mono text-base text-foreground">{top?.active_days ?? 0}<small className="ml-1 text-[9px] font-normal text-muted">/{selected?.valid_days ?? 0}日</small></b></div>
    </div>
    {rows.length ? <div data-testid="new-high-cluster-ranking" className="overflow-hidden rounded-md border border-border/70 bg-base/15">
      <div className="hidden grid-cols-[32px_minmax(140px,1.4fr)_64px_110px_74px_120px_76px] items-center gap-2 border-b border-border/70 bg-elevated/70 px-2.5 py-1.5 text-[9px] text-muted md:grid">
        <span>排名</span><span>聚类</span><span>状态</span><span>个股覆盖</span><span>活跃</span><span>新高占比</span><span className="text-right">趋势</span>
      </div>
      {(showAll ? rows : rows.slice(0, 10)).map((row, index) => {
        const share = window === 1 ? row.weighted_share_pct : row.average_share_pct
        return <button type="button" data-testid="new-high-cluster-row" aria-expanded={expandedName === row.name} onClick={() => setExpandedName(current => current === row.name ? null : row.name)} key={row.name} className={cn('grid w-full min-w-0 cursor-pointer grid-cols-[24px_minmax(0,1fr)_64px] items-center gap-2 border-b border-border/50 px-2.5 py-2 text-left transition-colors last:border-b-0 hover:bg-accent/5 md:grid-cols-[32px_minmax(140px,1.4fr)_64px_110px_74px_120px_76px]', expandedName === row.name && 'bg-accent/10 ring-1 ring-inset ring-accent/50')}>
          <span className="font-mono text-[9px] text-muted">{index + 1}</span>
          <div className="min-w-0"><div className="flex min-w-0 items-center gap-1.5"><b className="truncate text-[11px]" title={row.name}>{row.name}</b><span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[9px] md:hidden', statusTone[row.status] || 'bg-elevated text-muted')}>{row.status}</span></div><div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[9px] text-muted md:hidden"><span className="whitespace-nowrap">当 {row.current_count} / 窗 {row.unique_count}只</span><span className="whitespace-nowrap">活 {row.active_days}/{selected?.valid_days ?? 0}日</span><span className={cn('whitespace-nowrap font-mono', row.change_pct > 0 ? 'text-red-300' : row.change_pct < 0 ? 'text-green-300' : '')}>{row.change_pct > 0 ? '+' : ''}{row.change_pct.toFixed(1)}pct</span></div></div>
          <span className={cn('hidden w-fit rounded px-1.5 py-0.5 text-[9px] md:inline', statusTone[row.status] || 'bg-elevated text-muted')}>{row.status}</span>
          <span className="hidden text-[10px] text-muted md:inline">今日 <b className="font-mono text-foreground">{row.current_count}</b> · 窗口 <b className="font-mono text-foreground">{row.unique_count}</b>只</span>
          <span className="hidden font-mono text-[10px] text-muted md:inline">{row.active_days}/{selected?.valid_days ?? 0}日</span>
          <div className="min-w-0"><div className="text-right font-mono text-[10px] font-semibold">{share.toFixed(1)}%</div><div className="mt-1 h-1 overflow-hidden rounded-full bg-elevated"><div className="h-full rounded-full bg-gradient-to-r from-accent/70 to-orange-400" style={{ width: `${Math.max(2, Math.min(100, share))}%` }} /></div></div>
          <span className={cn('hidden text-right font-mono text-[10px] md:inline', row.change_pct > 0 ? 'text-red-300' : row.change_pct < 0 ? 'text-green-300' : 'text-muted')}>{row.change_pct > 0 ? '+' : ''}{row.change_pct.toFixed(1)}pct</span>
        </button>
      })}
      {rows.length > 10 && <button type="button" data-testid="new-high-toggle-all" aria-expanded={showAll} onClick={() => setShowAll(value => !value)} className="w-full cursor-pointer border-t border-border/70 bg-base/30 py-1.5 text-center text-[10px] text-muted transition-colors hover:bg-elevated hover:text-foreground">{showAll ? '收起至前 10 项' : `展开全部 ${rows.length} 项`}</button>}
    </div> : <div className="rounded border border-border/60 bg-base/25 py-8 text-center text-xs text-muted">当前映射未形成{dimensionLabels[dimension]}聚类</div>}
    {expandedName && <section data-testid="new-high-member-details" className="overflow-hidden rounded-md border border-accent/40 bg-base/35">
      <header className="flex flex-wrap items-center gap-2 border-b border-border/70 px-3 py-2"><b className="text-xs text-foreground">{expandedName} · 个股明细</b>{memberQuery.data && <span className="text-[9px] text-muted">今日 {memberQuery.data.current_count} 只 · {window}日窗口 {memberQuery.data.window_count} 只</span>}<button type="button" onClick={() => setExpandedName(null)} className="ml-auto cursor-pointer rounded border border-border px-2 py-1 text-[9px] text-muted hover:text-foreground">收起</button></header>
      {memberQuery.isLoading ? <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />正在读取成员证据</div> : memberQuery.error ? <div className="py-8 text-center text-xs text-red-300">个股明细加载失败：{String(memberQuery.error)}</div> : <div className="max-h-72 overflow-auto"><table className="w-full min-w-[680px] text-[10px]"><thead className="sticky top-0 bg-elevated"><tr className="text-left text-muted"><th className="px-3 py-1.5">状态</th><th className="px-2 py-1.5">代码</th><th className="px-2 py-1.5">名称</th><th className="px-2 py-1.5 text-right">最新涨跌</th><th className="px-2 py-1.5 text-right">窗口活跃</th><th className="px-2 py-1.5">首次出现</th><th className="px-3 py-1.5">最近出现</th></tr></thead><tbody>{(memberQuery.data?.members || []).map(member => <tr key={member.code} data-testid="new-high-member-row" className="border-t border-border/50 hover:bg-elevated/50"><td className="px-3 py-1.5"><span className={cn('rounded px-1.5 py-0.5 text-[9px]', member.current ? 'bg-red-500/15 text-red-300' : 'bg-elevated text-muted')}>{member.current ? '今日新高' : '窗口出现'}</span></td><td className="px-2 py-1.5 font-mono text-muted">{member.code}</td><td className="px-2 py-1.5 font-medium text-foreground">{member.name || '--'}</td><td className={cn('px-2 py-1.5 text-right font-mono', (member.pct_chg ?? 0) > 0 ? 'text-red-300' : (member.pct_chg ?? 0) < 0 ? 'text-green-300' : '')}>{member.pct_chg == null ? '--' : `${member.pct_chg > 0 ? '+' : ''}${member.pct_chg.toFixed(2)}%`}</td><td className="px-2 py-1.5 text-right font-mono">{member.active_days}/{memberQuery.data?.valid_days}</td><td className="px-2 py-1.5 font-mono text-muted">{member.first_seen}</td><td className="px-3 py-1.5 font-mono text-muted">{member.last_seen}</td></tr>)}</tbody></table>{memberQuery.data && !memberQuery.data.members.length && <div className="py-8 text-center text-xs text-muted">该聚类暂无成员证据</div>}</div>}
    </section>}
    <p className="text-[9px] leading-4 text-muted">读法：条形表示{window === 1 ? '当日按一股多标签 1/N 加权后的聚类占比' : `${window} 日内该聚类覆盖新高股的日均比例`}；右下角表示后半窗口较前半窗口的覆盖变化。行业与概念归属使用 TickFlow 当前扩展数据快照回映历史，仅作扩散代理。</p>
  </div>
}

function CompleteDataPanel({ data }: { data: Record<string, any> | undefined }) {
  const datasets = useMemo(() => data ? Object.keys(data).filter(key => key !== 'trade_date' && data[key] != null) : [], [data])
  const [selected, setSelected] = useState('')
  useEffect(() => { if (!selected && datasets.length) setSelected(datasets[0]) }, [datasets, selected])
  if (!data) return <div className="py-10 text-center text-xs text-muted">正在加载完整数据表</div>
  const value = data[selected]
  const rows = Array.isArray(value) ? value : Array.isArray(value?.rows) ? value.rows : value && typeof value === 'object' ? [value] : []
  return <div><div className="mb-2 flex flex-wrap gap-1">{datasets.map(dataset => <button key={dataset} onClick={() => setSelected(dataset)} className={cn('cursor-pointer rounded px-2 py-1 text-[10px]', selected === dataset ? 'bg-accent/20 text-accent' : 'bg-base text-muted')}>{dataset}</button>)}</div><GenericRows rows={rows} /></div>
}

function QualityPanel({ data }: { data: any }) {
  if (!data) return <div className="py-10 text-center text-xs text-muted">正在加载质量与血缘</div>
  return <div className="grid gap-4"><div><h3 className="mb-2 text-xs font-semibold">数据来源</h3><GenericRows rows={data.sources || []} /></div><div><h3 className="mb-2 text-xs font-semibold">Market Facts</h3><GenericRows rows={data.facts || []} /></div><div className="grid gap-3 xl:grid-cols-2"><div className="rounded border border-border p-3 text-xs"><div>发布状态：{data.status}</div><div>标准事实：{data.fact_summary?.present_partition_count ?? '--'}/{data.fact_summary?.expected_partition_count ?? '--'}</div><div>Review：{data.view?.schema_version ?? '--'} · canonical {data.view?.canonical_count ?? '--'} · derived {data.view?.derived_count ?? '--'}</div><div>多日：{data.multiday?.schema_version ?? '--'}</div></div><div className="rounded border border-border p-3 text-xs"><div>对账：{data.reconciliation?.status ?? '--'} · 缺口 {data.reconciliation?.gap_count ?? '--'}</div><div className="mt-1 text-orange-300">{(data.warnings || []).join('；') || '无警告'}</div><div className="mt-1 text-red-300">{(data.errors || []).join('；') || '无错误'}</div></div></div></div>
}

function DeepSection({ tab, review, multiday, tables, quality, breadth, breadthLevel, onBreadthLevel }: { tab: DeepTab; review: QuantXReviewData; multiday?: QuantXMultidaySnapshot; tables?: Record<string, any>; quality?: any; breadth: any[]; breadthLevel: 1 | 2; onBreadthLevel: (level: 1 | 2) => void }) {
  const { s1, s2, s3, s4, s5 } = review.sections
  if (tab === 'market') return <div className="grid gap-3 xl:grid-cols-2"><Panel title="主要指数" className="xl:col-span-2"><IndexChart indexes={s1.indexes} /></Panel><Panel title="涨跌家数 + 成交额"><UpCountChart history={s1.up_count_history} /></Panel><Panel title="融资余额 + 净买入"><MarginChart history={s1.margin_history} /></Panel></div>
  if (tab === 'themes') return <div className="grid gap-3 xl:grid-cols-2">{multiday && <><div className="xl:col-span-2"><ThemeLifecyclePanel data={multiday} /></div><FactorAttribution rows={multiday.factor_attribution} /></>}<Panel title="多源题材"><GenericRows rows={[...s2.themes_pywencai.map(row => ({ source: 'pywencai', ...row })), ...s2.themes_ths.map(row => ({ source: 'ths', name: row.tag, count: row.count, rank: row.rank }))]} columns={['source', 'name', 'count', 'rank']} /></Panel><Panel title="百日新高扩散聚类" hint="看哪些板块正批量创出阶段新高" className="xl:col-span-2"><NewHighPanel date={review.trade_date} data={s2.new_high} /></Panel></div>
  if (tab === 'emotion') return <div className="grid gap-3 xl:grid-cols-2"><Panel title="连板高度历史"><HeightChart history={s3.height_history} /></Panel><Panel title="晋级率 / 溢价率 / 涨停数"><AdvanceRateChart history={s3.advance_history} /></Panel></div>
  if (tab === 'flow') return <div data-testid="quantx-capital-workspace" className="grid gap-3">
    <div data-testid="quantx-capital-breadth-row" className="grid gap-3 xl:grid-cols-[repeat(16,minmax(0,1fr))]">
      <Panel testId="quantx-capital-ecosystem" title="行业资金分布" hint="行业涨跌与净流入的面积、方向和强弱结构" icon={<Sparkles className="h-3.5 w-3.5" />} className="xl:[grid-column:span_9/span_9]"><SectorTreemapChart data={s4.sector_treemap} height={750} /></Panel>
      <Panel testId="quantx-sector-breadth" title={`申万${breadthLevel === 1 ? '一级' : '二级'}行业均线宽度`} hint={`${breadth.length} 个行业 · 按 MA20 强度排序`} icon={<Gauge className="h-3.5 w-3.5" />} actions={<SmallTabs values={[[1, '一级'], [2, '二级']]} active={breadthLevel} onChange={onBreadthLevel} label="行业层级" />} className="xl:[grid-column:span_7/span_7]">
        <div data-testid="quantx-sector-breadth-legend" className="mb-2 grid grid-cols-2 gap-1 rounded border border-border/60 bg-base/35 p-2 text-[9px] sm:grid-cols-4"><span><b className="text-foreground">MA5</b><small className="ml-1 text-muted">站上5日均线占比</small></span><span><b className="text-foreground">MA10</b><small className="ml-1 text-muted">站上10日均线占比</small></span><span><b className="text-foreground">MA20</b><small className="ml-1 text-muted">站上20日均线占比</small></span><span><b className="text-foreground">MA60</b><small className="ml-1 text-muted">站上60日均线占比</small></span></div>
        <div data-testid="quantx-sector-breadth-scroll" className={cn('rounded border border-border/50 bg-base/20', breadthLevel === 1 ? 'overflow-x-clip' : 'max-h-[720px] overflow-y-auto overflow-x-hidden')}><SectorBreadthHeatmap data={breadth} height={breadthLevel === 1 ? Math.max(680, breadth.length * 20 + 76) : Math.max(720, breadth.length * 20 + 76)} /></div>
      </Panel>
    </div>
    <div className="grid gap-3 xl:grid-cols-2"><Panel title="行业流入 / 流出"><SectorFlowChart topIn={s4.sector_flow.top_in} topOut={s4.sector_flow.top_out} /></Panel><Panel title="涨跌幅 × 净流入"><SectorScatterChart data={s4.sector_treemap} /></Panel></div>
    {multiday && <SectorFlowContinuity data={multiday.sector_flow_continuity} />}
  </div>
  if (tab === 'watch') return <div className="grid gap-3 xl:grid-cols-[1.35fr_1fr]"><Panel title="完整关注名单"><GenericRows rows={s5.candidates} columns={['code', 'name', 'limit_times', 'reason', 'score', 'priority']} /></Panel><Panel testId="quantx-decision-zone" title="决断区" hint="仓位 · 场景 · 次日动作"><DecisionRail data={review} /></Panel></div>
  if (tab === 'data') return <CompleteDataPanel data={tables} />
  return <QualityPanel data={quality} />
}

export function QuantXDashboard() {
  const { date: routeDate } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [windowSize, setWindowSize] = useState<WindowSize>(20)
  const [breadthLevel, setBreadthLevel] = useState<1 | 2>(1)
  const [utilityOpen, setUtilityOpen] = useState({ data: false, quality: false })
  const [exporting, setExporting] = useState(false)

  const catalog = useQuery({ queryKey: QK.quantxCatalog, queryFn: quantxApi.getCatalog, staleTime: 30_000, retry: false })
  const records = useMemo(() => catalog.data?.records || [], [catalog.data])
  const dates = useMemo(() => records.map(record => record.trade_date).sort(), [records])
  const latest = useMemo(() => records.filter(record => record.multiday_available).at(-1)?.trade_date || dates.at(-1) || '', [dates, records])
  const date = routeDate || latest

  useEffect(() => {
    if (!routeDate && latest) navigate(`/quantx/${latest}`, { replace: true })
  }, [latest, navigate, routeDate])

  const reviewQuery = useQuery({ queryKey: QK.quantxReview(date), queryFn: () => quantxApi.getReviewData(date), enabled: Boolean(date), retry: false, staleTime: 0 })
  const multidayQuery = useQuery({ queryKey: QK.quantxMultiday(date), queryFn: () => quantxApi.getMultiday(date), enabled: Boolean(date), retry: false, staleTime: 30_000 })
  const advancedQuery = useQuery({ queryKey: QK.quantxAdvanced(date), queryFn: () => quantxApi.getAdvanced(date), enabled: Boolean(date), retry: false, staleTime: 30_000 })
  const tablesQuery = useQuery({ queryKey: QK.quantxTables(date), queryFn: () => quantxApi.getTables(date), enabled: Boolean(date) && utilityOpen.data, retry: false, staleTime: 30_000 })
  const qualityQuery = useQuery({ queryKey: QK.quantxObservability(date), queryFn: () => quantxApi.getObservability(date), enabled: Boolean(date) && utilityOpen.quality, retry: false, staleTime: 30_000 })
  const refresh = useMutation({
    mutationFn: () => quantxApi.runData(date, { force: true }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: QK.quantxCatalog }),
        queryClient.invalidateQueries({ queryKey: QK.quantxReview(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxMultiday(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxAdvanced(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxTables(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxObservability(date) }),
      ])
      toast(`QuantX ${date} 数据已刷新`, 'success')
    },
    onError: (error: Error) => toast(`QuantX 刷新失败：${error.message}`, 'error'),
  })

  const goDate = (target: string) => navigate(`/quantx/${target}`)
  const exportReport = async () => {
    const root = document.querySelector<HTMLElement>('[data-testid="quantx-unified-dashboard"]')
    if (!root) {
      toast('QuantX 导出失败：页面尚未准备完成', 'error')
      return
    }
    setExporting(true)
    try {
      const result = await downloadQuantXStaticHtml({ root, tradeDate: date })
      toast(`已导出 ${result.fileName}（${result.canvasCount} 张图表）`, 'success')
    } catch (error) {
      toast(`QuantX 导出失败：${error instanceof Error ? error.message : String(error)}`, 'error')
    } finally {
      setExporting(false)
    }
  }

  if (catalog.isLoading || (!routeDate && !latest)) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>
  if (!date || catalog.error) return <div className="py-16 text-center text-sm text-muted">QuantX 日期目录不可用：{String(catalog.error || '暂无已发布日期')}</div>
  if (reviewQuery.isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>
  if (reviewQuery.error || !reviewQuery.data) return <div data-testid="quantx-dashboard-error" className="space-y-3 py-16 text-center"><p className="text-sm text-muted">无 {date} 的单日标准事实</p>{multidayQuery.data && <p className="text-xs text-muted">该日期仅有多日派生数据</p>}</div>

  const review = reviewQuery.data
  if (review.data_foundation.canonical_fields.length === 0) {
    return (
      <div className="mx-auto max-w-[1720px] px-3 pb-16 md:px-4">
        <DashboardHeader date={date} dates={dates} refreshing={refresh.isPending} coverage="标准事实为空" onDate={goDate} onRefresh={() => refresh.mutate()} />
        <div data-testid="quantx-dashboard-empty" className="mt-8 rounded-xl border border-border py-20 text-center text-sm text-muted">该交易日没有可用的标准事实数据</div>
      </div>
    )
  }
  const multiday = multidayQuery.data
  const s = review.sections
  const breadth = breadthLevel === 2 ? s.s1.width_heat_level2 : s.s1.width_heat
  const coverage = multiday ? `覆盖 ${multiday.data_coverage.window_days}/20日` : '多日数据降级'

  return (
    <div className="mx-auto max-w-[1720px] overflow-x-clip px-3 pb-16 md:px-4" data-testid="quantx-unified-dashboard">
      <DashboardHeader date={date} dates={dates} refreshing={refresh.isPending} exporting={exporting} coverage={coverage} onDate={goDate} onRefresh={() => refresh.mutate()} onExport={() => void exportReport()} />
      <div className="mt-2 space-y-3">
        <MetricRibbon data={review} />
        <AnalysisDomainSection testId="quantx-domain-conclusion" title="今日市场结论" hint="先看市场方向、主线与风险，再进入各分析域验证" sequence="当前结论 → 今日行动" icon={<Zap className="h-4 w-4" />}>
          <div className="grid gap-2 xl:grid-cols-[repeat(16,minmax(0,1fr))]">
            <Panel testId="quantx-market-pulse" title="市场脉搏" hint="全A趋势 · MA · CCI5" icon={<TrendingUp className="h-3.5 w-3.5" />} className="xl:[grid-column:span_8/span_8]"><KlineChart history={s.s1.kline_history} height={236} /></Panel>
            <Panel testId="quantx-theme-mainline" title="题材主线" hint="按多源归一化强度降序 · 连续性 · 生命周期" icon={<Layers3 className="h-3.5 w-3.5" />} className="xl:[grid-column:span_8/span_8]"><ThemeMainline review={review} multiday={multiday} /></Panel>
            <RiskSignalBoard ebb={s.s3.ebb_signals} crash={s.s3.crash_signals} participation={s.s2.participation?.conditions || []} />
          </div>
        </AnalysisDomainSection>

        <section data-testid="quantx-deep-workspace" className="space-y-3">
          <AnalysisDomainSection testId="quantx-domain-market" title="市场状态与历史环境" hint="识别当前情绪阶段、历史异常与市场广度变化" sequence="当前状态 → 历史趋势 → 结构解释" icon={<Activity className="h-4 w-4" />}>
            <div data-testid="quantx-deep-market"><DeepSection tab="market" review={review} multiday={multiday} breadth={breadth} breadthLevel={breadthLevel} onBreadthLevel={setBreadthLevel} /></div>
            <Panel testId="quantx-emotion-calendar" title="情绪周期与交易日历" hint="QuantX market_state_daily 情绪分 · 不等同于 Regime 状态矩阵" icon={<Activity className="h-3.5 w-3.5" />}><EmotionCalendar data={review} records={records} multiday={multiday} date={date} /></Panel>
            <AdvancedPanels snapshot={advancedQuery.data} loading={advancedQuery.isLoading} error={advancedQuery.error} cardKeys={['sentiment_phase', 'state_transition', 'anomaly_calendar', 'advance_decline']} cardLayout={DOMAIN_ADVANCED_LAYOUTS.market} flat />
          </AnalysisDomainSection>

          <AnalysisDomainSection testId="quantx-domain-industry" title="行业轮动与资金生态" hint="把行业资金、宽度、相关性与轮动证据集中阅读" sequence="当前资金 → 历史连续性 → 结构解释 → 候选证据" icon={<Gauge className="h-4 w-4" />}>
            <div data-testid="quantx-deep-flow"><DeepSection tab="flow" review={review} multiday={multiday} breadth={breadth} breadthLevel={breadthLevel} onBreadthLevel={setBreadthLevel} /></div>
            <AdvancedPanels snapshot={advancedQuery.data} loading={advancedQuery.isLoading} error={advancedQuery.error} cardKeys={['sector_diffusion', 'industry_correlation', 'rps_rotation_clock']} cardLayout={DOMAIN_ADVANCED_LAYOUTS.industry} flat testId="quantx-advanced-industry" />
          </AnalysisDomainSection>

          <AnalysisDomainSection testId="quantx-domain-themes" title="题材生命周期与主线" hint="从多日信号进入题材生灭、排名演进与主线结构" sequence="当前主线 → 历史趋势 → 结构解释 → 股票证据" icon={<Layers3 className="h-4 w-4" />}>
            {multiday ? <WindowSignalMatrix data={multiday} active={windowSize} onChange={setWindowSize} /> : <Panel title="多日信号矩阵"><div className="py-12 text-center text-xs text-muted">该日期无多日快照</div></Panel>}
            <div data-testid="quantx-deep-themes"><DeepSection tab="themes" review={review} multiday={multiday} breadth={breadth} breadthLevel={breadthLevel} onBreadthLevel={setBreadthLevel} /></div>
            <AdvancedPanels snapshot={advancedQuery.data} loading={advancedQuery.isLoading} error={advancedQuery.error} cardKeys={['theme_river', 'mainline_waterfall']} cardLayout={DOMAIN_ADVANCED_LAYOUTS.themes} flat testId="quantx-advanced-themes" />
          </AnalysisDomainSection>

          <AnalysisDomainSection testId="quantx-domain-limit-board" title="连板与接力生态" hint="集中查看连板高度、晋级效率、层级结构与个股记录" sequence="当前梯队 → 历史趋势 → 晋级结构 → 个股证据" icon={<TrendingUp className="h-4 w-4" />}>
            <div data-testid="quantx-deep-emotion"><DeepSection tab="emotion" review={review} multiday={multiday} breadth={breadth} breadthLevel={breadthLevel} onBreadthLevel={setBreadthLevel} /></div>
            <AdvancedPanels snapshot={advancedQuery.data} loading={advancedQuery.isLoading} error={advancedQuery.error} cardKeys={['promotion_funnel', 'theme_ladder_sunburst']} cardLayout={DOMAIN_ADVANCED_LAYOUTS.limitBoard} flat testId="quantx-advanced-limit-board" />
          </AnalysisDomainSection>

          <AnalysisDomainSection testId="quantx-domain-liquidity" title="收益结构、拥挤与流动性" hint="解释赚钱效应、交易拥挤与成交集中程度" sequence="当前分布 → 历史拥挤 → 结构解释" icon={<Sparkles className="h-4 w-4" />}>
            <Panel testId="quantx-congestion-panel" title="市场拥挤度：最新状态与历史" hint="单一口径 · 前 5% 活跃股票成交额占比"><CongestionOverview data={s.s1.congestion} /></Panel>
            <AdvancedPanels snapshot={advancedQuery.data} loading={advancedQuery.isLoading} error={advancedQuery.error} cardKeys={['liquidity_participation', 'return_distribution', 'turnover_return_density', 'turnover_lorenz']} cardLayout={DOMAIN_ADVANCED_LAYOUTS.liquidity} flat testId="quantx-advanced-liquidity" />
          </AnalysisDomainSection>

          <AnalysisDomainSection testId="quantx-domain-decision" title="机会、关注池与最终决断" hint="把市场判断收束到机会、候选、仓位和次日动作" sequence="机会雷达 → 股票证据 → 仓位与场景" icon={<ShieldAlert className="h-4 w-4" />}>
            {multiday ? <OpportunityRadar data={multiday.opportunity_radar} /> : <Panel title="机会雷达"><div className="py-12 text-center text-xs text-muted">暂无多日机会数据</div></Panel>}
            <div data-testid="quantx-deep-watch"><DeepSection tab="watch" review={review} multiday={multiday} breadth={breadth} breadthLevel={breadthLevel} onBreadthLevel={setBreadthLevel} /></div>
          </AnalysisDomainSection>

          <AnalysisDomainSection testId="quantx-domain-data" title="数据与质量" hint="完整数据和质量血缘默认折叠，按需加载" sequence="数据覆盖 → 质量检查 → 来源血缘" icon={<Database className="h-4 w-4" />}>
            {([['data', '完整数据'], ['quality', '质量血缘']] as Array<[Extract<DeepTab, 'data' | 'quality'>, string]>).map(([tab, label]) => {
              const open = utilityOpen[tab]
              return <section key={tab} data-testid={`quantx-deep-${tab}`}>
                <button type="button" data-testid={`quantx-collapsible-${tab}`} aria-expanded={open} onClick={() => setUtilityOpen(current => ({ ...current, [tab]: !current[tab] }))} className="flex w-full cursor-pointer items-center gap-2 border-b border-border pb-2 text-left text-sm font-semibold transition-colors hover:text-accent"><ShieldCheck className="h-4 w-4 text-accent" /><h2>{label}</h2><span className="ml-auto text-[10px] font-normal text-muted">默认折叠 · 按需加载</span><ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} /></button>
                {open && <div className="pt-3"><DeepSection tab={tab} review={review} multiday={multiday} tables={tablesQuery.data as Record<string, any> | undefined} quality={qualityQuery.data} breadth={breadth} breadthLevel={breadthLevel} onBreadthLevel={setBreadthLevel} /></div>}
              </section>
            })}
          </AnalysisDomainSection>
        </section>
      </div>
    </div>
  )
}
