import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { amvApi, type AmvDimension } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

function number(value: number | null | undefined, suffix = '', digits = 2) {
  return value == null ? '—' : `${value.toFixed(digits)}${suffix}`
}
function signed(value: number | null | undefined, suffix = '%') {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`
}
function direction(value: number | null | undefined) {
  return value == null || value === 0 ? 'text-foreground' : value > 0 ? 'text-red-400' : 'text-emerald-400'
}

export function AmvPanel({ date, symbols, topic = '', compact = false, dimension = 'concept' }: {
  date: string; symbols: string[]; topic?: string; compact?: boolean; dimension?: AmvDimension
}) {
  const [fullSector, setFullSector] = useState(Boolean(topic))
  const [anchor, setAnchor] = useState(topic)
  const [showMembers, setShowMembers] = useState(false)
  const symbolKey = [...new Set(symbols)].sort().join(',')
  const mapping = useQuery({ queryKey: QK.amvSectors(dimension, date),
    queryFn: () => amvApi.sectors(dimension, date), enabled: Boolean(topic && symbols.length && fullSector),
    staleTime: 5 * 60_000, retry: false })
  const hasMapping = symbols.length === 0 || Boolean(mapping.data?.rows.some(row => row.sector === anchor))
  const enabled = Boolean(date && (fullSector ? anchor && hasMapping : symbolKey))
  const query = useQuery({
    queryKey: QK.amv(date, symbolKey, fullSector ? anchor : '', dimension),
    queryFn: () => amvApi.analyze(date, fullSector ? [] : symbolKey.split(',').filter(Boolean), fullSector ? anchor : '', dimension),
    enabled, staleTime: 5 * 60_000, retry: false,
  })
  const data = query.data
  const latest = data?.latest
  const option = useMemo(() => {
    const rows = data?.series ?? []
    const base = rows[0]
    return {
      animation: false,
      tooltip: { trigger: 'axis', valueFormatter: (value: number | null) => number(value), confine: true },
      legend: { data: ['活跃参考指数', '价格参考指数', '活跃占比'], textStyle: { color: '#a1a1aa', fontSize: 10 }, top: 0 },
      grid: { left: 42, right: 48, top: 40, bottom: 25 },
      xAxis: { type: 'category', data: rows.map(row => row.date.slice(5)), boundaryGap: false,
        axisLabel: { color: '#71717a', fontSize: 10 }, axisLine: { lineStyle: { color: '#303037' } } },
      yAxis: [{ type: 'value', scale: true, axisLabel: { color: '#71717a', fontSize: 10 },
        splitLine: { lineStyle: { color: '#29292e' } } },
        { type: 'value', scale: true, axisLabel: { color: '#fbbf24', fontSize: 10, formatter: '{value}%' }, splitLine: { show: false } }],
      series: [
        { name: '活跃参考指数', type: 'line', showSymbol: false, lineStyle: { width: 2, color: '#a78bfa' }, itemStyle: { color: '#a78bfa' },
          data: rows.map(row => base?.amv_yi ? row.amv_yi / base.amv_yi * 100 : null) },
        { name: '活跃占比', type: 'line', yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: '#fbbf24' }, itemStyle: { color: '#fbbf24' },
          data: rows.map(row => row.active_share_pct) },
        { name: '价格参考指数', type: 'line', showSymbol: false, lineStyle: { width: 1, color: '#94a3b8' }, itemStyle: { color: '#94a3b8' },
          data: rows.map(row => row.price_index) },
      ],
    }
  }, [data])
  return <section data-testid="amv-panel" className="mt-3 rounded-lg border border-violet-400/20 bg-[#111113] p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-baseline gap-2"><strong className="text-xs text-foreground">{fullSector ? `${anchor} · 板块活跃参考` : '1AMV · 筹码活跃参考'}</strong><span className="text-[10px] text-muted">研究估计 · 普通流通股本</span></div>
      {topic && symbols.length > 0 && <div className="flex gap-1 text-[10px]">{([true, false] as const).map(full => <button key={String(full)} aria-pressed={fullSector === full} onClick={() => setFullSector(full)}
        className={`rounded border px-2 py-1 ${fullSector === full ? 'border-violet-400/50 bg-violet-400/10 text-foreground' : 'border-border text-muted hover:text-foreground'}`}>{full ? '完整板块成分' : '题材入池成员'}</button>)}</div>}
    </div>
    {topic && symbols.length > 0 && fullSector && <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted"><span>题材 {topic} · 参考板块</span>
      <select aria-label="题材参考板块" className="max-w-full rounded border border-border bg-base px-2 py-1 text-foreground" value={hasMapping ? anchor : ''} onChange={event => setAnchor(event.target.value)}>
        <option value="" disabled>选择完整参考板块</option>{mapping.data?.rows.map(row => <option key={row.sector} value={row.sector ?? ''}>{row.sector}</option>)}
      </select>
      {mapping.isPending ? <span>正在读取成分映射…</span> : mapping.isError ? <span>{mapping.error.message}<button className="ml-2 text-accent" onClick={() => void mapping.refetch()}>重试</button></span> : !hasMapping && <span>该逻辑题材没有同名完整映射，请选择参考板块，或切回入池成员。</span>}
    </div>}
    {query.isPending && enabled && <p className="mt-3 text-xs text-muted">正在读取行情与历史股本…</p>}
    {query.isError && <div className="mt-3 text-xs text-secondary">{query.error.message}<button onClick={() => void query.refetch()} className="ml-3 text-accent hover:underline">重试</button></div>}
    {data && <>
      <div className="mt-2 text-[10px] text-muted">{data.trade_date} · {fullSector ? '最新板块成分固定回看' : symbols.length === 1 ? '当前个股' : '当前题材入池成员固定回看'} · 可比 {data.covered_members}/{data.requested_members}只
        {data.market_cap_coverage_pct != null ? ` · 市值覆盖 ${number(data.market_cap_coverage_pct, '%', 1)}` : ` · ${data.unknown_capital_members}只成分缺少当日市值，市值覆盖不可计算`}
        {data.unmapped_members > 0 ? ` · ${data.unmapped_members}只成分缺少证券映射` : ''}
        {data.latest?.latest_float_proxy_members ? ` · ${data.latest.latest_float_proxy_members}只当前使用最新股本代理` : ''}
        {data.calendar_basis === 'observed_member_sessions_proxy' ? ' · 日期轴由成员可用日线推定' : ''}</div>
      {!latest ? <p className="mt-3 text-xs text-secondary">{data.diagnosis}</p> : <>
        <p className="mt-2 text-xs text-secondary">{data.diagnosis}</p>
        <div className={`mt-3 grid gap-2 ${compact ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2 md:grid-cols-3 xl:grid-cols-6'}`}>
          {[
            ['活跃市值估计', number(latest.amv_yi, ' 亿'), `较前日 ${signed(latest.amv_change_pct)}`, latest.amv_change_pct],
            ['活跃占比', number(latest.active_share_pct, '%'), `流通市值 ${number(latest.float_mv_yi, ' 亿')}`, latest.active_share_change_5d_pp],
            ['近5日占比变化', signed(latest.active_share_change_5d_pp, ' pp'), `活跃总值 ${signed(latest.amv_change_5d_pct)}`, latest.active_share_change_5d_pp],
            ...(!compact ? [
              ['活跃扩散率', number(latest.expanding_members_5d_pct, '%', 0), `近5日占比上升 ${latest.expanding_members_5d}/${data.covered_members}只`, null],
              ['近5日价格', signed(latest.price_change_5d_pct), '固定可比成员等权涨跌', latest.price_change_5d_pct],
              ['前三活跃集中度', number(latest.top3_amv_share_pct, '%', 1), data.covered_members <= 3 ? '成员不足4只时参考有限' : '前三成员活跃市值占比', null],
            ] : []),
          ].map(([label, value, note, change]) => <div key={String(label)} className="rounded border border-[#29292e] px-2.5 py-2">
            <div className="text-[10px] text-muted">{label}</div><div className={`mt-1 whitespace-nowrap font-mono text-base ${direction(typeof change === 'number' ? change : null)}`}>{value}</div><div className="mt-1 text-[9px] text-muted">{note}</div>
          </div>)}
        </div>
        <ReactECharts option={option} notMerge style={{ height: compact ? 180 : 220 }} />
        <div className="text-[9px] text-muted">左轴：活跃市值与等权价格以 {data.series[0]?.date} 为100；右轴：活跃占比。pp为百分点；活跃增加不等于净流入。
          {latest.percentile_250 != null && ` 自身250日占比分位 ${number(latest.percentile_250, '%', 1)}。`}</div>
        {!compact && <>
          <button className="mt-2 text-[10px] text-accent hover:underline" onClick={() => setShowMembers(value => !value)}>{showMembers ? '收起成员读数' : `查看全部 ${data.members.length}只成员读数`}</button>
          {showMembers && <div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-left text-[10px]"><thead className="sticky top-0 bg-[#111113] text-muted"><tr>{['成员', '活跃市值/亿', '板块贡献', '日增减/亿', '活跃占比', '5日占比变化', '5日价格'].map(label => <th key={label} className="whitespace-nowrap px-2 py-1.5 font-normal">{label}</th>)}</tr></thead>
            <tbody>{data.members.map(row => <tr key={row.symbol} className="border-t border-border"><td className="whitespace-nowrap px-2 py-1.5">{row.name}<span className="ml-1 text-muted">{row.symbol.slice(0, 6)}</span></td><td className="px-2">{number(row.amv_yi)}</td><td className="px-2">{number(row.amv_share_pct, '%')}</td><td className={`whitespace-nowrap px-2 ${direction(row.amv_change_yi)}`}>{signed(row.amv_change_yi, '')}</td><td className="px-2">{number(row.active_share_pct, '%')}</td><td className={`whitespace-nowrap px-2 ${direction(row.active_share_change_5d_pp)}`}>{signed(row.active_share_change_5d_pp, 'pp')}</td><td className={`px-2 ${direction(row.price_change_5d_pct)}`}>{signed(row.price_change_5d_pct)}</td></tr>)}</tbody></table><p className="mt-2 text-muted">板块贡献为该股活跃市值占可比集合总值的比例；日增减包含价格与股本变化，不是净买入金额。</p></div>}
        </>}
      </>}
      {data.excluded.length > 0 && <div className="mt-2 text-[9px] text-muted" title={data.excluded.map(row => `${row.symbol}：${row.reason}`).join('\n')}>未计入 {data.excluded.length}只：缺日、无效输入或连续预热不足；曲线全程保持同一可比集合。</div>}
      <div className="mt-2 border-t border-border pt-2 text-[9px] text-muted">研究优选 H=8、γ=1、KF=1.15；普通流通股本估计，尚未以指南针原件校准。活跃增强需结合价格方向与参与广度。</div>
    </>}
  </section>
}
