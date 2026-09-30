import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { amvApi } from '@/lib/api'
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

export function AmvPanel({ date, symbols, topic = '', compact = false }: {
  date: string; symbols: string[]; topic?: string; compact?: boolean
}) {
  const [fullSector, setFullSector] = useState(false)
  const [showMembers, setShowMembers] = useState(false)
  const symbolKey = [...new Set(symbols)].sort().join(',')
  const query = useQuery({
    queryKey: QK.amv(date, symbolKey, fullSector ? topic : ''),
    queryFn: () => amvApi.analyze(date, symbolKey.split(',').filter(Boolean), fullSector ? topic : ''),
    enabled: Boolean(date && symbolKey), staleTime: 5 * 60_000, retry: false,
  })
  const data = query.data
  const latest = data?.latest
  const option = useMemo(() => {
    const rows = data?.series ?? []
    const base = rows[0]
    return {
      animation: false,
      tooltip: { trigger: 'axis', valueFormatter: (value: number | null) => number(value), confine: true },
      legend: { data: ['活跃市值', '平滑成交额对照', '价格'], textStyle: { color: '#a1a1aa', fontSize: 10 }, top: 0 },
      grid: { left: 42, right: 16, top: 32, bottom: 25 },
      xAxis: { type: 'category', data: rows.map(row => row.date.slice(5)), boundaryGap: false,
        axisLabel: { color: '#71717a', fontSize: 10 }, axisLine: { lineStyle: { color: '#303037' } } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#71717a', fontSize: 10 },
        splitLine: { lineStyle: { color: '#29292e' } } },
      series: [
        { name: '活跃市值', type: 'line', showSymbol: false, lineStyle: { width: 2, color: '#a78bfa' }, itemStyle: { color: '#a78bfa' },
          data: rows.map(row => base?.amv_yi ? row.amv_yi / base.amv_yi * 100 : null) },
        { name: '平滑成交额对照', type: 'line', showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: '#fbbf24' }, itemStyle: { color: '#fbbf24' },
          data: rows.map(row => base?.amount_proxy_yi ? row.amount_proxy_yi / base.amount_proxy_yi * 100 : null) },
        { name: '价格', type: 'line', showSymbol: false, lineStyle: { width: 1, color: '#94a3b8' }, itemStyle: { color: '#94a3b8' },
          data: rows.map(row => row.price_index) },
      ],
    }
  }, [data])
  return <section data-testid="amv-panel" className="mt-3 rounded-lg border border-violet-400/20 bg-[#111113] p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-baseline gap-2"><strong className="text-xs text-foreground">1AMV · 筹码活跃参考</strong><span className="text-[10px] text-muted">研究估计 · 普通流通股本</span></div>
      {topic && <div className="flex gap-1 text-[10px]">{([false, true] as const).map(full => <button key={String(full)} aria-pressed={fullSector === full} onClick={() => setFullSector(full)}
        className={`rounded border px-2 py-1 ${fullSector === full ? 'border-violet-400/50 bg-violet-400/10 text-foreground' : 'border-border text-muted hover:text-foreground'}`}>{full ? '同名概念成分' : '题材入池成员'}</button>)}</div>}
    </div>
    {query.isPending && <p className="mt-3 text-xs text-muted">正在读取行情与历史股本…</p>}
    {query.isError && <div className="mt-3 text-xs text-secondary">{query.error.message}<button onClick={() => void query.refetch()} className="ml-3 text-accent hover:underline">重试</button></div>}
    {data && <>
      <div className="mt-2 text-[10px] text-muted">{topic ? `${topic} · ` : ''}{fullSector ? '最新概念成分固定回看' : symbols.length === 1 ? '当前个股' : '当前题材入池成员固定回看'} · 可比 {data.covered_members}/{data.requested_members}只
        {data.unmapped_members > 0 ? ` · ${data.unmapped_members}只成分缺少证券映射` : ''}
        {data.latest?.latest_float_proxy_members ? ` · ${data.latest.latest_float_proxy_members}只当前使用最新股本代理` : ''}
        {data.calendar_basis === 'observed_member_sessions_proxy' ? ' · 日期轴由成员可用日线推定' : ''}</div>
      {!latest ? <p className="mt-3 text-xs text-secondary">{data.diagnosis}</p> : <>
        <p className="mt-2 text-xs text-secondary">{data.diagnosis}</p>
        <div className={`mt-3 grid gap-2 ${compact ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2 md:grid-cols-3 xl:grid-cols-6'}`}>
          {[
            ['活跃市值估计', number(latest.amv_yi, ' 亿'), `较前日 ${signed(latest.amv_change_pct)}`, latest.amv_change_pct],
            ['活跃占比', number(latest.active_share_pct, '%'), `近5日 ${signed(latest.active_share_change_5d_pp, ' 个百分点')}`, latest.active_share_change_5d_pp],
            ['近5日活跃变化', signed(latest.amv_change_5d_pct), `价格 ${signed(latest.price_change_5d_pct)}`, latest.amv_change_5d_pct],
            ['250日占比分位', number(latest.percentile_250, '%', 1), latest.percentile_250 == null ? '连续成熟样本不足250日' : '只与自身历史比较', null],
            ...(!compact ? [
              ['活跃扩散率', number(latest.expanding_members_5d_pct, '%', 0), `近5日占比上升 ${latest.expanding_members_5d}/${data.covered_members}只`, null],
              ['前三活跃集中度', number(latest.top3_amv_share_pct, '%', 1), data.covered_members <= 3 ? '成员不足4只时参考有限' : '前三成员活跃市值占比', null],
            ] : []),
          ].map(([label, value, note, change]) => <div key={String(label)} className="rounded border border-[#29292e] px-2.5 py-2">
            <div className="text-[10px] text-muted">{label}</div><div className={`mt-1 whitespace-nowrap font-mono text-base ${direction(typeof change === 'number' ? change : null)}`}>{value}</div><div className="mt-1 text-[9px] text-muted">{note}</div>
          </div>)}
        </div>
        <ReactECharts option={option} notMerge style={{ height: compact ? 180 : 220 }} />
        <div className="text-[9px] text-muted">三条线以 {data.series[0]?.date} 为100；价格为固定成员等权参照。活跃增加不等于净流入。</div>
        {!compact && <>
          <button className="mt-2 text-[10px] text-accent hover:underline" onClick={() => setShowMembers(value => !value)}>{showMembers ? '收起成员读数' : `查看全部 ${data.members.length}只成员读数`}</button>
          {showMembers && <div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-left text-[10px]"><thead className="sticky top-0 bg-[#111113] text-muted"><tr>{['成员', '活跃市值/亿', '活跃占比', '5日占比变化', '5日价格'].map(label => <th key={label} className="whitespace-nowrap px-2 py-1.5 font-normal">{label}</th>)}</tr></thead>
            <tbody>{data.members.map(row => <tr key={row.symbol} className="border-t border-border"><td className="whitespace-nowrap px-2 py-1.5">{row.name}<span className="ml-1 text-muted">{row.symbol.slice(0, 6)}</span></td><td className="px-2">{number(row.amv_yi)}</td><td className="px-2">{number(row.active_share_pct, '%')}</td><td className={`whitespace-nowrap px-2 ${direction(row.active_share_change_5d_pp)}`}>{signed(row.active_share_change_5d_pp, 'pp')}</td><td className={`px-2 ${direction(row.price_change_5d_pct)}`}>{signed(row.price_change_5d_pct)}</td></tr>)}</tbody></table></div>}
        </>}
      </>}
      {data.excluded.length > 0 && <div className="mt-2 text-[9px] text-muted" title={data.excluded.map(row => `${row.symbol}：${row.reason}`).join('\n')}>未计入 {data.excluded.length}只：缺日、无效输入或连续预热不足；曲线全程保持同一可比集合。</div>}
      <div className="mt-2 border-t border-border pt-2 text-[9px] text-muted">研究优选 H=8、γ=1、KF=1.15；普通流通股本估计，尚未以指南针原件校准。活跃增强需结合价格方向与参与广度。</div>
    </>}
  </section>
}
