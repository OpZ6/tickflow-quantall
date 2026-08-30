import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { Activity, Calculator, FlaskConical, Gauge, Layers3 } from 'lucide-react'

import { api, type MacroContributionRow, type SectorRadarRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { useChartTheme } from '@/lib/theme'

type Tab = 'etf' | 'sector' | 'macro' | 'risk'

const tabs = [
  { key: 'etf' as const, label: 'ETF 动量', icon: Activity },
  { key: 'sector' as const, label: '板块资金', icon: Layers3 },
  { key: 'macro' as const, label: '宏观离散度', icon: Gauge },
  { key: 'risk' as const, label: '仓位与模拟', icon: Calculator },
]
const card = 'rounded-lg border border-border bg-surface p-4'
const input = 'w-full rounded border border-border bg-base px-2.5 py-2 text-sm text-foreground outline-none focus:border-accent'
const button = 'rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50'
const fmt = (value: number | null | undefined, digits = 2) => value == null ? '--' : value.toFixed(digits)
const money = (value: number | null | undefined) => value == null ? '--' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
const billion = (yuan: number) => `${yuan >= 0 ? '+' : ''}${fmt(yuan / 1e8)} 亿`
const compactSector = (name: string) => {
  if (name.length <= 16) return name
  const parts = name.split('-')
  const tail = parts.slice(-2).join('-')
  return tail.length <= 16 ? tail : `${tail.slice(0, 15)}…`
}
const csvCell = (value: unknown) => {
  let text = String(value ?? '')
  if (/^[=+\-@]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

function Empty({ text }: { text: string }) {
  return <div className="grid min-h-64 place-items-center rounded-lg border border-dashed border-border text-sm text-muted">{text}</div>
}

function EtfPanel() {
  const query = useQuery({ queryKey: QK.marketLabEtf, queryFn: () => api.marketLabEtfMomentum(60) })
  const rows = query.data?.rows ?? []
  const option = useMemo(() => ({
    tooltip: { trigger: 'axis' }, grid: { left: 110, right: 30, top: 20, bottom: 35 },
    xAxis: { type: 'value', name: '%' },
    yAxis: { type: 'category', data: rows.slice(0, 15).map(row => row.name).reverse(), axisLabel: { width: 90, overflow: 'truncate' } },
    series: [{ type: 'bar', data: rows.slice(0, 15).map(row => row.weighted_momentum_pct).reverse(), itemStyle: { color: '#8b5cf6' } }],
  }), [rows])
  if (query.isLoading) return <Empty text="正在计算 ETF 动量…" />
  if (!query.data?.available) return <Empty text={query.data?.detail ?? '暂无 ETF 数据'} />
  return <div className="space-y-4">
    <div className={card}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="text-base font-semibold">主流 ETF 动量排名</h2><p className="text-xs text-muted">{query.data.formula}；斜率动量为 20 日对数回归年化收益 × R²</p></div>
        <span className="rounded bg-accent/10 px-2 py-1 text-xs text-accent">截至 {rows[0]?.as_of}</span>
      </div>
      <ReactECharts option={option} style={{ height: 360 }} />
    </div>
    <div className={`${card} overflow-x-auto`}>
      <table className="w-full min-w-[980px] text-right text-xs">
        <thead className="text-muted"><tr><th className="py-2 text-left">排名 / 标的</th><th>1日</th><th>5日</th><th>20日</th><th>50日</th><th>加权动量</th><th>斜率动量</th><th>量比5/20</th><th>较前日</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.symbol} className="border-t border-border/60">
          <td className="py-2 text-left"><b className="mr-2 text-accent">{row.rank}</b>{row.name}<span className="ml-2 text-muted">{row.symbol}</span></td>
          {[row.return_1d_pct, row.return_5d_pct, row.return_20d_pct, row.return_50d_pct, row.weighted_momentum_pct, row.slope_momentum_pct].map((v, i) => <td key={i} className={(v ?? 0) >= 0 ? 'text-bull' : 'text-bear'}>{fmt(v)}%</td>)}
          <td>{fmt(row.volume_ratio_5_20)}</td><td>{row.rank_change == null ? '--' : `${row.rank_change > 0 ? '↑' : row.rank_change < 0 ? '↓' : '→'} ${Math.abs(row.rank_change)}`}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </div>
}

type RadarMetric = 'swing' | 'ratio' | 'amount' | 'change'
type RankWindow = 1 | 3 | 5

const radarValue = (row: SectorRadarRow, metric: RadarMetric, rankWindow: RankWindow) => {
  if (metric === 'swing') return row.swing_ratio_pct
  if (metric === 'ratio') return row.flow_ratio_pct
  if (metric === 'amount') return row.flow_yuan / 1e8
  return row[`swing_rank_change_${rankWindow}d`]
}
const radarRank = (row: SectorRadarRow, metric: RadarMetric) => metric === 'ratio' ? row.ratio_rank : metric === 'amount' ? row.amount_rank : row.swing_rank
const radarRankPct = (row: SectorRadarRow, metric: RadarMetric) => metric === 'ratio' ? row.ratio_rank_pct : metric === 'amount' ? row.amount_rank_pct : row.swing_rank_pct
const radarDays = (row: SectorRadarRow, metric: RadarMetric, high: boolean) => {
  const prefix = metric === 'ratio' ? 'ratio' : metric === 'amount' ? 'amount' : 'swing'
  return row[`${prefix}_${high ? 'top' : 'bottom'}_30d`]
}

function SectorPanel() {
  const ct = useChartTheme()
  const [dimension, setDimension] = useState<'industry' | 'concept'>('industry')
  const [metric, setMetric] = useState<RadarMetric>('swing')
  const [rankWindow, setRankWindow] = useState<RankWindow>(1)
  const [asOf, setAsOf] = useState<string>()
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [memberMetric, setMemberMetric] = useState<'return_pct' | 'main_net_amount' | 'active_buy_net_amount'>('return_pct')
  const radar = useQuery({ queryKey: QK.marketLabRadar(dimension, asOf), queryFn: () => api.marketLabSectorRadar(dimension, asOf) })
  const flow = useQuery({ queryKey: QK.marketLabSector(dimension), queryFn: () => api.marketLabSectorFlow(dimension) })
  const members = useQuery({
    queryKey: QK.marketLabMembers(dimension, selectedSector ?? '', asOf),
    queryFn: () => api.marketLabSectorMembers(selectedSector!, dimension, asOf),
    enabled: Boolean(selectedSector),
  })
  const rows = radar.data?.rows ?? []
  const flowRows = flow.data?.rows ?? []
  useEffect(() => {
    if (!asOf && radar.data?.as_of) setAsOf(radar.data.as_of)
  }, [asOf, radar.data?.as_of])
  useEffect(() => {
    if (!rows.length) return
    const radarHasSelection = rows.some(row => row.sector === selectedSector)
    const flowHasSelection = flowRows.some(row => row.sector === selectedSector)
    if (!radarHasSelection || (flowRows.length > 0 && !flowHasSelection)) {
      const shared = rows.find(row => flowRows.some(flowRow => flowRow.sector === row.sector))
      setSelectedSector(shared?.sector ?? rows[0].sector)
    }
  }, [flowRows, rows, selectedSector])

  const ordered = useMemo(() => rows.filter(row => row.sector.toLowerCase().includes(search.trim().toLowerCase())).sort((a, b) => radarValue(b, metric, rankWindow) - radarValue(a, metric, rankWindow)), [metric, rankWindow, rows, search])
  const rankChangeCount = Math.max(1, Math.ceil(ordered.length * 0.1))
  const attackers = metric === 'change' ? ordered.slice(0, rankChangeCount) : ordered.filter(row => radarRankPct(row, metric) >= 90)
  const retreaters = metric === 'change' ? ordered.slice(-rankChangeCount).reverse() : ordered.filter(row => radarRankPct(row, metric) <= 10).reverse()
  const maxAbs = Math.max(1e-9, ...attackers.concat(retreaters).map(row => Math.abs(radarValue(row, metric, rankWindow))))
  const selectedFlow = flowRows.find(row => row.sector === selectedSector)
  const metricLabel = metric === 'swing' ? '波段流入率' : metric === 'ratio' ? '单日流入率' : metric === 'amount' ? '单日净额' : `${rankWindow}日排名变化`
  const metricText = (row: SectorRadarRow) => metric === 'amount'
    ? billion(row.flow_yuan)
    : metric === 'change'
      ? `${radarValue(row, metric, rankWindow) >= 0 ? '↑' : '↓'} ${Math.abs(radarValue(row, metric, rankWindow))}`
      : `${radarValue(row, metric, rankWindow) >= 0 ? '+' : ''}${fmt(radarValue(row, metric, rankWindow))}%`
  const trendOption = useMemo(() => ({
    animationDuration: 250,
    tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${fmt(value)} 亿`, backgroundColor: ct.tooltipBg, borderColor: ct.tooltipBorder, textStyle: { color: ct.tooltipText } },
    grid: { left: 58, right: 18, top: 18, bottom: 36 },
    xAxis: { type: 'category', data: selectedFlow?.points.map(point => point.date.slice(5)) ?? [], axisLabel: { color: ct.text }, axisLine: { lineStyle: { color: ct.border } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '亿元', nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } },
    series: [{ type: 'bar', barMaxWidth: 38, data: (selectedFlow?.points ?? []).map(point => ({ value: point.flow_yuan / 1e8, itemStyle: { color: point.flow_yuan >= 0 ? '#F04438' : '#12B76A', borderRadius: 3 } })) }],
  }), [ct, selectedFlow])
  const selectedHistory = selectedSector ? radar.data?.rank_history?.[selectedSector] ?? [] : []
  const calendarOption = useMemo(() => ({
    tooltip: { trigger: 'axis' }, grid: { left: 44, right: 16, top: 18, bottom: 30 },
    xAxis: { type: 'category', data: selectedHistory.map(point => point.date.slice(5)), axisLabel: { color: ct.text, interval: Math.max(0, Math.floor(selectedHistory.length / 8)) }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: { type: 'value', inverse: true, min: 1, max: radar.data?.universe_size, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } },
    series: [{ name: '排名', type: 'line', showSymbol: false, data: selectedHistory.map(point => metric === 'ratio' ? point.ratio_rank : metric === 'amount' ? point.amount_rank : point.swing_rank), lineStyle: { color: '#3B82F6', width: 2 }, areaStyle: { color: 'rgba(59,130,246,.12)' } }],
  }), [ct, metric, radar.data?.universe_size, selectedHistory])
  const memberRows = members.data?.metrics?.[memberMetric]
  const exportMembers = () => {
    if (!memberRows || !selectedSector) return
    const rowsToExport = [...memberRows.top, ...memberRows.bottom]
    const csv = [
      ['方向', '代码', '名称', '数值'].map(csvCell).join(','),
      ...rowsToExport.map((row, index) => [
        index < memberRows.top.length ? 'TOP' : 'BOTTOM', row.symbol, row.name,
        row[memberMetric],
      ].map(csvCell).join(',')),
    ].join('\n')
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' }))
    link.download = `${selectedSector}-${memberMetric}-${asOf ?? 'latest'}.csv`
    link.click()
    URL.revokeObjectURL(link.href)
  }
  const renderSide = (sideRows: SectorRadarRow[], high: boolean) => <div className="min-w-0">
    <div className={`mb-2 flex items-center justify-between text-xs font-semibold ${high ? 'text-bull' : 'text-bear'}`}><span>{high ? '进攻方 · 流入' : '流出 · 撤退方'}</span><span className="text-muted">{high ? 'TOP 10%' : 'BOTTOM 10%'}</span></div>
    <div className="space-y-1.5">{sideRows.map(row => {
      const value = radarValue(row, metric, rankWindow)
      return <button key={row.sector} type="button" onClick={() => setSelectedSector(row.sector)} className={`w-full rounded border px-2.5 py-2 text-left transition-colors ${selectedSector === row.sector ? 'border-accent bg-accent/5' : 'border-border/70 hover:bg-elevated'}`}>
        <div className="flex items-center justify-between gap-2 text-xs"><span className="min-w-0 truncate font-medium" title={row.sector}>{compactSector(row.sector)}</span><span className={`shrink-0 font-mono font-semibold ${high ? 'text-bull' : 'text-bear'}`}>{metricText(row)}</span></div>
        <div className="mt-1.5 flex items-center gap-2"><span className="w-9 shrink-0 font-mono text-[10px] text-muted">#{radarRank(row, metric)}</span><div className={`h-1.5 rounded ${high ? 'ml-auto bg-bull' : 'bg-bear'}`} style={{ width: `${Math.max(5, Math.abs(value) / maxAbs * 70)}%` }} /><span className="ml-auto shrink-0 text-[10px] text-muted">{row.return_pct >= 0 ? '+' : ''}{fmt(row.return_pct)}% · 在榜{radarDays(row, metric, high)}天</span></div>
      </button>
    })}</div>
  </div>

  if (radar.isLoading) return <Empty text="正在计算板块资金雷达…" />
  if (!radar.data?.available) return <Empty text={radar.data?.detail ?? '暂无板块资金数据'} />
  return <div className="space-y-4">
    <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
      <div><h2 className="text-base font-semibold">板块资金雷达</h2><p className="text-xs text-muted">按资金流入强弱识别进攻与撤退板块；评分和排名沿用 OneChart 口径。</p></div>
      <div className="flex flex-wrap items-center gap-2 xl:flex-nowrap">
        <input aria-label="搜索板块" className={input} style={{ width: 170 }} placeholder="搜索板块" value={search} onChange={event => setSearch(event.target.value)} />
        <div className="flex overflow-hidden rounded border border-border">{([['swing', '波段流入率'], ['ratio', '单日流入率'], ['amount', '单日净额'], ['change', '排名变化']] as const).map(([key, label]) => <button key={key} type="button" onClick={() => setMetric(key)} className={`px-3 py-2 text-xs ${metric === key ? 'bg-accent text-white' : 'bg-surface text-secondary hover:bg-elevated'}`}>{label}</button>)}</div>
        {metric === 'change' && <select aria-label="排名变化窗口" className={input} style={{ width: 88 }} value={rankWindow} onChange={event => setRankWindow(Number(event.target.value) as RankWindow)}><option value={1}>1 日</option><option value={3}>3 日</option><option value={5}>5 日</option></select>}
        <select aria-label="板块维度" className={input} style={{ width: 116 }} value={dimension} onChange={event => { setDimension(event.target.value as typeof dimension); setAsOf(undefined) }}><option value="industry">行业板块</option><option value="concept">概念板块</option></select>
        <select aria-label="雷达日期" className={input} style={{ width: 142 }} value={asOf ?? radar.data.as_of} onChange={event => setAsOf(event.target.value)}>{radar.data.available_dates?.slice().reverse().map(value => <option key={value} value={value}>{value}</option>)}</select>
      </div>
    </div>
    <div className={card} data-testid="sector-radar-mirror">
      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border pb-3 text-xs"><span className={`rounded px-2 py-1 ${radar.data.quality === 'observed' ? 'bg-bull/10 text-bull' : 'bg-warning/10 text-warning'}`}>{radar.data.quality === 'observed' ? '真实资金流' : 'OHLCV 资金压力代理'}</span><span className="text-muted">{metricLabel} · {radar.data.universe_size} 个板块 · 截至 {radar.data.as_of}</span><span className="ml-auto text-muted">排名分位评分：波段 9.16×RankPct+61.53</span></div>
      {radar.data.detail && <p className="mb-3 text-xs text-warning">{radar.data.detail}</p>}
      <div className="grid gap-5 md:grid-cols-2">{renderSide(attackers, true)}{renderSide(retreaters, false)}</div>
    </div>
    <div className={`${card} grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]`}>
      <div><h3 className="text-sm font-semibold">板块明细 · {selectedSector ?? '--'}</h3><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[680px] text-right text-xs"><thead className="text-muted"><tr><th className="pb-2 text-left">指标</th><th>数值</th><th>排名</th><th>评分</th><th>1日变化</th><th>3日变化</th><th>5日变化</th></tr></thead><tbody>{rows.filter(row => row.sector === selectedSector).map(row => ([['波段流入率', row.swing_ratio_pct, row.swing_rank, row.swing_score, row.swing_rank_change_1d, row.swing_rank_change_3d, row.swing_rank_change_5d], ['单日流入率', row.flow_ratio_pct, row.ratio_rank, row.ratio_score, row.ratio_rank_change_1d, row.ratio_rank_change_3d, row.ratio_rank_change_5d], ['单日净额(亿)', row.flow_yuan / 1e8, row.amount_rank, row.amount_score, row.amount_rank_change_1d, row.amount_rank_change_3d, row.amount_rank_change_5d]] as const).map(values => <tr key={values[0]} className="border-t border-border/60"><td className="py-2 text-left">{values[0]}</td>{values.slice(1).map((value, index) => <td key={index} className="font-mono">{fmt(value as number)}</td>)}</tr>))}</tbody></table></div></div>
      <div className="min-w-0 border-t border-border pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0"><h3 className="text-sm font-semibold">近 3 日资金趋势</h3>{flow.data?.available && selectedFlow ? <div data-testid="sector-flow-trend-chart"><ReactECharts option={trendOption} style={{ height: 220 }} /></div> : <p className="mt-8 text-center text-xs text-muted">暂无逐日资金数据</p>}</div>
    </div>
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(520px,1.35fr)]">
      <div className={card} data-testid="sector-rank-calendar"><div className="mb-2"><h3 className="text-sm font-semibold">排名日历 · {selectedSector ?? '--'}</h3><p className="text-xs text-muted">纵轴越靠上排名越强；使用当前指标近 {selectedHistory.length} 个交易日。</p></div>{selectedHistory.length ? <ReactECharts option={calendarOption} style={{ height: 280 }} /> : <Empty text="暂无排名历史" />}</div>
      <div className={card} data-testid="sector-member-evidence">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-semibold">成分股强度 · {selectedSector ?? '--'}</h3><p className="text-xs text-muted">{members.data?.member_count ?? 0} 只本地成分 · 资金质量 {members.data?.flow_quality ?? '--'} · 主动买入 {members.data?.active_quality ?? '--'}</p></div><button type="button" className="rounded border border-border px-2.5 py-1.5 text-xs hover:bg-elevated" onClick={exportMembers} disabled={!memberRows}>导出 CSV</button></div>
        <div className="mb-3 flex overflow-hidden rounded border border-border">{([['return_pct', '涨跌幅'], ['main_net_amount', '主力净额'], ['active_buy_net_amount', '主动买入净额']] as const).map(([key, label]) => <button key={key} type="button" onClick={() => setMemberMetric(key)} className={`flex-1 px-2 py-1.5 text-xs ${memberMetric === key ? 'bg-accent text-white' : 'hover:bg-elevated'}`}>{label}</button>)}</div>
        {members.isLoading ? <Empty text="正在加载成分股证据…" /> : !members.data?.available ? <Empty text={members.data?.detail ?? '暂无成分股证据'} /> : memberRows && (memberRows.top.length || memberRows.bottom.length) ? <div className="grid gap-4 md:grid-cols-2">{([['TOP', memberRows.top], ['BOTTOM', memberRows.bottom]] as const).map(([title, evidenceRows]) => <div key={title}><div className="mb-1 text-xs font-semibold text-muted">{title}</div>{evidenceRows.map(row => <div key={`${title}-${row.symbol}`} className="grid grid-cols-[64px_minmax(0,1fr)_86px] gap-2 border-t border-border/60 py-1.5 text-xs"><span className="font-mono text-muted">{row.symbol}</span><span className="truncate" title={row.name}>{row.name}</span><span className={`text-right font-mono ${(row[memberMetric] ?? 0) >= 0 ? 'text-bull' : 'text-bear'}`}>{memberMetric === 'return_pct' ? `${fmt(row[memberMetric])}%` : billion(row[memberMetric] ?? 0)}</span></div>)}</div>)}</div> : <Empty text={memberMetric === 'active_buy_net_amount' ? '当前数据源不提供主动买入净额' : '当前指标暂无可用成分数据'} />}
      </div>
    </div>
  </div>
}

type ContributionWindow = '1' | '3' | '5' | '10'

function MacroPanel() {
  const ct = useChartTheme()
  const [contributionWindow, setContributionWindow] = useState<ContributionWindow>('1')
  const query = useQuery({ queryKey: QK.marketLabMacro, queryFn: api.marketLabMacroDispersion })
  const history = query.data?.history ?? []
  const indices = query.data?.indices ?? []
  const dates = history.map(point => point.date)
  const historyOption = useMemo(() => {
    const palette = ['#7C3AED', '#0EA5E9', '#14B8A6', '#F59E0B', '#EC4899', '#64748B', '#84CC16']
    return {
      animationDuration: 250,
      tooltip: { trigger: 'axis', backgroundColor: ct.tooltipBg, borderColor: ct.tooltipBorder, textStyle: { color: ct.tooltipText } },
      legend: { type: 'scroll', top: 0, left: 8, right: 8, textStyle: { color: ct.text, fontSize: 10 } },
      grid: { left: 56, right: 56, top: 56, bottom: 68 },
      dataZoom: [{ type: 'inside', start: Math.max(0, 100 - 90 / Math.max(1, history.length) * 100), end: 100 }, { type: 'slider', height: 18, bottom: 16, borderColor: ct.border, textStyle: { color: ct.text } }],
      xAxis: { type: 'category', boundaryGap: false, data: dates.map(value => value.slice(5)), axisLabel: { color: ct.text }, axisLine: { lineStyle: { color: ct.border } }, axisTick: { show: false } },
      yAxis: [
        { type: 'value', name: '离散度', min: 0, nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } },
        { type: 'value', name: '指数归一化', nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text }, splitLine: { show: false } },
      ],
      series: [
        { name: '离散度 D', type: 'line', yAxisIndex: 0, showSymbol: false, data: history.map(point => point.dispersion), lineStyle: { color: '#F04438', width: 1.4 }, itemStyle: { color: '#F04438' }, markLine: { silent: true, symbol: 'none', data: [{ yAxis: 30, lineStyle: { color: '#12B76A', type: 'dashed' }, label: { formatter: '30', color: '#12B76A' } }, { yAxis: 70, lineStyle: { color: '#F79009', type: 'dashed' }, label: { formatter: '70', color: '#F79009' } }, { yAxis: 120, lineStyle: { color: '#F04438', type: 'dashed' }, label: { formatter: '120', color: '#F04438' } }] } },
        { name: 'MA3', type: 'line', yAxisIndex: 0, showSymbol: false, data: history.map(point => point.ma3), lineStyle: { color: '#3B82F6', width: 2.4 }, itemStyle: { color: '#3B82F6' } },
        ...indices.map((series, index) => {
          const byDate = new Map(series.points.map(point => [point.date, point.normalized]))
          return { name: series.label, type: 'line', yAxisIndex: 1, showSymbol: false, connectNulls: true, data: dates.map(value => byDate.get(value) ?? null), lineStyle: { color: palette[index % palette.length], width: 1, opacity: 0.72 }, itemStyle: { color: palette[index % palette.length] } }
        }),
      ],
    }
  }, [ct, dates, history, indices])
  if (query.isLoading) return <Empty text="正在计算宏观离散度…" />
  if (!query.data?.available) return <Empty text={query.data?.detail ?? '本地行业历史不足，暂不能计算'} />
  const selectedContribution = query.data.contribution_windows?.[contributionWindow] ?? { high: [], low: [] }
  const zoneTone = query.data.ma3 < 30 ? 'bg-bull/10 text-bull' : query.data.ma3 < 70 ? 'bg-accent/10 text-accent' : query.data.ma3 < 120 ? 'bg-warning/10 text-warning' : 'bg-bear/10 text-bear'
  const contributionColumn = (title: string, rows: MacroContributionRow[], high: boolean) => <div className="min-w-0">
    <div className="border-b border-border px-3 py-2 text-xs font-semibold text-muted">{title}</div>
    {rows.map(row => <div key={row.name} className="grid grid-cols-[minmax(0,1fr)_72px_62px] items-center gap-2 border-b border-border/60 px-3 py-2 text-xs last:border-0"><span className="truncate font-medium" title={row.name}>{row.name}</span><span className={`rounded px-1.5 py-0.5 text-center text-[10px] ${row.state === '强者扩张' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>{row.state}</span><span className={`text-right font-mono ${high ? 'text-bull' : 'text-muted'}`}>{fmt(row.contribution_pct)}%</span></div>)}
  </div>
  return <div className="space-y-4">
    <div><h2 className="text-base font-semibold">宏观择时</h2><p className="text-xs text-muted">观察行业收益分化与市场拥挤程度；离散度不是方向信号。</p></div>
    <div className={`${card} grid gap-4 sm:grid-cols-3 xl:grid-cols-6`} data-testid="macro-summary">
      <div><p className="text-xs text-muted">行情离散度 (MA3)</p><p className="mt-1 text-2xl font-semibold">{fmt(query.data.ma3)}</p></div>
      <div><p className="text-xs text-muted">精确值 (D)</p><p className="mt-1 text-xl font-semibold">{fmt(query.data.dispersion)}</p></div>
      <div className="flex items-center"><span className={`rounded px-2.5 py-1.5 text-xs font-medium ${zoneTone}`}>{query.data.zone}</span></div>
      <div><p className="text-xs text-muted">1日变化</p><p className={`mt-1 font-mono text-sm ${query.data.change_1d >= 0 ? 'text-bull' : 'text-bear'}`}>{query.data.change_1d >= 0 ? '+' : ''}{fmt(query.data.change_1d)}</p></div>
      <div><p className="text-xs text-muted">5日变化</p><p className={`mt-1 font-mono text-sm ${query.data.change_5d >= 0 ? 'text-bull' : 'text-bear'}`}>{query.data.change_5d >= 0 ? '+' : ''}{fmt(query.data.change_5d)}</p></div>
      <div><p className="text-xs text-muted">本地历史分位</p><p className="mt-1 font-mono text-sm">{fmt(query.data.ma3_percentile)}%</p></div>
    </div>
    <div className={card}><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-semibold">离散度与指数走势</h3><p className="text-xs text-muted">D / MA3 使用左轴，{indices.length} 个可用指数以首日对数收益归一化后使用右轴。</p></div><span className="text-xs text-muted">{query.data.industry_count} 个本地行业 · 截至 {query.data.as_of}</span></div><div data-testid="macro-dispersion-combined-chart"><ReactECharts option={historyOption} style={{ height: 500 }} /></div></div>
    <div className={`${card} p-0`} data-testid="macro-contribution-board"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3"><div><h3 className="text-sm font-semibold">离散度贡献榜</h3><p className="text-xs text-muted">聚合期内贡献度 C 与方向 O；高/低贡献分别对应横截面两端。</p></div><div className="flex overflow-hidden rounded border border-border">{(['1', '3', '5', '10'] as const).map(value => <button key={value} type="button" onClick={() => setContributionWindow(value)} className={`px-3 py-1.5 text-xs ${contributionWindow === value ? 'bg-accent text-white' : 'text-secondary hover:bg-elevated'}`}>{value}日</button>)}</div></div><div className="grid md:grid-cols-2 md:divide-x md:divide-border">{contributionColumn('高贡献 TOP10', selectedContribution.high, true)}{contributionColumn('低贡献 TOP10', selectedContribution.low, false)}</div></div>
    <p className="px-1 text-[11px] text-muted">口径：{query.data.basis}；分位仅基于本地可用历史，不代表近十年。阈值 30 / 70 / 120 沿用 OneChart 展示。</p>
  </div>
}

type PositionInput = {
  balance: number; risk_pct: number; entry: number; stop: number
  mode: 'brave' | 'sensitive'; trade_type: 'B1' | 'B2'
}
type SimulationInput = { balance: number; win_rate: number; win_r: number; loss_r: number; risk_pct: number; trades: number; paths: number; seed: number; target_return_pct: number; max_drawdown_pct: number; annual_trades: number }

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <label className="text-xs text-muted">{label}<input aria-label={label} className={`${input} mt-1`} type="number" step="any" value={value} onChange={e => onChange(Number(e.target.value))} /></label>
}

function RiskPanel() {
  const ct = useChartTheme()
  const [position, setPosition] = useState<PositionInput>({ balance: 100000, risk_pct: 0.01, entry: 10, stop: 9, mode: 'brave', trade_type: 'B1' })
  const [stopMode, setStopMode] = useState<'price' | 'percent'>('price')
  const [stopPercent, setStopPercent] = useState(10)
  const [pitInput, setPitInput] = useState({ top: 10, bottom: 8, current: 9 })
  const [drawInput, setDrawInput] = useState({ entry: 10, stop: 9, high: 20, target_r: 10, drawdown_pct: 0.1 })
  const [simulation, setSimulation] = useState<SimulationInput>({ balance: 100000, win_rate: 0.55, win_r: 1.5, loss_r: 1, risk_pct: 0.01, trades: 100, paths: 1000, seed: 42, target_return_pct: 50, max_drawdown_pct: 20, annual_trades: 50 })
  const [basis, setBasis] = useState<'decision' | 'theory'>('decision')
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>()
  const [history, setHistory] = useState<{ entry: number; stop: number; shares: number; at: string }[]>(() => { try { return JSON.parse(localStorage.getItem('market-lab-position-history') ?? '[]') } catch { return [] } })
  const effectiveStop = stopMode === 'percent' ? position.entry * (1 - stopPercent / 100) : position.stop
  const pos = useMutation({ mutationFn: api.marketLabPosition, onSuccess: result => {
    const next = [{ entry: position.entry, stop: effectiveStop, shares: result.shares, at: new Date().toLocaleString('zh-CN') }, ...history].slice(0, 10)
    setHistory(next); localStorage.setItem('market-lab-position-history', JSON.stringify(next))
  } })
  const pit = useMutation({ mutationFn: api.marketLabPit })
  const draw = useMutation({ mutationFn: api.marketLabDrawdown })
  const sim = useMutation({ mutationFn: api.marketLabSimulate })
  const visibleStrategies = (sim.data?.strategies ?? []).filter(row => row.basis === basis)
  const selectedStrategy = visibleStrategies.find(row => row.id === selectedStrategyId) ?? visibleStrategies[0]
  const simulationOption = useMemo(() => ({
    tooltip: { trigger: 'axis', backgroundColor: ct.tooltipBg, borderColor: ct.tooltipBorder, textStyle: { color: ct.tooltipText } }, grid: { left: 70, right: 25, top: 28, bottom: 42 },
    xAxis: { type: 'category', name: '交易', data: selectedStrategy?.median_path.map((_, index) => index) ?? [], axisLabel: { color: ct.text }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: { type: 'value', name: '权益', scale: true, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } },
    series: selectedStrategy ? [
      { name: 'P90', type: 'line', showSymbol: false, data: selectedStrategy.p90_path, lineStyle: { color: '#12B76A', width: 1 } },
      { name: '中位数', type: 'line', showSymbol: false, data: selectedStrategy.median_path, lineStyle: { color: '#3B82F6', width: 2.5 } },
      { name: 'P10', type: 'line', showSymbol: false, data: selectedStrategy.p10_path, lineStyle: { color: '#F04438', width: 1 } },
      ...selectedStrategy.sample_paths.slice(0, 5).map((path, index) => ({ name: `样本${index + 1}`, type: 'line', showSymbol: false, data: path, lineStyle: { color: '#94A3B8', width: 0.7, opacity: 0.35 } })),
    ] : [],
  }), [ct, selectedStrategy])
  const distributionOption = useMemo(() => ({
    tooltip: { trigger: 'axis' }, grid: { left: 54, right: 16, top: 20, bottom: 42 },
    xAxis: { type: 'category', data: (sim.data?.distribution.bins ?? []).map(bin => money((bin.from + bin.to) / 2)), axisLabel: { color: ct.text, interval: 5, rotate: 25 } },
    yAxis: { type: 'value', name: '概率', axisLabel: { color: ct.text, formatter: (value: number) => `${fmt(value * 100, 0)}%` }, splitLine: { lineStyle: { color: ct.grid } } },
    series: [{ type: 'bar', data: (sim.data?.distribution.bins ?? []).map(bin => bin.density), itemStyle: { color: '#8B5CF6' } }],
  }), [ct, sim.data])
  const runPosition = () => pos.mutate({ ...position, stop: effectiveStop })
  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-2">
    <div className={card}>
      <h2 className="mb-4 flex items-center gap-2 font-semibold"><Calculator className="h-4 w-4 text-accent" />风险仓位计算</h2>
      <div className="grid grid-cols-2 gap-3">
        <NumberField label="账户资金" value={position.balance} onChange={balance => setPosition(old => ({ ...old, balance }))} />
        <NumberField label="单笔风险(小数)" value={position.risk_pct} onChange={risk_pct => setPosition(old => ({ ...old, risk_pct }))} />
        <NumberField label="入场价" value={position.entry} onChange={entry => setPosition(old => ({ ...old, entry }))} />
        {stopMode === 'price' ? <NumberField label="止损价" value={position.stop} onChange={stop => setPosition(old => ({ ...old, stop }))} /> : <NumberField label="止损幅度(%)" value={stopPercent} onChange={setStopPercent} />}
        <label className="text-xs text-muted">止损模式<select aria-label="止损模式" className={`${input} mt-1`} value={stopMode} onChange={e => setStopMode(e.target.value as typeof stopMode)}><option value="price">固定价格</option><option value="percent">固定幅度</option></select></label>
        <label className="text-xs text-muted">性格模式<select aria-label="性格模式" className={`${input} mt-1`} value={position.mode} onChange={e => setPosition(old => ({ ...old, mode: e.target.value as PositionInput['mode'] }))}><option value="brave">勇气模式</option><option value="sensitive">敏感模式</option></select></label>
        <label className="text-xs text-muted">交易类型<select aria-label="交易类型" className={`${input} mt-1`} value={position.trade_type} onChange={e => setPosition(old => ({ ...old, trade_type: e.target.value as PositionInput['trade_type'] }))}><option value="B1">回调企稳 B1</option><option value="B2">启动突破 B2</option></select></label>
      </div>
      <div className="mt-3 text-xs text-muted">当前止损价：{fmt(effectiveStop)} · 风险参数可由下方模拟器回填</div>
      <button className={`${button} mt-3`} onClick={runPosition} disabled={pos.isPending}>计算仓位</button>
      {pos.data && <><div className="mt-4 grid grid-cols-2 gap-2 text-sm"><span>风险等级 <b>{pos.data.risk_level}</b></span><span>股数 <b>{pos.data.shares}</b></span><span>资金占用 <b>{fmt(pos.data.capital_usage_pct)}%</b></span><span>实际风险 <b>{fmt(pos.data.actual_risk_pct)}%</b></span><span>计划亏损 <b>{money(pos.data.planned_loss)}</b></span><span>保本位 <b>{fmt(pos.data.breakeven_price)} ({fmt(pos.data.breakeven_r)}R)</b></span><span>目标位 <b>{fmt(pos.data.target_price)} ({fmt(pos.data.target_r)}R)</b></span><span>预期利润 <b>{money(pos.data.projected_profit)}</b></span></div>{pos.data.warnings.length > 0 && <div className="mt-3 rounded border border-warning/30 bg-warning/5 p-2 text-xs text-warning">{pos.data.warnings.map(item => <div key={item}>• {item}</div>)}</div>}</>}
      {history.length > 0 && <details className="mt-4 text-xs"><summary className="cursor-pointer text-muted">最近 {history.length} 次计算</summary><div className="mt-2 space-y-1">{history.map((row, index) => <div key={`${row.at}-${index}`} className="flex justify-between border-t border-border/60 py-1"><span>{row.entry} / {row.stop}</span><span>{row.shares}股 · {row.at}</span></div>)}</div></details>}
    </div>
    <div className={card}>
      <h2 className="mb-4 flex items-center gap-2 font-semibold"><FlaskConical className="h-4 w-4 text-accent" />Kelly + 蒙特卡洛</h2>
      <div className="grid grid-cols-2 gap-3">{Object.entries(simulation).map(([key, value]) => <NumberField key={key} label={{ balance: '初始资金', win_rate: '胜率(小数)', win_r: '盈利R', loss_r: '亏损R', risk_pct: '手工风险(小数)', trades: '观察交易数', paths: '模拟路径数', seed: '随机种子', target_return_pct: '目标年化(%)', max_drawdown_pct: '可承受回撤(%)', annual_trades: '年均交易数' }[key]!} value={value} onChange={v => setSimulation(old => ({ ...old, [key]: v }))} />)}</div>
      <div className="mt-4 flex gap-2"><button className={button} onClick={() => sim.mutate(simulation)} disabled={sim.isPending}>{sim.isPending ? '正在模拟…' : '运行模拟'}</button><button className="rounded border border-border px-3 py-2 text-sm hover:bg-elevated" onClick={() => { setSimulation(old => ({ ...old, seed: old.seed + 1 })); sim.mutate({ ...simulation, seed: simulation.seed + 1 }) }} disabled={sim.isPending}>重新抽样</button></div>
      {sim.data && <><div className="mt-4 grid grid-cols-2 gap-2 text-sm"><span>单笔期望 <b>{fmt(sim.data.expectancy_r)}R</b></span><span>盈亏平衡 <b>{fmt(sim.data.break_even_pct)}%</b></span><span>Kelly上限 <b>{fmt(sim.data.kelly_pct)}%</b></span><span>建议风险 <b>{fmt(sim.data.reverse.recommended_risk_pct)}%</b></span><span>半额测试 <b>{fmt(sim.data.reverse.test_risk_pct)}%</b></span><span>主要约束 <b>{sim.data.reverse.limiting_factor === 'drawdown' ? '最大回撤' : sim.data.reverse.limiting_factor === 'kelly' ? 'Kelly上限' : '负期望'}</b></span><span>收益目标 <b className={sim.data.reverse.target_reachable ? 'text-bull' : 'text-warning'}>{sim.data.reverse.target_reachable ? '风险边界内可达' : '当前参数不可达'}</b></span></div><div className="mt-3 flex gap-2"><button className="rounded border border-border px-2 py-1 text-xs hover:bg-elevated" onClick={() => setPosition(old => ({ ...old, risk_pct: sim.data!.reverse.recommended_risk_pct / 100 }))}>应用满额到仓位</button><button className="rounded border border-border px-2 py-1 text-xs hover:bg-elevated" onClick={() => setPosition(old => ({ ...old, risk_pct: sim.data!.reverse.test_risk_pct / 100 }))}>应用半额到仓位</button></div></>}
    </div>
    <div className={card}>
      <h2 className="mb-4 font-semibold">出坑计算</h2>
      <div className="grid grid-cols-3 gap-3"><NumberField label="坑口价" value={pitInput.top} onChange={top => setPitInput(old => ({ ...old, top }))} /><NumberField label="坑底价" value={pitInput.bottom} onChange={bottom => setPitInput(old => ({ ...old, bottom }))} /><NumberField label="当前价" value={pitInput.current} onChange={current => setPitInput(old => ({ ...old, current }))} /></div>
      <button className={`${button} mt-4`} onClick={() => pit.mutate(pitInput)}>计算出坑</button>
      {pit.data && <div className="mt-4 grid grid-cols-3 gap-2 text-sm"><span>目标 <b>{fmt(pit.data.target)}</b></span><span>坑深 <b>{fmt(pit.data.depth_pct)}%</b></span><span>潜在空间 <b>{fmt(pit.data.upside_pct)}%</b></span></div>}
    </div>
    <div className={card}>
      <h2 className="mb-4 font-semibold">回撤保护</h2>
      <div className="grid grid-cols-3 gap-3"><NumberField label="买入价" value={drawInput.entry} onChange={entry => setDrawInput(old => ({ ...old, entry }))} /><NumberField label="保护止损" value={drawInput.stop} onChange={stop => setDrawInput(old => ({ ...old, stop }))} /><NumberField label="持仓最高价" value={drawInput.high} onChange={high => setDrawInput(old => ({ ...old, high }))} /><NumberField label="预期R" value={drawInput.target_r} onChange={target_r => setDrawInput(old => ({ ...old, target_r }))} /><NumberField label="回撤比例(小数)" value={drawInput.drawdown_pct} onChange={drawdown_pct => setDrawInput(old => ({ ...old, drawdown_pct }))} /></div>
      <button className={`${button} mt-4`} onClick={() => draw.mutate(drawInput)}>计算保护位</button>
      {draw.data && <div className="mt-4 grid grid-cols-3 gap-2 text-sm"><span>实际 <b>{fmt(draw.data.actual_r)}R</b></span><span>退出价 <b>{fmt(draw.data.exit_price)}</b></span><span>锁定收益 <b>{fmt(draw.data.locked_profit_pct)}%</b></span><span>目标状态 <b className={draw.data.target_achieved ? 'text-bull' : 'text-warning'}>{draw.data.target_achieved ? '已达到' : '未达到'}</b></span></div>}
    </div>
    </div>
    {sim.data && <div className={card} data-testid="simulation-evidence">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold">风险档位与结果证据</h2><p className="text-xs text-muted">所有档位使用同一组随机胜负序列，差异只来自风险敞口。</p></div><div className="flex overflow-hidden rounded border border-border">{([['decision', '风险敞口'], ['theory', 'Kelly 理论档']] as const).map(([key, label]) => <button key={key} onClick={() => { setBasis(key); setSelectedStrategyId(undefined) }} className={`px-3 py-1.5 text-xs ${basis === key ? 'bg-accent text-white' : 'hover:bg-elevated'}`}>{label}</button>)}</div></div>
      <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-5">{visibleStrategies.map(row => <button key={row.id} onClick={() => setSelectedStrategyId(row.id)} className={`rounded border p-3 text-left ${selectedStrategy?.id === row.id ? 'border-accent bg-accent/5' : 'border-border'}`}><div className="text-xs font-semibold">{row.name}</div><div className="mt-1 text-lg font-mono">{fmt(row.risk_pct)}%</div><div className="mt-1 text-[10px] text-muted">P50 {money(row.p50_final)} · P80回撤 {fmt(row.p80_drawdown_pct)}%</div><div className="text-[10px] text-muted">减半 {fmt(row.halve_probability_pct)}% · 破产 {fmt(row.ruin_probability_pct)}%</div></button>)}</div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2"><div><h3 className="mb-2 text-sm font-semibold">资金路径分位带 · {selectedStrategy?.name}</h3><ReactECharts option={simulationOption} style={{ height: 360 }} /></div><div><h3 className="mb-2 text-sm font-semibold">手工风险最终资金分布</h3><ReactECharts option={distributionOption} style={{ height: 360 }} /></div></div>
      {selectedStrategy && <div className="mt-3 grid grid-cols-3 gap-3 rounded bg-base p-3 text-xs"><span>最低分位 <b>{money(selectedStrategy.p10_final)}</b></span><span>中位结果 <b>{money(selectedStrategy.p50_final)}</b></span><span>最高分位 <b>{money(selectedStrategy.p90_final)}</b></span></div>}
    </div>}
  </div>
}

export function MarketLab() {
  const [tab, setTab] = useState<Tab>('etf')
  return <div className="space-y-5 p-4 md:p-6" data-testid="market-lab">
    <div><h1 className="text-xl font-semibold">市场实验室</h1><p className="mt-1 text-sm text-muted">复现 ETF 动量、板块资金趋势、宏观离散度、仓位与交易模拟，并沿用 TickFlow 本地数据底座。</p></div>
    <div className="flex flex-wrap gap-2">{tabs.map(item => <button key={item.key} onClick={() => setTab(item.key)} className={`inline-flex items-center gap-2 rounded-btn border px-3 py-2 text-sm ${tab === item.key ? 'border-accent bg-accent/10 text-accent' : 'border-border text-secondary hover:bg-elevated'}`}><item.icon className="h-4 w-4" />{item.label}</button>)}</div>
    {tab === 'etf' && <EtfPanel />}{tab === 'sector' && <SectorPanel />}{tab === 'macro' && <MacroPanel />}{tab === 'risk' && <RiskPanel />}
  </div>
}
