import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts'
import { Activity, Boxes, GitBranch, Loader2, Orbit, Radar } from 'lucide-react'
import type { QuantXAdvancedCard, QuantXAdvancedSnapshot } from '@/lib/api'
import { useChartTheme } from '@/lib/theme'
import { cn } from '@/lib/cn'

const RED = '#f85149'
const GREEN = '#3fb950'
const BLUE = '#58a6ff'
const ORANGE = '#f78166'
const PURPLE = '#bc8cff'
const YELLOW = '#d29922'
const PALETTE = [RED, BLUE, ORANGE, PURPLE, GREEN, YELLOW, '#39c5cf', '#ff9f43', '#7f8cff', '#e56b9f', '#5dd39e', '#b8a1ff']

type ChartTheme = ReturnType<typeof useChartTheme>

const CARD_META: Record<string, { title: string; hint: string; group: 'state' | 'rotation' | 'structure'; span?: string }> = {
  sentiment_phase: { title: '市场情绪状态相图', hint: '趋势情绪 × 短线情绪 · 气泡为涨停家数', group: 'state' },
  liquidity_participation: { title: '流动性—参与度四象限', hint: '全市场成交额 × 上涨家数占比', group: 'state' },
  risk_transmission: { title: '风险传导链', hint: '集中度、扩散、炸板、梯队与热度的当日传导', group: 'state' },
  state_transition: { title: '市场状态转移矩阵', hint: '245 日五状态条件转移概率', group: 'state' },
  anomaly_calendar: { title: '历史异常日历', hint: '收益、广度、涨停、成交额综合异常强度', group: 'state' },
  return_distribution: { title: '全市场收益分布剖面', hint: '当日全 A 收益横截面与中位数', group: 'state' },
  advance_decline: { title: 'A/D 累积线与指数背离', hint: '涨跌家数差累积 vs 中证全指', group: 'state' },
  turnover_lorenz: { title: '成交额洛伦兹曲线与 Gini', hint: '交易集中度；虚线为完全均等', group: 'state' },
  sector_diffusion: { title: '申万一级行业宽度扩散地图', hint: '近 20 日站上 MA20 成分占比', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]' },
  theme_river: { title: '题材排名河流图', hint: '近 20 日多源题材排名强度与持续性', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]' },
  industry_correlation: { title: '行业收益相关性矩阵', hint: '当前申万一级成分的近 35 日收益相关性', group: 'rotation', span: 'xl:[grid-column:span_10/span_10]' },
  mainline_waterfall: { title: '主线强度贡献瀑布', hint: '涨停广度、连板高度与梯队完整度综合得分', group: 'rotation', span: 'xl:[grid-column:span_6/span_6]' },
  theme_ladder_sunburst: { title: '题材—连板层级旭日图', hint: '当日题材 → 连板高度 → 个股', group: 'rotation' },
  rps_rotation_clock: { title: '行业 RPS 轮动时钟', hint: '近 5 日动量 × 相对前 5 日加速度', group: 'rotation' },
  promotion_funnel: { title: '连板晋级漏斗', hint: '近 75 日逐层晋级样本与转化率', group: 'structure' },
  turnover_return_density: { title: '换手—收益拥挤密度', hint: '当日换手率 × 收益率二维密度', group: 'structure' },
}

function base(ct: ChartTheme) {
  return {
    textStyle: { color: ct.text, fontSize: 10 },
    tooltip: { trigger: 'item', confine: true },
    animationDuration: 280,
  }
}

function heatVisual(max: number) {
  return { min: 0, max: Math.max(max, 1), calculable: true, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, inRange: { color: ['#101a2d', '#244b75', '#d29922', '#f85149'] }, textStyle: { color: '#8b949e', fontSize: 9 } }
}

