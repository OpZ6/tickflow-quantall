import { useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import type { StockPoolCandidate, StockPoolEvolution } from '@/lib/api'

const LOW_STAGES = new Set(['趋势延续', '回踩整理', '企稳修复'])
const KIND: Record<string, { label: string; tone: string; rank: number }> = {
  entered_topic: { label: '新入题材', tone: 'text-violet-300 border-violet-500/30 bg-violet-500/10', rank: 0 },
  stage_changed: { label: '阶段变化', tone: 'text-blue-300 border-blue-500/30 bg-blue-500/10', rank: 1 },
  entered_pool: { label: '昨日未入池', tone: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10', rank: 2 },
  source_changed: { label: '来源变化', tone: 'text-cyan-300 border-cyan-500/30 bg-cyan-500/10', rank: 3 },
  left_topic: { label: '离开题材', tone: 'text-amber-300 border-amber-500/30 bg-amber-500/10', rank: 4 },
  left_pool: { label: '今日未入池', tone: 'text-rose-300 border-rose-500/30 bg-rose-500/10', rank: 5 },
  unchanged: { label: '阶段未变', tone: 'text-muted border-border bg-elevated', rank: 6 },
  unknown: { label: '暂无前日', tone: 'text-muted border-border bg-elevated', rank: 7 },
}
const FLOW_COLOR: Record<string, string> = {
  entered_topic: '#a78bfa', stage_changed: '#60a5fa', entered_pool: '#34d399',
  source_changed: '#67e8f9', left_topic: '#fbbf24', left_pool: '#fb7185', unchanged: '#64748b',
}

type Props = {
  data?: StockPoolEvolution
  loading: boolean
  error: boolean
  mode: 'hot' | 'low'
  topic: string
  selectedStage: string
  onSelectStage: (stage: string) => void
  candidates: StockPoolCandidate[]
  search: string
  onOpen: (candidate: StockPoolCandidate) => void
  personal: Record<string, string>
  onPersonal: (symbol: string, value: 'unseen' | 'priority' | 'pending' | 'seen' | 'ignored') => void
  window: number
  onWindow: (window: number) => void
}

function compactDay(day: string) { return day.slice(5).replace('-', '/') }
function escapeHtml(value: string) { return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] ?? char) }

