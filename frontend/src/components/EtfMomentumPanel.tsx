import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { api, type EtfMomentumRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

type Metric = 'return_1d_pct' | 'return_5d_pct' | 'return_20d_pct' | 'return_50d_pct' | 'slope_momentum_pct' | 'weighted_momentum_pct' | 'volume_ratio_5_20'
type SortKey = Metric | 'name'
const columns: Array<[Metric, string]> = [['return_1d_pct', '1日'], ['return_5d_pct', '5日'], ['return_20d_pct', '20日'], ['return_50d_pct', '50日'], ['slope_momentum_pct', '斜率动量'], ['weighted_momentum_pct', '加权涨幅'], ['volume_ratio_5_20', '量比5/20']]
const control = 'rounded border border-border bg-base px-2.5 py-1.5 text-xs'
const fmt = (value: number | null | undefined, suffix = '%') => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`

export function EtfMomentumPanel() {
  const [scope, setScope] = useState('')
  const [draft, setDraft] = useState(() => localStorage.getItem('market-lab-etf-symbols') ?? '')
  const [error, setError] = useState('')
  const [custom, setCustom] = useState(false)
  const [sort, setSort] = useState<{ key: SortKey; ascending: boolean } | null>(null)
  const query = useQuery({ queryKey: QK.marketLabEtfScope(scope), queryFn: () => api.marketLabEtfMomentum(60, scope || undefined), staleTime: 300_000 })
  const key = sort?.key ?? 'slope_momentum_pct'
  const ascending = sort?.ascending ?? false
  const rows = useMemo(() => [...(query.data?.rows ?? [])].sort((a, b) => {
    const av = a[key], bv = b[key]
    if (av == null || bv == null) return av == null ? bv == null ? a.symbol.localeCompare(b.symbol) : 1 : -1
    return (ascending ? 1 : -1) * (typeof av === 'string' && typeof bv === 'string' ? av.localeCompare(bv, 'zh-CN') : Number(av) - Number(bv)) || a.symbol.localeCompare(b.symbol)
  }), [query.data, key, ascending])
  const previousRanks = useMemo(() => {
    if (key === 'name') return new Map<string, number>()
    return new Map([...rows].filter(r => r.previous_metrics?.[key] != null).sort((a, b) =>
      (ascending ? 1 : -1) * ((a.previous_metrics[key] ?? 0) - (b.previous_metrics[key] ?? 0)) || a.symbol.localeCompare(b.symbol))
      .map((r, i) => [r.symbol, i + 1]))
  }, [rows, key, ascending])
  const toggle = (next: SortKey) => setSort(current => current?.key !== next ? { key: next, ascending: true } : current.ascending ? { key: next, ascending: false } : null)
  const apply = () => {
    const values = [...new Set(draft.toUpperCase().split(/[\s,，;；]+/).filter(Boolean))]
    if (!values.length || values.length > 200 || values.some(v => !/^\d{6}\.(SH|SZ|BJ)$/.test(v))) { setError('填写带交易所的ETF代码，例如 510300.SH,159915.SZ；最多200只。'); return }
    setError(''); setScope(values.join(',')); localStorage.setItem('market-lab-etf-symbols', values.join(',')); setSort(null)
  }
  const metric = key === 'name' ? 'slope_momentum_pct' : key
  return <div className="space-y-3 text-foreground" data-testid="etf-momentum">
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-semibold text-foreground">ETF 动量排名</h2><div className="flex gap-2"><button className={control} onClick={() => { setScope(''); setSort(null); setCustom(false) }}>成交活跃 ETF</button><button className={control} onClick={() => setCustom(v => !v)}>自选 ETF</button><button className={control} onClick={() => setSort(null)}>默认排名</button></div></div>
      <p className="mt-2 text-xs text-muted">20日对数价格普通回归：年化斜率收益 × R²；加权涨幅为1/5/20/50日的40/30/20/10%。动量用于相对观察。</p>
      <p className="mt-1 text-xs text-muted">截至 {rows[0]?.as_of ?? '—'} · {scope ? '自选名单' : '最新成交额前60只'} · 有效 {rows.length}/{query.data?.requested_count ?? '—'}；昨日排名按今天同一名单及当前排序指标比较。</p>
      {custom && <div className="mt-3 flex flex-wrap gap-2"><input aria-label="自选ETF代码" className={`${control} min-w-0 flex-1`} placeholder="510300.SH,159915.SZ" value={draft} onChange={e => setDraft(e.target.value)} /><button className={control} onClick={apply}>应用名单</button></div>}
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </div>
    {query.isPending && <p className="p-8 text-center text-xs text-muted">正在读取 ETF 日线…</p>}
    {query.isError && <p className="p-4 text-xs text-danger">{query.error.message}<button className="ml-3 text-accent" onClick={() => void query.refetch()}>重试</button></p>}
    {query.data && !query.data.available && <p className="p-8 text-center text-xs text-muted">{query.data.detail}</p>}
    {!!rows.length && <div className="overflow-x-auto rounded-lg border border-border bg-surface p-3"><table className="w-full min-w-[1050px] text-right text-xs"><thead className="text-muted"><tr><th className="py-2 text-left" aria-sort={key === 'name' ? ascending ? 'ascending' : 'descending' : 'none'}><button onClick={() => toggle('name')}>排名／ETF {key === 'name' ? ascending ? '↑' : '↓' : ''}</button></th>{columns.map(([col, label]) => <th key={col} aria-sort={key === col ? ascending ? 'ascending' : 'descending' : 'none'}><button className="px-2 py-2" onClick={() => toggle(col)}>{label} {key === col ? ascending ? '↑' : '↓' : ''}</button></th>)}<th title="所选排序指标的今日数值减昨日数值；名称排序时不显示">动量变化</th><th title="今天这批ETF中的昨日排名减今日排名">排名变化</th></tr></thead><tbody>{rows.map((r: EtfMomentumRow, i) => {
      const old = key === 'name' ? null : r.previous_metrics?.[key]
      const delta = old == null || key === 'name' || r[key] == null ? null : Number(r[key]) - old
      const rankDelta = previousRanks.has(r.symbol) ? previousRanks.get(r.symbol)! - i - 1 : null
      return <tr key={r.symbol} className="border-t border-border/60"><td className="py-3 text-left"><span className="mr-3 font-mono text-muted">{i + 1}</span>{r.name}<span className="ml-2 text-muted">{r.symbol}</span></td>{columns.map(([col]) => { const v = r[col]; return <td key={col} className={`px-2 font-mono ${col === 'volume_ratio_5_20' || v == null || v === 0 ? '' : v > 0 ? 'text-bull bg-red-500/[.04]' : 'text-bear bg-emerald-500/[.04]'}`}>{fmt(v, col === 'volume_ratio_5_20' ? '倍' : '%')}</td> })}<td className={delta == null || delta === 0 ? '' : delta > 0 ? 'text-bull' : 'text-bear'}>{fmt(delta, key === 'volume_ratio_5_20' ? '倍' : 'pp')}</td><td className="font-mono text-secondary">{rankDelta == null ? '—' : `${rankDelta > 0 ? '↑' : rankDelta < 0 ? '↓' : '→'}${Math.abs(rankDelta)}`}</td></tr>
    })}</tbody></table></div>}
    {!!rows.length && <details className="rounded-lg border border-border bg-surface p-3"><summary className="cursor-pointer text-xs text-muted">动量前15名图示</summary><ReactECharts option={{ tooltip: { trigger: 'axis' }, grid: { left: 120, right: 35, top: 20, bottom: 30 }, xAxis: { type: 'value' }, yAxis: { type: 'category', data: rows.slice(0, 15).map(r => r.name).reverse() }, series: [{ type: 'bar', data: rows.slice(0, 15).map(r => ({ value: r[metric], itemStyle: { color: (r[metric] ?? 0) >= 0 ? '#f87171' : '#34d399' } })).reverse() }] }} style={{ height: 360 }} /></details>}
  </div>
}
