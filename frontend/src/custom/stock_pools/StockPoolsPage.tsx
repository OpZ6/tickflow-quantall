import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, CircleDot, RefreshCw, Search, Telescope, X } from 'lucide-react'
import { stockPoolApi, type StockPoolCandidate, type StockPoolCluster, type StockPoolThemeContext } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { usePipelineRefresh } from '@/lib/usePipelineRefresh'
import { StockPoolHistoryReview } from './StockPoolHistoryReview'
import { StockPoolMiniKline } from './StockPoolMiniKline'
import { AmvPanel } from '@/components/AmvPanel'

type PersonalState = 'unseen' | 'priority' | 'pending' | 'seen' | 'ignored'
type View = 'workbench' | 'all' | 'review'
type ChangeView = 'complete' | 'today'
type QueueMode = 'members' | 'topic_event' | 'signal' | 'low_buy' | 'research' | 'priority' | 'pending'
type LowEvidence = 'all' | 'logic' | 'smnc' | 'static'

const PERSONAL_LABELS: Record<PersonalState, string> = {
  unseen: '未处理', priority: '重点跟踪', pending: '待确认', seen: '已看', ignored: '暂不关注',
}
const LOW_STAGES = new Set(['趋势延续', '回踩整理', '企稳修复'])
function lowBuyDistanceOrder(a: StockPoolCandidate, b: StockPoolCandidate): number {
  const aDistance = a.price_context?.ma20_distance_pct == null ? Infinity : Math.abs(a.price_context.ma20_distance_pct)
  const bDistance = b.price_context?.ma20_distance_pct == null ? Infinity : Math.abs(b.price_context.ma20_distance_pct)
  return aDistance === bDistance ? 0 : aDistance < bDistance ? -1 : 1
}
const EVENT_SOURCES = new Set(['breakthrough', 'limit_ladder', 'abnormal_surge', 'divergence', 'failed_limit_repair', 'trend_pullback'])
const TOPIC_PREVIEW_LIMIT = 15
const THEME_SOURCE_NAMES: Record<string, string> = { ths_hot: '同花顺热点', pywencai: '问财涨停题材', deepq: 'DeepQ题材' }

function themeContextShort(context?: StockPoolThemeContext): string | null {
  if (!context) return null
  const ranked = context.sources.find(item => item.status === 'ranked')
  if (ranked) return `${THEME_SOURCE_NAMES[ranked.source] || ranked.source} ${ranked.rank ? `第${ranked.rank}/${ranked.list_size}位` : '上榜'} · 近5日${ranked.seen_days}/${ranked.available_days}次`
  if (context.sources.some(item => item.status === 'ambiguous')) return '外部名称存在歧义'
  const related = context.sources.find(item => item.related_narrower?.length)
  if (related) return `${THEME_SOURCE_NAMES[related.source] || related.source}相关细分：${related.related_narrower?.[0]?.name}`
  return null
}

