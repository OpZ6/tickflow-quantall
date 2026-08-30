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
  const activeSignal = data.window_signals[String(active) as '5' | '10' | '20']
  const themeGroups = [['主线', activeSignal.themes?.mainline || []], ['升温', activeSignal.themes?.warming || []], ['降温', activeSignal.themes?.cooling || []]] as const
  return <Panel title="5 / 10 / 20 日信号与统计" icon={<TrendingUp className="h-4 w-4" />} hint="同卡对比方向、变化和区间统计；均按真实交易日计算，风险箭头上行为风险增加" testId="window-signal-matrix">
    <div className="grid gap-3 lg:grid-cols-3">
      {([5, 10, 20] as WindowSize[]).map(window => {
        const signal = data.window_signals[String(window) as '5' | '10' | '20']
        const stats = data.window_statistics[String(window) as '5' | '10' | '20']
        const statRows = [['热度', stats.market_heat], ['涨停', stats.limit_up], ['封板率', stats.seal_rate], ['最高板', stats.max_board]] as const
        return <button key={window} type="button" data-testid={`window-statistics-${window}`} aria-pressed={active === window} onClick={() => onChange(window)} className={cn('cursor-pointer rounded-lg border p-3 text-left transition-colors', active === window ? 'border-accent bg-accent/10' : 'border-border hover:bg-elevated')}>
          <div className="flex items-center justify-between gap-2"><span className="font-semibold">{window} 日</span><span className="rounded bg-base px-1.5 py-0.5 text-[10px] text-muted">有效 {stats.valid_days} 日 · 风险 {stats.risk_days} 日 · {signal.confidence}</span></div>
          <div className="mt-1 text-lg font-bold">{signal.market.direction}</div>
          <div className="mt-3 grid grid-cols-4 gap-1">
            {signal.market.components.map(component => <div key={component.key} className={cn('rounded bg-base/70 p-1.5 text-center text-[10px]', componentTone(component))}>
              <div className="flex justify-center">{ARROW[component.arrow]}</div><div>{labels[component.key]}</div><div className="font-mono">{component.delta == null ? '--' : `${component.delta > 0 ? '+' : ''}${component.delta}`}</div>
            </div>)}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1.5 border-t border-border/60 pt-2">
            {statRows.map(([label, item]) => <div key={label} className="rounded bg-base/45 px-2 py-1.5"><div className="flex items-baseline justify-between gap-1"><span className="text-[9px] text-muted">{label}均值</span><span className="font-mono text-xs font-semibold">{item?.average ?? '--'}</span></div><div className="mt-0.5 text-right font-mono text-[8px] text-muted">高 {item?.max ?? '--'} · 低 {item?.min ?? '--'}</div></div>)}
          </div>
        </button>
      })}
    </div>
    <div data-testid="window-theme-structure" className="mt-3 rounded-lg border border-border/70 bg-base/25 p-2.5">
      <div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold">{active} 日题材结构</h3><span className="text-[10px] text-muted">窗口内有效题材 {activeSignal.themes.observed_days} 日</span></div>
      <div className="grid gap-2 md:grid-cols-3">{themeGroups.map(([label, rows]) => <section key={label} className="min-w-0 rounded-md border border-border/60 bg-base/40 p-2"><h4 className="mb-1.5 text-[10px] font-semibold text-muted">{label}题材</h4><div className="flex flex-wrap gap-1">{rows.slice(0, 8).map(row => <span key={row.name} title={`${row.active_days}/${activeSignal.themes.observed_days} 日 · 均值 ${row.average_strength} · 前后半窗 ${row.strength_change > 0 ? '+' : ''}${row.strength_change}`} className="rounded bg-elevated px-1.5 py-0.5 text-[10px]">{row.name}</span>)}{!rows.length && <span className="text-[10px] text-muted">暂无</span>}</div></section>)}</div>
    </div>
  </Panel>
}

