import { useMemo, useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, CalendarDays, Radar, Shapes, TrendingUp } from 'lucide-react'
import type { QuantXMultidaySnapshot, QuantXWindowComponent } from '@/lib/api'
import { cn } from '@/lib/cn'

export type WindowSize = 5 | 10 | 20

export function Panel({ title, icon, hint, children, testId }: { title: string; icon?: React.ReactNode; hint?: string; children: React.ReactNode; testId?: string }) {
  return <section data-testid={testId} className="rounded-xl border border-border bg-elevated/25 p-4">
    <div className="mb-3 flex items-start gap-2">
      <span className="mt-0.5 text-accent">{icon}</span>
      <div><h2 className="text-sm font-semibold">{title}</h2>{hint && <p className="text-[11px] text-muted">{hint}</p>}</div>
    </div>
    {children}
  </section>
}

const ARROW = {
  up: <ArrowUp className="h-3.5 w-3.5" />,
  down: <ArrowDown className="h-3.5 w-3.5" />,
  flat: <ArrowRight className="h-3.5 w-3.5" />,
  missing: <span>--</span>,
}

function componentTone(component: QuantXWindowComponent) {
  if (component.arrow === 'missing') return 'text-muted'
  if (component.key === 'risk') return component.arrow === 'up' ? 'text-red-400' : component.arrow === 'down' ? 'text-green-400' : 'text-muted'
  return component.arrow === 'up' ? 'text-red-400' : component.arrow === 'down' ? 'text-green-400' : 'text-muted'
}

export function WindowSignalMatrix({ data, active, onChange }: { data: QuantXMultidaySnapshot; active: WindowSize; onChange: (window: WindowSize) => void }) {
  const labels: Record<string, string> = { heat: '热度', breadth: '广度', relay: '接力', risk: '风险' }
  return <Panel title="5 / 10 / 20 日窗口信号矩阵" icon={<TrendingUp className="h-4 w-4" />} hint="按真实交易日计算；风险箭头上行为风险增加" testId="window-signal-matrix">
    <div className="grid gap-3 lg:grid-cols-3">
      {([5, 10, 20] as WindowSize[]).map(window => {
        const signal = data.window_signals[String(window) as '5' | '10' | '20']
        return <button key={window} onClick={() => onChange(window)} className={cn('rounded-lg border p-3 text-left transition-colors', active === window ? 'border-accent bg-accent/10' : 'border-border hover:bg-elevated')}>
          <div className="flex items-center justify-between"><span className="font-semibold">{window} 日</span><span className="rounded bg-base px-1.5 py-0.5 text-[10px] text-muted">{signal.confidence}</span></div>
          <div className="mt-1 text-lg font-bold">{signal.market.direction}</div>
          <div className="mt-3 grid grid-cols-4 gap-1">
            {signal.market.components.map(component => <div key={component.key} className={cn('rounded bg-base/70 p-1.5 text-center text-[10px]', componentTone(component))}>
              <div className="flex justify-center">{ARROW[component.arrow]}</div><div>{labels[component.key]}</div><div className="font-mono">{component.delta == null ? '--' : `${component.delta > 0 ? '+' : ''}${component.delta}`}</div>
            </div>)}
          </div>
        </button>
      })}
    </div>
  </Panel>
}

export function TradingCalendarGrid({ rows, selectedDate, onSelect, compact = false }: { rows: QuantXMultidaySnapshot['calendar']; selectedDate: string; onSelect: (date: string) => void; compact?: boolean }) {
  return (
    <div className={cn('grid grid-cols-5 gap-1.5', !compact && 'sm:grid-cols-10')}>
      {rows.slice(-30).map(row => {
        const heat = Number(row.market_heat_score ?? 0)
        const background = heat >= 70 ? 'bg-red-500/25' : heat >= 50 ? 'bg-orange-500/20' : heat >= 35 ? 'bg-blue-500/20' : 'bg-slate-500/15'
        return <button key={row.trade_date} aria-label={`选择交易日 ${row.trade_date}`} onClick={() => onSelect(row.trade_date)} className={cn('cursor-pointer rounded border px-1 text-center transition-colors', compact ? 'py-1' : 'py-2', background, selectedDate === row.trade_date ? 'border-accent ring-1 ring-accent' : 'border-border hover:border-muted')}>
          <div className="font-mono text-[10px] text-muted">{row.trade_date.slice(4, 6)}-{row.trade_date.slice(6)}</div>
          <div className="text-base font-bold">{row.market_heat_score ?? '--'}</div>
        </button>
      })}
    </div>
  )
}