export function StageEvolution({
  data, loading, error, mode, topic, selectedStage, onSelectStage, candidates, search,
  onOpen, personal, onPersonal, window, onWindow,
}: Props) {
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null)
  const [selectedKind, setSelectedKind] = useState<string | null>(null)
  const [showAllMembers, setShowAllMembers] = useState(false)
  const candidateBySymbol = useMemo(() => new Map(candidates.map(row => [row.symbol, row])), [candidates])
  const graphFlows = useMemo(() => {
    if (!data || data.previous_count === null) return []
    const unchanged = new Map<string, { key: string; kind: string; from_stage: string; to_stage: string; count: number }>()
    for (const row of data.members) {
      if (row.kind !== 'unchanged') continue
      const existing = unchanged.get(row.flow_key)
      if (existing) existing.count += 1
      else unchanged.set(row.flow_key, {
        key: row.flow_key, kind: 'unchanged',
        from_stage: row.previous_stage ?? '未知阶段', to_stage: row.current_stage ?? '未知阶段', count: 1,
      })
    }
    return [...data.flows, ...unchanged.values()].sort((a, b) =>
      (KIND[a.kind]?.rank ?? 9) - (KIND[b.kind]?.rank ?? 9) || b.count - a.count || a.key.localeCompare(b.key))
  }, [data])
  const selected = graphFlows.find(flow => flow.key === selectedFlow)
  const chartHeight = Math.min(390, Math.max(270, Math.max(
    new Set(graphFlows.map(flow => flow.from_stage)).size,
    new Set(graphFlows.map(flow => flow.to_stage)).size,
  ) * 34))
  const sankeyOption = useMemo(() => {
    const previousStages = [...new Set(graphFlows.map(flow => flow.from_stage))]
    const currentStages = [...new Set(graphFlows.map(flow => flow.to_stage))]
    const nodes = [
      ...previousStages.map(stage => ({ name: `before:${stage}`, stage, itemStyle: { color: stage === '昨日未入池' ? '#34d399' : '#64748b' } })),
      ...currentStages.map(stage => ({ name: `after:${stage}`, stage, itemStyle: { color: stage === '今日未入池' ? '#fb7185' : stage === '其他题材' ? '#fbbf24' : '#60a5fa' } })),
    ]
    return {
      backgroundColor: 'transparent', animationDuration: typeof globalThis.window !== 'undefined' && globalThis.window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 450,
      tooltip: {
        trigger: 'item', backgroundColor: '#18181b', borderColor: '#52525b', textStyle: { color: '#e4e4e7', fontSize: 11 },
        formatter: (params: { dataType?: string; data?: { kind?: string; from_stage?: string; to_stage?: string; stage?: string; value?: number } ; value?: number }) => {
          const item = params.data ?? {}
          if (params.dataType === 'edge') return `${escapeHtml(KIND[item.kind ?? '']?.label ?? '')}<br/>${escapeHtml(item.from_stage ?? '')} → ${escapeHtml(item.to_stage ?? '')}<br/><b>${item.value ?? 0}只 · 点击看股票</b>`
          return `${escapeHtml(item.stage ?? '')}<br/><b>${params.value ?? 0}只</b>`
        },
      },
      aria: { enabled: true, label: { description: '昨日到今日股票阶段迁移流水图。流带宽度表示股票数量；下方提供可点击的文字路径。' } },
      series: [{
        type: 'sankey', left: 95, right: 95, top: 15, bottom: 15,
        nodeWidth: 11, nodeGap: 10, draggable: false, layoutIterations: 32,
        emphasis: { focus: 'adjacency' },
        label: { color: '#cbd5e1', fontSize: 10, formatter: (params: { data?: { stage?: string } }) => params.data?.stage ?? '' },
        levels: [{ depth: 0, label: { position: 'left' } }, { depth: 1, label: { position: 'right' } }],
        lineStyle: { curveness: 0.55 },
        data: nodes,
        links: graphFlows.map(flow => {
          const focused = selectedFlow ? selectedFlow === flow.key
            : selectedKind ? selectedKind === flow.kind
              : selectedStage ? (flow.kind.startsWith('left_') ? flow.from_stage : flow.to_stage) === selectedStage
                : true
          return {
            source: `before:${flow.from_stage}`, target: `after:${flow.to_stage}`,
            value: flow.count, flow_key: flow.key, kind: flow.kind,
            from_stage: flow.from_stage, to_stage: flow.to_stage,
            lineStyle: { color: FLOW_COLOR[flow.kind] ?? '#64748b', opacity: focused ? (selectedFlow || selectedKind || selectedStage ? 0.85 : flow.kind === 'unchanged' ? 0.28 : 0.67) : 0.08 },
          }
        }),
      }],
    }
  }, [graphFlows, selectedFlow, selectedKind, selectedStage])
  const needle = search.trim().toLowerCase()
  const movementRows = useMemo(() => {
    if (!data) return []
    const all = [
      ...data.members.map(row => ({ ...row, exit: false })),
      ...data.exits.map(row => ({ ...row, exit: true, added_sources: [] as string[], removed_sources: [] as string[],
        pct_chg: null, price_context: undefined, research_count: 0, freshness: '', reentry: false })),
    ]
    return all.filter(row =>
      (!selectedFlow || row.flow_key === selectedFlow)
      && (!selectedKind || row.kind === selectedKind)
      && (!selectedStage || (row.exit ? row.previous_stage : row.current_stage) === selectedStage)
      && (!needle || `${row.symbol} ${row.name} ${row.current_stage ?? ''} ${row.previous_stage ?? ''}`.toLowerCase().includes(needle))
      && (showAllMembers || selectedFlow || row.kind !== 'unchanged')
    ).sort((a, b) =>
      (KIND[a.kind]?.rank ?? 9) - (KIND[b.kind]?.rank ?? 9)
      || Number(b.freshness === '当日事件') - Number(a.freshness === '当日事件')
      || a.symbol.localeCompare(b.symbol))
  }, [data, selectedFlow, selectedKind, selectedStage, needle, showAllMembers])
  const maxHistory = Math.max(1, ...(data?.history.map(point => point.count ?? 0) ?? []))
  const selectKind = (kind: string) => {
    setSelectedKind(value => value === kind ? null : kind)
    setSelectedFlow(null)
    onSelectStage('')
  }
  const selectFlow = (key: string) => {
    setSelectedFlow(value => value === key ? null : key)
    setSelectedKind(null)
    onSelectStage('')
  }

  return <section className="border-b border-[#29292e] p-[13px]" aria-label="阶段与迁移">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <span className="grid h-[23px] min-w-[23px] place-items-center rounded-md border border-accent/40 bg-accent/10 px-1 font-mono text-[9px] font-semibold text-accent">02</span>
        <h3 className="text-xs font-semibold text-foreground">阶段与真实迁移</h3>
        <span className="text-[10px] text-muted">{topic || (mode === 'low' ? '全部趋势低吸' : '全部候选')}</span>
      </div>
      <div className="flex items-center gap-2 text-[10px]">
        {selectedStage && <button onClick={() => onSelectStage('')} className="cursor-pointer text-accent hover:text-accent/80">清除阶段</button>}
        <span className="text-muted">历史</span>
        {([5, 10, 30] as const).map(days => <button key={days} onClick={() => onWindow(days)} className={`cursor-pointer rounded border px-2 py-1 ${window === days ? 'border-accent/60 bg-accent/10 text-accent' : 'border-border text-muted hover:text-foreground'}`}>{days === 30 ? '全部' : `${days}日`}</button>)}
      </div>
    </div>
    {loading && <div className="mt-3 rounded border border-border p-4 text-xs text-muted">正在比较已发布股票池快照…</div>}
    {error && <div className="mt-3 rounded border border-danger/40 p-4 text-xs text-danger">阶段历史加载失败，请重试。</div>}
    {data && <>
      <div className="mt-2 text-[10px] text-muted">
        {data.basis === 'current_cohort'
          ? '今日低吸候选的历史回看；静态概念只用于圈定今日成员，昨日数字表示这组股票昨日在池数量，昨日可能处于其他阶段。'
          : `同名当日题材与前一已发布交易日对比 · ${data.previous_date ?? '暂无前日快照'}`}
        {data.comparison_status === 'limited' && <span className="ml-2 text-warning">部分来源降级，跨日变化仅供核对。</span>}
        {data.comparison_status === 'incompatible' && <span className="ml-2 text-warning">规则版本不同，跨日变化口径受限。</span>}
        {data.comparison_status === 'unavailable' && <span className="ml-2 text-warning">暂无可比较的前日快照。</span>}
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
        <span className="rounded border border-accent/30 bg-accent/10 px-2.5 py-1.5 text-accent">今日 {data.current_count}只</span>
        <span className="rounded border border-border bg-base px-2.5 py-1.5 text-secondary">{mode === 'low' ? '昨日在池' : '昨日同范围'} {data.previous_count ?? '—'}只</span>
        {data.previous_count !== null && <>
          <span className="rounded border border-border bg-base px-2.5 py-1.5 text-secondary">两日留存 {data.counts.retained}</span>
          {mode === 'hot' && topic && <button onClick={() => selectKind('entered_topic')} aria-pressed={selectedKind === 'entered_topic'} className={`cursor-pointer rounded border border-violet-500/30 bg-violet-500/10 px-2.5 py-1.5 text-violet-300 hover:border-violet-300 ${selectedKind === 'entered_topic' ? 'ring-1 ring-violet-300' : ''}`}>昨日已在池 · 新入题材 {data.counts.entered_topic}</button>}
          <button onClick={() => selectKind('entered_pool')} aria-pressed={selectedKind === 'entered_pool'} className={`cursor-pointer rounded border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1.5 text-emerald-300 hover:border-emerald-300 ${selectedKind === 'entered_pool' ? 'ring-1 ring-emerald-300' : ''}`}>昨日未入池 {data.counts.entered_pool}</button>
          <button onClick={() => selectKind('stage_changed')} aria-pressed={selectedKind === 'stage_changed'} className={`cursor-pointer rounded border border-blue-500/30 bg-blue-500/10 px-2.5 py-1.5 text-blue-300 hover:border-blue-300 ${selectedKind === 'stage_changed' ? 'ring-1 ring-blue-300' : ''}`}>阶段变化 {data.counts.stage_changed}</button>
          {mode === 'hot' && topic && <button onClick={() => selectKind('left_topic')} aria-pressed={selectedKind === 'left_topic'} className={`cursor-pointer rounded border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-amber-300 hover:border-amber-300 ${selectedKind === 'left_topic' ? 'ring-1 ring-amber-300' : ''}`}>离开题材 {data.counts.left_topic}</button>}
          {mode === 'hot' && <button onClick={() => selectKind('left_pool')} aria-pressed={selectedKind === 'left_pool'} className={`cursor-pointer rounded border border-rose-500/30 bg-rose-500/10 px-2.5 py-1.5 text-rose-300 hover:border-rose-300 ${selectedKind === 'left_pool' ? 'ring-1 ring-rose-300' : ''}`}>今日未入池 {data.counts.left_pool}</button>}
        </>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
        {data.stages.filter(item => mode === 'hot' || LOW_STAGES.has(item.stage)).map(item => {
          const delta = item.previous === null ? null : item.current - item.previous
          return <button key={item.stage} onClick={() => { setSelectedFlow(null); setSelectedKind(null); onSelectStage(selectedStage === item.stage ? '' : item.stage) }}
            aria-pressed={selectedStage === item.stage}
            className={`cursor-pointer rounded-lg border p-2.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${selectedStage === item.stage ? 'border-accent/70 bg-accent/10' : 'border-[#353539] bg-[#111113] hover:border-accent/50'}`}>
            <div className="text-[10px] text-secondary">{item.stage}</div>
            <div className="mt-1.5 flex items-end justify-between"><strong className="font-mono text-xl leading-none text-foreground">{item.current}<small className="ml-1 text-[9px] font-normal text-muted">只</small></strong><span className={`font-mono text-[10px] ${delta == null ? 'text-muted' : delta > 0 ? 'text-bull' : delta < 0 ? 'text-bear' : 'text-secondary'}`}>{delta == null ? '前日 —' : `昨 ${item.previous} · ${delta > 0 ? '+' : ''}${delta}`}</span></div>
            <div className="mt-2 h-1 overflow-hidden rounded bg-elevated"><div className="h-full rounded bg-accent" style={{ width: `${data.current_count ? item.current / data.current_count * 100 : 0}%` }} /></div>
          </button>
        })}
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]">
        <div className="min-w-0 rounded-lg border border-[#353539] bg-[#111113] p-3">
          <div className="mb-1 flex items-center justify-between"><h4 className="text-[11px] font-semibold">阶段流水图 <span className="font-normal text-muted">· 带宽=股票数，点击流带看股票</span></h4>{selectedFlow && <button onClick={() => setSelectedFlow(null)} className="cursor-pointer text-[10px] text-accent">清除路径</button>}</div>
          {graphFlows.length ? <>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-muted">
              {(['unchanged', 'stage_changed', 'source_changed', 'entered_topic', 'entered_pool', 'left_topic', 'left_pool'] as const).filter(kind => graphFlows.some(flow => flow.kind === kind)).map(kind => <span key={kind} className="inline-flex items-center gap-1"><i className="h-1.5 w-3 rounded-full" style={{ backgroundColor: FLOW_COLOR[kind] }} />{KIND[kind].label}</span>)}
            </div>
            <p className="mt-1 text-[9px] text-muted sm:hidden">左右滑动查看完整流水图；下方可展开文字路径。</p>
            <div className="mt-1 overflow-x-auto">
              <ReactECharts option={sankeyOption} className="min-w-[480px] sm:min-w-0" style={{ height: chartHeight }} opts={{ renderer: 'svg' }} onEvents={{ click: (params: { dataType?: string; data?: { flow_key?: string } }) => {
                if (params.dataType === 'edge' && params.data?.flow_key) selectFlow(params.data.flow_key)
              } }} />
            </div>
            <details className="border-t border-[#29292e] pt-2">
              <summary className="cursor-pointer text-[10px] text-accent">查看文字路径 · {graphFlows.length}条</summary>
              <div className="mt-2 max-h-[180px] space-y-1 overflow-y-auto pr-1">
                {graphFlows.map(flow => <button key={flow.key} onClick={() => selectFlow(flow.key)} aria-pressed={selectedFlow === flow.key}
                  className={`flex w-full cursor-pointer items-center gap-2 rounded border px-2 py-1.5 text-left text-[10px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${selectedFlow === flow.key ? 'border-accent/60 bg-accent/10' : 'border-[#29292e] hover:border-accent/40'}`}>
                  <i className="h-1.5 w-3 shrink-0 rounded-full" style={{ backgroundColor: FLOW_COLOR[flow.kind] ?? '#64748b' }} />
                  <span className="min-w-0 flex-1 truncate">{KIND[flow.kind]?.label ?? flow.kind} · {flow.from_stage} → {flow.to_stage}</span>
                  <strong className="shrink-0 font-mono">{flow.count}只</strong>
                </button>)}
              </div>
            </details>
          </> : <div className="py-5 text-center text-xs text-muted">{data.previous_date ? '当前范围暂无可比较的迁移路径' : '暂无前日快照，尚不能显示迁移'}</div>}
        </div>
        <div className="rounded-lg border border-[#353539] bg-[#111113] p-3">
          <h4 className="text-[11px] font-semibold">{mode === 'low' ? '今日成员的历史在池情况' : '范围广度 · 已发布交易日'}</h4>
          <div className="mt-1 text-[9px] text-muted">柱：成员数 · 数字：当日事件候选</div>
          <div className="mt-3 flex h-[115px] items-end gap-1.5">
            {data.history.map(point => <div key={point.date} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1" title={`${point.date} · ${point.count ?? '缺失'}只 · 事件 ${point.event_count ?? '缺失'}`}>
              <span className="font-mono text-[8px] text-muted">{point.event_count ?? '—'}</span>
              <div className="flex h-[75px] w-full items-end rounded-sm bg-elevated/50"><div className="w-full rounded-sm bg-accent/70" style={{ height: `${point.count == null ? 0 : Math.max(3, point.count / maxHistory * 100)}%` }} /></div>
              <span className="truncate font-mono text-[8px] text-muted">{compactDay(point.date)}</span>
            </div>)}
          </div>
          <p className="mt-3 border-t border-border pt-2 text-[10px] leading-relaxed text-secondary">盘后先核对新入题材与阶段变化的来源，再检查价格位置和 K 线，标记次日待观察股票。阶段标签本身不构成交易信号。</p>
        </div>
      </div>
      <div className="mt-3 rounded-lg border border-[#353539] bg-[#111113] p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h4 className="text-[11px] font-semibold">{selected ? `${KIND[selected.kind]?.label} · ${selected.from_stage} → ${selected.to_stage}` : selectedKind ? KIND[selectedKind]?.label : '逐股变化与次日核对'} <span className="font-normal text-muted">· {movementRows.length}只</span></h4><div className="flex gap-3 text-[10px]">{selectedStage && <span className="text-secondary">当前阶段：{selectedStage}</span>}{selectedKind && <button onClick={() => setSelectedKind(null)} className="cursor-pointer text-accent">清除类别</button>}{!selectedKind && !selectedFlow && <button onClick={() => setShowAllMembers(value => !value)} className="cursor-pointer text-accent">{showAllMembers ? '只看变化' : '含未变化股票'}</button>}</div></div>
        {search && <div className="mb-2 text-[9px] text-muted">上方统计为范围全量；搜索只筛下列股票。</div>}
        {movementRows.length ? <div className="max-h-[245px] divide-y divide-[#29292e] overflow-y-auto">
          {movementRows.slice(0, showAllMembers || selectedFlow || selectedKind ? undefined : 8).map(row => {
            const current = candidateBySymbol.get(row.symbol)
            return <div key={row.symbol} className="grid grid-cols-[minmax(115px,1fr)_minmax(145px,1.2fr)_minmax(180px,1.6fr)_115px] items-center gap-2 py-2 text-[10px]">
              {current ? <button onClick={() => onOpen(current)} className="min-w-0 cursor-pointer text-left hover:text-accent"><strong className="block truncate">{row.name}</strong><span className="font-mono text-muted">{row.symbol}</span></button>
                : <div className="min-w-0"><strong className="block truncate">{row.name}</strong><span className="font-mono text-muted">{row.symbol}</span></div>}
              <div className="min-w-0"><span className={`inline-block rounded border px-1 py-0.5 text-[9px] ${KIND[row.kind]?.tone ?? KIND.unchanged.tone}`}>{KIND[row.kind]?.label ?? row.kind}{row.reentry ? ' · 历史回归' : ''}</span><div className="mt-1 truncate text-secondary" title={`${row.previous_stage ?? '昨日未入池'} → ${row.current_stage ?? '今日未入池'}`}>{row.previous_stage ?? '昨日未入池'} → {row.current_stage ?? '今日未入池'}</div></div>
              <div className="min-w-0 text-[9px] text-secondary"><div className="truncate" title={`新增：${row.added_sources.join('、')}；消失：${row.removed_sources.join('、')}`}>{row.added_sources.length ? `来源＋${row.added_sources.join('、')}` : row.removed_sources.length ? `来源－${row.removed_sources.join('、')}` : '来源未变'}</div><div className="mt-1 truncate text-muted">{current ? `${row.freshness === '当日事件' ? '当日事件 · ' : ''}${current.source_ids.length}类源 · ${row.pct_chg == null ? '—' : `${row.pct_chg >= 0 ? '+' : ''}${row.pct_chg.toFixed(2)}%`} · 距MA20 ${row.price_context?.ma20_distance_pct == null ? '—' : `${row.price_context.ma20_distance_pct.toFixed(1)}%`}${mode === 'low' ? ` · 近10日 ${row.price_context?.return10_pct == null ? '—' : `${row.price_context.return10_pct.toFixed(1)}%`}` : ''}${row.research_count ? ` · 定向材料${row.research_count}` : ''}` : '已不在此范围；点击 K 线核对'}</div></div>
              {current ? <select aria-label={`${row.name} 跟踪状态`} value={personal[row.symbol] ?? 'unseen'} onChange={event => onPersonal(row.symbol, event.target.value as 'unseen' | 'priority' | 'pending' | 'seen' | 'ignored')} className="min-w-0 rounded border border-border bg-surface px-1 py-1 text-[9px]">
                <option value="unseen">未处理</option><option value="priority">重点跟踪</option><option value="pending">待确认</option><option value="seen">已看</option><option value="ignored">暂不关注</option>
              </select> : <a href={`/stock-analysis?symbol=${encodeURIComponent(row.symbol)}&name=${encodeURIComponent(row.name)}`} target="_blank" rel="noreferrer" className="text-right text-accent hover:underline">查看K线 ↗</a>}
            </div>
          })}
        </div> : <div className="py-5 text-center text-xs text-muted">当前条件下没有逐股变化；可清除路径或阶段筛选。</div>}
        {!showAllMembers && !selectedFlow && !selectedKind && movementRows.length > 8 && <button onClick={() => setShowAllMembers(true)} className="mt-2 cursor-pointer text-[10px] text-accent">查看全部 {movementRows.length} 只及未变化股票</button>}
      </div>
    </>}
  </section>
}
