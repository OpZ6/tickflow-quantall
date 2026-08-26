/**
 * QuantX structured data view.
 *
 * This page deliberately consumes only /api/quantx-data/* artifacts. It is a
 * table/chart viewer for deterministic source data; it does not render or
 * depend on an HTML report, LLM decision or editorial output.
 */
import { useMemo, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts'
import { ChevronLeft, ChevronRight, CalendarDays, Loader2, LayoutGrid, Database, AlertTriangle } from 'lucide-react'
import { quantxApi, type QuantXDataTables } from '@/lib/api'
import { useChartTheme } from '@/lib/theme'
import { cn } from '@/lib/cn'

const RED = '#f85149'
const CYAN = '#58a6ff'

function number(value: unknown, digits = 2): string {
  if (value === null || value === undefined || value === '') return '--'
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : String(value)
}

function useEChart(option: echarts.EChartsOption, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!ref.current) return
    instance.current ??= echarts.init(ref.current)
    instance.current.setOption(option, true)
    return () => { instance.current?.dispose(); instance.current = null }
  }, deps)
  return ref
}

function DateNav({ date, dates }: { date: string; dates: string[] }) {
  const navigate = useNavigate()
  const sorted = useMemo(() => [...dates].sort(), [dates])
  const index = sorted.indexOf(date)
  const previous = index > 0 ? sorted[index - 1] : null
  const next = index >= 0 && index < sorted.length - 1 ? sorted[index + 1] : null
  const latest = sorted.at(-1) || date
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button aria-label="前一交易日" disabled={!previous} onClick={() => previous && navigate(`/quantx/${previous}`)} className="rounded-btn border border-border p-1.5 disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
      <div className="relative">
        <CalendarDays className="h-4 w-4 text-muted absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        <select aria-label="交易日" value={date} onChange={(event) => navigate(`/quantx/${event.target.value}`)} className="appearance-none rounded-btn border border-border bg-elevated pl-8 pr-7 py-1.5 text-sm font-semibold">
          {sorted.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
      </div>
      <button aria-label="后一交易日" disabled={!next} onClick={() => next && navigate(`/quantx/${next}`)} className="rounded-btn border border-border p-1.5 disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
      <button onClick={() => navigate(`/quantx/${latest}`)} className="rounded-btn border border-border px-2.5 py-1.5 text-xs text-muted">最新</button>
      <button onClick={() => navigate('/quantx')} className="ml-auto rounded-btn border border-border px-2.5 py-1.5 text-xs text-muted flex items-center gap-1"><LayoutGrid className="h-3 w-3" />驾驶舱</button>
    </div>
  )
}

function Card({ label, value, tone = 'text-foreground' }: { label: string; value: React.ReactNode; tone?: string }) {
  return <div className="rounded-lg border border-border bg-elevated/40 px-3 py-2"><div className="text-[10px] text-muted">{label}</div><div className={cn('text-lg font-semibold font-mono', tone)}>{value}</div></div>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mt-6"><h2 className="text-base font-semibold border-b border-border pb-2 mb-3">{title}</h2>{children}</section>
}

function TrendChart({ rows }: { rows: any[] }) {
  const theme = useChartTheme()
  const sorted = useMemo(() => [...rows].sort((a, b) => String(a.date).localeCompare(String(b.date))), [rows])
  const option = useMemo<echarts.EChartsOption>(() => ({
    tooltip: { trigger: 'axis' },
    legend: { data: ['市场热度', '短线情绪', '趋势情绪'], textStyle: { color: theme.text, fontSize: 11 } },
    grid: { left: 38, right: 18, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: sorted.map(row => row.date), axisLabel: { color: theme.text, fontSize: 10 } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: theme.text, fontSize: 10 }, splitLine: { lineStyle: { color: theme.grid } } },
    series: [
      { name: '市场热度', type: 'line', data: sorted.map(row => row.market_heat ?? null), itemStyle: { color: RED }, lineStyle: { color: RED } },
      { name: '短线情绪', type: 'line', data: sorted.map(row => row.short_term ?? null), itemStyle: { color: '#f78166' }, lineStyle: { color: '#f78166' } },
      { name: '趋势情绪', type: 'line', data: sorted.map(row => row.trend ?? null), itemStyle: { color: CYAN }, lineStyle: { color: CYAN } },
    ],
  }), [sorted, theme.text, theme.grid])
  const ref = useEChart(option, [option])
  return sorted.length > 1 ? <div ref={ref} className="w-full" style={{ height: 260 }} /> : <div className="text-xs text-muted py-8 text-center">历史数据不足</div>
}