export function TradingCalendar({ rows, selectedDate, onSelect }: { rows: QuantXMultidaySnapshot['calendar']; selectedDate: string; onSelect: (date: string) => void }) {
  return <Panel title="交易日历" icon={<CalendarDays className="h-4 w-4" />} hint="点击日期联动整个多日面板" testId="trading-calendar">
    <TradingCalendarGrid rows={rows} selectedDate={selectedDate} onSelect={onSelect} />
  </Panel>
}

export function WindowStatistics({ data, active, compact = false }: { data: QuantXMultidaySnapshot; active: WindowSize; compact?: boolean }) {
  const stats = data.window_statistics[String(active) as '5' | '10' | '20']
  const cards = [
    ['热度', stats.market_heat], ['涨停家数', stats.limit_up], ['封板率', stats.seal_rate], ['连板高度', stats.max_board],
  ] as const
  return <Panel title={`${active} 日窗口统计情报`} icon={<Radar className="h-4 w-4" />} hint={`${stats.valid_days} 个有效交易日 · 风险日 ${stats.risk_days}`} testId="window-statistics">
    <div className={cn('grid grid-cols-2 gap-2', !compact && 'sm:grid-cols-4')}>
      {cards.map(([label, item]) => <div key={label} className="rounded-lg border border-border bg-base/50 p-2"><div className="text-[10px] text-muted">{label}</div><div className="mt-1 font-mono text-lg font-semibold">{item?.average ?? '--'}</div><div className="text-[10px] text-muted">高 {item?.max ?? '--'} · 低 {item?.min ?? '--'}</div></div>)}
    </div>
  </Panel>
}