function ThemeContextPanel({ context, staticProxy = false }: { context?: StockPoolThemeContext; staticProxy?: boolean }) {
  if (!context) return null
  return <div className="mt-2.5 rounded-lg border border-[#303037] bg-[#111113] px-3 py-2 text-[10px]">
    <div className="flex flex-wrap items-baseline justify-between gap-1"><strong className="text-secondary">外部题材观察</strong><span className="text-muted">各源仅为自身榜单；名次只与同源比较{staticProxy || context.basis === 'latest_static_proxy' ? ' · 当前关联含最新静态概念' : ''}</span></div>
    <div className="mt-1.5 grid gap-1.5 sm:grid-cols-3">{context.sources.map(item => <div key={item.source} className="rounded border border-[#28282e] px-2 py-1.5">
      <div className="font-medium text-secondary">{THEME_SOURCE_NAMES[item.source] || item.source}</div>
      <div className="mt-0.5 text-foreground">{item.status === 'ranked' ? `今日第${item.rank ?? '—'}/${item.list_size ?? '—'}位` : item.status === 'not_ranked' ? '今日榜单未见' : item.status === 'ambiguous' ? '名称匹配有歧义' : '今日来源缺失'}{item.previous_date ? ` · ${item.previous_date.slice(5)} ${item.previous_rank ? `第${item.previous_rank}位` : '未上榜'}` : ''}</div>
      <div className="mt-0.5 text-muted">{item.available_days ? `近5日可用${item.available_days}次 · 上榜${item.seen_days}次` : '近5日无可用榜单'}{item.raw_name ? ` · ${item.raw_name}` : ''}</div>
      {Boolean(item.related_narrower?.length) && <div className="mt-0.5 text-amber-200">名称相关细分：{item.related_narrower?.map(value => `${value.name}${value.rank ? ` #${value.rank}` : ''}`).join('、')} · 未核对成员</div>}
    </div>)}</div>
  </div>
}
const STAGE_CHIP: Record<string, string> = {
  '活跃观察': 'border-amber-500/45 bg-amber-500/10 text-amber-300',
  '人气观察': 'border-violet-500/45 bg-violet-500/10 text-violet-300',
  '突破启动': 'border-blue-500/45 bg-blue-500/10 text-blue-300',
  '异动加速': 'border-orange-500/45 bg-orange-500/10 text-orange-300',
  '涨停强化': 'border-red-500/45 bg-red-500/10 text-red-300',
  '趋势延续': 'border-cyan-500/45 bg-cyan-500/10 text-cyan-300',
  '高位分歧': 'border-fuchsia-500/45 bg-fuchsia-500/10 text-fuchsia-300',
  '回踩整理': 'border-emerald-500/45 bg-emerald-500/10 text-emerald-300',
  '企稳修复': 'border-teal-500/45 bg-teal-500/10 text-teal-300',
}
const SOURCE_STYLE: Record<string, { dot: string; chip: string; role: string }> = {
  breakthrough: { dot: 'bg-blue-400', chip: 'border-blue-500/40 bg-blue-500/10 text-blue-300', role: '事件' },
  limit_ladder: { dot: 'bg-red-500', chip: 'border-red-500/45 bg-red-500/10 text-red-300', role: '事件' },
  abnormal_surge: { dot: 'bg-orange-400', chip: 'border-orange-500/40 bg-orange-500/10 text-orange-300', role: '事件' },
  liquidity_trend: { dot: 'bg-cyan-400', chip: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300', role: '状态' },
  divergence: { dot: 'bg-violet-400', chip: 'border-violet-500/40 bg-violet-500/10 text-violet-300', role: '事件' },
  failed_limit_repair: { dot: 'bg-rose-400', chip: 'border-rose-500/40 bg-rose-500/10 text-rose-300', role: '事件' },
  trend_pullback: { dot: 'bg-emerald-400', chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300', role: '状态' },
  active_character: { dot: 'bg-yellow-400', chip: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-300', role: '记忆' },
  popularity_warm: { dot: 'bg-indigo-400', chip: 'border-indigo-500/40 bg-indigo-500/10 text-indigo-300', role: '外部' },
}
const CHANGE_KINDS: [string, string][] = [
  ['all', '全部信号+变化'],
  ['signal', '当日事件信号'],
  ['new', '新增入池'],
  ['source', '来源变化'],
  ['stage', '阶段变化'],
]
const RANGE_DEFS: [keyof RangeState, string][] = [
  ['pct', '涨跌幅 %'],
  ['amount', '成交额 亿'],
  ['market_cap', '市值 亿'],
  ['turnover', '换手 %'],
]
const QUEUE_META: Record<QueueMode, { label: string; note: string; copy: string }> = {
  members: { label: '全部成员', note: '当前筛选范围内的完整成员', copy: '列出当前筛选范围内的全部成员，逐股核对阶段、来源与个人状态。' },
  topic_event: { label: '题材事件', note: '当日事件 + 题材 + 至少2类召回', copy: '只关注同时具备当日事件、明确题材和至少两类召回的交叉候选，用于先处理信息密度最高的股票。' },
  signal: { label: '全部当日信号', note: '查看所有事件触发', copy: '展示所有事件型召回，并保留题材、研究材料、来源数量和阶段状态，便于检查当天发生了什么。' },
  low_buy: { label: '趋势低吸', note: '趋势延续、回踩或修复', copy: '按阶段和距MA20由近及远排队，再核对近10日涨幅与研究材料；价格位置只用于浏览顺序。' },
  research: { label: '有研究材料', note: '定向公司材料', copy: '汇总已审计主证据、辅助证据或SMNC标题单股材料；反证、多股罗列和正文提及可在个股详情核对。' },
  priority: { label: '重点跟踪', note: '你的个人名单', copy: '这是手动维护的注意力队列，不会改变候选召回和阶段判断。' },
  pending: { label: '待确认', note: '需要继续核对', copy: '集中处理仍需补证据或主观判断的候选。' },
}
type RangeState = { pct: { min: string; max: string }; amount: { min: string; max: string }; market_cap: { min: string; max: string }; turnover: { min: string; max: string } }
const FIELD_MAP: Record<keyof RangeState, (r: StockPoolCandidate) => number> = {
  pct: r => r.pct_chg, amount: r => r.amount_yi, market_cap: r => r.market_cap_yi, turnover: r => r.turnover_pct,
}

function storageKey(date: string) { return `stock-pools:personal:v1:${date}` }
const trackedKey = 'stock-pools:tracked:v1'

function readPersonal(date: string): Record<string, PersonalState> {
  try {
    const daily = JSON.parse(localStorage.getItem(storageKey(date)) || '{}') as Record<string, PersonalState>
    let tracked = JSON.parse(localStorage.getItem(trackedKey) || 'null') as Record<string, PersonalState> | null
    if (!tracked) {
      tracked = Object.fromEntries(Object.entries(daily).filter(([, state]) => state === 'priority' || state === 'pending'))
      localStorage.setItem(trackedKey, JSON.stringify(tracked))
    }
    const merged = { ...daily }
    for (const [symbol, state] of Object.entries(tracked)) {
      if (state === 'priority' || state === 'pending') merged[symbol] = state
      else if (merged[symbol] === 'priority' || merged[symbol] === 'pending') merged[symbol] = 'unseen'
    }
    return merged
  } catch { return {} }
}

function Tag({ children, tone = 'normal' }: { children: React.ReactNode; tone?: 'normal' | 'accent' | 'warm' }) {
  const cls = tone === 'accent' ? 'border-accent/30 bg-accent/15 text-accent' : tone === 'warm' ? 'border-warning/30 bg-warning/10 text-warning' : 'border-border bg-elevated text-secondary'
  return <span className={`inline-flex rounded border px-1.5 py-0.5 text-[9px] ${cls}`}>{children}</span>
}

function Metric({ label, value, note, accent }: { label: string; value: string | number; note?: string; accent?: boolean }) {
  return <div className="rounded-card border border-border bg-surface px-4 py-3">
    <div className="text-xs text-muted">{label}</div><div className={`mt-1 text-2xl font-semibold ${accent ? 'text-accent' : 'text-foreground'}`}>{value}</div>
    {note && <div className="mt-1 text-[11px] text-muted">{note}</div>}
  </div>
}

function SummaryMetric({ label, value, note, tone }: { label: string; value: string; note: string; tone: 'slate' | 'blue' | 'red' | 'amber' }) {
  const colors = { slate: 'after:bg-slate-400', blue: 'after:bg-blue-500', red: 'after:bg-red-500', amber: 'after:bg-amber-500' }
  const values = { slate: 'text-foreground', blue: 'text-blue-400', red: 'text-red-400', amber: 'text-amber-400' }
  return <div className={`relative min-h-[76px] overflow-hidden rounded-lg border border-[#2a2a2f] bg-gradient-to-br from-[#18181b] to-[#131315] px-4 py-3 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 ${colors[tone]}`}><div className="text-[10px] text-muted">{label}</div><div className={`mt-2 font-mono text-2xl font-bold leading-none ${values[tone]}`}>{value}<span className="ml-2 text-[9px] font-normal text-secondary">{note}</span></div></div>
}

function lowTopicLabels(row: StockPoolCandidate): string[] {
  if (row.topics.length) return row.topics
  return [row.primary_concept || row.memberships?.concept?.[0]].filter((label): label is string => Boolean(label))
}
const ROLE_DEFS: [string, string[]][] = [
  ['启动与加速', ['突破启动', '异动加速']],
  ['涨停强化', ['涨停强化']],
  ['分歧与修复', ['高位分歧', '回踩整理', '企稳修复']],
  ['趋势延续', ['趋势延续']],
  ['历史与人气观察', ['活跃观察', '人气观察']],
]

function clusterLow(rows: StockPoolCandidate[]): StockPoolCluster[] {
  const groups = new Map<string, StockPoolCandidate[]>()
  for (const row of rows.filter(item => LOW_STAGES.has(item.primary_stage))) {
    for (const label of lowTopicLabels(row)) groups.set(label, [...(groups.get(label) ?? []), row])
  }
  return [...groups].filter(([, items]) => items.length >= 3).map(([name, items]) => {
    const related = new Map<string, string[]>()
    for (const item of items) for (const concept of item.memberships?.concept ?? []) {
      if (concept !== name) related.set(concept, [...(related.get(concept) ?? []), item.symbol])
    }
    const subgroups = [...related].filter(([, symbols]) => symbols.length >= 2)
      .map(([label, symbols]) => ({ name: label, count: symbols.length, symbols }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)).slice(0, 10)
    const logicCount = items.filter(item => item.topics.includes(name)).length
    return {
      name, dimension: logicCount === items.length ? 'logic' : logicCount ? 'mixed' : 'concept',
      count: items.length, event_count: items.filter(item => item.source_ids.some(source => EVENT_SOURCES.has(source))).length,
      up_count: items.filter(item => item.pct_chg > 0).length,
      mean_pct_chg: items.reduce((sum, item) => sum + item.pct_chg, 0) / items.length,
      stage_counts: Object.fromEntries([...new Set(items.map(item => item.primary_stage))].map(stage => [stage, items.filter(item => item.primary_stage === stage).length])),
      symbols: items.map(item => item.symbol), subgroups,
    }
  }).sort((a, b) =>
    ({ logic: 0, mixed: 1, concept: 2 }[a.dimension] ?? 3) - ({ logic: 0, mixed: 1, concept: 2 }[b.dimension] ?? 3)
    || b.count - a.count || b.event_count - a.event_count || a.name.localeCompare(b.name))
}

type TopicCluster = StockPoolCluster & { startupCount: number; pullbackCount: number }

function mergeTopicClusters(hot: StockPoolCluster[], low: StockPoolCluster[], rows: StockPoolCandidate[]): TopicCluster[] {
  const bySymbol = new Map(rows.map(row => [row.symbol, row]))
  const hotByName = new Map(hot.map(cluster => [cluster.name, cluster]))
  const lowByName = new Map(low.map(cluster => [cluster.name, cluster]))
  return [...new Set([...hotByName.keys(), ...lowByName.keys()])].map(name => {
    const dynamic = hotByName.get(name)
    const pullback = lowByName.get(name)
    const members = [...new Set([...(dynamic?.symbols ?? []), ...(pullback?.symbols ?? [])])]
      .map(symbol => bySymbol.get(symbol)).filter((row): row is StockPoolCandidate => Boolean(row))
    const memberSymbols = new Set(members.map(row => row.symbol))
    const subgroupSymbols = new Map<string, Set<string>>()
    for (const subgroup of [...(dynamic?.subgroups ?? []), ...(pullback?.subgroups ?? [])]) {
      const symbols = subgroupSymbols.get(subgroup.name) ?? new Set<string>()
      for (const symbol of subgroup.symbols) if (memberSymbols.has(symbol)) symbols.add(symbol)
      subgroupSymbols.set(subgroup.name, symbols)
    }
    const subgroups = [...subgroupSymbols].map(([label, symbols]) => ({ name: label, count: symbols.size, symbols: [...symbols] }))
      .filter(subgroup => subgroup.count >= 2).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)).slice(0, 10)
    const logicCount = members.filter(row => row.topics.includes(name)).length
    return {
      name, dimension: logicCount === members.length ? 'logic' : logicCount ? 'mixed' : 'concept',
      count: members.length,
      event_count: members.filter(row => row.source_ids.some(source => EVENT_SOURCES.has(source))).length,
      up_count: members.filter(row => row.pct_chg > 0).length,
      mean_pct_chg: members.length ? members.reduce((sum, row) => sum + row.pct_chg, 0) / members.length : 0,
      stage_counts: Object.fromEntries([...new Set(members.map(row => row.primary_stage))].map(stage => [stage, members.filter(row => row.primary_stage === stage).length])),
      symbols: members.map(row => row.symbol), subgroups,
      research_background: dynamic?.research_background,
      startupCount: members.filter(row => ['突破启动', '异动加速', '涨停强化'].includes(row.primary_stage)).length,
      pullbackCount: members.filter(row => LOW_STAGES.has(row.primary_stage)).length,
    }
  }).filter(cluster => cluster.count > 0).sort((a, b) => b.count - a.count || b.event_count - a.event_count || a.name.localeCompare(b.name))
}

function signedPct(value: number | null | undefined): string {
  return value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function reviewSelect(symbol: string, personal: Record<string, PersonalState>, onPersonal: (s: string, v: PersonalState) => void) {
  return <select value={personal[symbol] ?? 'unseen'} onChange={e => onPersonal(symbol, e.target.value as PersonalState)} className="w-full rounded border border-border bg-surface px-2 py-1 text-xs">
    {Object.entries(PERSONAL_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
  </select>
}

export function StockPoolsPage() {
  const pipelineRefresh = usePipelineRefresh()
  const memberSectionRef = useRef<HTMLDivElement>(null)
  const catalog = useQuery({ queryKey: QK.stockPoolCatalog, queryFn: stockPoolApi.getCatalog })
  const [date, setDate] = useState('')
  const [view, setView] = useState<View>('workbench')
  const [topic, setTopic] = useState('')
  const [stage, setStage] = useState('')
  const [subgroup, setSubgroup] = useState('')
  const [sources, setSources] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [showAllTopics, setShowAllTopics] = useState(false)
  const [showAllQueue, setShowAllQueue] = useState(false)
  const [queueMode, setQueueMode] = useState<QueueMode>('topic_event')
  const [lowEvidence, setLowEvidence] = useState<LowEvidence>('all')
  const [workbenchQuery, setWorkbenchQuery] = useState('')
  const [selected, setSelected] = useState<StockPoolCandidate | null>(null)
  const [historySelection, setHistorySelection] = useState<{ date: string; symbol: string; snapshot: 'current' | 'first' } | null>(null)
  const [personal, setPersonal] = useState<Record<string, PersonalState>>({})

  // All-candidates view state
  const [changeView, setChangeView] = useState<ChangeView>('complete')
  const [changeKind, setChangeKind] = useState('all')
  const [tier, setTier] = useState('all')
  const [exchange, setExchange] = useState('')
  const [sourceCount, setSourceCount] = useState(0)
  const [researchFilter, setResearchFilter] = useState('all')
  const [freshFilter, setFreshFilter] = useState('')
  const [hideReviewed, setHideReviewed] = useState(false)
  const [reviewFilter, setReviewFilter] = useState('all')
  const [sortMode, setSortMode] = useState('default')
  const [ranges, setRanges] = useState<RangeState>({ pct: { min: '', max: '' }, amount: { min: '', max: '' }, market_cap: { min: '', max: '' }, turnover: { min: '', max: '' } })
  const [showExitPanel, setShowExitPanel] = useState(false)

  useEffect(() => { if (!date && catalog.data?.latest_date) setDate(catalog.data.latest_date) }, [catalog.data?.latest_date, date])
  useEffect(() => { if (date) setPersonal(readPersonal(date)) }, [date])
  useEffect(() => { setLowEvidence('all'); setShowAllQueue(false) }, [date])
  useEffect(() => {
    const job = pipelineRefresh.job
    if (job?.status !== 'succeeded') return
    const refreshedDate = job.result?.stock_pools?.trade_date || job.result?.quantx?.trade_date
    if (refreshedDate && refreshedDate !== date) { setDate(refreshedDate); setTopic(''); setStage(''); setSubgroup('') }
  }, [date, pipelineRefresh.job])

  const summary = useQuery({ queryKey: QK.stockPoolSummary(date), queryFn: () => stockPoolApi.getSummary(date), enabled: Boolean(date) })
  const candidates = useQuery({ queryKey: QK.stockPoolCandidates(date), queryFn: () => stockPoolApi.getCandidates(date), enabled: Boolean(date) })
  const detail = useQuery({ queryKey: QK.stockPoolDetail(date, selected?.symbol ?? ''), queryFn: () => stockPoolApi.getCandidate(date, selected!.symbol), enabled: Boolean(date && selected) })
  const historyDetail = useQuery({
    queryKey: QK.stockPoolDetail(historySelection?.date ?? '', historySelection?.symbol ?? '', historySelection?.snapshot ?? 'current'),
    queryFn: () => stockPoolApi.getCandidate(historySelection!.date, historySelection!.symbol, historySelection!.snapshot),
    enabled: Boolean(historySelection),
  })
  const rows = candidates.data?.rows ?? []
  const lowClusters = useMemo(() => clusterLow(rows), [rows])
  const clusters = useMemo(() => mergeTopicClusters(summary.data?.clusters ?? [], lowClusters, rows), [summary.data?.clusters, lowClusters, rows])

  useEffect(() => {
    if (view === 'workbench' && topic && !clusters.some(item => item.name === topic)) { setTopic(''); setSubgroup('') }
  }, [clusters, topic, view])
  const setPersonalState = (symbol: string, value: PersonalState) => {
    const next = { ...personal, [symbol]: value }
    setPersonal(next)
    try {
      const tracked = JSON.parse(localStorage.getItem(trackedKey) || '{}') as Record<string, PersonalState>
      if (value === 'priority' || value === 'pending') tracked[symbol] = value
      else tracked[symbol] = 'unseen'
      localStorage.setItem(trackedKey, JSON.stringify(tracked))
      localStorage.setItem(storageKey(date), JSON.stringify(next))
    } catch { /* current session remains usable */ }
  }
  const chooseTopic = (name: string) => {
    setTopic(name); setStage(''); setSubgroup(''); setQueueMode('members'); setShowAllQueue(false)
    requestAnimationFrame(() => memberSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  // Workbench topic rows
  const workbenchRows = useMemo(() => {
    const needle = workbenchQuery.trim().toLowerCase()
    return needle ? rows.filter(row => `${row.name} ${row.code} ${row.symbol} ${row.primary_stage} ${row.sources.join(' ')} ${row.topics.join(' ')} ${row.primary_concept ?? ''} ${(row.memberships?.concept ?? []).join(' ')}`.toLowerCase().includes(needle)) : rows
  }, [rows, workbenchQuery])
  const displayTopic = topic
  const activeCluster = clusters.find(item => item.name === displayTopic)
  const topicSymbols = useMemo(() => new Set(activeCluster?.symbols ?? []), [activeCluster])
  const memberRows = useMemo(() => workbenchRows.filter(row => !topic || topicSymbols.has(row.symbol)), [topic, topicSymbols, workbenchRows])
  const activeSubgroup = activeCluster?.subgroups?.find(item => item.name === subgroup)
  const queueGroups = useMemo(() => {
    const base = workbenchRows.filter(row =>
      (!topic || topicSymbols.has(row.symbol))
      && (!stage || row.primary_stage === stage)
      && (!activeSubgroup || activeSubgroup.symbols.includes(row.symbol))
    )
    return {
      members: base,
      topic_event: base.filter(row => row.source_ids.some(item => EVENT_SOURCES.has(item)) && row.source_ids.length >= 2 && (topic ? row.topics.includes(topic) : row.topics.length > 0)),
      signal: base.filter(row => row.source_ids.some(item => EVENT_SOURCES.has(item))),
      low_buy: base.filter(row => LOW_STAGES.has(row.primary_stage)),
      research: base.filter(row => (row.research_count ?? 0) > 0),
      priority: base.filter(row => (personal[row.symbol] ?? 'unseen') === 'priority'),
      pending: base.filter(row => (personal[row.symbol] ?? 'unseen') === 'pending'),
    }
  }, [personal, workbenchRows, topic, topicSymbols, stage, activeSubgroup])
  const queue = useMemo(() => {
    const order: Record<string, number> = { '涨停强化': 0, '异动加速': 1, '突破启动': 2, '高位分歧': 3, '企稳修复': 4, '回踩整理': 5, '趋势延续': 6, '活跃观察': 7, '人气观察': 8 }
    const visible = queueMode === 'low_buy' ? queueGroups.low_buy.filter(row =>
      lowEvidence === 'all' || (lowEvidence === 'logic' && (topic ? row.topics.includes(topic) : row.topics.length > 0))
      || (lowEvidence === 'smnc' && Boolean(row.research_focus))
      || (lowEvidence === 'static' && (topic ? !row.topics.includes(topic) : row.topics.length === 0))
    ) : queueGroups[queueMode]
    return [...visible].sort((a, b) =>
      Number((personal[b.symbol] ?? 'unseen') === 'priority') - Number((personal[a.symbol] ?? 'unseen') === 'priority') ||
      Number((personal[b.symbol] ?? 'unseen') === 'pending') - Number((personal[a.symbol] ?? 'unseen') === 'pending') ||
      (queueMode === 'low_buy' ? (order[a.primary_stage] ?? 99) - (order[b.primary_stage] ?? 99) : 0) ||
      (queueMode === 'low_buy' ? lowBuyDistanceOrder(a, b) : (b.research_count ?? 0) - (a.research_count ?? 0)) ||
      b.source_ids.length - a.source_ids.length ||
      (order[a.primary_stage] ?? 99) - (order[b.primary_stage] ?? 99) ||
      b.amount_yi - a.amount_yi)
  }, [personal, queueGroups, queueMode, lowEvidence, topic])

  // All-candidates filtered rows
  const filtered = useMemo(() => {
    let result = rows
    if (tier === 'core') result = result.filter(r => r.tier === 'core')
    else if (tier === 'focus') result = result.filter(r => r.tier === 'core' || r.tier === 'focus')
    if (sources.length) result = result.filter(r => sources.every(source => r.source_ids.includes(source)))
    if (stage) result = result.filter(r => r.primary_stage === stage)
    if (topic && view === 'all') result = result.filter(r => r.topics.includes(topic))
    if (exchange) result = result.filter(r => r.exchange === exchange)
    if (sourceCount === 1) result = result.filter(r => r.source_ids.length === 1)
    else if (sourceCount >= 2) result = result.filter(r => r.source_ids.length >= sourceCount)
    if (researchFilter === 'direct') result = result.filter(r => (r.research_count ?? 0) > 0)
    else if (researchFilter === 'indirect') result = result.filter(r => (r.research_count ?? 0) === 0)
    if (freshFilter === 'event') result = result.filter(r => r.change_types.length > 0 || r.freshness === '当日事件')
    else if (freshFilter === 'continuation') result = result.filter(r => r.change_types.length === 0 && r.freshness !== '当日事件')
    else if (freshFilter === 'updated') result = result.filter(r => r.change_types.includes('source') || r.change_types.includes('stage'))
    if (changeView === 'today') {
      if (changeKind === 'signal') result = result.filter(r => r.change_types.length > 0 || r.freshness === '当日事件')
      else if (changeKind === 'new') result = result.filter(r => r.change_types.includes('new'))
      else if (changeKind === 'source') result = result.filter(r => r.change_types.includes('source'))
      else if (changeKind === 'stage') result = result.filter(r => r.change_types.includes('stage'))
    }
    if (reviewFilter !== 'all') result = result.filter(r => (personal[r.symbol] ?? 'unseen') === reviewFilter)
    else if (hideReviewed) result = result.filter(r => !['seen', 'ignored'].includes(personal[r.symbol] ?? 'unseen'))
    if (search) result = result.filter(r => `${r.code}${r.name}`.toLowerCase().includes(search.toLowerCase()))
    for (const [field, range] of Object.entries(ranges)) {
      const getter = FIELD_MAP[field as keyof RangeState]
      if (range.min !== '') result = result.filter(r => getter(r) >= parseFloat(range.min))
      if (range.max !== '') result = result.filter(r => getter(r) <= parseFloat(range.max))
    }
    return result
  }, [rows, tier, sources, stage, topic, view, exchange, sourceCount, researchFilter, freshFilter, changeView, changeKind, reviewFilter, hideReviewed, search, ranges, personal])
  const sortedFiltered = useMemo(() => {
    const result = [...filtered]
    if (sortMode === 'sources') result.sort((a, b) => b.source_ids.length - a.source_ids.length || b.amount_yi - a.amount_yi)
    else if (sortMode === 'amount') result.sort((a, b) => b.amount_yi - a.amount_yi)
    else if (sortMode === 'change') result.sort((a, b) => b.pct_chg - a.pct_chg)
    return result
  }, [filtered, sortMode])

  // Attention counts
  const attentionCounts = useMemo(() => {
    const counts: Record<PersonalState, number> = { unseen: 0, priority: 0, pending: 0, seen: 0, ignored: 0 }
    for (const r of rows) counts[(personal[r.symbol] ?? 'unseen') as PersonalState]++
    return counts
  }, [rows, personal])

  // Daily changes data
  const dc = summary.data?.daily_changes
  const exits = (dc?.exits as Array<{ symbol: string; name?: string; previous_stage?: string; previous_sources?: string[] }>) ?? []
  const dcCounts = dc?.counts ?? {}

  // Context for the selected topic
  const staticRelated = useMemo(() => {
    if (!displayTopic) return []
    const members = new Set(memberRows.map(row => row.symbol))
    return workbenchRows.filter(row => !members.has(row.symbol) && (row.memberships?.concept ?? []).includes(displayTopic))
  }, [displayTopic, memberRows, workbenchRows])
  const topicSourceCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of memberRows) for (const label of row.sources) counts.set(label, (counts.get(label) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [memberRows])
  const topicOverlaps = useMemo(() => {
    if (!activeCluster) return []
    const members = new Set(activeCluster.symbols)
    return clusters.filter(item => item.name !== activeCluster.name).map(item => {
      const shared = item.symbols.filter(symbol => members.has(symbol)).length
      return { name: item.name, shared, ratio: shared / Math.max(1, activeCluster.count + item.count - shared) }
    }).filter(item => item.shared >= 2).sort((a, b) => b.ratio - a.ratio || b.shared - a.shared).slice(0, 3)
  }, [activeCluster, clusters])

  const resetListFilters = () => {
    setSources([]); setStage(''); setTopic(''); setSearch(''); setExchange(''); setSourceCount(0)
    setResearchFilter('all'); setFreshFilter(''); setTier('all'); setChangeKind('all')
    setReviewFilter('all'); setHideReviewed(false); setChangeView('complete'); setSortMode('default')
    setRanges({ pct: { min: '', max: '' }, amount: { min: '', max: '' }, market_cap: { min: '', max: '' }, turnover: { min: '', max: '' } })
  }

  // Filter tokens for display
  const filterTokens: string[] = []
  if (tier === 'core') filterTokens.push('核心关注')
  else if (tier === 'focus') filterTokens.push('核心+重点')
  if (sources.length) filterTokens.push(`来源交集:${sources.join('+')}`)
  if (stage) filterTokens.push(`阶段:${stage}`)
  if (topic && view === 'all') filterTokens.push(`题材:${topic}`)
  if (exchange) filterTokens.push(`交易所:${exchange}`)
  if (sourceCount === 1) filterTokens.push('仅单源')
  else if (sourceCount >= 2) filterTokens.push(`≥${sourceCount}源`)
  if (researchFilter === 'direct') filterTokens.push('有研究材料')
  else if (researchFilter === 'indirect') filterTokens.push('无研究材料')
  if (freshFilter === 'event') filterTokens.push('当日事件')
  else if (freshFilter === 'continuation') filterTokens.push('延续观察')
  else if (freshFilter === 'updated') filterTokens.push('信号有更新')
  if (changeView === 'today') filterTokens.push(`今日变化:${CHANGE_KINDS.find(([k]) => k === changeKind)?.[1] ?? '全部'}`)
  if (reviewFilter !== 'all') filterTokens.push(PERSONAL_LABELS[reviewFilter as PersonalState])
  else if (hideReviewed) filterTokens.push('隐藏已看/暂不关注')
  if (search) filterTokens.push(`搜索:"${search}"`)
  for (const [field, label] of RANGE_DEFS) {
    const range = ranges[field]
    if (range.min !== '' || range.max !== '') filterTokens.push(`${label} ${range.min || '下限'}~${range.max || '上限'}`)
  }

  if (catalog.isLoading || !date || summary.isLoading || candidates.isLoading) return <div className="p-8 text-sm text-muted">正在加载股票池快照…</div>
  if (catalog.isError || summary.isError || candidates.isError) return <div className="p-8 text-sm text-danger">股票池数据加载失败：{String(catalog.error || summary.error || candidates.error)}</div>
  if (!catalog.data?.dates.length) return <div className="p-8"><div className="rounded-card border border-border bg-surface p-8 text-center text-muted">尚无正式股票池快照。<button onClick={() => pipelineRefresh.refresh()} disabled={pipelineRefresh.isRefreshing} className="mt-3 inline-flex items-center gap-1.5 rounded-btn border border-border bg-surface px-3 py-2 text-sm text-foreground hover:bg-elevated disabled:opacity-50"><RefreshCw size={14} className={pipelineRefresh.isRefreshing ? 'animate-spin' : ''} />{pipelineRefresh.isRefreshing ? '更新中…' : '运行盘后数据流水线'}</button></div></div>
  if (!summary.data || !candidates.data) return <div className="p-8 text-sm text-muted">正在加载股票池快照…</div>
  const data = summary.data

  return <div className="mx-auto w-full max-w-[1760px] space-y-3 px-[22px] pb-8 text-[13px] text-foreground">
    <header className="sticky top-0 z-20 -mx-[18px] mb-3 flex min-h-[58px] items-center gap-3.5 border-b border-[#353539] bg-[#0a0a0bf5] px-[18px] py-2 backdrop-blur-xl">
      <div className="flex min-w-[252px] items-center gap-2.5"><div className="grid h-[30px] w-[30px] place-items-center rounded-lg border border-accent/50 bg-accent/10 text-[#75a7ff]"><Telescope size={17} /></div><div><h1 className="text-[15px] font-semibold tracking-[.02em] text-foreground">QuantX 候选池工作台</h1><p className="mt-0.5 text-[10px] text-muted">今日处理 · 题材阶段 · 全量审计</p></div></div>
      <select value={date} onChange={event => { setDate(event.target.value); setTopic(''); setStage(''); setSubgroup(''); resetListFilters() }} className="rounded-[7px] border border-[#353539] bg-[#151517] px-2.5 py-[7px] font-mono text-[11px] text-foreground">
        {[...catalog.data.dates].reverse().map(value => <option key={value}>{value}</option>)}
      </select>
      <span className={`rounded-[7px] border px-2.5 py-[7px] text-[11px] ${data.status === 'complete' ? 'border-warning/35 bg-warning/[.05] text-[#fbc16b]' : 'border-danger/35 bg-danger/[.06] text-danger'}`}>{data.status === 'complete' ? `${date.slice(5).replace('-', '')}正式快照` : `降级：${data.degraded_sources.join('、')}`}</span>
      <div className="ml-auto flex items-center gap-2">
        {view !== 'review' && <label className="relative block w-64"><Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" size={14} /><input value={view === 'workbench' ? workbenchQuery : search} onChange={event => view === 'workbench' ? setWorkbenchQuery(event.target.value) : setSearch(event.target.value)} placeholder="搜索名称、代码或标签" className="w-full rounded-md border border-border bg-surface py-2 pl-8 pr-8 text-xs text-foreground outline-none transition-colors placeholder:text-muted focus:border-accent/60" />{(view === 'workbench' ? workbenchQuery : search) && <button onClick={() => view === 'workbench' ? setWorkbenchQuery('') : setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer text-muted hover:text-foreground" aria-label="清除搜索"><X size={13} /></button>}</label>}
        <button title="更新数据" aria-label="更新数据" onClick={() => pipelineRefresh.refresh()} disabled={pipelineRefresh.isRefreshing} className="grid h-8 w-8 place-items-center rounded-[7px] border border-[#353539] bg-[#151517] text-foreground transition-colors hover:border-accent/60 hover:bg-elevated disabled:opacity-50">
          <RefreshCw size={15} className={pipelineRefresh.isRefreshing ? 'animate-spin' : ''} />
        </button>
      </div>
    </header>

    <div className="-mt-1 mb-3 flex w-max gap-1 rounded-[9px] border border-[#353539] bg-[#111113] p-1">
      {([['workbench', '今日工作台'], ['all', '完整候选'], ['review', '历史复盘']] as const).map(([key, label]) => <button key={key} onClick={() => { setView(key); setStage(''); if (key === 'all') setTopic('') }} className={`min-w-32 rounded-md px-3.5 py-2 text-[11px] transition-colors ${view === key ? 'bg-accent/10 text-foreground shadow-[inset_0_0_0_1px_#3b82f655]' : 'text-muted hover:bg-elevated hover:text-foreground'}`}>{label}</button>)}
    </div>

    {view === 'review' ? <StockPoolHistoryReview date={date} onOpen={(snapshotDate, symbol, snapshot) => setHistorySelection({ date: snapshotDate, symbol, snapshot })} /> : view === 'workbench' ? <section className="overflow-hidden rounded-[9px] border border-[#353539] bg-[#151517]">
      <div className="flex min-h-[38px] items-center justify-between border-b border-[#29292e] px-[11px] py-[7px]"><div className="flex items-baseline gap-2"><h2 className="text-xs font-semibold text-foreground">今日工作台</h2><span className="text-[10px] text-muted">选择题材后，按状态查看成员</span></div><span className="rounded-[5px] bg-accent/10 px-[7px] py-[3px] text-[10px] text-[#83afff]">{date.slice(5).replace('-', '')} 收盘</span></div>
      {summary.data && <div className="border-b border-[#29292e] px-[11px] py-1.5 text-[10px] text-muted">当前快照发布于 {summary.data.published_at ? new Date(summary.data.published_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '时间未记录'} · {summary.data.first_published_available ? '首次版已留存' : '该日期没有首次版留存'}</div>}

      <div className="border-b border-[#29292e] p-[13px]">
        <WorkbenchHeader index="01" title="今日题材分类池" actions={<><span className="text-[10px] text-muted">{clusters.length}组</span>{topic && <button onClick={() => { setTopic(''); setStage(''); setSubgroup(''); setQueueMode('topic_event') }} className="cursor-pointer text-[10px] text-accent hover:text-accent/80">清除题材筛选</button>}{clusters.length > TOPIC_PREVIEW_LIMIT && <button onClick={() => setShowAllTopics(value => !value)} className="cursor-pointer text-[10px] text-accent hover:text-accent/80">{showAllTopics ? `收起到${TOPIC_PREVIEW_LIMIT}组` : '展开全部'}</button>}</>} />
        <p className="mt-2 text-[10px] text-muted">合并当日逻辑题材与至少3只候选共有的回调题材；静态关联只作今日成员线索。</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {(showAllTopics ? clusters : clusters.slice(0, TOPIC_PREVIEW_LIMIT)).map(cluster => {
            const leading = Object.entries(cluster.stage_counts || {}).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([name]) => name).join('／')
            const subgroupHint = (cluster.subgroups ?? []).slice(0, 2).map(item => `${item.name} ${item.count}`).join(' · ')
            const basis = cluster.dimension === 'logic' ? '当日逻辑' : cluster.dimension === 'mixed' ? '逻辑／静态' : '静态关联'
            const direction = cluster.startupCount > cluster.pullbackCount ? '偏启动' : cluster.pullbackCount > cluster.startupCount ? '偏回调' : cluster.startupCount ? '启动／回调并存' : '观察中'
            const observation = themeContextShort(summary.data?.theme_contexts?.[cluster.name])
            return <button key={cluster.name} onClick={() => chooseTopic(cluster.name)} className={`grid min-h-[66px] cursor-pointer grid-cols-[minmax(0,1fr)_auto] gap-x-2 rounded-[7px] border bg-[#111113] p-2.5 text-left transition-colors ${topic === cluster.name ? 'border-accent/70 bg-accent/10' : 'border-[#29292e] hover:border-accent/45 hover:bg-elevated/60'}`}>
              <strong className="truncate text-[11px] text-foreground">{cluster.name}</strong><b className="font-mono text-[13px] text-[#aeb8ff]">{cluster.count}只</b>
              <div className="col-span-2 mt-0.5 truncate text-[9px] text-muted">{direction} · 启动 {cluster.startupCount} · 回调 {cluster.pullbackCount} · {basis}</div>
              <div className="col-span-2 truncate text-[9px] text-muted">候选事件 {cluster.event_count} · {subgroupHint || leading || '阶段待确认'}</div>
              {observation && <div className="col-span-2 mt-0.5 truncate text-[9px] text-[#9ca9c6]">{observation}</div>}
            </button>
          })}
        </div>
      </div>

      <div ref={memberSectionRef} className="scroll-mt-16 bg-[#818cf809] p-[13px]">
        <WorkbenchHeader index="02" title={topic ? `${topic} · 成员与处理` : '候选处理'} note={topic ? `题材成员 ${activeCluster?.count ?? memberRows.length}只 · 当前范围 ${queueGroups.members.length}只` : `当前范围 ${queueGroups.members.length}只`} />
        {topic && <>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-secondary">
          <span>候选上涨 {activeCluster ? Math.round(activeCluster.up_count / Math.max(1, activeCluster.count) * 100) : Math.round(memberRows.filter(row => row.pct_chg > 0).length / Math.max(1, memberRows.length) * 100)}%</span>
          <span>等权涨幅 {activeCluster?.mean_pct_chg.toFixed(2) ?? '0.00'}%</span>
          <span>当日事件 {activeCluster?.event_count ?? memberRows.filter(row => row.source_ids.some(sourceId => EVENT_SOURCES.has(sourceId))).length}</span>
          {topicSourceCounts.slice(0, 6).map(([label, count]) => <Tag key={label}>{label} {count}</Tag>)}
        </div>
        <ThemeContextPanel context={summary.data?.theme_contexts?.[displayTopic]} staticProxy={activeCluster?.dimension !== 'logic'} />
        {activeCluster && <AmvPanel key={`${date}:${displayTopic}`} date={date} topic={displayTopic} selectableSector />}
        {activeCluster?.subgroups?.length ? <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[9px]"><span className="text-muted">细分方向：</span>{[{ name: '', count: activeCluster.count }, ...activeCluster.subgroups].map(item => { const active = item.name ? subgroup === item.name : !subgroup; return <button key={item.name || '__all__'} onClick={() => setSubgroup(item.name)} className={`cursor-pointer rounded border px-2 py-1 transition-colors ${active ? 'border-accent/60 bg-accent/15 text-foreground' : 'border-border bg-base text-secondary hover:border-accent/50 hover:text-foreground'}`}>{item.name || '全部'} {item.count}</button> })}</div> : null}
        {topicOverlaps.length > 0 && <div className="mt-2 flex items-center gap-1.5 text-[9px] text-muted"><span>成员重叠：</span>{topicOverlaps.map(item => <button key={item.name} onClick={() => chooseTopic(item.name)} className="cursor-pointer rounded border border-border bg-base px-2 py-1 text-secondary hover:border-accent/50 hover:text-foreground">{item.name} · {item.shared}只 · {(item.ratio * 100).toFixed(0)}%</button>)}</div>}
        <div className="mt-2.5 rounded-lg border border-accent/30 bg-accent/[.04] px-3 py-2 text-[10px] text-secondary">来源强化：{[...new Set(memberRows.map(row => row.industry || row.topics[1]).filter(Boolean))].slice(0, 3).join('、') || '当前题材材料待补充'}</div>
        {activeCluster?.research_background?.length ? <details className="mt-2.5 rounded-md border border-[#29292e] bg-[#111113] p-2.5">
          <summary className="cursor-pointer text-[11px] text-secondary">SMNC题材背景 {activeCluster?.research_background?.length ?? 0}条 · 研究线索</summary>
          <div className="mt-2 divide-y divide-[#29292e]">{activeCluster?.research_background?.length ? activeCluster.research_background.slice(0, 3).map((item, index) => <div key={index} className="py-2 text-[10px]"><div className="flex items-center gap-1.5"><strong className="min-w-0 flex-1 truncate text-foreground" title={String(item.title || '')}>{String(item.title || item.takeaway || '研究材料')}</strong><span className="shrink-0 text-[9px] text-muted">{item.topic_match_basis === 'audited' ? '已审计概念' : item.topic_match_basis === 'title' ? '标题直提' : item.topic_match_basis === 'title_alias' ? '标题术语' : '标题旧标签'}</span>{Boolean(item.source_url) && <a href={String(item.source_url)} target="_blank" rel="noreferrer" className="shrink-0 text-accent hover:underline">原文</a>}</div><span className="mt-1 block text-[9px] text-muted">{String(item.takeaway || '')}</span></div>) : <div className="py-2 text-[9px] text-muted">当前题材暂无可展示的研究背景材料</div>}</div>
        </details> : null}
        {staticRelated.length > 0 && <details className="mt-1.5 rounded-md border border-[#29292e] bg-[#111113] px-2.5 py-2"><summary className="cursor-pointer text-[10px] text-secondary">仅静态关联 {staticRelated.length}只 · 不计入当前题材成员</summary><div className="mt-2 overflow-hidden rounded-md border border-border"><CompactCandidateRows rows={staticRelated} personal={personal} onOpen={setSelected} onPersonal={setPersonalState} /></div></details>}
        </>}
        <div className={topic ? 'mt-3 border-t border-[#29292e] pt-3' : 'mt-2'}>
        <div className="flex flex-wrap items-baseline justify-between gap-2"><strong className="text-[11px] text-secondary">按状态查看</strong><span className="text-[10px] text-muted">{topic ? `${topic} · ` : ''}{QUEUE_META[queueMode].label} · 显示 {showAllQueue || topic ? queue.length : Math.min(30, queue.length)} / {queue.length}只</span></div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(Object.entries(QUEUE_META) as [QueueMode, typeof QUEUE_META[QueueMode]][]).map(([mode, meta]) => <button key={mode} title={meta.note} onClick={() => { setQueueMode(mode); setShowAllQueue(false) }} className={`cursor-pointer rounded-md border px-2.5 py-1.5 text-[10px] transition-colors ${queueMode === mode ? 'border-accent/60 bg-accent/10 text-foreground' : 'border-[#29292e] bg-[#111113] text-secondary hover:border-accent/40 hover:text-foreground'}`}>{meta.label} <span className="ml-1 font-mono text-accent">{queueGroups[mode].length}</span></button>)}
        </div>
        {queueMode === 'low_buy' && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]"><span className="mr-1 text-muted">线索范围</span>{([['all', '全部'], ['logic', '当日成组题材'], ['smnc', 'SMNC定向'], ['static', '无成组题材']] as const).map(([key, label]) => <button key={key} onClick={() => { setLowEvidence(key); setShowAllQueue(false) }} className={`rounded border px-2 py-1 ${lowEvidence === key ? 'border-accent/60 bg-accent/15 text-foreground' : 'border-border text-secondary hover:border-accent/40'}`}>{label}</button>)}<span className="ml-1 text-muted">只筛浏览线索</span></div>}
        {queue.length ? <div data-testid="topic-role-groups" className="mt-2 space-y-2">
          {ROLE_DEFS.map(([role, stages]) => ({ role, members: (showAllQueue || topic ? queue : queue.slice(0, 30)).filter(row => stages.includes(row.primary_stage)) })).filter(group => group.members.length > 0).map(group => <section key={group.role} className="overflow-hidden rounded-md border border-border bg-base/25">
            <div className="flex items-center justify-between border-b border-border px-3 py-2 text-[11px]"><strong className="text-foreground">{group.role}</strong><span className="font-mono text-muted">{group.members.length}只</span></div>
            <CompactCandidateRows rows={group.members} personal={personal} onOpen={setSelected} onPersonal={setPersonalState} numbered lowBuy={queueMode === 'low_buy'} />
          </section>)}
        </div> : <div className="mt-2 rounded-md border border-dashed border-border px-3 py-5 text-center text-[11px] text-muted">{topic ? `${topic}在当前状态范围内没有成员` : '当前状态范围没有候选'}</div>}
        {!topic && queue.length > 30 && <div className="mt-2 text-center"><button onClick={() => setShowAllQueue(value => !value)} className="cursor-pointer rounded-md border border-border bg-base px-4 py-1.5 text-xs text-secondary transition-colors hover:bg-elevated hover:text-foreground">{showAllQueue ? '收起到30只' : `展开全部 ${queue.length}只`}</button></div>}
        </div>
      </div>
    </section> : <section className="space-y-4">
      <div className="grid grid-cols-5 gap-2">
        <SummaryMetric label="行情记录" value={(data.market_count ?? 0).toLocaleString()} note="当日日线" tone="slate" />
        <SummaryMetric label="九池原始命中" value={data.raw_hit_count.toLocaleString()} note="允许重复" tone="slate" />
        <SummaryMetric label="去重候选" value={data.candidate_count.toLocaleString()} note={`${data.market_count ? (data.candidate_count / data.market_count * 100).toFixed(1) : '—'}% 行情记录`} tone="blue" />
        <SummaryMetric label="事件型候选" value={data.event_count.toLocaleString()} note="当日事件来源" tone="red" />
        <SummaryMetric label="多源重叠" value={data.overlap_count.toLocaleString()} note="至少两类" tone="amber" />
      </div>
      <div className="flex items-center gap-2 rounded-lg border border-accent/25 bg-accent/5 px-3 py-2 text-[10px] text-secondary"><strong className="text-accent">统一基础过滤</strong><span>总市值20—3000亿 · 成交额≥1亿 · 换手≥1% · 排除ST；全市场{data.market_count?.toLocaleString() ?? '—'}只 → 基础过滤{data.eligible_count.toLocaleString()}只 → 九池去重{data.candidate_count.toLocaleString()}只。</span><Tag tone="accent">9路召回</Tag>{data.exchange_coverage && <span>基础合格：沪{data.exchange_coverage.SH?.eligible ?? 0} · 深{data.exchange_coverage.SZ?.eligible ?? 0} · 北{data.exchange_coverage.BJ?.eligible ?? 0}</span>}</div>
      {/* 9 source cards */}
      <div className="overflow-hidden rounded-lg border border-[#2a2a2f] bg-[#151517]">
        <div className="flex min-h-10 items-center border-b border-[#2a2a2f] px-3"><h2 className="text-xs font-semibold">九个召回来源</h2><span className="ml-2 text-[9px] text-muted">点击筛选；多选取交集，保留全部来源理由</span><button onClick={() => setSources([])} className="ml-auto text-[10px] text-accent hover:text-accent/80">清除来源筛选</button></div>
        <div className="grid grid-cols-9 gap-2 p-3">{data.source_stats.map(item => { const style = SOURCE_STYLE[item.id]; const active = sources.includes(item.id); return <button key={item.id} onClick={() => setSources(current => active ? current.filter(value => value !== item.id) : [...current, item.id])} className={`relative min-h-[88px] rounded-lg border bg-gradient-to-br from-[#141416] to-[#101012] p-2.5 text-left transition-colors ${active ? 'border-accent bg-accent/10' : 'border-[#2a2a2f] hover:border-[#5a5a62]'}`}><div className="flex items-center gap-1.5"><i className={`h-2 w-2 rounded-full ${style?.dot || 'bg-slate-400'}`} /><strong className="text-[11px]">{item.label}</strong><span className="ml-auto rounded bg-elevated px-1.5 py-0.5 text-[8px] text-muted">{style?.role || '来源'}</span></div><div className="mt-2 font-mono text-xl font-bold">{item.count}</div><div className="mt-1 text-[9px] text-muted">占去重候选 {Math.round(item.count / Math.max(1, data.candidate_count) * 100)}%</div></button> })}</div>
      </div>

      {/* Change view toggle */}
      <div className="flex flex-col overflow-hidden rounded-lg border border-[#2a2a2f] bg-[#151517]">
      <div className="order-2 flex flex-wrap items-center gap-3 border-b border-[#2a2a2f] px-3 py-2.5">
        <div className="flex gap-1 rounded bg-elevated p-1">
          {([['complete', '完整观察'], ['today', '今日变化']] as const).map(([key, label]) => <button key={key} onClick={() => setChangeView(key)} className={`rounded px-3 py-1.5 text-xs ${changeView === key ? 'bg-surface text-foreground' : 'text-muted'}`}>{label}</button>)}
        </div>
        {changeView === 'today' && <select value={changeKind} onChange={e => setChangeKind(e.target.value)} className="rounded-btn border border-border bg-base px-3 py-1.5 text-xs">
          {CHANGE_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>}
        <span className="text-xs text-muted">
          {dc?.status === 'complete' ? `当日信号 ${rows.filter(r => r.change_types.length > 0).length} · 新增 ${dcCounts.new ?? 0} · 来源变化 ${dcCounts.source ?? 0} · 阶段变化 ${dcCounts.stage ?? 0} · 退出 ${dcCounts.exit ?? 0}` : '暂无同口径前日快照，当日信号仍可筛选'}
        </span>
        {changeView === 'today' && exits.length > 0 && <button onClick={() => setShowExitPanel(v => !v)} className="ml-auto inline-flex items-center gap-1 text-xs text-accent">{showExitPanel ? '收起退出区' : `退出 ${exits.length} 只`} {showExitPanel ? <ChevronUp size={13} /> : <ChevronDown size={13} />}</button>}
        <div className="w-full border-t border-[#242429] pt-2 text-[9px] text-muted">当日信号指当前已有的事件触发分类，不等于首次入池。前后日回规则、基础过滤或来源覆盖状态不一致时，暂不判断成员变化。{dc?.topic_status === 'incompatible' && '题材聚类口径已变，本日不判题材变化。'}</div>
      </div>
      {changeView === 'today' && showExitPanel && exits.length > 0 && <div className="order-3 border-b border-[#2a2a2f] p-4">
        <div className="mb-2 text-sm font-semibold">退出候选 <span className="ml-1 text-xs font-normal text-muted">{exits.length}只 · 昨日有今日无</span></div>
        <div className="flex flex-wrap gap-2">{exits.slice(0, 30).map(exit => <div key={exit.symbol} className="rounded border border-border bg-base px-3 py-1.5 text-xs"><strong>{exit.name || exit.symbol}</strong> <span className="text-muted">昨日 {exit.previous_stage || '—'}</span></div>)}</div>
      </div>}

      {/* Attention bar */}
      <div className="order-1 flex items-center gap-3 border-b border-[#2a2a2f] bg-[#818cf808] px-4 py-2.5">
        <strong className="text-sm">处理进度</strong>
        <span className="text-xs text-muted">未处理 {attentionCounts.unseen} · 重点 {attentionCounts.priority} · 待确认 {attentionCounts.pending} · 已看 {attentionCounts.seen} · 暂不关注 {attentionCounts.ignored}</span>
        <label className="flex items-center gap-1.5 text-xs text-secondary"><input type="checkbox" checked={hideReviewed} onChange={e => setHideReviewed(e.target.checked)} />隐藏已看/暂不关注</label>
        <select value={reviewFilter} onChange={e => setReviewFilter(e.target.value)} className="rounded border border-border bg-base px-2 py-1 text-xs">
          <option value="all">全部状态</option>
          {Object.entries(PERSONAL_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {/* Facet filters */}
      <div className="order-4 border-b border-[#2a2a2f] bg-[#111113] p-3">
        <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">列表筛选</h3><button onClick={resetListFilters} className="text-xs text-muted hover:text-foreground">清除列表筛选</button></div>
        <div className="grid grid-cols-4 gap-3">
          <label className="space-y-1"><span className="text-[11px] text-muted">交易所</span><select value={exchange} onChange={e => setExchange(e.target.value)} className="w-full rounded border border-border bg-base px-2 py-1.5 text-xs"><option value="">全部</option><option value="SH">沪市</option><option value="SZ">深市</option><option value="BJ">北交所</option></select></label>
          <label className="space-y-1"><span className="text-[11px] text-muted">阶段</span><select value={stage} onChange={e => setStage(e.target.value)} className="w-full rounded border border-border bg-base px-2 py-1.5 text-xs"><option value="">全部阶段</option>{data.stage_stats.map(item => <option key={item.stage} value={item.stage}>{item.stage}</option>)}</select></label>
          <label className="space-y-1"><span className="text-[11px] text-muted">新鲜度</span><select value={freshFilter} onChange={e => setFreshFilter(e.target.value)} className="w-full rounded border border-border bg-base px-2 py-1.5 text-xs"><option value="">全部</option><option value="event">当日事件</option><option value="continuation">延续观察</option><option value="updated">信号有更新</option></select></label>
          <label className="space-y-1"><span className="text-[11px] text-muted">来源数量</span><select value={sourceCount} onChange={e => setSourceCount(Number(e.target.value))} className="w-full rounded border border-border bg-base px-2 py-1.5 text-xs"><option value="0">不限</option><option value="1">仅单源</option><option value="2">≥2源</option><option value="3">≥3源</option><option value="4">≥4源</option></select></label>
          <label className="space-y-1"><span className="text-[11px] text-muted">题材</span><select value={topic} onChange={e => setTopic(e.target.value)} className="w-full rounded border border-border bg-base px-2 py-1.5 text-xs"><option value="">全部题材</option>{data.clusters.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
          <label className="space-y-1"><span className="text-[11px] text-muted">研究材料</span><select value={researchFilter} onChange={e => setResearchFilter(e.target.value)} className="w-full rounded border border-border bg-base px-2 py-1.5 text-xs"><option value="all">全部</option><option value="direct">有个股材料</option><option value="indirect">无个股材料</option></select></label>
          <label className="space-y-1"><span className="text-[11px] text-muted">搜索</span><div className="relative"><Search className="absolute left-2 top-1.5 text-muted" size={14} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="代码或名称" className="w-full rounded border border-border bg-base py-1.5 pl-8 pr-2 text-xs" /></div></label>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-3">
          {RANGE_DEFS.map(([field, label]) => <div key={field} className="flex items-center gap-1.5"><span className="whitespace-nowrap text-[11px] text-muted">{label}</span><input type="number" placeholder="下限" value={ranges[field].min} onChange={e => setRanges(prev => ({ ...prev, [field]: { ...prev[field], min: e.target.value } }))} className="w-16 rounded border border-border bg-base px-1.5 py-1 text-xs" /><span className="text-[11px] text-muted">~</span><input type="number" placeholder="上限" value={ranges[field].max} onChange={e => setRanges(prev => ({ ...prev, [field]: { ...prev[field], max: e.target.value } }))} className="w-16 rounded border border-border bg-base px-1.5 py-1 text-xs" /></div>)}
        </div>
      </div>

      {/* Tier tabs + filter state */}
      <div className="order-5 flex min-h-12 items-center justify-between gap-3 border-b border-[#2a2a2f] px-3 py-2">
        <div className="flex gap-1 rounded bg-elevated p-1">
          {([['core', `多源交叉 ${data.tier_stats.core ?? 0}`], ['focus', `事件 / 多源 ${(data.tier_stats.core ?? 0) + (data.tier_stats.focus ?? 0)}`], ['all', `完整候选 ${data.candidate_count}`]] as const).map(([key, label]) => <button key={key} onClick={() => setTier(key)} className={`rounded px-3 py-1.5 text-xs ${tier === key ? 'bg-surface text-foreground' : 'text-muted'}`}>{label}</button>)}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>当前：</span>
          {filterTokens.length ? filterTokens.map(t => <span key={t} className="rounded bg-elevated px-1.5 py-0.5 text-[11px]">{t}</span>) : <span className="text-[11px]">无额外筛选</span>}
          <select value={sortMode} onChange={event => setSortMode(event.target.value)} className="rounded border border-border bg-surface px-2 py-1.5 text-[10px] text-secondary"><option value="default">阶段与来源顺序</option><option value="sources">召回来源数</option><option value="amount">成交额从高到低</option><option value="change">当日涨幅从高到低</option></select>
          <span className="text-secondary">{filtered.length} / {rows.length}只</span>
        </div>
      </div>

      <div className="order-6"><CandidateTable rows={sortedFiltered} personal={personal} onOpen={setSelected} onPersonal={setPersonalState} /></div>
      </div>
    </section>}

    {selected && <DetailDrawer date={date} candidate={selected} detail={detail.data} loading={detail.isLoading} onClose={() => setSelected(null)} />}
    {historySelection && historyDetail.data && <DetailDrawer key={`${historySelection.date}:${historySelection.symbol}:${historySelection.snapshot}`} date={historySelection.date} candidate={historyDetail.data} detail={historyDetail.data} loading={historyDetail.isLoading} snapshot={historySelection.snapshot} onClose={() => setHistorySelection(null)} />}
    {historySelection && historyDetail.isLoading && <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 text-sm text-foreground">正在读取历史个股详情…</div>}
    {historySelection && historyDetail.isError && <div className="fixed inset-0 z-50 grid place-items-center bg-black/50"><div className="rounded border border-danger/40 bg-surface p-5 text-sm text-danger">历史个股详情读取失败<button className="ml-4 text-accent" onClick={() => setHistorySelection(null)}>关闭</button></div></div>}
  </div>
}

function WorkbenchHeader({ index, title, note, actions }: { index: string; title: string; note?: string; actions?: React.ReactNode }) {
  return <div className="flex min-h-[30px] items-center justify-between gap-3"><div className="flex items-center gap-2"><span className="grid h-[23px] min-w-[23px] place-items-center rounded-md border border-accent/40 bg-accent/10 px-1 font-mono text-[9px] font-semibold text-accent">{index}</span><h3 className="text-xs font-semibold text-foreground">{title}</h3>{note && <span className="text-[9px] text-muted">{note}</span>}</div>{actions && <div className="flex items-center gap-2">{actions}</div>}</div>
}

function CompactCandidateRows({ rows, personal, onOpen, onPersonal, numbered, lowBuy }: { rows: StockPoolCandidate[]; personal: Record<string, PersonalState>; onOpen: (row: StockPoolCandidate) => void; onPersonal: (symbol: string, value: PersonalState) => void; numbered?: boolean; lowBuy?: boolean }) {
  if (!rows.length) return <div className="py-5 text-center text-xs text-muted">当前条件下没有候选</div>
  return <div className="max-h-[610px] divide-y divide-[#29292e] overflow-auto [scrollbar-gutter:stable]">{rows.map((row, index) => <div key={row.symbol} className="grid min-h-[55px] grid-cols-[34px_150px_155px_minmax(200px,1fr)_150px_104px] items-center gap-2.5 px-2.5 py-2 transition-colors hover:bg-accent/10">
    <span className="font-mono text-[10px] font-semibold text-muted">{numbered ? String(index + 1).padStart(2, '0') : '·'}</span>
    <button onClick={() => onOpen(row)} className="min-w-0 cursor-pointer text-left"><div className="truncate text-xs font-semibold text-foreground hover:text-accent">{row.name}</div><div className="font-mono text-[9px] text-muted">{row.symbol}</div></button>
    <div><span className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-1 text-[9px] ${STAGE_CHIP[row.primary_stage] || 'border-border bg-elevated text-secondary'}`}><i className="h-1 w-1 rounded-full bg-current" />{row.primary_stage}</span><div className="mt-1 truncate text-[9px] text-muted">{lowBuy ? row.topics.length ? `当日逻辑 · ${row.topics.slice(0, 2).join('／')}` : row.unclustered_terms?.length ? '当日解读 · 未成组' : row.primary_concept ? `静态关联 · ${row.primary_concept}` : '题材待确认' : row.topics.slice(0, 2).join('／') || row.primary_concept || '题材待确认'}</div></div>
    <div className="min-w-0 text-[9px] leading-[1.45] text-secondary"><div className="truncate" title={row.evidence || ''}>{row.evidence || row.sources.join(' · ')}</div>{lowBuy && row.price_context && <div className="truncate text-muted">距MA20 {signedPct(row.price_context.ma20_distance_pct)} · 近10日 {signedPct(row.price_context.return10_pct)}</div>}{lowBuy && !row.topics.length && Boolean(row.unclustered_terms?.length) && <div className="truncate text-amber-200">当日来源术语 · {row.unclustered_terms?.join('／')} · 未成组</div>}{lowBuy && row.research_focus?.title && <div className="truncate text-indigo-300" title={row.research_focus.title}>SMNC定向{row.research_focus.age_days != null ? ` · ${row.research_focus.age_days}天前可用` : ''}{row.research_focus.topic_mentions?.[0] ? ` · ${row.research_focus.topic_mentions[0].label}（${row.research_focus.topic_mentions[0].location === 'title' ? '标题' : '摘录'}提及）` : ''} · {row.research_focus.title}</div>}</div>
    <div className="text-[9px] text-muted">{row.source_ids.length}类召回{(row.research_count ?? 0) > 0 ? ` · 定向材料${row.research_count}条` : ''}<br /><span className={`font-semibold ${row.pct_chg >= 0 ? 'text-bull' : 'text-bear'}`}>{row.pct_chg >= 0 ? '+' : ''}{row.pct_chg.toFixed(2)}%</span> · {row.amount_yi.toFixed(1)}亿</div>
    <div>{reviewSelect(row.symbol, personal, onPersonal)}</div>
  </div>)}</div>
}

function CandidateTable({ rows, personal, onOpen, onPersonal }: { rows: StockPoolCandidate[]; personal: Record<string, PersonalState>; onOpen: (row: StockPoolCandidate) => void; onPersonal: (symbol: string, value: PersonalState) => void }) {
  return <div className="max-h-[720px] overflow-auto bg-[#111113] [scrollbar-gutter:stable]">
    <table className="w-full min-w-[1540px] table-fixed border-collapse text-[10px]">
      <colgroup><col className="w-10" /><col className="w-32" /><col className="w-24" /><col className="w-20" /><col className="w-28" /><col className="w-36" /><col className="w-28" /><col className="w-52" /><col /><col className="w-28" /><col className="w-24" /><col className="w-24" /></colgroup>
      <thead><tr>{['#', '股票', '收盘 / 涨幅', '成交额', '总市值 / 换手', '概念 / 行业', '当前阶段', '召回来源', '为什么进入观察', '个人状态', '新鲜度', '观察窗口'].map(label => <th key={label} className="sticky top-0 z-[1] h-9 border-b border-[#2a2a2f] bg-[#111113] px-2.5 text-left text-[9px] font-semibold text-muted">{label}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.symbol} className="border-b border-[#26262b] transition-colors hover:bg-accent/[0.04]">
        <td className="px-2.5 py-2"><span className="grid h-6 w-6 place-items-center rounded-md bg-elevated font-mono text-[9px] text-secondary">{String(index + 1).padStart(2, '0')}</span></td>
        <td className="px-2.5 py-2"><button onClick={() => onOpen(row)} className="cursor-pointer text-left"><strong className="block truncate text-[11px] text-foreground hover:text-accent">{row.name}</strong><span className="mt-0.5 block font-mono text-[9px] text-muted">{row.symbol}</span></button></td>
        <td className="px-2.5 py-2"><strong className="block font-mono text-[11px] text-foreground">{row.price.toFixed(2)}</strong><span className={`mt-0.5 block font-mono text-[11px] font-semibold ${row.pct_chg >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>{row.pct_chg >= 0 ? '+' : ''}{row.pct_chg.toFixed(2)}%</span></td>
        <td className="px-2.5 py-2 font-mono text-secondary">{row.amount_yi.toFixed(1)}亿</td>
        <td className="px-2.5 py-2"><span className="block font-mono text-secondary">{row.market_cap_yi.toFixed(1)}亿</span><span className="mt-0.5 block font-mono text-[9px] text-muted">{row.turnover_pct.toFixed(1)}%</span></td>
        <td className="px-2.5 py-2"><span className="inline-flex max-w-full truncate rounded border border-indigo-500/30 bg-indigo-500/10 px-1.5 py-0.5 text-[9px] text-indigo-300">{row.topics[0] || row.primary_concept || row.industry || '题材待确认'}</span><span className="mt-1 block truncate text-[9px] text-muted">{row.industry || (row.memberships?.concept ?? []).slice(0, 3).join(' · ') || '静态分类待补充'}</span></td>
        <td className="px-2.5 py-2"><span className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-1 text-[9px] ${STAGE_CHIP[row.primary_stage] || 'border-border bg-elevated text-secondary'}`}><i className="h-1 w-1 rounded-full bg-current" />{row.primary_stage}</span></td>
        <td className="px-2.5 py-2"><div className="flex max-h-12 flex-wrap gap-1 overflow-hidden">{row.sources.slice(0, 5).map((label, sourceIndex) => { const sourceId = row.source_ids[sourceIndex]; const style = SOURCE_STYLE[sourceId]; return <span key={sourceId} className={`rounded border px-1.5 py-0.5 text-[9px] ${style?.chip || 'border-border bg-elevated text-secondary'}`}>{label}</span> })}{row.sources.length > 5 && <span className="rounded border border-accent/25 bg-accent/10 px-1.5 py-0.5 text-[9px] text-accent">+{row.sources.length - 5}</span>}</div></td>
        <td className="px-2.5 py-2"><button onClick={() => onOpen(row)} title={row.evidence || ''} className="line-clamp-2 cursor-pointer text-left text-[10px] leading-relaxed text-secondary hover:text-foreground">{row.evidence || row.sources.join(' · ')}</button></td>
        <td className="px-2.5 py-2">{reviewSelect(row.symbol, personal, onPersonal)}</td>
        <td className="px-2.5 py-2"><span className={`inline-flex rounded border px-1.5 py-1 text-[9px] ${row.freshness === '当日事件' ? 'border-accent/35 bg-accent/10 text-accent' : 'border-warning/35 bg-warning/10 text-warning'}`}>{row.freshness}</span></td>
        <td className="px-2.5 py-2 font-mono text-[9px] text-secondary">{row.observation_window || '—'}</td>
      </tr>)}</tbody>
    </table>
  </div>
}

function DetailDrawer({ date, candidate, detail, loading, snapshot = 'current', onClose }: { date: string; candidate: StockPoolCandidate; detail: Awaited<ReturnType<typeof stockPoolApi.getCandidate>> | undefined; loading: boolean; snapshot?: 'current' | 'first'; onClose: () => void }) {
  const [historyWindow, setHistoryWindow] = useState(10)
  const history = useQuery({
    queryKey: QK.stockPoolHistory(date, candidate.symbol, historyWindow),
    queryFn: () => stockPoolApi.getCandidateHistory(date, candidate.symbol, historyWindow),
    enabled: snapshot === 'current',
  })
  useEffect(() => { const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }; window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler) }, [onClose])
  return <div className="fixed inset-0 z-50 bg-black/40" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><aside className="ml-auto h-full w-full overflow-y-auto border-l border-border bg-surface shadow-2xl md:w-1/2 md:min-w-[560px]"><div className="sticky top-0 z-10 flex items-start justify-between border-b border-border bg-surface p-5"><div><div className="flex items-center gap-2"><h2 className="text-lg font-semibold">{candidate.name}</h2><span className="text-sm text-muted">{candidate.symbol}</span></div><div className="mt-2 flex gap-1"><Tag tone="accent">{candidate.primary_stage}</Tag><Tag>{candidate.tier}</Tag><Tag>{candidate.exchange}</Tag><a href={`/stock-analysis?symbol=${encodeURIComponent(candidate.symbol)}&name=${encodeURIComponent(candidate.name)}`} target="_blank" rel="noreferrer" className="rounded border border-accent/40 px-2 py-0.5 text-[10px] text-accent hover:bg-accent/10">查看K线与个股分析 ↗</a></div></div><button onClick={onClose} aria-label="关闭个股详情" className="rounded p-2 text-muted hover:bg-elevated hover:text-foreground"><X size={18} /></button></div>
    <div className="space-y-5 p-5">{snapshot === 'first' && <div className="rounded border border-accent/30 bg-accent/5 px-3 py-2 text-[11px] text-secondary">首次发布快照证据；此后重算的材料和阶段不回填至这里。</div>}<div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="收盘价" value={candidate.price.toFixed(2)} /><Metric label="涨跌" value={`${candidate.pct_chg >= 0 ? '+' : ''}${candidate.pct_chg.toFixed(2)}%`} /><Metric label="成交额" value={`${candidate.amount_yi.toFixed(1)}亿`} /><Metric label="换手" value={`${candidate.turnover_pct.toFixed(1)}%`} /></div>
      <StockPoolMiniKline key={`${date}:${candidate.symbol}`} date={date} symbol={candidate.symbol} />
      <AmvPanel key={`amv:${date}:${candidate.symbol}`} date={date} symbols={[candidate.symbol]} compact />
      <div className="grid grid-cols-3 gap-2"><Metric label="市值" value={`${candidate.market_cap_yi.toFixed(0)}亿`} /><Metric label="量比" value={candidate.volume_ratio.toFixed(1)} /><Metric label="来源数" value={candidate.source_ids.length} /></div>
      {candidate.price_context && <div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><Metric label="距MA10" value={signedPct(candidate.price_context.ma10_distance_pct)} /><Metric label="距MA20" value={signedPct(candidate.price_context.ma20_distance_pct)} /><Metric label="距20日高点" value={signedPct(candidate.price_context.high20_drawdown_pct)} /><Metric label="近10日" value={signedPct(candidate.price_context.return10_pct)} /></div>}
      {snapshot === 'current' && <section><div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold">已发布快照中的个股轨迹</h3><div className="flex gap-1">{([5, 10, 30] as const).map(days => <button key={days} onClick={() => setHistoryWindow(days)} className={`cursor-pointer rounded border px-2 py-1 text-[10px] ${historyWindow === days ? 'border-accent/60 bg-accent/10 text-accent' : 'border-border text-muted'}`}>{days === 30 ? '全部' : `${days}日`}</button>)}</div></div>
        {history.isLoading && <div className="text-xs text-muted">正在读取历史快照…</div>}
        {history.isError && <div className="text-xs text-danger">历史快照读取失败</div>}
        {history.data && <div className="flex gap-1.5 overflow-x-auto pb-2">{history.data.timeline.map(point => <div key={point.date} className={`min-w-[118px] rounded border p-2 text-[10px] ${point.present ? 'border-accent/35 bg-accent/5' : 'border-border bg-base text-muted'}`} title={point.sources.join('、')}>
          <div className="font-mono text-muted">{point.date.slice(5)}</div><div className="mt-1 font-semibold">{!point.available ? '快照缺失' : point.present ? point.stage : '当日未入池'}</div>
          {point.present && <><div className="mt-1 text-secondary">来源 {point.sources.length}类 · {point.pct_chg == null ? '—' : `${point.pct_chg >= 0 ? '+' : ''}${point.pct_chg.toFixed(1)}%`}</div><div className="mt-1 truncate text-muted">距MA20 {signedPct(point.price_context?.ma20_distance_pct)}</div></>}
        </div>)}</div>}
        <p className="mt-1 text-[10px] text-muted">空白日表示该股票未进入当日股票池；轨迹按已有交易日快照展示，不补造未发布日期。</p>
      </section>}
      <section><h3 className="mb-2 text-sm font-semibold">召回与观察窗口</h3>{loading ? <div className="text-xs text-muted">加载证据…</div> : <div className="space-y-2">{detail?.source_events.map(event => <div key={event.source_id} className="rounded-card border border-border bg-base p-3"><div className="flex items-center justify-between"><div className="flex items-center gap-2"><CircleDot size={13} className="text-accent" /><strong className="text-sm">{event.source}</strong><Tag>{event.stage}</Tag></div><span className="text-[11px] text-muted">{event.event_date} · 第{event.event_age}日</span></div><p className="mt-2 text-xs text-secondary">{event.evidence}</p><div className="mt-2 text-[11px] text-muted">有效期 {event.expires}{event.anchor_price != null ? ` · 锚点 ${event.anchor_price}` : ''}</div></div>)}</div>}</section>
      <section><h3 className="mb-2 text-sm font-semibold">当日交易逻辑</h3><div className="flex flex-wrap gap-1">{candidate.topics.length ? candidate.topics.map(value => <Tag key={value} tone="warm">{value}</Tag>) : <span className="text-xs text-muted">尚无当日题材证据</span>}</div>{detail?.topic_evidence.map((item, index) => { const labels = Array.isArray(item.topics) ? item.topics.map(String) : []; return <div key={index} className="mt-2 rounded border border-border p-2 text-xs text-secondary"><div className="flex items-center gap-1.5"><strong className="text-foreground">{String(item.source || '')}</strong>{item.tag ? <Tag>{String(item.tag)}</Tag> : null}{item.fallback ? <Tag tone="warm">降级材料</Tag> : null}</div>{labels.length ? <div className="mt-1 flex flex-wrap gap-1">{labels.map(value => <Tag key={value} tone="warm">{value}</Tag>)}</div> : null}<p className="mt-1 leading-relaxed">{String(item.text || '')}</p>{item.catalyst ? <div className="mt-1 text-[10px] text-muted">催化：{String(item.catalyst)}</div> : null}<div className="mt-1 text-[10px] text-muted">{String(item.observed_at || '')}</div></div> })}</section>
      <section><h3 className="mb-2 text-sm font-semibold">静态关联</h3><div className="space-y-2 text-xs">{[['细分概念', candidate.memberships?.concept], ['一级行业', candidate.memberships?.industry_level1], ['二级行业', candidate.memberships?.industry_level2], ['属性标签', candidate.memberships?.attribute]].map(([label, values]) => <div key={String(label)} className="flex items-start gap-2"><span className="mt-0.5 w-16 shrink-0 text-muted">{String(label)}</span><div className="flex flex-wrap gap-1">{(values as string[] | undefined)?.length ? (values as string[]).map(value => <Tag key={value}>{value}</Tag>) : <span className="text-muted">—</span>}</div></div>)}</div><p className="mt-2 text-[10px] text-muted">最新静态成分快照，不代表历史时点归属或当日上涨原因。</p></section>
       <section><h3 className="mb-2 text-sm font-semibold">研究材料与市场提及</h3>{detail?.research.length ? <div className="space-y-2">{detail.research.map((item, index) => <a key={String(item.item_id || index)} href={String(item.source_url || '#')} target="_blank" rel="noreferrer" className="block rounded-card border border-border bg-base p-3 hover:border-accent/40"><div className="text-sm font-medium">{String(item.title || '')}</div><p className="mt-1 text-xs text-secondary">{String(item.match_excerpt || item.takeaway || '')}</p><div className="mt-2 text-[10px] text-muted">{String(item.created_at || '')} · {item.match_basis === 'mention' ? '正文提及' : item.match_basis === 'focused' ? '标题单股' : item.match_basis === 'basket' ? '标题多股' : item.match_basis === 'audited' ? `已审计${item.material_role === 'counter' ? '反证' : item.material_role === 'primary' ? '主证据' : item.material_role === 'supporting' ? '辅助证据' : item.material_role === 'background' ? '背景' : '公司映射'}` : '历史材料关联'}{item.quality_grade ? ` · ${String(item.quality_grade)}` : ''}</div></a>)}</div> : <div className="rounded border border-dashed border-border p-4 text-xs text-muted">暂无完成态Research索引命中；该层不会影响召回和阶段。</div>}</section>
    </div></aside></div>
}
