import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { amvApi, type AmvDimension } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { AmvPanel } from './AmvPanel'

type Metric = 'active_share_change_5d_pp' | 'active_share_pct' | 'expanding_members_5d_pct'
const fmt = (value: number | null | undefined, suffix = '', signed = false) => value == null
  ? '—' : `${signed && value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`
const color = (value: number | null | undefined) => value == null || value === 0
  ? 'text-foreground' : value > 0 ? 'text-red-400' : 'text-emerald-400'
const control = 'rounded border border-border bg-base px-2.5 py-2 text-xs text-foreground'

export function SectorActivityPanel() {
  const [dimension, setDimension] = useState<AmvDimension>('concept')
  const [date, setDate] = useState<string>()
  const [metric, setMetric] = useState<Metric>('active_share_change_5d_pp')
  const [descending, setDescending] = useState(true)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'expanding' | 'contracting'>('all')
  const [selection, setSelection] = useState<string | null>(null)
  const query = useQuery({ queryKey: QK.amvSectors(dimension, date),
    queryFn: () => amvApi.sectors(dimension, date), staleTime: 5 * 60_000, retry: false })
  const data = query.data
  const ordered = useMemo(() => (data?.rows ?? []).filter(row => {
    if (!row.sector?.toLowerCase().includes(search.trim().toLowerCase())) return false
    const delta = row.latest?.active_share_change_5d_pp
    return filter === 'all' || (delta != null && (filter === 'expanding' ? delta > 0 : delta < 0))
  }).sort((a, b) => {
    const av = a.latest?.[metric], bv = b.latest?.[metric]
    if (av == null || bv == null) return av == null ? (bv == null ? (a.sector ?? '').localeCompare(b.sector ?? '') : 1) : -1
    return (descending ? bv - av : av - bv) || (a.sector ?? '').localeCompare(b.sector ?? '')
  }), [data, filter, metric, search, descending])
  const selected = ordered.find(row => row.sector === selection) ?? ordered[0]
  const expanding = data?.rows.filter(row => (row.latest?.active_share_change_5d_pp ?? 0) > 0).length ?? 0
  const covered = data?.rows.filter(row => row.latest).length ?? 0

  return <div className="space-y-4" data-testid="sector-activity">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h2 className="text-base font-semibold text-foreground">板块活跃参与</h2><p className="mt-1 text-xs text-muted">观察参与扩张、收缩与集中程度；活跃占比上升需结合价格方向判断。</p></div>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="活跃板块分类" className={control} value={dimension} onChange={event => { setDimension(event.target.value as AmvDimension); setSelection(null) }}>
          <option value="concept">概念题材</option><option value="industry_level1">一级行业</option><option value="industry_level2">二级行业</option>
        </select>
        <input aria-label="活跃参与日期" className={control} type="date" value={date ?? data?.trade_date ?? ''} onChange={event => { setDate(event.target.value || undefined); setSelection(null) }} />
        <button className={control} onClick={() => { if (date) setDate(undefined); else void query.refetch() }}>最新</button>
      </div>
    </div>
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="text-xs text-muted">{data?.trade_date ?? '读取本地日线'} · 可计算 {covered}/{data?.rows.length ?? 0} 个板块 · 近5日扩张 {expanding} 个</div>
        <div className="flex flex-wrap gap-2">
          <input aria-label="搜索活跃板块" className={control} placeholder="搜索板块" value={search} onChange={event => setSearch(event.target.value)} />
          <select aria-label="活跃变化范围" className={control} value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="all">全部</option><option value="expanding">占比扩张</option><option value="contracting">占比收缩</option></select>
          <select aria-label="活跃排序指标" className={control} value={metric} onChange={event => setMetric(event.target.value as Metric)}><option value="active_share_change_5d_pp">5日占比变化</option><option value="active_share_pct">活跃占比</option><option value="expanding_members_5d_pct">活跃扩散率</option></select>
          <button className={control} onClick={() => setDescending(value => !value)}>{descending ? '↓ 降序' : '↑ 升序'}</button>
        </div>
      </div>
      {query.isPending && <p className="py-8 text-center text-xs text-muted">正在批量计算个股与板块活跃参与，首次读取需要稍候…</p>}
      {query.isError && <div className="py-6 text-xs text-secondary">{query.error.message}<button className="ml-3 text-accent" onClick={() => void query.refetch()}>重试</button></div>}
      {data && <>
        <div className="mt-3 max-h-[420px] overflow-auto" data-testid="sector-activity-table">
          <table className="w-full min-w-[740px] text-right text-xs">
            <thead className="sticky top-0 z-10 bg-surface text-muted"><tr>{['板块', '活跃占比', '5日占比变化/pp', '活跃扩散率', '5日价格', '可比成员', '市值覆盖'].map((label, i) => <th className={`whitespace-nowrap px-3 py-2 font-normal ${i === 0 ? 'text-left' : ''}`} key={label}>{label}</th>)}</tr></thead>
            <tbody>{ordered.map(row => <tr key={row.sector} className={`border-t border-border/60 ${row.sector === selected?.sector ? 'bg-violet-400/10' : 'hover:bg-elevated'}`}>
              <td className="whitespace-nowrap px-3 py-2 text-left"><button className="text-left hover:text-accent" aria-pressed={row.sector === selected?.sector} onClick={() => setSelection(row.sector)}>{row.sector}</button></td>
              <td className="px-3 font-mono">{fmt(row.latest?.active_share_pct, '%')}</td>
              <td className={`px-3 font-mono ${color(row.latest?.active_share_change_5d_pp)}`}>{fmt(row.latest?.active_share_change_5d_pp, '', true)}</td>
              <td className="px-3 font-mono">{fmt(row.latest?.expanding_members_5d_pct, '%')}</td>
              <td className={`px-3 font-mono ${color(row.latest?.price_change_5d_pct)}`}>{fmt(row.latest?.price_change_5d_pct, '%', true)}</td>
              <td className="whitespace-nowrap px-3 font-mono" title={row.unmapped_members ? `${row.unmapped_members}只成分缺少证券映射` : '近30交易日使用相同成熟成员集合'}>{row.covered_members}/{row.requested_members}</td>
              <td className="px-3 font-mono" title={row.unknown_capital_members ? `${row.unknown_capital_members}只缺少目标日流通市值，不能计算覆盖率` : '可比成员流通市值/全部成员流通市值'}>{fmt(row.market_cap_coverage_pct, '%')}</td>
            </tr>)}</tbody>
          </table>
          {ordered.length === 0 && <p className="py-6 text-center text-xs text-muted">当前范围没有可展示的板块。</p>}
        </div>
        <p className="mt-3 text-[10px] text-muted">扩散率＝近5日活跃占比上升的可比成员比例。红增绿减，颜色表示方向。{data.detail} 概念成分重叠，不可相加作为全市场值。</p>
      </>}
    </div>
    {selected?.sector && data?.trade_date && <AmvPanel key={`${dimension}:${data.trade_date}:${selected.sector}`} date={data.trade_date} symbols={[]} topic={selected.sector} dimension={dimension} />}
    <details className="rounded-lg border border-border bg-surface p-4 text-xs">
      <summary className="cursor-pointer font-medium">如何结合资金与选股池使用</summary>
      <div className="mt-3 space-y-2 leading-relaxed text-secondary">
        <p>先按5日占比变化找扩张板块，再看扩散率：多只成员同步增强，比只由少数大市值成员推动更广泛。前三活跃集中度用于辨认龙头集中。</p>
        <p>价格上涨且占比扩张，可作为参与增强的研究线索；价格下跌且占比扩张，可能是分歧换手和抛压；价格上涨而占比收缩，需关注参与衰减。</p>
        <p>结合资金页签时先确认日期、分类与成分一致。行业资金为来源净额，概念资金为OHLCV压力代理；活跃市值不代表净买入，不能仅凭同名板块合并口径。</p>
        <p>股票池题材详情默认显示这里的完整板块参考，也可切换入池成员对比。用于复盘与跟踪；当前不参与入池过滤或评分。</p>
      </div>
    </details>
  </div>
}