function MiniTable({ columns, rows }: { columns: Array<[string, string]>; rows: any[] }) {
  if (!rows.length) return <div className="py-8 text-center text-xs text-muted">当前覆盖范围暂无数据</div>
  return <div data-testid="quantx-adaptive-table" className="overflow-x-auto"><table className="w-max min-w-full table-auto text-[11px]"><thead><tr>{columns.map(([key, label]) => <th key={key} className="whitespace-nowrap border-b border-border px-2 py-1.5 text-left text-muted first:pl-0">{label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.code || row.name || index}-${index}`} className="border-b border-border/60">{columns.map(([key]) => { const value = LIFECYCLE_LABELS[String(row[key])] || row[key] || '--'; return <td key={key} className="max-w-44 truncate whitespace-nowrap px-2 py-1.5 first:pl-0 tabular-nums" title={String(value)}>{value}</td> })}</tr>)}</tbody></table></div>
}

const LIFECYCLE_LABELS: Record<string, string> = { new: '新生', strengthening: '增强', continuing: '延续', weakening: '转弱', exited: '退出' }

function LifecycleEventGrid({ rows }: { rows: any[] }) {
  if (!rows.length) return <div className="py-8 text-center text-xs text-muted">当前窗口无生灭事件</div>
  return <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 xl:grid-cols-4">{rows.map((row, index) => <div key={`${row.name}-${row.lifecycle}-${index}`} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-b border-border/50 py-1.5 text-[10px]"><span className="truncate font-medium" title={row.name}>{row.name}</span><span className={cn('rounded px-1.5 py-0.5', row.lifecycle === 'exited' || row.lifecycle === 'weakening' ? 'bg-green-500/10 text-green-300' : row.lifecycle === 'new' || row.lifecycle === 'strengthening' ? 'bg-red-500/10 text-red-300' : 'bg-elevated text-muted')}>{LIFECYCLE_LABELS[row.lifecycle] || row.lifecycle || '--'}</span><span className="tabular-nums text-muted">{row.streak ?? '--'}日</span></div>)}</div>
}

function LifecycleHeatmap({ heat }: { heat: QuantXMultidaySnapshot['theme_lifecycle']['heatmap'] }) {
  if (!heat.rows.length) return <div className="py-8 text-center text-xs text-muted">当前窗口无连续性数据</div>
  const columns = `72px repeat(${heat.dates.length}, minmax(10px, 1fr))`
  return <div className="text-[9px]" style={{ display: 'grid', gridTemplateColumns: columns, gap: '3px 2px' }}>
    <div className="text-muted">题材</div>
    {heat.dates.map(date => <div key={date} title={date} className="truncate text-center text-muted">{date.slice(-2)}</div>)}
    {heat.rows.map(row => <div key={row.name} className="contents"><div className="truncate py-0.5 font-medium" title={row.name}>{row.name}</div>{row.values.map((value, index) => <span key={index} title={`${row.name} ${heat.dates[index]} ${value ?? 0}`} className="h-4 min-w-0 rounded-sm" style={{ background: value == null ? 'hsl(var(--border))' : `rgba(248,81,73,${Math.max(.08, value / 110)})` }} />)}</div>)}
  </div>
}

export function ThemeLifecyclePanel({ data }: { data: QuantXMultidaySnapshot }) {
  const heat = data.theme_lifecycle.heatmap
  return <Panel title="题材生灭与连续性" icon={<Shapes className="h-4 w-4" />} hint="多源排名归一化后计算生命周期" testId="theme-lifecycle">
    <div data-testid="theme-lifecycle-all" className="grid items-start gap-3 xl:grid-cols-12">
      <section data-testid="theme-lifecycle-current" className="min-w-0 rounded-lg border border-border/70 bg-base/25 p-2.5 xl:col-span-5">
        <h3 className="mb-2 text-xs font-semibold">当日结构</h3>
        <MiniTable columns={[["name", "题材"], ["source_count", "来源"], ["rank_strength", "强度"], ["streak", "连续"], ["lifecycle", "状态"]]} rows={data.theme_lifecycle.current.slice(0, 20)} />
      </section>
      <section data-testid="theme-lifecycle-heatmap" className="min-w-0 rounded-lg border border-border/70 bg-base/25 p-2.5 xl:col-span-7">
        <h3 className="mb-2 text-xs font-semibold">连续性热力图</h3>
        <LifecycleHeatmap heat={heat} />
      </section>
      <section data-testid="theme-lifecycle-events" className="min-w-0 rounded-lg border border-border/70 bg-base/25 p-2.5 xl:col-span-12">
        <h3 className="mb-2 text-xs font-semibold">跨日生灭</h3>
        <LifecycleEventGrid rows={[...data.theme_lifecycle.events, ...data.theme_lifecycle.exited]} />
      </section>
    </div>
  </Panel>
}

export function FactorAttribution({ rows }: { rows: QuantXMultidaySnapshot['factor_attribution'] }) {
  const max = Math.max(1, ...rows.map(row => row.count || 0))
  return <Panel title="涨停因子归因" hint="同花顺原因标签的确定性计数" testId="factor-attribution"><div className="space-y-2">{rows.slice(0, 10).map(row => <div key={row.name}><div className="mb-0.5 flex justify-between text-xs"><span>{row.name}</span><span className="font-mono text-muted">{row.count}</span></div><div className="h-1.5 rounded bg-base"><div className="h-full rounded bg-accent" style={{ width: `${Math.max(3, row.count / max * 100)}%` }} /></div></div>)}</div></Panel>
}

export function OpportunityRadar({ data }: { data: QuantXMultidaySnapshot['opportunity_radar'] }) {
  const [tab, setTab] = useState<'themes' | 'sectors' | 'stocks'>('themes')
  const rows = data[tab]
  const columns: Array<[string, string]> = tab === 'stocks'
    ? [['code', '代码'], ['name', '名称'], ['score', '评分'], ['active_days', '活跃日'], ['source', '来源']]
    : [['name', tab === 'themes' ? '题材' : '行业'], ['score', '评分'], ['active_days', '活跃日'], ['last_seen', '最近']]
  return <Panel title="题材 / 行业 / 个股多日机会雷达" icon={<Radar className="h-4 w-4" />} hint="确定性规则评分，不含人工或 LLM 判断" testId="opportunity-radar">
    <div className="mb-3 flex items-center gap-1">{(['themes', 'sectors', 'stocks'] as const).map(key => <button key={key} onClick={() => setTab(key)} className={cn('rounded px-2.5 py-1 text-xs', tab === key ? 'bg-accent/20 text-accent' : 'text-muted')}>{key === 'themes' ? '题材' : key === 'sectors' ? '行业' : '个股'}</button>)}<span className="ml-auto text-[10px] text-muted">覆盖 {(data.coverage_confidence[tab] * 100).toFixed(0)}%</span></div>
    <MiniTable columns={columns} rows={rows} />
  </Panel>
}

export function SectorFlowContinuity({ data }: { data: QuantXMultidaySnapshot['sector_flow_continuity'] }) {
  const industries = useMemo(() => data.industries.map(row => ({ ...row, net_inflow_sum_yi: Number(row.net_inflow_sum_yi ?? 0).toFixed(2) })), [data.industries])
  return <Panel title="行业资金与规则候选连续性" icon={<TrendingUp className="h-4 w-4" />} hint={`${data.direction} · 覆盖 ${(data.coverage * 100).toFixed(0)}% · 不代表机构身份`} testId="sector-flow-continuity">
    <MiniTable columns={[["name", "行业"], ["active_days", "活跃日"], ["net_inflow_sum_yi", "累计净流入(亿)"], ["last_pct_chg", "最新涨跌"], ["last_seen", "最近"]]} rows={industries} />
    {data.rule_candidates.length > 0 && <div className="mt-4"><h3 className="mb-2 text-xs font-semibold">连续规则候选</h3><MiniTable columns={[["code", "代码"], ["name", "名称"], ["priority", "层级"], ["active_days", "活跃日"], ["source", "规则类型"]]} rows={data.rule_candidates} /></div>}
  </Panel>
}