function optionFor(key: string, data: Record<string, any>, ct: ChartTheme): any {
  const common = base(ct)
  if (key === 'sentiment_phase' || key === 'liquidity_participation') {
    const points = data.points || []
    const isPhase = key === 'sentiment_phase'
    return { ...common, grid: { left: 52, right: 18, top: 20, bottom: 40 }, xAxis: { type: 'value', name: isPhase ? '趋势情绪' : '成交额(亿)', nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', name: isPhase ? '短线情绪' : '上涨占比%', nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'scatter', symbolSize: (value: number[]) => Math.max(7, Math.min(28, 6 + Math.sqrt(value[2] || 0) * 1.7)), data: points.map((row: any, index: number) => ({ value: [row.x, row.y, row.size, row.heat], name: row.date, itemStyle: { color: index === points.length - 1 ? RED : BLUE, opacity: index === points.length - 1 ? 1 : 0.45 } })), tooltip: { formatter: (p: any) => `${p.name}<br/>${isPhase ? '趋势情绪' : '成交额'}：${p.value[0]}<br/>${isPhase ? '短线情绪' : '上涨占比'}：${p.value[1]}<br/>涨停：${p.value[2]}<br/>热度：${p.value[3]}` }, markLine: { silent: true, symbol: 'none', lineStyle: { color: ct.border, type: 'dashed' }, data: isPhase ? [{ xAxis: 50 }, { yAxis: 50 }] : [{ xAxis: data.amount_mid }, { yAxis: 50 }] } }] }
  }
  if (key === 'risk_transmission') {
    const nodes = data.nodes || []
    return { ...common, series: [{ type: 'graph', layout: 'none', roam: false, symbolSize: (value: number) => Math.max(44, Math.min(76, 42 + value / 2)), label: { show: true, color: ct.textStrong, formatter: (p: any) => `${p.name}\n${p.value}` }, edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 8, lineStyle: { color: ORANGE, width: 2, curveness: 0.08, opacity: 0.7 }, data: nodes.map((node: any, index: number) => ({ ...node, x: 80 + (index % 3) * 180, y: 70 + Math.floor(index / 3) * 130, itemStyle: { color: [BLUE, PURPLE, ORANGE, GREEN, YELLOW, RED][index] } })), links: data.links || [] }] }
  }
  if (key === 'state_transition') {
    const matrix = data.matrix || []
    const values = matrix.flatMap((row: number[], y: number) => row.map((value, x) => [x, y, value]))
    return { ...common, grid: { left: 62, right: 20, top: 15, bottom: 50 }, xAxis: { type: 'category', data: data.labels || [], axisLabel: { color: ct.text } }, yAxis: { type: 'category', data: data.labels || [], axisLabel: { color: ct.text } }, visualMap: { ...heatVisual(100), min: 0, max: 100 }, series: [{ type: 'heatmap', data: values, label: { show: true, color: ct.textStrong, formatter: (p: any) => `${p.value[2]}%` } }] }
  }
  if (key === 'sector_diffusion') {
    const values = (data.values || []).flatMap((row: Array<number | null>, y: number) => row.map((value, x) => [x, y, value]))
    return { ...common, grid: { left: 82, right: 18, top: 10, bottom: 50 }, xAxis: { type: 'category', data: data.dates || [], axisLabel: { color: ct.text, rotate: 35, fontSize: 9 } }, yAxis: { type: 'category', data: data.sectors || [], axisLabel: { color: ct.text, width: 68, overflow: 'truncate', fontSize: 9 } }, visualMap: { ...heatVisual(100), min: 0, max: 100 }, series: [{ type: 'heatmap', data: values, progressive: 1000, tooltip: { formatter: (p: any) => `${data.dates[p.value[0]]}<br/>${data.sectors[p.value[1]]}<br/>MA20 宽度：${p.value[2] ?? '--'}%` } }] }
  }
  if (key === 'theme_river') {
    return { ...common, color: PALETTE, legend: { type: 'scroll', top: 0, textStyle: { color: ct.text, fontSize: 9 } }, grid: { left: 40, right: 20, top: 45, bottom: 40 }, xAxis: { type: 'category', data: data.dates || [], axisLabel: { color: ct.text, rotate: 30, fontSize: 9 } }, yAxis: { type: 'value', name: '排名强度', axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, series: (data.themes || []).map((name: string, index: number) => ({ name, type: 'line', smooth: true, symbol: 'none', lineStyle: { width: 1.5 }, areaStyle: { opacity: 0.05 }, data: data.values[index] })) }
  }
  if (key === 'promotion_funnel') {
    return { ...common, series: [{ type: 'funnel', left: '8%', top: 15, bottom: 15, width: '84%', minSize: '30%', maxSize: '100%', sort: 'none', gap: 3, label: { color: ct.textStrong, formatter: (p: any) => `${p.name}  ${p.data.promoted}/${p.data.pool}  ${p.data.rate}%` }, itemStyle: { borderColor: ct.border, borderWidth: 1 }, data: (data.stages || []).map((row: any) => ({ ...row, value: row.pool })) }] }
  }
  if (key === 'anomaly_calendar') {
    const records = data.records || []
    const max = Math.max(1, ...records.map((row: any) => row.value || 0))
    const years = Array.from(new Set(records.map((row: any) => String(row.date).slice(0, 4))))
    return { ...common, tooltip: { formatter: (p: any) => `${p.value[0]}<br/>异常强度：${p.value[1]}<br/>指数收益：${p.data.return_pct}%<br/>状态：${p.data.state || '--'}` }, visualMap: { ...heatVisual(max), max }, calendar: years.map((year, index) => ({ range: String(year), top: 20 + index * 120, left: 38, right: 15, cellSize: ['auto', 13], splitLine: { show: false }, itemStyle: { color: ct.grid, borderWidth: 2, borderColor: ct.tooltipBg }, dayLabel: { color: ct.text }, monthLabel: { color: ct.text }, yearLabel: { color: ct.textStrong } })), series: years.map((year, index) => ({ type: 'heatmap', coordinateSystem: 'calendar', calendarIndex: index, data: records.filter((row: any) => String(row.date).startsWith(String(year))).map((row: any) => ({ value: [row.date, row.value], return_pct: row.return_pct, state: row.state })) })) }
  }
  if (key === 'return_distribution') {
    return { ...common, grid: { left: 45, right: 18, top: 18, bottom: 48 }, xAxis: { type: 'category', data: data.bins || [], axisLabel: { color: ct.text, rotate: 35, fontSize: 9 } }, yAxis: { type: 'value', axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'bar', data: (data.counts || []).map((value: number, index: number) => ({ value, itemStyle: { color: index < 5 ? GREEN : index > 5 ? RED : ct.text } })), barMaxWidth: 34, label: { show: true, position: 'top', color: ct.text, fontSize: 9 } }] }
  }
  if (key === 'advance_decline') {
    return { ...common, legend: { data: ['A/D 累积线', data.index_symbol || '指数'], textStyle: { color: ct.text } }, grid: { left: 55, right: 55, top: 36, bottom: 42 }, xAxis: { type: 'category', data: data.dates || [], axisLabel: { color: ct.text, fontSize: 9 } }, yAxis: [{ type: 'value', axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, { type: 'value', axisLabel: { color: ct.text }, splitLine: { show: false } }], series: [{ name: 'A/D 累积线', type: 'line', symbol: 'none', data: data.ad_line || [], lineStyle: { color: ORANGE, width: 2 } }, { name: data.index_symbol || '指数', type: 'line', yAxisIndex: 1, symbol: 'none', data: data.index_close || [], lineStyle: { color: BLUE, width: 1.5 } }] }
  }
  if (key === 'turnover_lorenz') {
    const points = data.points || []
    return { ...common, grid: { left: 50, right: 20, top: 20, bottom: 42 }, xAxis: { type: 'value', min: 0, max: 100, name: '股票累计占比%', axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', min: 0, max: 100, name: `成交额累计占比% · Gini ${data.gini ?? '--'}`, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'line', symbol: 'none', data: points.map((row: any) => [row.population_pct, row.amount_pct]), lineStyle: { color: ORANGE, width: 2 }, areaStyle: { color: 'rgba(247,129,102,.12)' } }, { type: 'line', symbol: 'none', data: [[0, 0], [100, 100]], lineStyle: { color: ct.text, type: 'dashed' } }] }
  }
  if (key === 'industry_correlation') {
    const matrix = data.matrix || []
    const values = matrix.flatMap((row: Array<number | null>, y: number) => row.map((value, x) => [x, y, value]))
    return { ...common, grid: { left: 80, right: 20, top: 10, bottom: 78 }, xAxis: { type: 'category', data: data.industries || [], axisLabel: { color: ct.text, rotate: 50, fontSize: 9 } }, yAxis: { type: 'category', data: data.industries || [], axisLabel: { color: ct.text, fontSize: 9 } }, visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, inRange: { color: [GREEN, '#172033', RED] }, textStyle: { color: ct.text } }, series: [{ type: 'heatmap', data: values, tooltip: { formatter: (p: any) => `${data.industries[p.value[1]]} × ${data.industries[p.value[0]]}<br/>相关系数：${p.value[2] ?? '--'}` } }] }
  }
  if (key === 'mainline_waterfall') {
    const components = data.components || []
    let cumulative = 0
    const baseValues = components.map((row: any) => { const value = cumulative; cumulative += row.value || 0; return value })
    const labels = [...components.map((row: any) => row.name), '综合得分']
    return { ...common, title: { text: data.focus || '', subtext: `${data.trade_date || ''} · ${data.score ?? '--'} 分`, left: 'center', textStyle: { color: ct.textStrong, fontSize: 12 }, subtextStyle: { color: ct.text, fontSize: 9 } }, grid: { left: 42, right: 18, top: 58, bottom: 42 }, xAxis: { type: 'category', data: labels, axisLabel: { color: ct.text, fontSize: 9 } }, yAxis: { type: 'value', max: 100, axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ name: '基座', type: 'bar', stack: 'total', itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }, data: [...baseValues, 0] }, { name: '贡献', type: 'bar', stack: 'total', data: [...components.map((row: any, index: number) => ({ value: row.value, raw: row.raw, itemStyle: { color: PALETTE[index] } })), { value: data.score, itemStyle: { color: RED } }], label: { show: true, position: 'top', color: ct.textStrong, formatter: (p: any) => `${p.value}` }, tooltip: { formatter: (p: any) => p.name === '综合得分' ? `${data.focus}<br/>综合得分：${p.value}` : `${p.name}<br/>得分贡献：${p.value}<br/>原始值：${p.data.raw}` } }] }
  }
  if (key === 'theme_ladder_sunburst') {
    return { ...common, series: [{ type: 'sunburst', radius: ['8%', '92%'], sort: null, emphasis: { focus: 'ancestor' }, label: { color: ct.textStrong, rotate: 'radial', minAngle: 8 }, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 1 }, data: data.children || [], levels: [{}, { r0: '8%', r: '38%', label: { rotate: 0, fontSize: 10 } }, { r0: '38%', r: '66%', label: { fontSize: 9 } }, { r0: '66%', r: '92%', label: { show: false } }] }] }
  }
  if (key === 'rps_rotation_clock') {
    return { ...common, grid: { left: 48, right: 18, top: 18, bottom: 42 }, xAxis: { type: 'value', name: '近5日动量%', axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', name: '加速度%', axisLabel: { color: ct.text }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'scatter', symbolSize: 14, data: (data.points || []).map((row: any, index: number) => ({ name: row.name, value: [row.momentum, row.acceleration], itemStyle: { color: PALETTE[index % PALETTE.length] } })), label: { show: true, position: 'right', color: ct.text, fontSize: 9, formatter: '{b}' }, markLine: { silent: true, symbol: 'none', lineStyle: { color: ct.border, type: 'dashed' }, data: [{ xAxis: 0 }, { yAxis: 0 }] } }] }
  }
  const values = data.values || []
  return { ...common, grid: { left: 72, right: 15, top: 12, bottom: 55 }, xAxis: { type: 'category', data: data.x_bins || [], axisLabel: { color: ct.text, rotate: 40, fontSize: 9 } }, yAxis: { type: 'category', data: data.y_bins || [], axisLabel: { color: ct.text, fontSize: 9 } }, visualMap: heatVisual(Math.max(1, ...values.map((row: number[]) => row[2]))), series: [{ type: 'heatmap', data: values, label: { show: true, color: ct.textStrong, fontSize: 9, formatter: (p: any) => p.value[2] || '' } }] }
}

function EChart({ chartKey, card, height = 320 }: { chartKey: string; card: QuantXAdvancedCard; height?: number }) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.ECharts | null>(null)
  const theme = useChartTheme()
  const option = useMemo(() => optionFor(chartKey, card.data, theme), [card.data, chartKey, theme])

  useEffect(() => {
    if (!container.current) return
    instance.current ||= echarts.init(container.current, undefined, { renderer: 'canvas' })
    instance.current.setOption(option, true)
  }, [option])

  useEffect(() => {
    const observer = new ResizeObserver(() => instance.current?.resize())
    if (container.current) observer.observe(container.current)
    return () => { observer.disconnect(); instance.current?.dispose(); instance.current = null }
  }, [])

  return <div ref={container} role="img" aria-label={CARD_META[chartKey].title} className="w-full" style={{ height }} />
}

function AdvancedCard({ chartKey, card }: { chartKey: string; card: QuantXAdvancedCard }) {
  const meta = CARD_META[chartKey]
  const height = chartKey === 'sector_diffusion' ? 610 : chartKey === 'theme_river' ? 390 : chartKey === 'anomaly_calendar' ? 390 : chartKey === 'industry_correlation' ? 460 : 320
  return (
    <section data-testid={`quantx-advanced-${chartKey}`} className={cn('min-w-0 overflow-hidden rounded-lg border border-border bg-elevated/25 xl:[grid-column:span_8/span_8]', meta.span)}>
      <header className="flex min-h-11 items-center gap-2 border-b border-border/70 px-3 py-1.5">
        <Activity className="h-3.5 w-3.5 shrink-0 text-accent" />
        <div className="min-w-0"><h3 className="truncate text-xs font-semibold">{meta.title}</h3><p className="truncate text-[9px] text-muted">{meta.hint}</p></div>
        {card.status === 'ok' && <span className="ml-auto shrink-0 rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[9px] text-accent">{card.rows ?? 0} 行</span>}
      </header>
      <div className="p-2">
        {card.status === 'ok' ? <EChart chartKey={chartKey} card={card} height={height} /> : <div className="flex items-center justify-center text-xs text-muted" style={{ height }}><span>{card.reason || '暂无足够数据'}</span></div>}
        {card.note && <p className="border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-orange-300">口径提示：{card.note}</p>}
      </div>
    </section>
  )
}

const GROUPS = [
  { key: 'state', title: '市场状态与风险结构', hint: '先确认环境、异常、广度和流动性', icon: Radar },
  { key: 'rotation', title: '主线扩散与轮动结构', hint: '再定位行业、题材与连板主线', icon: Orbit },
  { key: 'structure', title: '接力效率与拥挤结构', hint: '最后检查晋级质量和交易拥挤', icon: GitBranch },
] as const

export function AdvancedPanels({ snapshot, loading, error }: { snapshot?: QuantXAdvancedSnapshot; loading: boolean; error?: Error | null }) {
  if (loading) return <section data-testid="quantx-advanced-loading" className="flex items-center justify-center rounded-lg border border-border bg-elevated/20 py-20 text-xs text-muted"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在构建高级市场图谱</section>
  if (error || !snapshot) return <section data-testid="quantx-advanced-error" className="rounded-lg border border-orange-500/30 bg-orange-500/5 px-4 py-12 text-center text-xs text-orange-300">高级图谱暂不可用：{error?.message || '没有快照'}</section>
  return (
    <section data-testid="quantx-advanced-workspace" className="space-y-5 rounded-lg border border-border bg-elevated/20 p-3">
      <header className="flex flex-wrap items-center gap-2 border-b border-border pb-2"><Boxes className="h-4 w-4 text-accent" /><div><h2 className="text-sm font-semibold">高级市场图谱</h2><p className="text-[10px] text-muted">16 张真实数据卡片 · 单一批量快照 · {snapshot.coverage.history_start} 至 {snapshot.coverage.history_end}</p></div><span className="ml-auto rounded border border-border bg-base px-2 py-1 font-mono text-[10px] text-accent">{snapshot.coverage.available}/{snapshot.coverage.total} 可用</span></header>
      {GROUPS.map(group => {
        const Icon = group.icon
        const keys = Object.keys(CARD_META).filter(key => CARD_META[key].group === group.key)
        return <section key={group.key} data-testid={`quantx-advanced-group-${group.key}`}><div className="mb-2 flex items-center gap-2"><Icon className="h-3.5 w-3.5 text-accent" /><h3 className="text-xs font-semibold">{group.title}</h3><span className="text-[9px] text-muted">{group.hint}</span></div><div className="grid gap-2 xl:grid-cols-[repeat(16,minmax(0,1fr))]">{keys.map(key => <AdvancedCard key={key} chartKey={key} card={snapshot.cards[key]} />)}</div></section>
      })}
    </section>
  )
}