export function TradingCalendarGrid({ rows, selectedDate, onSelect, compact = false }: { rows: QuantXMultidaySnapshot['calendar']; selectedDate: string; onSelect: (date: string) => void; compact?: boolean }) {
  return (
    <div data-testid="quantx-emotion-calendar-grid" className={cn('grid grid-cols-5 gap-1.5', !compact && 'sm:grid-cols-10')}>
      {rows.slice(-30).map(row => {
        const heat = Number(row.market_heat_score ?? 0)
        const background = heat >= 70 ? 'border-red-400/70 bg-red-500/40 text-red-50' : heat >= 50 ? 'border-orange-400/65 bg-orange-500/35 text-orange-50' : heat >= 35 ? 'border-sky-400/60 bg-sky-500/30 text-sky-50' : 'border-slate-400/55 bg-slate-600/45 text-slate-50'
        return <button key={row.trade_date} aria-label={`选择交易日 ${row.trade_date}`} onClick={() => onSelect(row.trade_date)} className={cn('cursor-pointer rounded border px-1 text-center shadow-sm transition-colors hover:brightness-110', compact ? 'py-1' : 'py-2', background, selectedDate === row.trade_date && 'ring-2 ring-accent ring-offset-1 ring-offset-base')}>
          <div className="font-mono text-[10px] opacity-80">{row.trade_date.slice(4, 6)}-{row.trade_date.slice(6)}</div>
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

function MiniTable({ columns, rows }: { columns: Array<[string, string]>; rows: any[] }) {
  if (!rows.length) return <div className="py-8 text-center text-xs text-muted">当前覆盖范围暂无数据</div>
  return <div data-testid="quantx-adaptive-table" className="overflow-x-auto"><table className="w-max min-w-full table-auto text-[11px]"><thead><tr>{columns.map(([key, label]) => <th key={key} className="whitespace-nowrap border-b border-border px-2 py-1.5 text-left text-muted first:pl-0">{label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.code || row.name || index}-${index}`} className="border-b border-border/60">{columns.map(([key]) => { const value = LIFECYCLE_LABELS[String(row[key])] || row[key] || '--'; return <td key={key} className="max-w-44 truncate whitespace-nowrap px-2 py-1.5 first:pl-0 tabular-nums" title={String(value)}>{value}</td> })}</tr>)}</tbody></table></div>
}

const LIFECYCLE_LABELS: Record<string, string> = { new: '新生', strengthening: '增强', continuing: '延续', weakening: '转弱', exited: '退出' }

function LifecycleEventGrid({ rows }: { rows: any[] }) {
  if (!rows.length) return <div className="py-8 text-center text-xs text-muted">当前窗口无生灭事件</div>
  const uniqueRows = Array.from(new Map(rows.map(row => [`${row.name}-${row.lifecycle}-${row.streak}`, row])).values())
  const order = ['new', 'strengthening', 'continuing', 'weakening', 'exited']
  const groups = order.map(status => ({ status, rows: uniqueRows.filter(row => row.lifecycle === status) })).filter(group => group.rows.length)
  return <div className="space-y-2">{groups.map(group => <section key={group.status} data-testid={`lifecycle-group-${group.status}`} className="grid gap-2 rounded-md border border-border/60 bg-base/30 p-2 sm:grid-cols-[84px_minmax(0,1fr)]">
    <div className="flex items-center justify-between gap-2 self-start sm:block"><h4 className={cn('text-[11px] font-semibold', group.status === 'exited' || group.status === 'weakening' ? 'text-green-300' : group.status === 'new' || group.status === 'strengthening' ? 'text-red-300' : 'text-foreground')}>{LIFECYCLE_LABELS[group.status]}</h4><span className="text-[9px] text-muted">{group.rows.length}项</span></div>
    <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2 xl:grid-cols-4">{group.rows.map((row, index) => <div key={`${row.name}-${index}`} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-border/40 py-1 text-[10px]"><span className="truncate font-medium" title={row.name}>{row.name}</span><span className="tabular-nums text-muted">{row.streak ?? '--'}日</span></div>)}</div>
  </section>)}</div>
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
  return <Panel title="题材生灭与多源连续性" icon={<Shapes className="h-4 w-4" />} hint="多源排名先分别归一化，再计算强度、连续出现和生命周期；不是原始名次" testId="theme-lifecycle">
    <div data-testid="theme-lifecycle-all" className="grid items-start gap-3 xl:grid-cols-12">
      <section data-testid="theme-lifecycle-current" className="min-w-0 rounded-lg border border-border/70 bg-base/25 p-2.5 xl:col-span-5">
        <h3 className="mb-2 text-xs font-semibold">当日结构</h3>
        <MiniTable columns={[["name", "题材"], ["source_count", "来源"], ["rank_strength", "强度"], ["streak", "连续"], ["lifecycle", "状态"]]} rows={data.theme_lifecycle.current.slice(0, 20)} />
      </section>
      <section data-testid="theme-lifecycle-heatmap" className="min-w-0 rounded-lg border border-border/70 bg-base/25 p-2.5 xl:col-span-7">
        <h3 className="mb-0.5 text-xs font-semibold">多源归一化强度连续性</h3>
        <p className="mb-2 text-[9px] text-muted">同花顺热榜、问财、DeepQ 各自按榜单长度归一化至 0–100，再按题材合并；颜色越深代表跨源持续强度越高</p>
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
  return <Panel title="同花顺热点题材覆盖" hint="同花顺热点榜题材的覆盖股票数；不是涨停原因标签归因" testId="factor-attribution"><div className="space-y-2">{rows.slice(0, 10).map(row => <div key={row.name}><div className="mb-0.5 flex justify-between text-xs"><span>{row.name}</span><span className="font-mono text-muted">{row.count}</span></div><div className="h-1.5 rounded bg-base"><div className="h-full rounded bg-accent" style={{ width: `${Math.max(3, row.count / max * 100)}%` }} /></div></div>)}</div></Panel>
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
    <div className="grid items-start gap-3 xl:grid-cols-2">
      <section data-testid="sector-flow-industries" className="min-w-0 rounded-lg border border-border/60 bg-base/25 p-2.5"><h3 className="mb-2 text-xs font-semibold">行业资金连续性</h3><MiniTable columns={[["name", "行业"], ["active_days", "活跃日"], ["net_inflow_sum_yi", "累计净流入(亿)"], ["last_pct_chg", "最新涨跌"], ["last_seen", "最近"]]} rows={industries} /></section>
      <section data-testid="sector-flow-rules" className="min-w-0 rounded-lg border border-border/60 bg-base/25 p-2.5"><h3 className="mb-2 text-xs font-semibold">连续规则候选</h3><MiniTable columns={[["code", "代码"], ["name", "名称"], ["priority", "层级"], ["active_days", "活跃日"], ["source", "规则类型"]]} rows={data.rule_candidates} /></section>
    </div>
  </Panel>
}
