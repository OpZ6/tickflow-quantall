import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { useChartTheme } from '@/lib/theme'

const control = 'rounded border border-border bg-base px-2.5 py-1.5 text-xs'
const card = 'rounded-lg border border-border bg-surface p-4 text-foreground'
const fmt = (v: number | null | undefined, suffix = '') => v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}${suffix}`
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)

export function SectorResearchPanel({ view }: { view: 'phase' | 'outcomes' }) {
  const theme = useChartTheme()
  const [dimension, setDimension] = useState('industry_level1')
  const [asOf, setAsOf] = useState<string>()
  const [horizon, setHorizon] = useState(5)
  const [search, setSearch] = useState('')
  const [allLabels, setAllLabels] = useState(false)
  const [sort, setSort] = useState<{ key: string; ascending: boolean } | null>(null)
  const query = useQuery({ queryKey: QK.marketLabResearch(dimension, horizon, asOf), queryFn: () => api.marketLabSectorResearch(dimension, horizon, asOf), staleTime: 300_000, retry: false })
  const data = query.data
  const points = (data?.phase ?? []).filter(p => p.x != null && p.y != null)
  const selected = points.filter(p => !search || p.sector.includes(search))
  const outcomeRows = useMemo(() => (data?.outcomes?.sectors ?? []).filter(r => !search || r.sector.includes(search)).sort((a, b) => {
    const key = (sort?.key ?? 'breadth_change_5d_pp') as keyof typeof a
    const av = a[key], bv = b[key]
    if (av == null || bv == null) return av == null ? bv == null ? a.sector.localeCompare(b.sector) : 1 : -1
    return (sort?.ascending ? 1 : -1) * (typeof av === 'string' && typeof bv === 'string' ? av.localeCompare(bv, 'zh-CN') : Number(av) - Number(bv)) || a.sector.localeCompare(b.sector)
  }), [data, search, sort])
  const toggle = (key: string) => setSort(old => old?.key !== key ? { key, ascending: true } : old.ascending ? { key, ascending: false } : null)
  const phaseOption = {
    animation: false, backgroundColor: 'transparent', tooltip: { trigger: 'item', formatter: (p: { data?: { sector?: string } }) => {
      const row = points.find(r => r.sector === p.data?.sector)
      return row ? `${esc(row.sector)}<br/>5日成交压力 ${fmt(row.x, '%')}<br/>宽度变化 ${fmt(row.y, 'pp')}<br/>当前MA20宽度 ${fmt(row.breadth_pct, '%')}<br/>有效宽度成员 ${row.breadth_members}/${row.member_count}<br/>压力成员 ${row.pressure_members}/${row.member_count}<br/>点击行业筛选` : ''
    } }, grid: { left: 70, right: 45, top: 45, bottom: 60 },
    xAxis: { type: 'value', name: '5日成交压力／%', nameLocation: 'middle', nameGap: 35, axisLabel: { color: theme.text }, splitLine: { lineStyle: { color: theme.grid } } },
    yAxis: { type: 'value', name: 'MA20宽度5日变化／pp', axisLabel: { color: theme.text }, splitLine: { lineStyle: { color: theme.grid } } },
    series: [{ type: 'lines', coordinateSystem: 'cartesian2d', symbol: ['none', 'arrow'], symbolSize: 6, lineStyle: { color: '#94a3b8', opacity: .3 }, data: selected.filter(p => p.previous_x != null && p.previous_y != null).map(p => ({ coords: [[p.previous_x, p.previous_y], [p.x, p.y]], sector: p.sector })), silent: true },
      { type: 'scatter', labelLayout: { hideOverlap: true }, symbolSize: (v: number[]) => Math.min(36, 8 + Math.sqrt(Math.max(v[2], 0))), data: selected.map(p => ({ value: [p.x, p.y, p.amount_yi], sector: p.sector, itemStyle: { color: p.x! >= 0 && p.y! >= 0 ? '#f87171' : p.x! < 0 && p.y! < 0 ? '#34d399' : '#fbbf24' } })), label: { show: allLabels || !!search || dimension === 'industry_level1', color: theme.text, position: 'top', formatter: (p: { data: { sector: string } }) => p.data.sector, fontSize: 10 }, markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: '#64748b', type: 'dashed' }, data: [{ xAxis: 0 }, { yAxis: 0 }] } }],
  }
  const cells = data?.outcomes?.cells ?? []
  const bound = Math.max(.1, ...cells.map(c => Math.abs(c.mean_excess_pct ?? 0)))
  const heatOption = { animation: false, tooltip: { formatter: (p: { data: { value: number[]; sample: number; dates: number } }) => `MA20宽度 ${p.data.value[0] * 20}—${(p.data.value[0] + 1) * 20}%<br/>${p.data.value[1] ? '扩散／持平' : '收缩'}<br/>日期等权相对收益 ${fmt(p.data.value[2], '%')}<br/>${p.data.sample}次 · ${p.data.dates}个日期` },
    grid: { left: 90, right: 25, top: 25, bottom: 70 }, xAxis: { type: 'category', data: ['0—20%', '20—40%', '40—60%', '60—80%', '80—100%'], axisLabel: { color: theme.text }, name: '观察日MA20宽度' }, yAxis: { type: 'category', data: ['5日收缩', '5日扩散／持平'], axisLabel: { color: theme.text } },
    visualMap: { min: -bound, max: bound, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#166534', '#28282e', '#991b1b'] }, textStyle: { color: theme.text } },
    series: [{ type: 'heatmap', data: cells.filter(c => c.mean_excess_pct != null).map(c => ({ value: [c.band, Number(c.expanding), c.mean_excess_pct], sample: c.sample_count, dates: c.date_count })), label: { show: true, color: '#fafafa', fontSize: 10, formatter: (p: { data: { value: number[]; dates: number } }) => `${fmt(p.data.value[2], '%')}\n${p.data.dates}日` } }],
  }
  return <div className="space-y-3" data-testid={`sector-${view}`}><div className={card}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-semibold text-foreground">{view === 'phase' ? '行业资金—宽度联合相图' : '行业后续收益验证'}</h2><div className="flex flex-wrap gap-2"><select aria-label="行业研究层级" className={control} value={dimension} onChange={e => setDimension(e.target.value)}><option value="industry_level1">THS一级行业</option><option value="industry_level2">THS二级行业</option></select><input aria-label="行业研究日期" className={control} type="date" value={asOf ?? data?.trade_date ?? ''} onChange={e => setAsOf(e.target.value || undefined)} /><button className={control} onClick={() => { setAsOf(undefined); void query.refetch() }}>最新</button>{view === 'outcomes' && <select aria-label="行业后续周期" className={control} value={horizon} onChange={e => setHorizon(Number(e.target.value))}>{[1, 3, 5, 10].map(n => <option key={n} value={n}>{n}日后</option>)}</select>}</div></div>
    <p className="mt-2 text-xs text-muted">{data?.detail ?? 'THS完整行业成员；当前成分快照回看。'}</p>
    <div className="mt-3 flex flex-wrap items-center gap-3"><input aria-label="搜索研究行业" className={control} placeholder="搜索行业" value={search} onChange={e => setSearch(e.target.value)} />{search && <button className="text-xs text-accent" onClick={() => setSearch('')}>清除筛选</button>}{view === 'phase' && <label className="text-xs text-muted"><input type="checkbox" checked={allLabels} onChange={e => setAllLabels(e.target.checked)} /> 全部标签</label>}</div>
  </div>
    {query.isPending && <p className="p-8 text-center text-xs text-muted">正在批量读取本地日线并计算，首次加载需要稍候…</p>}
    {query.isError && <p className="p-4 text-xs text-danger">{query.error.message}<button className="ml-3 text-accent" onClick={() => void query.refetch()}>重试</button></p>}
    {data && !data.available && <p className="p-6 text-xs text-muted">{data.detail}</p>}
    {data?.available && (view === 'phase' ? <><div className={card}><p className="text-xs text-muted">横轴为收盘位置×成交额形成的5日压力比例；纵轴为宽度5日变化；气泡为今日成交额；箭头为昨日→今日。</p><ReactECharts option={phaseOption} style={{ height: 470 }} onEvents={{ click: (p: { data?: { sector?: string } }) => { if (p.data?.sector) setSearch(p.data.sector) } }} /><div className="flex flex-wrap gap-4 text-xs text-muted"><span>右上：压力与扩散同向</span><span>右下：压力集中／宽度收缩</span><span>左上：结构分歧</span><span>左下：压力与收缩同向</span></div></div><div className={`${card} overflow-x-auto`}><table className="w-full min-w-[640px] text-right text-xs"><thead className="text-muted"><tr><th className="text-left">行业</th><th>5日压力</th><th>宽度变化</th><th>当前宽度</th><th>宽度有效成员</th><th>压力有效成员</th><th>成交额／亿</th></tr></thead><tbody>{data.phase.filter(r => !search || r.sector.includes(search)).map(r => <tr key={r.sector} className="border-t border-border"><td className="py-2 text-left">{r.sector}</td><td>{fmt(r.x, '%')}</td><td>{fmt(r.y, 'pp')}</td><td>{fmt(r.breadth_pct, '%')}</td><td>{r.breadth_members}/{r.member_count}</td><td>{r.pressure_members}/{r.member_count}</td><td>{r.amount_yi.toFixed(1)}</td></tr>)}</tbody></table></div></> : <>
      <div className={card}><p className="text-xs text-muted">{data.outcomes?.first_date ?? '—'} 至 {data.outcomes?.last_date ?? '—'} · 已成熟 {data.outcomes?.matured_count} 次行业观察 · 待到期 {data.outcomes?.pending_count} · 缺行情 {data.outcomes?.missing_count}。相对收益比较同期全市场等权序列；区间按实际交易日，先同日平均再日期等权。</p><ReactECharts option={heatOption} style={{ height: 290 }} /><p className="mt-2 text-xs text-muted">当前成分回看结果；同日行业及相邻日期的结果有关联，样本数不等于独立试验次数。</p></div>
      <div className={`${card} overflow-x-auto`}><h3 className="mb-3 text-sm font-medium text-foreground">各行业当前状态对应的历史结果</h3><table className="w-full min-w-[820px] text-right text-xs"><thead className="text-muted"><tr>{[['sector', '行业'], ['breadth_pct', '当前宽度'], ['breadth_change_5d_pp', '5日变化'], ['sample_count', '样本／日期'], ['mean_excess_pct', '相对收益均值'], ['median_return_pct', '收益中位'], ['outperform_pct', '跑赢市场比例']].map(([key, label]) => <th key={key} className="py-2 first:text-left" aria-sort={sort?.key === key ? sort.ascending ? 'ascending' : 'descending' : 'none'}><button onClick={() => toggle(key)}>{label}{sort?.key === key ? sort.ascending ? ' ↑' : ' ↓' : ''}</button></th>)}</tr></thead><tbody>{outcomeRows.map(r => <tr key={r.sector} className="border-t border-border"><td className="py-2 text-left">{r.sector}</td><td>{fmt(r.breadth_pct, '%')}</td><td>{fmt(r.breadth_change_5d_pp, 'pp')}</td><td>{r.sample_count}／{r.date_count}</td><td className={(r.mean_excess_pct ?? 0) >= 0 ? 'text-bull' : 'text-bear'}>{fmt(r.mean_excess_pct, '%')}</td><td>{fmt(r.median_return_pct, '%')}</td><td>{fmt(r.outperform_pct, '%')}</td></tr>)}</tbody></table></div>
    </>)}
  </div>
}

export function ConceptOverlapPanel() {
  const theme = useChartTheme()
  const [sector, setSector] = useState('')
  const [pair, setPair] = useState('')
  const query = useQuery({ queryKey: QK.marketLabOverlap(sector), queryFn: () => api.marketLabConceptOverlap(sector || undefined), staleTime: 300_000, retry: false })
  const data = query.data
  const selected = data?.rows.find(r => r.sector === pair)
  const option = { backgroundColor: 'transparent', tooltip: { formatter: (p: { dataType: string; data: { name?: string; common_count?: number; jaccard_pct?: number } }) => p.dataType === 'edge' ? `共同成员 ${p.data.common_count}只<br/>Jaccard ${fmt(p.data.jaccard_pct, '%')}<br/>点击查看共同股票` : esc(p.data.name ?? '') }, series: [{ type: 'graph', layout: 'force', roam: true, force: { repulsion: 450, edgeLength: [100, 190] }, label: { show: true, color: theme.textStrong, position: 'right', backgroundColor: theme.tooltipBg, padding: [2, 3], borderRadius: 3, fontSize: 11 }, lineStyle: { color: '#64748b', opacity: .45 }, data: data ? [{ name: data.sector, symbolSize: 48, itemStyle: { color: '#818cf8' } }, ...data.rows.map(r => ({ name: r.sector, symbolSize: 20 + Math.sqrt(r.common_count), itemStyle: { color: '#60a5fa' } }))] : [], links: data?.edges.map(e => ({ ...e, lineStyle: { width: 1 + e.jaccard_pct / 20, color: e.source === data.sector ? '#818cf8' : '#475569' } })) ?? [] }] }
  return <div className="space-y-3" data-testid="concept-overlap"><div className={card}><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-semibold text-foreground">题材成员重叠网络</h2><select aria-label="重叠网络概念" className={`${control} max-w-full`} value={data?.sector ?? sector} onChange={e => { setSector(e.target.value); setPair('') }}>{data?.concepts.map(s => <option key={s} value={s}>{s}</option>)}</select></div><p className="mt-2 text-xs text-muted">{data?.detail} · {data?.member_count ?? '—'}只完整成员 · 显示重叠最高10个概念／共{data?.related_count ?? '—'}个关联。连线宽度表示Jaccard；图中位置不表示产业关系。</p></div>
    {query.isPending && <p className="p-8 text-center text-xs text-muted">正在计算完整成分交集…</p>}{query.isError && <p className="text-xs text-danger">{query.error.message}<button onClick={() => void query.refetch()} className="ml-3 text-accent">重试</button></p>}
    {data && !data.available && <p className="p-6 text-xs text-muted">暂无完整概念成员</p>}
    {data?.available && <><div className={card}><ReactECharts option={option} style={{ height: 430 }} onEvents={{ click: (p: { dataType: string; data?: { name?: string; source?: string; target?: string } }) => {
      if (p.dataType === 'node' && p.data?.name && p.data.name !== data.sector) { setSector(p.data.name); setPair('') }
      if (p.dataType === 'edge') { const other = p.data?.source === data.sector ? p.data.target : p.data?.target === data.sector ? p.data.source : null; if (other) setPair(other) }
    } }} /></div><div className={`${card} overflow-x-auto`}><table className="w-full min-w-[660px] text-right text-xs"><thead className="text-muted"><tr><th className="text-left">关联概念</th><th>共同成员</th><th>Jaccard</th><th>本概念被覆盖</th><th>对方被覆盖</th><th>对方成员</th></tr></thead><tbody>{data.rows.map(r => <tr key={r.sector} className={`border-t border-border ${pair === r.sector ? 'bg-accent/10' : ''}`}><td className="py-2 text-left"><button className="text-accent" onClick={() => setPair(r.sector)}>{r.sector}</button></td><td>{r.common_count}</td><td>{r.jaccard_pct.toFixed(2)}%</td><td>{r.coverage_pct.toFixed(2)}%</td><td>{r.other_coverage_pct.toFixed(2)}%</td><td>{r.member_count}</td></tr>)}</tbody></table></div>{selected && <div className={card}><h3 className="mb-3 text-sm font-medium text-foreground">{data.sector} ∩ {selected.sector} · {selected.common_count}只共同成员</h3><div className="flex flex-wrap gap-2">{selected.common_members.map(member => <span key={member.code} className="rounded border border-border px-2 py-1 text-xs">{member.name} <span className="font-mono text-muted">{member.code}</span></span>)}</div></div>}</>}
  </div>
}
