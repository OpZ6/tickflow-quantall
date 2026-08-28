import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Database,
  Gauge,
  Layers3,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { toast } from '@/components/Toast'
import {
  FactorAttribution,
  OpportunityRadar,
  SectorFlowContinuity,
  ThemeLifecyclePanel,
  TradingCalendarGrid,
  WindowSignalMatrix,
  WindowStatistics,
  type WindowSize,
} from '@/components/quantx/MultidayPanels'
import { quantxApi, type QuantXMultidaySnapshot, type QuantXReviewData } from '@/lib/api'
import { cn } from '@/lib/cn'
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

const DEEP_TABS: Array<[DeepTab, string]> = [
  ['market', '市场趋势'],
  ['themes', '题材行业'],
  ['emotion', '情绪连板'],
  ['flow', '资金生态'],
  ['watch', '关注预案'],
  ['data', '完整数据'],
  ['quality', '质量血缘'],
]

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

function DashboardHeader({ date, dates, refreshing, coverage, onDate, onRefresh }: {
  date: string
  dates: string[]
  refreshing: boolean
  coverage?: string
  onDate: (date: string) => void
  onRefresh: () => void
}) {
  const index = dates.indexOf(date)
  const previous = index > 0 ? dates[index - 1] : null
  const next = index >= 0 && index < dates.length - 1 ? dates[index + 1] : null
  const latest = dates.at(-1)
  return (
    <header data-testid="quantx-dashboard-header" className="sticky top-0 z-20 -mx-3 flex flex-wrap items-center gap-2 border-b border-border bg-base/95 px-3 py-2 backdrop-blur md:-mx-4 md:px-4">
      <div className="mr-2 flex items-center gap-2"><Zap className="h-4 w-4 text-accent" /><h1 className="text-base font-bold text-foreground">QuantX 市场驾驶舱</h1></div>
      <button aria-label="前一交易日" disabled={!previous} onClick={() => previous && onDate(previous)} className="cursor-pointer rounded border border-border p-1.5 disabled:cursor-not-allowed disabled:opacity-30"><ChevronLeft className="h-3.5 w-3.5" /></button>
      <label className="relative">
        <CalendarDays className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
        <select aria-label="QuantX交易日" value={date} onChange={event => onDate(event.target.value)} className="cursor-pointer appearance-none rounded border border-border bg-elevated py-1.5 pl-7 pr-6 text-xs font-semibold">
          {dates.map(value => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <button aria-label="后一交易日" disabled={!next} onClick={() => next && onDate(next)} className="cursor-pointer rounded border border-border p-1.5 disabled:cursor-not-allowed disabled:opacity-30"><ChevronRight className="h-3.5 w-3.5" /></button>
      <button type="button" disabled={!latest || latest === date} onClick={() => latest && onDate(latest)} className="cursor-pointer rounded border border-border px-2 py-1.5 text-[10px] text-muted disabled:cursor-not-allowed disabled:opacity-40">最新</button>
      <div className="ml-auto flex items-center gap-2 text-[10px] text-muted">
        <span className="hidden items-center gap-1 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-green-400" />{coverage || '覆盖待确认'}</span>
        <button type="button" onClick={onRefresh} disabled={refreshing} className="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-2 py-1.5 text-foreground disabled:cursor-not-allowed disabled:opacity-50">
          {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}刷新
        </button>
      </div>
    </header>
  )
}

function ThemeMainline({ review, multiday }: { review: QuantXReviewData; multiday?: QuantXMultidaySnapshot }) {
  const rows = multiday?.theme_lifecycle.current?.slice(0, 8) || []
  if (!rows.length) {
    const fallback = review.sections.s2.themes_pywencai.slice(0, 8)
    return <div className="space-y-1">{fallback.map((row, index) => <div key={`${row.name}-${index}`} className="flex items-center justify-between rounded bg-base/40 px-2 py-1.5 text-xs"><span>{index + 1}. {row.name}</span><span className="font-mono text-muted">{row.count ?? '--'}</span></div>)}</div>
  }
  return (
    <div className="space-y-1">
      {rows.map((row: any, index: number) => (
        <div key={`${row.name}-${index}`} className="grid grid-cols-[24px_1fr_52px_52px_68px] items-center gap-1 rounded bg-base/40 px-1.5 py-1.5 text-[10px] hover:bg-elevated">
          <span className="text-muted">{index + 1}</span><span className="truncate text-xs font-medium">{row.name}</span><span className="text-right font-mono text-red-400">{row.rank_strength ?? '--'}</span><span className="text-right">{row.streak ?? '--'}日</span><span className="truncate text-right text-muted">{row.lifecycle ?? '--'}</span>
        </div>
      ))}
    </div>
  )
}

function DecisionRail({ data }: { data: QuantXReviewData }) {
  const { s0, s3, s6 } = data.sections
  return (
    <div className="space-y-2">
      <div className="rounded border border-orange-500/30 bg-orange-500/5 p-2"><div className="text-[9px] text-muted">仓位与动作</div><div className="mt-0.5 font-semibold text-orange-300">{s6.position?.band || '--'}</div><div className="mt-1 text-[10px] text-muted">{s6.position?.action || '--'}</div></div>
      <div className="space-y-1">
        {s0.risks.slice(0, 6).map((risk, index) => <div key={`${risk.name}-${index}`} className="grid grid-cols-[8px_1fr_auto] items-center gap-1.5 rounded bg-base/40 px-2 py-1 text-[10px]"><span className={cn('h-1.5 w-1.5 rounded-full', risk.triggered ? 'bg-orange-400' : 'bg-green-400')} /><span className="truncate">{risk.name}</span><span className={risk.triggered ? 'text-orange-300' : 'text-muted'}>{risk.status || (risk.triggered ? '触发' : '正常')}</span></div>)}
      </div>
      <div className="grid grid-cols-2 gap-1 text-[10px]"><div className="rounded bg-base/40 p-1.5">退潮信号 <b className="float-right">{s3.ebb_signals.filter(item => item.triggered).length}</b></div><div className="rounded bg-base/40 p-1.5">崩塌信号 <b className="float-right">{s3.crash_signals.filter(item => item.triggered).length}</b></div></div>
    </div>
  )
}

function EmotionCalendar({ data, records, multiday, date, onDate }: { data: QuantXReviewData; records: Array<{ trade_date: string; metrics: Record<string, number | string | boolean | null> }>; multiday?: QuantXMultidaySnapshot; date: string; onDate: (date: string) => void }) {
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
        <div className="mb-2 flex items-center justify-between"><div><h3 className="text-xs font-semibold">交易日情绪分数</h3><p className="text-[10px] text-muted">点击日期切换整页；颜色对应市场热度</p></div><CalendarDays className="h-4 w-4 text-accent" /></div>
        {multiday ? <TradingCalendarGrid rows={multiday.calendar} selectedDate={date} onSelect={onDate} compact /> : <div className="py-16 text-center text-xs text-muted">该日期无交易日历快照</div>}
      </div>
    </div>
  )
}

function Watchlist({ data }: { data: QuantXReviewData }) {
  const rows = data.sections.s5.candidates
  if (!rows.length) return <div className="py-12 text-center text-xs text-muted">当前没有关注候选</div>
  return <div>{rows.slice(0, 8).map((row, index) => <div key={`${row.code}-${index}`} className="grid grid-cols-[1fr_auto_auto] gap-2 border-b border-border/60 px-1 py-2 text-[10px]"><div><b className="text-xs">{row.name}</b> <span className="font-mono text-muted">{row.code}</span><div className="mt-0.5 truncate text-muted">{row.reason}</div></div><span className="text-accent">{row.limit_times ?? '--'}板</span><span>{row.score ?? row.priority ?? '--'}</span></div>)}</div>
}

function WindowDetails({ snapshot, windowSize }: { snapshot: QuantXMultidaySnapshot; windowSize: WindowSize }) {
  const signal = snapshot.window_signals[String(windowSize) as '5' | '10' | '20']
  const groups = [['主线', signal.themes?.mainline || []], ['升温', signal.themes?.warming || []], ['降温', signal.themes?.cooling || []]] as const
  return <div className="mt-2 grid gap-2 md:grid-cols-3">{groups.map(([label, rows]) => <div key={label} className="rounded border border-border bg-base/30 p-2"><div className="mb-1 text-[10px] text-muted">{label}题材</div><div className="flex flex-wrap gap-1">{rows.slice(0, 6).map((row: any, index: number) => <span key={`${row.name || row}-${index}`} className="rounded bg-elevated px-1.5 py-0.5 text-[10px]">{row.name || String(row)}</span>)}{!rows.length && <span className="text-[10px] text-muted">暂无</span>}</div></div>)}</div>
}

function GenericRows({ rows }: { rows: any[] }) {
  if (!rows.length) return <div className="py-8 text-center text-xs text-muted">当前数据集无记录</div>
  const columns = Array.from(new Set(rows.slice(0, 20).flatMap(row => row && typeof row === 'object' ? Object.keys(row) : []))).slice(0, 12)
  if (!columns.length) return <pre className="max-h-96 overflow-auto text-[10px]">{JSON.stringify(rows, null, 2)}</pre>
  return <div className="max-h-[520px] overflow-auto"><table className="w-full text-[10px]"><thead className="sticky top-0 bg-elevated"><tr>{columns.map(column => <th key={column} className="border-b border-border px-2 py-1.5 text-left text-muted">{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-b border-border/50">{columns.map(column => <td key={column} className="max-w-56 truncate px-2 py-1.5" title={typeof row[column] === 'object' ? JSON.stringify(row[column]) : String(row[column] ?? '')}>{typeof row[column] === 'object' ? JSON.stringify(row[column]) : String(row[column] ?? '--')}</td>)}</tr>)}</tbody></table></div>
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
  return <div className="grid gap-3 xl:grid-cols-2"><div><h3 className="mb-2 text-xs font-semibold">数据来源</h3><GenericRows rows={data.sources || []} /></div><div><h3 className="mb-2 text-xs font-semibold">Market Facts</h3><GenericRows rows={data.facts || []} /></div><div className="rounded border border-border p-3 text-xs"><div>发布状态：{data.status}</div><div>标准事实：{data.fact_summary?.present_partition_count ?? '--'}/{data.fact_summary?.expected_partition_count ?? '--'}</div><div>Review：{data.view?.schema_version ?? '--'} · canonical {data.view?.canonical_count ?? '--'} · derived {data.view?.derived_count ?? '--'}</div><div>多日：{data.multiday?.schema_version ?? '--'}</div></div><div className="rounded border border-border p-3 text-xs"><div>对账：{data.reconciliation?.status ?? '--'} · 缺口 {data.reconciliation?.gap_count ?? '--'}</div><div className="mt-1 text-orange-300">{(data.warnings || []).join('；') || '无警告'}</div><div className="mt-1 text-red-300">{(data.errors || []).join('；') || '无错误'}</div></div></div>
}

function DeepSection({ tab, review, multiday, tables, quality }: { tab: DeepTab; review: QuantXReviewData; multiday?: QuantXMultidaySnapshot; tables?: Record<string, any>; quality?: any }) {
  const { s1, s2, s3, s4, s5, s6 } = review.sections
  if (tab === 'market') return <div className="grid gap-3 xl:grid-cols-2"><Panel title="主要指数" className="xl:col-span-2"><IndexChart indexes={s1.indexes} /></Panel><Panel title="涨跌家数 + 成交额"><UpCountChart history={s1.up_count_history} /></Panel><Panel title="融资余额 + 净买入"><MarginChart history={s1.margin_history} /></Panel><Panel title="拥挤度"><CongestionGauge pct={s1.congestion?.latest.congestion_pct ?? 0} /></Panel><Panel title="拥挤度历史"><GenericRows rows={(s1.congestion?.table || []).map(row => ({ date: row[0], close: row[1], top5_amount: row[2], total_amount: row[3], congestion_pct: row[4] }))} /></Panel></div>
  if (tab === 'themes') return <div className="grid gap-3 xl:grid-cols-2">{multiday && <><div className="xl:col-span-2"><ThemeLifecyclePanel data={multiday} /></div><FactorAttribution rows={multiday.factor_attribution} /></>}<Panel title="参与度条件"><GenericRows rows={s2.participation?.conditions || []} /></Panel><Panel title="多源题材"><GenericRows rows={[...s2.themes_pywencai.map(row => ({ source: 'pywencai', ...row })), ...s2.themes_ths.map(row => ({ source: 'ths', name: row.tag, count: row.count, rank: row.rank }))]} /></Panel><Panel title="百日新高" className="xl:col-span-2"><GenericRows rows={s2.new_high?.stocks || []} /></Panel></div>
  if (tab === 'emotion') return <div className="grid gap-3 xl:grid-cols-2"><Panel title="连板高度历史"><HeightChart history={s3.height_history} /></Panel><Panel title="晋级率 / 溢价率 / 涨停数"><AdvanceRateChart history={s3.advance_history} /></Panel><Panel title="连板梯队网格"><GenericRows rows={s3.ladder_grid} /></Panel><Panel title="连板详细记录"><GenericRows rows={s3.ladder_detail} /></Panel><Panel title="退潮信号"><GenericRows rows={s3.ebb_signals} /></Panel><Panel title="崩塌信号"><GenericRows rows={s3.crash_signals} /></Panel></div>
  if (tab === 'flow') return <div className="grid gap-3 xl:grid-cols-2"><Panel title="行业流入 / 流出" className="xl:col-span-2"><SectorFlowChart topIn={s4.sector_flow.top_in} topOut={s4.sector_flow.top_out} /></Panel><Panel title="涨跌幅 × 净流入" className="xl:col-span-2"><SectorScatterChart data={s4.sector_treemap} /></Panel>{multiday && <><div className="xl:col-span-2"><SectorFlowContinuity data={multiday.sector_flow_continuity} /></div><Panel title="机构趋势连续性"><GenericRows rows={multiday.institution_continuity.industries || []} /></Panel><Panel title="机构规则候选"><GenericRows rows={multiday.institution_continuity.rule_candidates || []} /></Panel><Panel title="核心个股" className="xl:col-span-2"><GenericRows rows={[...(multiday.sector_flow_continuity.core_stocks || []), ...(multiday.institution_continuity.core_stocks || [])]} /></Panel></>}</div>
  if (tab === 'watch') return <div className="grid gap-3 xl:grid-cols-[1.4fr_1fr]"><Panel title="完整关注名单"><GenericRows rows={s5.candidates} /></Panel><Panel title="仓位与次日场景"><div className="rounded bg-base/40 p-3 text-sm"><b>{s6.position?.band || '--'}</b><p className="mt-1 text-xs text-muted">{s6.position?.action || '--'}</p></div><div className="mt-2"><GenericRows rows={s6.scenes} /></div><p className="mt-3 rounded border border-border p-3 text-xs text-muted">{review.emotion.daily_summary}</p></Panel></div>
  if (tab === 'data') return <CompleteDataPanel data={tables} />
  return <QualityPanel data={quality} />
}

export function QuantXDashboard() {
  const { date: routeDate } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [windowSize, setWindowSize] = useState<WindowSize>(20)
  const [breadthLevel, setBreadthLevel] = useState<1 | 2>(1)

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
  const tablesQuery = useQuery({ queryKey: QK.quantxTables(date), queryFn: () => quantxApi.getTables(date), enabled: Boolean(date), retry: false, staleTime: 30_000 })
  const qualityQuery = useQuery({ queryKey: QK.quantxObservability(date), queryFn: () => quantxApi.getObservability(date), enabled: Boolean(date), retry: false, staleTime: 30_000 })
  const refresh = useMutation({
    mutationFn: () => quantxApi.runData(date, { force: true }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: QK.quantxCatalog }),
        queryClient.invalidateQueries({ queryKey: QK.quantxReview(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxMultiday(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxTables(date) }),
        queryClient.invalidateQueries({ queryKey: QK.quantxObservability(date) }),
      ])
      toast(`QuantX ${date} 数据已刷新`, 'success')
    },
    onError: (error: Error) => toast(`QuantX 刷新失败：${error.message}`, 'error'),
  })

  const goDate = (target: string) => navigate(`/quantx/${target}`)

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
    <div className="mx-auto max-w-[1720px] px-3 pb-16 md:px-4" data-testid="quantx-unified-dashboard">
      <DashboardHeader date={date} dates={dates} refreshing={refresh.isPending} coverage={coverage} onDate={goDate} onRefresh={() => refresh.mutate()} />
      <div className="mt-2 space-y-2">
        <MetricRibbon data={review} />
        <div className="grid gap-2 xl:grid-cols-[repeat(16,minmax(0,1fr))]">
          <Panel testId="quantx-market-pulse" title="市场脉搏" hint="全A趋势 · MA · CCI5" icon={<TrendingUp className="h-3.5 w-3.5" />} className="xl:[grid-column:span_6/span_6]"><KlineChart history={s.s1.kline_history} height={236} /></Panel>
          <Panel testId="quantx-theme-mainline" title="题材主线" hint="强度 · 连续性 · 生命周期" icon={<Layers3 className="h-3.5 w-3.5" />} className="xl:[grid-column:span_6/span_6]"><ThemeMainline review={review} multiday={multiday} /></Panel>
          <Panel testId="quantx-decision-rail" title="今日决断" hint="仓位 · 风险 · 预案" icon={<ShieldAlert className="h-3.5 w-3.5" />} className="xl:[grid-column:span_4/span_4]"><DecisionRail data={review} /></Panel>

          {multiday ? <div className="xl:[grid-column:span_7/span_7]"><WindowSignalMatrix data={multiday} active={windowSize} onChange={setWindowSize} /><WindowDetails snapshot={multiday} windowSize={windowSize} /></div> : <Panel title="多日信号矩阵" className="xl:[grid-column:span_7/span_7]"><div className="py-12 text-center text-xs text-muted">该日期无多日快照</div></Panel>}
          <Panel testId="quantx-emotion-calendar" title="情绪周期与交易日历" hint="趋势、分数与日期上下文统一展示" icon={<Activity className="h-3.5 w-3.5" />} className="xl:[grid-column:span_9/span_9]"><EmotionCalendar data={review} records={records} multiday={multiday} date={date} onDate={goDate} /></Panel>

          <div className="xl:[grid-column:span_5/span_5]">{multiday ? <OpportunityRadar data={multiday.opportunity_radar} /> : <Panel title="机会雷达"><div className="py-12 text-center text-xs text-muted">暂无多日机会数据</div></Panel>}</div>
          <Panel testId="quantx-sector-breadth" title={`申万${breadthLevel === 1 ? '一级' : '二级'}行业均线宽度`} hint="MA5 / MA10 / MA20 / MA60" icon={<Gauge className="h-3.5 w-3.5" />} actions={<SmallTabs values={[[1, '一级'], [2, '二级']]} active={breadthLevel} onChange={setBreadthLevel} label="行业层级" />} className="xl:[grid-column:span_7/span_7]"><SectorBreadthHeatmap data={breadth} maxRows={10} height={250} /></Panel>
          <Panel testId="quantx-watchlist" title="关注池与触发条件" hint={`${s.s5.candidates.length} 个候选`} icon={<AlertTriangle className="h-3.5 w-3.5" />} className="xl:[grid-column:span_4/span_4]"><div className="max-h-[250px] overflow-auto"><Watchlist data={review} /></div></Panel>

          <Panel testId="quantx-capital-ecosystem" title="资金生态" hint="行业净流入结构" icon={<Sparkles className="h-3.5 w-3.5" />} className="xl:[grid-column:span_6/span_6]"><SectorTreemapChart data={s.s4.sector_treemap} height={292} /></Panel>
          <div className="grid gap-2 xl:[grid-column:span_10/span_10] xl:grid-cols-3">{multiday ? ([5, 10, 20] as WindowSize[]).map(value => <WindowStatistics key={value} data={multiday} active={value} compact />) : <Panel title="窗口统计情报"><div className="py-12 text-center text-xs text-muted">暂无多日窗口统计</div></Panel>}</div>
        </div>

        <section data-testid="quantx-deep-workspace" className="rounded-lg border border-border bg-elevated/20">
          <header className="flex items-center gap-2 border-b border-border px-3 py-2 text-xs font-semibold"><Database className="h-3.5 w-3.5 text-accent" />深度图表与完整数据</header>
          <div className="p-3">
            <div className="space-y-8">{DEEP_TABS.map(([tab, label]) => <section key={tab}><h2 className="mb-3 flex items-center gap-2 border-b border-border pb-2 text-sm font-semibold"><Database className="h-4 w-4 text-accent" />{label}</h2><DeepSection tab={tab} review={review} multiday={multiday} tables={tablesQuery.data as Record<string, any> | undefined} quality={qualityQuery.data} /></section>)}</div>
          </div>
        </section>
      </div>
    </div>
  )
}
