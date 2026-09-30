import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { amvApi, type AmvDimension, type AmvSectorRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { AmvPanel } from './AmvPanel'

type Metric = 'active_share_change_5d_pp' | 'active_share_pct' | 'expanding_members_5d_pct' | 'price_change_5d_pct'
type SortKey = Metric | 'sector' | 'covered_members' | 'market_cap_coverage_pct'
const columns: { key: SortKey; label: string; description?: string }[] = [
  { key: 'sector', label: '板块' },
  { key: 'active_share_pct', label: '活跃占比' },
  { key: 'active_share_change_5d_pp', label: '5日占比变化/pp' },
  { key: 'expanding_members_5d_pct', label: '活跃扩散率', description: '近5日活跃占比上升的可比成员比例' },
  { key: 'price_change_5d_pct', label: '5日价格' },
  { key: 'covered_members', label: '可比成员', description: '按可比成员数量排序' },
  { key: 'market_cap_coverage_pct', label: '市值覆盖' },
]
const sortValue = (row: AmvSectorRow, key: SortKey) =>
  key === 'sector' || key === 'covered_members' || key === 'market_cap_coverage_pct' ? row[key] : row.latest?.[key]
const fmt = (value: number | null | undefined, suffix = '', signed = false) => value == null
  ? '—' : `${signed && value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`
const color = (value: number | null | undefined) => value == null || value === 0
  ? 'text-foreground' : value > 0 ? 'text-red-400' : 'text-emerald-400'
const control = 'rounded border border-border bg-base px-2.5 py-2 text-xs text-foreground'

export function SectorActivityPanel() {
  const [dimension, setDimension] = useState<AmvDimension>('concept')
  const [date, setDate] = useState<string>()
  const [sort, setSort] = useState<{ key: SortKey; direction: 'ascending' | 'descending' } | null>(null)
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
    const key = sort?.key ?? 'active_share_change_5d_pp'
    const av = sortValue(a, key), bv = sortValue(b, key)
    if (av == null || bv == null) return av == null ? (bv == null ? (a.sector ?? '').localeCompare(b.sector ?? '') : 1) : -1
    const comparison = typeof av === 'string' && typeof bv === 'string' ? av.localeCompare(bv, 'zh-CN') : Number(av) - Number(bv)
    return ((sort?.direction === 'ascending' ? 1 : -1) * comparison) || (a.sector ?? '').localeCompare(b.sector ?? '')
  }), [data, filter, sort, search])
  const toggleSort = (key: SortKey) => setSort(current => current?.key !== key
    ? { key, direction: 'ascending' } : current.direction === 'ascending' ? { key, direction: 'descending' } : null)
  const selected = ordered.find(row => row.sector === selection) ?? ordered[0]
  const expanding = data?.rows.filter(row => (row.latest?.active_share_change_5d_pp ?? 0) > 0).length ?? 0
  const covered = data?.rows.filter(row => row.latest).length ?? 0

  return <div className="space-y-4" data-testid="sector-activity">
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="text-xs text-muted">可计算 {covered}/{data?.rows.length ?? 0} 个板块 · 近5日扩张 {expanding} 个</div>
        <div className="flex flex-wrap gap-2">
          <select aria-label="活跃板块分类" className={control} value={dimension} onChange={event => { setDimension(event.target.value as AmvDimension); setSelection(null) }}>
            <option value="concept">THS概念题材</option><option value="industry_level1">THS一级行业</option><option value="industry_level2">THS二级行业</option>
          </select>
          <input aria-label="活跃参与日期" className={control} type="date" value={date ?? data?.trade_date ?? ''} onChange={event => { setDate(event.target.value || undefined); setSelection(null) }} />
          <button className={control} onClick={() => { if (date) setDate(undefined); else void query.refetch() }}>最新</button>
          <input aria-label="搜索活跃板块" className={control} placeholder="搜索板块" value={search} onChange={event => setSearch(event.target.value)} />
          <select aria-label="活跃变化范围" className={control} value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="all">全部</option><option value="expanding">占比扩张</option><option value="contracting">占比收缩</option></select>
        </div>
      </div>
      {query.isPending && <p className="py-8 text-center text-xs text-muted">正在批量计算个股与板块活跃参与，首次读取需要稍候…</p>}
      {query.isError && <div className="py-6 text-xs text-secondary">{query.error.message}<button className="ml-3 text-accent" onClick={() => void query.refetch()}>重试</button></div>}
      {data && <>
        <div className="mt-3 max-h-[420px] overflow-auto" data-testid="sector-activity-table">
          <table className="w-full min-w-[740px] text-right text-xs">
            <thead className="sticky top-0 z-10 bg-surface text-muted"><tr>{columns.map(({ key, label, description }, i) => <th className={`whitespace-nowrap px-3 py-2 font-normal ${i === 0 ? 'text-left' : ''}`} key={key}
              aria-sort={(sort?.key ?? 'active_share_change_5d_pp') === key ? (sort?.direction ?? 'descending') : 'none'}>
              <button type="button" className={`inline-flex items-center gap-1 hover:text-foreground ${sort?.key === key ? 'text-foreground' : ''}`} onClick={() => toggleSort(key)}
                title={`${description ? `${description}；` : ''}点击：升序 → 降序 → 恢复默认（5日占比变化降序）`}>
                {label}<span className={sort?.key === key ? 'text-accent' : 'text-muted/50'} aria-hidden="true">{sort?.key === key ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span>
              </button>
            </th>)}</tr></thead>
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
        {dimension === 'concept' && <p className="mt-3 text-[10px] text-muted">概念成分可重叠，不可累加为全市场值。</p>}
      </>}
    </div>
    {selected?.sector && data?.trade_date && <AmvPanel key={`${dimension}:${data.trade_date}:${selected.sector}`} date={data.trade_date} symbols={[]} topic={selected.sector} dimension={dimension} />}
    <details className="rounded-lg border border-border bg-surface p-4 text-xs">
      <summary className="cursor-pointer font-medium">如何结合资金与选股池使用</summary>
      <div className="mt-3 space-y-2 leading-relaxed text-secondary">
        <p>先按5日占比变化找扩张板块，再看扩散率：多只成员同步增强，比只由少数大市值成员推动更广泛。前三活跃集中度用于辨认龙头集中。</p>
        <p>价格上涨且占比扩张，可作为参与增强的研究线索；价格下跌且占比扩张，可能是分歧换手和抛压；价格上涨而占比收缩，需关注参与衰减。</p>
        <p>THS板块压力与这里共用完整成分；OHLCV压力代理和活跃市值均不代表净买入。外部资金观察保留来源自带分类，不与THS板块合并。</p>
        <p>股票池题材详情固定显示这里的完整概念板块参考，计算范围独立于入池名单。合并逻辑题材可选择对应概念板块。用于复盘与跟踪；当前不参与入池过滤或评分。</p>
      </div>
    </details>
  </div>
}