function SimpleTable({ columns, rows, empty = '暂无数据' }: { columns: Array<{ key: string; label: string; numeric?: boolean }>; rows: any[]; empty?: string }) {
  if (!rows.length) return <div className="text-xs text-muted py-6 text-center">{empty}</div>
  return <div className="overflow-x-auto rounded-lg border border-border"><table className="w-full text-xs"><thead className="bg-elevated"><tr>{columns.map(column => <th key={column.key} className={cn('px-2 py-1.5 whitespace-nowrap', column.numeric ? 'text-right' : 'text-left')}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.code || row.name || index}-${index}`} className="border-t border-border hover:bg-elevated/50">{columns.map(column => <td key={column.key} className={cn('px-2 py-1.5 whitespace-nowrap', column.numeric ? 'text-right font-mono' : '')}>{row[column.key] ?? '--'}</td>)}</tr>)}</tbody></table></div>
}

function Overview({ data }: { data: QuantXDataTables }) {
  const overview = data.market_overview || {}
  const breadth = data.market_breadth || overview.breadth || {}
  const limit = data.limit_summary || {}
  const sentiment = data.sentiment_state || data._computed || {}
  return <>
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 mt-4">
      <Card label="市场热度" value={number(sentiment.market_heat?.score, 0)} tone="text-red-400" />
      <Card label="短线情绪" value={number(sentiment.short_term_sentiment?.score, 0)} tone="text-orange-400" />
      <Card label="趋势情绪" value={number(sentiment.trend_sentiment?.score, 0)} tone="text-blue-400" />
      <Card label="涨停" value={limit.limit_up_count ?? '--'} tone="text-red-400" />
      <Card label="跌停" value={limit.limit_down_count ?? '--'} tone="text-green-400" />
      <Card label="封板率" value={limit.seal_rate == null ? '--' : `${number(limit.seal_rate, 1)}%`} />
      <Card label="上涨/下跌" value={`${breadth.up_count ?? '--'} / ${breadth.down_count ?? '--'}`} />
      <Card label="成交额" value={overview.total_amount_yi == null ? '--' : `${number(overview.total_amount_yi, 0)}亿`} />
    </div>
    <Section title="市场指数"><SimpleTable columns={[{ key: 'name', label: '指数' }, { key: 'close', label: '收盘', numeric: true }, { key: 'pct_chg', label: '涨跌幅', numeric: true }]} rows={overview.indexes || []} /></Section>
  </>
}

export function QuantXReview() {
  const { date = '' } = useParams()
  const navigate = useNavigate()
  const catalogQuery = useQuery({ queryKey: ['quantx-data-catalog'], queryFn: () => quantxApi.getCatalog(), staleTime: 30_000 })
  const dates = useMemo(() => (catalogQuery.data?.records || []).map(record => record.trade_date), [catalogQuery.data])
  const dataQuery = useQuery({ queryKey: ['quantx-data-tables', date], queryFn: () => quantxApi.getTables(date), enabled: Boolean(date), retry: false, staleTime: 30_000 })
  if (catalogQuery.isLoading || dataQuery.isLoading) return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>
  if (dataQuery.error || !dataQuery.data) return <div className="text-center py-12 space-y-3"><p className="text-muted text-sm">无 {date} 的结构化数据</p><button onClick={() => navigate('/quantx')} className="text-accent text-sm hover:underline">返回驾驶舱</button></div>
  const data = dataQuery.data
  const quality = data.quality || {}
  const ladder = Object.entries(data.limit_ladder?.ladder_by_height || {}).flatMap(([height, rows]: [string, any]) => (Array.isArray(rows) ? rows : []).map(row => ({ ...row, height })))
  const themes = data.theme_rankings?.themes || data.theme_snapshot?.themes || []
  const themeHistory = data.theme_history?.days || []
  const sectors = data.sector_fund_flow?.sectors || []
  const candidates = data.screening_candidates?.candidates || []
  const trendRows = data.trend_history?.days || []
  return <div className="mx-auto max-w-7xl p-4 pb-20">
    <DateNav date={date} dates={dates.length ? dates : [date]} />
    <div className="flex items-center gap-2 mt-4"><Database className="h-5 w-5 text-accent" /><h1 className="text-xl font-bold">QuantX 数据面板</h1><span className="text-xs text-muted">{date} · 结构化数据</span><span className={cn('ml-auto rounded px-2 py-1 text-xs', quality.status === 'complete' ? 'bg-green-500/10 text-green-400' : 'bg-orange-500/10 text-orange-400')}>{quality.status || 'legacy'}</span></div>
    {quality.warnings?.length > 0 && <div className="mt-3 rounded border border-orange-500/30 bg-orange-500/5 p-2 text-xs text-orange-300"><AlertTriangle className="inline h-3 w-3 mr-1" />{quality.warnings.join('；')}</div>}
    <Overview data={data} />
    <Section title="情绪趋势"><div className="rounded-lg border border-border bg-elevated/30 p-2"><TrendChart rows={trendRows} /></div></Section>
    <Section title="连板梯队"><SimpleTable columns={[{ key: 'height', label: '板数', numeric: true }, { key: 'code', label: '代码' }, { key: 'name', label: '名称' }, { key: 'limit_times', label: '连板', numeric: true }, { key: 'turnover_pct', label: '换手率', numeric: true }, { key: 'theme_name', label: '题材' }]} rows={ladder} /></Section>
    <Section title="题材排行"><SimpleTable columns={[{ key: 'rank', label: '排名', numeric: true }, { key: 'name', label: '题材' }, { key: 'count', label: '关联数量', numeric: true }]} rows={themes} /></Section>
    <Section title="题材历史"><SimpleTable columns={[{ key: 'date', label: '日期' }, { key: 'themes', label: '当日题材' }]} rows={themeHistory.slice(-10).map((row: any) => ({ ...row, themes: row.themes?.slice(0, 5).map((item: any) => `${item.name}(${item.count})`).join('、') }))} /></Section>
    <Section title="板块资金流"><SimpleTable columns={[{ key: 'name', label: '板块' }, { key: 'pct_chg', label: '涨跌幅', numeric: true }, { key: 'net_inflow_yi', label: '净流入(亿)', numeric: true }, { key: 'amount_yi', label: '成交额(亿)', numeric: true }]} rows={sectors.slice(0, 40)} /></Section>
    <Section title="规则筛选结果"><p className="text-xs text-muted mb-2">仅表示确定性规则命中，不包含人工或 LLM 判断。</p><SimpleTable columns={[{ key: 'code', label: '代码' }, { key: 'name', label: '名称' }, { key: 'rules_matched', label: '命中规则' }, { key: 'rules_failed', label: '未通过规则' }]} rows={candidates.map((row: any) => ({ ...row, rules_matched: row.rules_matched?.join('、'), rules_failed: row.rules_failed?.join('、') }))} /></Section>
  </div>
}
