import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { ArrowRight, Search } from 'lucide-react'
import { stockPoolApi, type StockPoolReviewRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

const GROUPS = [
  ['all', '全部观察'], ['new', '本版首次入池'], ['reentry', '再次入池'],
  ['stage', '阶段变化'], ['source', '来源变化'], ['topic', '题材变化'], ['unchanged', '持续观察'],
] as const
const STAGE_COLORS: Record<string, string> = {
  '未入池': '#fb7185', '活跃观察': '#fbbf24', '人气观察': '#a78bfa',
  '突破启动': '#60a5fa', '异动加速': '#fb923c', '涨停强化': '#f87171',
  '趋势延续': '#22d3ee', '高位分歧': '#e879f9', '回踩整理': '#34d399', '企稳修复': '#2dd4bf',
}

type FlowMode = 'outcome' | 'entry'

function flowKey(row: StockPoolReviewRow, mode: FlowMode): string {
  return mode === 'entry'
    ? `${row.previous_stage || '未入池'}→${row.stage}`
    : `${row.stage}→${row.target_stage || '未入池'}`
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char] || char)
}

function signed(value: number | null): string {
  return value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function percent(numerator: number, denominator: number): string {
  return denominator ? `${(numerator / denominator * 100).toFixed(0)}%` : '—'
}

function median(values: number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return (sorted[middle] + sorted[Math.floor((sorted.length - 1) / 2)]) / 2
}

function resultLabel(row: StockPoolReviewRow): string {
  if (row.outcome_status === 'pending') return '尚未到期'
  if (row.outcome_status === 'unavailable') return '后续快照不可比'
  return row.target_stage || '未入池'
}

export function StockPoolHistoryReview({ date, onOpen }: { date: string; onOpen: (date: string, symbol: string, snapshot: 'current' | 'first') => void }) {
  const [window, setWindow] = useState(20)
  const [horizon, setHorizon] = useState<1 | 3 | 5>(3)
  const [costBps, setCostBps] = useState(20)
  const [group, setGroup] = useState<string>('all')
  const [topic, setTopic] = useState('')
  const [attributionMode, setAttributionMode] = useState<'sources' | 'added_sources' | 'transitions' | 'research'>('sources')
  const [flowMode, setFlowMode] = useState<FlowMode>('outcome')
  const [showAllFlows, setShowAllFlows] = useState(false)
  const [transition, setTransition] = useState('')
  const [selectedDate, setSelectedDate] = useState('')
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(60)
  const review = useQuery({
    queryKey: QK.stockPoolReview(date, window, horizon, costBps),
    queryFn: () => stockPoolApi.getReview(date, window, horizon, costBps),
    enabled: Boolean(date),
    placeholderData: previous => previous,
  })
  const data = review.data
  const topics = useMemo(() => {
    const counts = new Map<string, { count: number; dates: Set<string> }>()
    for (const row of data?.rows ?? []) for (const label of row.topics) {
      const entry = counts.get(label) ?? { count: 0, dates: new Set<string>() }
      entry.count += 1
      entry.dates.add(row.date)
      counts.set(label, entry)
    }
    return [...counts].map(([name, entry]) => ({ name, count: entry.count, days: entry.dates.size }))
      .sort((a, b) => b.days - a.days || b.count - a.count || a.name.localeCompare(b.name))
  }, [data])
  const groupRows = useMemo(() => data?.rows.filter(row => row.labels.includes(group) && (!topic || row.topics.includes(topic))) ?? [], [data, group, topic])
  const topicStats = useMemo(() => {
    if (!topic) return null
    const matured = groupRows.filter(row => row.outcome_status === 'mature')
    const priced = matured.map(row => row.return_pct).filter((value): value is number => value != null)
    const opening = matured.map(row => row.open_proxy_pct).filter((value): value is number => value != null)
    const openingNet = matured.map(row => row.open_proxy_net_pct).filter((value): value is number => value != null)
    return {
      samples: groupRows.length, days: new Set(groupRows.map(row => row.date)).size,
      symbols: new Set(groupRows.map(row => row.symbol)).size, matured: matured.length,
      retained: matured.filter(row => row.target_stage != null).length,
      priced: priced.length, up: priced.filter(value => value > 0).length,
      mean: priced.length ? priced.reduce((sum, value) => sum + value, 0) / priced.length : null,
      median: median(priced), openMean: opening.length ? opening.reduce((sum, value) => sum + value, 0) / opening.length : null,
      openMedian: median(opening), openNetMedian: median(openingNet), openCount: opening.length,
      pending: groupRows.filter(row => row.outcome_status === 'pending').length,
      unavailable: groupRows.filter(row => row.outcome_status === 'unavailable').length,
    }
  }, [groupRows, topic])
  const visibleRows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return groupRows.filter(row => (!selectedDate || row.date === selectedDate)
      && (!transition || (flowMode === 'entry' || row.outcome_status === 'mature') && flowKey(row, flowMode) === transition)
      && (!needle || `${row.symbol} ${row.name} ${row.stage} ${row.topics.join(' ')} ${row.sources.join(' ')}`.toLowerCase().includes(needle)))
  }, [groupRows, flowMode, search, selectedDate, transition])
  const flows = useMemo(() => {
    const buckets = new Map<string, StockPoolReviewRow[]>()
    for (const row of groupRows) {
      if (flowMode === 'outcome' && row.outcome_status !== 'mature') continue
      const key = flowKey(row, flowMode)
      const bucket = buckets.get(key)
      if (bucket) bucket.push(row)
      else buckets.set(key, [row])
    }
    return [...buckets].map(([key, rows]) => {
      const [from, to] = key.split('→')
      const priced = rows.map(row => row.return_pct).filter((value): value is number => value != null).sort((a, b) => a - b)
      const middle = Math.floor(priced.length / 2)
      const median = priced.length ? (priced[middle] + priced[Math.floor((priced.length - 1) / 2)]) / 2 : null
      return { key, from, to, count: rows.length, retained: rows.filter(row => row.target_stage != null && row.outcome_status === 'mature').length, median }
    }).sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
  }, [groupRows, flowMode])
  const shownFlows = useMemo(() => showAllFlows ? flows : flows.slice(0, 18), [flows, showAllFlows])
  const chartCount = shownFlows.reduce((sum, flow) => sum + flow.count, 0)
  const daily = useMemo(() => {
    const days = new Map<string, StockPoolReviewRow[]>()
    for (const row of groupRows) {
      const bucket = days.get(row.date)
      if (bucket) bucket.push(row)
      else days.set(row.date, [row])
    }
    return [...days].sort((a, b) => b[0].localeCompare(a[0])).map(([day, rows]) => {
      const mature = rows.filter(row => row.outcome_status === 'mature')
      const priced = mature.map(row => row.return_pct).filter((value): value is number => value != null)
      const opening = mature.map(row => row.open_proxy_pct).filter((value): value is number => value != null)
      return { day, sample: rows.length, mature: mature.length,
        retained: mature.filter(row => row.target_stage != null).length,
        recorded: mature.filter(row => row.snapshot_status === 'recorded').length,
        unavailable: rows.filter(row => row.outcome_status === 'unavailable').length,
        median: median(priced), openMedian: median(opening) }
    })
  }, [groupRows])
  const topicTargetStages = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const row of groupRows) if (row.outcome_status === 'mature') {
      const stage = row.target_stage || '未入池'
      counts[stage] = (counts[stage] ?? 0) + 1
    }
    return counts
  }, [groupRows])
  const chartOption = useMemo(() => ({
    backgroundColor: 'transparent',
    animationDuration: typeof globalThis.window !== 'undefined' && globalThis.window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 550,
    tooltip: { trigger: 'item', backgroundColor: '#18181b', borderColor: '#52525b', textStyle: { color: '#e4e4e7', fontSize: 11 },
      formatter: (params: { dataType?: string; data?: { from?: string; to?: string; count?: number; retained?: number; median?: number | null; stage?: string }; value?: number }) => {
        const item = params.data ?? {}
        if (params.dataType === 'edge') return `${escapeHtml(item.from || '')} → ${escapeHtml(item.to || '')}<br/><b>${item.count || 0} 次观察</b>${flowMode === 'outcome' ? `<br/>留池 ${percent(item.retained || 0, item.count || 0)} · 收盘变化中位 ${signed(item.median ?? null)}` : ''}<br/>点击查看逐股明细`
        return `${escapeHtml(item.stage || '')}<br/><b>${params.value || 0} 次观察</b>`
      },
    },
    aria: { enabled: true, label: { description: '历史股池阶段流水图。流带宽度表示观察样本数，点击流带筛选逐股明细。' } },
    series: [{ type: 'sankey', left: 88, right: 88, top: 18, bottom: 16, nodeWidth: 12, nodeGap: 9,
      draggable: false, layoutIterations: 32, emphasis: { focus: 'adjacency' },
      label: { color: '#d4d4d8', fontSize: 10, formatter: (params: { data?: { stage?: string } }) => params.data?.stage || '' },
      levels: [{ depth: 0, label: { position: 'left' } }, { depth: 1, label: { position: 'right' } }],
      lineStyle: { curveness: 0.55 },
      data: [
        ...[...new Set(shownFlows.map(flow => flow.from))].map(stage => ({ name: `from:${stage}`, stage, itemStyle: { color: STAGE_COLORS[stage] || '#64748b' } })),
        ...[...new Set(shownFlows.map(flow => flow.to))].map(stage => ({ name: `to:${stage}`, stage, itemStyle: { color: STAGE_COLORS[stage] || '#64748b' } })),
      ],
      links: shownFlows.map(flow => ({ source: `from:${flow.from}`, target: `to:${flow.to}`, value: flow.count,
        flow_key: flow.key, from: flow.from, to: flow.to, count: flow.count, retained: flow.retained, median: flow.median,
        lineStyle: { color: flow.from === flow.to ? '#64748b' : STAGE_COLORS[flow.to] || '#64748b', opacity: transition ? (transition === flow.key ? .85 : .07) : flow.from === flow.to ? .25 : .6 },
      })),
    }],
  }), [flowMode, shownFlows, transition])
  const stats = data?.groups[group]
  const attributionRows = Object.entries(data?.attribution[attributionMode] ?? {})
    .filter(([, item]) => item.matured_count > 0)
    .sort((a, b) => b[1].matured_count - a[1].matured_count)
    .slice(0, attributionMode === 'transitions' ? 12 : 9)
  const coverageDays = [...new Set([...(data?.anchor_dates ?? []), ...(data?.skipped_dates.map(item => item.date) ?? [])])].sort()

  return <section className="space-y-3">
    <div className="rounded-[9px] border border-[#353539] bg-[#151517] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-[15px] font-semibold">历史入池与阶段复盘</h2><p className="mt-1 text-[11px] text-secondary">从每个已发布快照出发，观察后续留池、阶段去向和复权收盘变化。</p></div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="text-muted">观察范围</span>
          <select aria-label="观察范围" value={window} onChange={event => { setWindow(Number(event.target.value)); setTransition(''); setSelectedDate(''); setLimit(60) }} className="rounded border border-border bg-base px-2 py-1.5"><option value={10}>近10个快照</option><option value={20}>近20个快照</option><option value={30}>近30个快照</option></select>
          <span className="ml-2 text-muted">观察终点</span>
          <div className="flex rounded border border-border bg-base p-0.5">{([1, 3, 5] as const).map(value => <button key={value} onClick={() => { setHorizon(value); setTransition(''); setSelectedDate(''); setLimit(60) }} className={`rounded px-2.5 py-1 ${horizon === value ? 'bg-accent/20 text-accent' : 'text-muted hover:text-foreground'}`}>{value}日后</button>)}</div>
          <label className="ml-2 flex items-center gap-1 text-muted">假设往返成本<select aria-label="假设往返成本" value={costBps} onChange={event => setCostBps(Number(event.target.value))} className="rounded border border-border bg-base px-2 py-1.5 text-foreground"><option value={0}>0bp</option><option value={20}>20bp</option><option value={50}>50bp</option></select></label>
        </div>
      </div>
      {data && <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-[#2a2a2f] pt-2 text-[10px] text-muted">
        <span>可比观察日 {data.anchor_dates.length} / {coverageDays.length} · {data.anchor_dates[0] || '—'} 至 {data.anchor_dates[data.anchor_dates.length - 1] || '—'}</span>
        <span>未纳入 {data.skipped_dates.length} 天：{data.skipped_dates.filter(item => item.reason === 'incompatible').length} 天版本不同，其余缺前日或质量不足</span>
        <span>同一股票可在不同日期重复出现；变化类型可重叠</span>
        {review.isFetching && <span>更新中…</span>}
      </div>}
      {data && <div className="mt-2 flex flex-wrap items-center gap-1" aria-label="历史样本覆盖">
        <span className="mr-2 text-[10px] text-muted">样本日历</span>
        {coverageDays.map(day => {
          const skipped = data.skipped_dates.find(item => item.date === day)
          const matured = data.rows.some(row => row.date === day && row.outcome_status === 'mature')
          const unavailable = data.rows.some(row => row.date === day && row.outcome_status === 'unavailable')
          return <span key={day} title={`${day} · ${skipped ? skipped.reason === 'incompatible' ? '规则版本不同' : skipped.reason === 'quality' || skipped.reason === 'limited' ? '快照或来源质量不足' : '缺少可比前日' : matured ? `${horizon}日结果已到期` : unavailable ? '后续快照或交易日缺口，结果不可比' : '后续结果尚未到期'}`} className={`rounded border px-1.5 py-0.5 font-mono text-[9px] ${skipped || (unavailable && !matured) ? 'border-[#34343a] bg-[#1a1a1d] text-[#777780]' : matured ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-300' : 'border-blue-500/35 bg-blue-500/10 text-blue-300'}`}>{day.slice(5)}</span>
        })}
        <span className="ml-1 text-[9px] text-muted">绿：已到期 · 蓝：待到期 · 灰：不可比</span>
      </div>}
    </div>

    {review.isLoading && <div className="rounded border border-border bg-surface p-8 text-center text-muted">正在计算历史观察…</div>}
    {review.isError && <div className="rounded border border-danger/40 bg-danger/5 p-5 text-danger">历史复盘加载失败：{String(review.error)}</div>}
    {data && <>
      <div className="rounded-[8px] border border-amber-500/30 bg-amber-500/[.06] px-3 py-2 text-[10px] leading-5 text-amber-100">
        <strong className="mr-2 text-[11px]">{data.audit_counts.recorded ? '历史样本覆盖' : '探索性复盘'}</strong>
        可比 {data.anchor_dates.length} / {coverageDays.length} 个快照日 · 到期 {data.groups.all.matured_count} 次观察 · 实盘可核验 {data.audit_counts.recorded ?? 0} 次 · 历史回放 {data.audit_counts.replay ?? 0} 次。
        {data.audit_counts.late || data.audit_counts.early || data.audit_counts.unknown ? ` 发布时间不可核验 ${Number(data.audit_counts.late ?? 0) + Number(data.audit_counts.early ?? 0) + Number(data.audit_counts.unknown ?? 0)} 次。` : ''}
        以下收益包含回放样本，按当时已发布股池和后续行情描述结果。
      </div>
      <div className="rounded-[9px] border border-[#353539] bg-[#151517] p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-xs font-semibold">按题材回看</h3><p className="mt-0.5 text-[10px] text-muted">题材来自观察日快照；一次观察可同时属于多个题材。选择后，下方流水图、逐日样本和逐股明细都限定在该题材。</p></div><select aria-label="历史题材" value={topic} onChange={event => { setTopic(event.target.value); setSelectedDate(''); setTransition(''); setLimit(60) }} className="max-w-full rounded border border-border bg-base px-2 py-1.5 text-[11px]"><option value="">全部题材</option>{topics.map(item => <option key={item.name} value={item.name}>{item.name} · {item.days}日 / {item.count}次</option>)}</select></div>
        <div className="mt-2 flex flex-wrap gap-1.5">{topics.slice(0, 10).map(item => <button key={item.name} onClick={() => { setTopic(current => current === item.name ? '' : item.name); setSelectedDate(''); setTransition(''); setLimit(60) }} className={`rounded border px-2 py-1 text-[10px] ${topic === item.name ? 'border-accent/60 bg-accent/10 text-foreground' : 'border-[#303037] bg-[#111113] text-secondary hover:border-accent/40'}`}>{item.name} <span className="ml-1 font-mono text-muted">{item.days}日 · {item.count}次</span></button>)}{topic && !topics.slice(0, 10).some(item => item.name === topic) && <button onClick={() => setTopic('')} className="rounded border border-accent/60 bg-accent/10 px-2 py-1 text-[10px]">{topic} ×</button>}{!topics.length && <span className="text-[10px] text-muted">可比观察日暂无当日题材标签</span>}</div>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">{GROUPS.map(([key, label]) => {
        const item = data.groups[key]
        return <button key={key} onClick={() => { setGroup(key); setTransition(''); setSelectedDate(''); setLimit(60) }} className={`min-h-[102px] rounded-[8px] border px-3 py-2.5 text-left transition-colors ${group === key ? 'border-accent/60 bg-accent/10' : 'border-[#353539] bg-[#151517] hover:border-accent/40'}`}>
          <div className="text-[10px] text-muted">{label}</div><div className="mt-1 font-mono text-xl font-semibold">{item?.sample_count ?? 0}<span className="ml-1 text-[9px] font-normal text-muted">次观察</span></div>
          <div className="mt-1 text-[9px] text-secondary">到期 {item?.matured_count ?? 0} · 留池 {item ? percent(item.retained_count, item.matured_count) : '—'}</div>
          <div className="mt-0.5 text-[9px] text-muted">全局样本 · 同日对照 {signed(item?.peer_diff_pct ?? null)}{item?.peer_days ? ` · ${item.peer_days}日` : ''}</div>
        </button>
      })}</div>

      {stats && <><div className="px-1 text-[10px] text-secondary">当前统计：{topic ? `${topic} · ` : ''}{GROUPS.find(([key]) => key === group)?.[1]}{topic && <span className="ml-2 text-muted">上方变化类型卡片展示全局样本</span>}</div><div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">{(topicStats ? [
        ['到期样本', `${topicStats.matured} / ${topicStats.samples}`, `${topicStats.days} 个观察日 · ${topicStats.symbols} 只不同股票`],
        ['仍在池中', percent(topicStats.retained, topicStats.matured), `${topicStats.retained} 次仍在池`],
        ['平均收盘变化', signed(topicStats.mean), `有行情 ${topicStats.priced} / ${topicStats.matured}`],
        ['收盘变化中位数', signed(topicStats.median), `待到期 ${topicStats.pending} · 不可比 ${topicStats.unavailable}`],
        ['收盘上涨占比', percent(topicStats.up, topicStats.priced), `${topicStats.up} 次上涨`],
        ['题材样本量', `${topicStats.days}日`, `题材归属来自观察日快照`],
      ] : [
        ['到期样本', `${stats.matured_count} / ${stats.sample_count}`, `${stats.matured_dates} 个观察日 · ${stats.unique_symbols} 只不同股票`],
        ['仍在池中', percent(stats.retained_count, stats.matured_count), `${stats.retained_count} 次仍在池`],
        ['平均收盘变化', signed(stats.mean_return_pct), `有行情 ${stats.priced_count} / ${stats.matured_count}`],
        ['收盘变化中位数', signed(stats.median_return_pct), `待到期 ${stats.pending_count} · 不可比 ${stats.unavailable_count}`],
        ['收盘上涨占比', percent(stats.up_count, stats.priced_count), `${stats.up_count} 次上涨`],
        ['同日池内对照差', signed(stats.peer_diff_pct), stats.peer_days ? `对比同日其余候选 · ${stats.peer_days}日等权` : '选择变化类型后显示'],
      ]).map(([label, value, note]) => <div key={label} className="rounded-[8px] border border-[#353539] bg-[#151517] px-3.5 py-3"><div className="text-[10px] text-muted">{label}</div><div className="mt-1 font-mono text-[19px] font-semibold text-foreground">{value}</div><div className="mt-1 text-[9px] text-muted">{note}</div></div>)}</div></>}

      {stats && <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-[8px] border border-[#353539] bg-[#151517] px-3.5 py-2.5 text-[10px]">
        <strong className="text-foreground">次日开盘价格代理</strong>
        <span>均值 <b className="font-mono text-foreground">{signed(topicStats ? topicStats.openMean : stats.mean_open_proxy_pct)}</b></span>
        <span>中位 <b className="font-mono text-foreground">{signed(topicStats ? topicStats.openMedian : stats.median_open_proxy_pct)}</b></span>
        <span>扣假设成本后中位 <b className="font-mono text-foreground">{signed(topicStats ? topicStats.openNetMedian : stats.median_open_proxy_net_pct)}</b></span>
        {!topic && <><span>同日池内差 <b className="font-mono text-foreground">{signed(stats.peer_open_diff_pct)}</b></span><span>池外合格股差 <b className="font-mono text-foreground">{signed(stats.eligible_diff_pct)}</b>{stats.eligible_days ? ` · ${stats.eligible_days}日` : ' · 待首发合格全集'}</span></>}
        <span className="text-muted">有价格 {topicStats ? topicStats.openCount : stats.open_proxy_count} / {topicStats ? topicStats.matured : stats.matured_count} · 成本为情景假设，未检验实际可买性</span>
      </div>}

      <div className="overflow-hidden rounded-[9px] border border-[#353539] bg-[#151517]">
        <div className="flex items-center justify-between px-3.5 py-3"><div><h3 className="text-xs font-semibold">逐日观察</h3><p className="mt-0.5 text-[10px] text-muted">{topic ? `${topic} · ` : ''}{GROUPS.find(([key]) => key === group)?.[1]} · 点击日期筛选下方逐股记录</p></div>{selectedDate && <button onClick={() => setSelectedDate('')} className="text-[10px] text-accent">清除日期</button>}</div>
        <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-[10px]"><thead className="bg-[#111113] text-muted"><tr>{['观察日', '观察次数', '到期／不可比', '留池比例', '收盘变化中位', '开盘代理中位', '实盘可核验'].map(label => <th key={label} className="border-y border-[#29292e] px-3 py-2 text-right font-medium first:text-left">{label}</th>)}</tr></thead><tbody>{daily.map(item => <tr key={item.day} className={`border-b border-[#25252a] text-right font-mono ${selectedDate === item.day ? 'bg-accent/10 text-accent' : 'text-secondary hover:bg-elevated/40'}`}><td className="px-3 py-2.5 text-left"><button onClick={() => { setSelectedDate(current => current === item.day ? '' : item.day); setTransition(''); setLimit(60) }} className="text-accent hover:underline">{item.day}</button></td><td className="px-3 py-2.5">{item.sample}</td><td className="px-3 py-2.5">{item.mature} / {item.unavailable}</td><td className="px-3 py-2.5">{percent(item.retained, item.mature)}</td><td className="px-3 py-2.5">{signed(item.median)}</td><td className="px-3 py-2.5">{signed(item.openMedian)}</td><td className="px-3 py-2.5">{item.recorded} / {item.mature}</td></tr>)}</tbody></table>{!daily.length && <div className="px-3 py-6 text-center text-[10px] text-muted">当前题材与变化类型没有可比观察日</div>}</div>
      </div>

      {!topic && <div className="rounded-[9px] border border-[#353539] bg-[#151517] p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-xs font-semibold">全局来源与迁移拆分</h3><p className="mt-0.5 text-[10px] text-muted">各类可能重叠；对照差按观察日等权，结果包含历史回放。</p></div><div className="flex rounded border border-border bg-base p-0.5 text-[10px]">{([['sources', '九路来源'], ['added_sources', '新增来源'], ['transitions', '具体迁移'], ['research', '研究材料']] as const).map(([mode, label]) => <button key={mode} onClick={() => setAttributionMode(mode)} className={`rounded px-2 py-1 ${attributionMode === mode ? 'bg-accent/20 text-accent' : 'text-muted hover:text-foreground'}`}>{label}</button>)}</div></div>
        {attributionMode === 'research' && <p className="mt-2 text-[10px] text-muted">SMNC 标题单股细分在 {data.research_breakdown_observations} / {data.groups.all.matured_count} 次到期观察中有记录；旧快照未记录不视为零。</p>}
        {(attributionMode === 'added_sources' || attributionMode === 'transitions') && <p className="mt-2 text-[10px] text-muted">变化归因需观察日与前一日均有按时首次版；下列“实盘可核验”只计算满足该条件的到期观察。</p>}
        <div className="mt-2 grid gap-1.5 md:grid-cols-2 xl:grid-cols-3">{attributionRows.map(([key, item]) => <div key={key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 rounded border border-[#29292e] bg-[#111113] px-2.5 py-2 text-[10px]"><span className="truncate text-secondary" title={item.label || key}>{item.label || key}</span><b className="font-mono text-foreground">{item.matured_count}次</b><span className="mt-0.5 text-muted">开盘代理中位 {signed(item.median_open_proxy_pct)}</span><span className="mt-0.5 font-mono text-muted">{attributionMode === 'added_sources' || attributionMode === 'transitions' ? `实盘可核验变化 ${item.recorded_transition_count ?? 0}次` : `同日差 ${signed(item.peer_open_diff_pct)}`}</span></div>)}{!attributionRows.length && <div className="py-3 text-[10px] text-muted">暂无到期观察</div>}</div>
      </div>}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(310px,1fr)]">
        <div className="min-w-0 rounded-[9px] border border-[#353539] bg-[#151517] p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-xs font-semibold">阶段流水图</h3><p className="mt-0.5 text-[10px] text-muted">带宽＝观察次数 · 点击流带下钻股票</p></div><div className="flex items-center gap-1 rounded border border-border bg-base p-0.5 text-[10px]">{([['outcome', `${horizon}日后去向`], ['entry', '入池变化']] as const).map(([mode, label]) => <button key={mode} onClick={() => { setFlowMode(mode); setTransition(''); setShowAllFlows(false); setLimit(60) }} aria-pressed={flowMode === mode} className={`rounded px-2 py-1 ${flowMode === mode ? 'bg-accent/20 text-accent' : 'text-muted hover:text-foreground'}`}>{label}</button>)}</div></div>
          {flowMode === 'outcome' && <div className="mt-2 rounded border border-amber-500/25 bg-amber-500/[.06] px-2 py-1 text-[10px] text-amber-200">事后去向：目标阶段在观察日尚不可知，只用于复盘。</div>}
          {flows.length ? <>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[9px] text-muted"><span>图示 {shownFlows.length} / {flows.length} 条路径 · 覆盖 {chartCount} / {flowMode === 'outcome' ? topicStats?.matured ?? stats?.matured_count ?? 0 : groupRows.length} 次观察</span>{flows.length > 18 && <button onClick={() => setShowAllFlows(value => !value)} className="text-accent">{showAllFlows ? '只看主要路径' : '显示全部路径'}</button>}{transition && <button onClick={() => setTransition('')} className="text-accent">清除路径筛选</button>}</div>
            <div className="mt-1 overflow-x-auto"><ReactECharts option={chartOption} className="min-w-[520px] sm:min-w-0" style={{ height: 340 }} opts={{ renderer: 'svg' }} onEvents={{ click: (params: { dataType?: string; data?: { flow_key?: string } }) => {
              if (params.dataType === 'edge' && params.data?.flow_key) { setTransition(current => current === params.data?.flow_key ? '' : params.data?.flow_key || ''); setSelectedDate(''); setLimit(60) }
            } }} /></div>
            <div className="grid gap-1.5 border-t border-[#29292e] pt-2 sm:grid-cols-2">{flows.slice(0, 6).map(flow => <button key={flow.key} onClick={() => { setTransition(current => current === flow.key ? '' : flow.key); setSelectedDate(''); setLimit(60) }} aria-pressed={transition === flow.key} className={`flex items-center gap-2 rounded border px-2 py-1.5 text-left text-[10px] ${transition === flow.key ? 'border-accent/60 bg-accent/10' : 'border-[#2a2a2f] bg-[#111113] hover:border-accent/40'}`}><i className="h-1.5 w-2 shrink-0 rounded-full" style={{ backgroundColor: STAGE_COLORS[flow.to] || '#64748b' }} /><span className="min-w-0 flex-1 truncate" title={flow.key}>{flow.key}</span><strong className="shrink-0 font-mono">{flow.count}</strong>{flowMode === 'outcome' && <span className="shrink-0 text-muted">中位 {signed(flow.median)}</span>}</button>)}</div>
          </> : <div className="py-12 text-center text-xs text-muted">{flowMode === 'outcome' ? '当前类型尚无到期样本' : '当前类型没有可展示的入池变化'}</div>}
        </div>
        <div className="rounded-[9px] border border-[#353539] bg-[#151517] p-3.5">
          <h3 className="text-xs font-semibold">{horizon}日后阶段去向</h3>
          <div className="mt-2 space-y-1.5">{Object.entries(topic ? topicTargetStages : stats?.target_stages ?? {}).sort((a, b) => b[1] - a[1]).map(([stage, count]) => <div key={stage} className="flex items-center gap-2 text-[10px]"><span className="w-16 shrink-0 text-secondary">{stage}</span><span className="h-1.5 flex-1 rounded-full bg-elevated"><span className="block h-full rounded-full bg-emerald-400" style={{ width: `${count / Math.max(topicStats?.matured ?? stats?.matured_count ?? 1, 1) * 100}%` }} /></span><span className="w-10 text-right font-mono">{count}</span></div>)}{!(topicStats?.matured ?? stats?.matured_count) && <div className="py-5 text-center text-[11px] text-muted">暂无到期样本</div>}</div>

        </div>
      </div>

      <div className="overflow-hidden rounded-[9px] border border-[#353539] bg-[#151517]">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2a2a2f] px-3.5 py-3"><div><h3 className="text-xs font-semibold">逐股观察明细</h3><p className="mt-0.5 text-[10px] text-muted">{visibleRows.length} 次观察{transition ? ` · ${transition}` : ''}{selectedDate ? ` · ${selectedDate}` : ''} · 点击股票可查看该日股池证据和120根日K</p></div><label className="relative"><Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" /><input value={search} onChange={event => { setSearch(event.target.value); setLimit(60) }} placeholder="搜索股票、阶段、题材或来源" className="w-60 rounded border border-border bg-base py-1.5 pl-7 pr-2 text-[11px] outline-none focus:border-accent/50" /></label></div>
        <div className="max-h-[670px] overflow-auto"><table className="w-full min-w-[1150px] table-fixed text-[10px]"><colgroup><col className="w-[88px]" /><col className="w-[132px]" /><col className="w-[180px]" /><col className="w-[190px]" /><col className="w-[290px]" /><col className="w-[150px]" /><col className="w-[90px]" /></colgroup><thead><tr>{['观察日', '股票', '入池／变化', '召回来源变化', '阶段轨迹', `${horizon}日后`, '收盘／开盘代理'].map(label => <th key={label} className="sticky top-0 z-[1] border-b border-[#2a2a2f] bg-[#111113] px-2.5 py-2 text-left font-medium text-muted">{label}</th>)}</tr></thead><tbody>{visibleRows.slice(0, limit).map(row => <tr key={`${row.date}:${row.symbol}`} className="border-b border-[#25252a] hover:bg-accent/[.05]"><td className="px-2.5 py-2 align-top font-mono text-muted">{row.date.slice(5)}</td><td className="px-2.5 py-2 align-top"><button onClick={() => onOpen(row.date, row.symbol, row.snapshot_basis === 'first_published' ? 'first' : 'current')} className="text-left hover:text-accent"><strong className="block truncate text-[11px]">{row.name}</strong><span className="font-mono text-[9px] text-muted">{row.symbol}</span></button></td><td className="px-2.5 py-2 align-top"><div className="flex flex-wrap gap-1">{row.labels.filter(label => label !== 'all').map(label => <span key={label} className="rounded border border-accent/25 bg-accent/[.07] px-1 py-0.5 text-[9px] text-secondary">{GROUPS.find(([key]) => key === label)?.[1]}</span>)}</div><div className="mt-1 truncate text-[9px] text-muted" title={row.topics.join('、')}>{row.topics.slice(0, 2).join('／') || '题材待确认'}</div></td><td className="px-2.5 py-2 align-top text-[9px] leading-4"><div className="truncate text-emerald-300" title={row.added_sources.join('、')}>{row.added_sources.length ? `+ ${row.added_sources.join('、')}` : '—'}</div>{row.removed_sources.length > 0 && <div className="truncate text-rose-300" title={row.removed_sources.join('、')}>− {row.removed_sources.join('、')}</div>}</td><td className="px-2.5 py-2 align-top"><div className="flex items-center gap-1 overflow-hidden">{row.path.map((point, index) => <span key={point.date} className="flex min-w-0 items-center gap-1"><span className={`max-w-[72px] truncate rounded border px-1 py-0.5 text-[9px] ${point.stage ? 'border-accent/25 bg-accent/[.07] text-secondary' : 'border-border bg-base text-muted'}`} title={`${point.date} ${point.stage || '未入池'}`}>{point.stage || '未入池'}</span>{index < row.path.length - 1 && <ArrowRight size={10} className="shrink-0 text-muted" />}</span>)}</div></td><td className="px-2.5 py-2 align-top"><span className={row.outcome_status === 'mature' ? 'text-foreground' : 'text-muted'}>{resultLabel(row)}</span><div className="mt-1 font-mono text-[9px] text-muted">{row.target_date?.slice(5) || '待发布'}</div></td><td className={`px-2.5 py-2 align-top font-mono font-semibold ${row.return_pct == null ? 'text-muted' : row.return_pct >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>{signed(row.return_pct)}<div className="mt-1 text-[9px] font-normal text-muted">开盘代理 {signed(row.open_proxy_pct)} · 扣费 {signed(row.open_proxy_net_pct)}</div><div className="text-[9px] font-normal text-muted">区间最低 {signed(row.max_adverse_pct)} / 最高 {signed(row.max_favorable_pct)}</div></td></tr>)}</tbody></table>{!visibleRows.length && <div className="p-8 text-center text-[11px] text-muted">当前条件下没有观察记录</div>}</div>
        {visibleRows.length > limit && <button onClick={() => setLimit(value => value + 60)} className="w-full border-t border-border py-2 text-[11px] text-accent hover:bg-accent/5">继续显示 · 已显示 {limit} / {visibleRows.length}</button>}
      </div>
      <p className="px-1 text-[10px] leading-5 text-muted">观察日使用当日收盘后的股池，不代表次日可成交价格。收盘变化按同一股票复权日K的观察日与目标日收盘价计算；未入池仍保留行情统计。缺失行情不纳入收益分母。“同日池内对照差”先在每个观察日计算该类型与其余候选的平均收盘变化差，再按日期等权平均；它不是全市场基准或可执行收益。阶段去向只用规则一致、质量完整的已发布快照；当前仍未到期的观察单列，不计入结果。</p>
    </>}
  </section>
}
