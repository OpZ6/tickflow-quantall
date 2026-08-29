import { useEffect, useMemo, useRef, useState } from 'react'
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
type ChartSelection = { sectorDimension?: string; sectorWindow?: number }

const CARD_META: Record<string, { title: string; hint: string; group: 'state' | 'rotation' | 'structure'; span?: string }> = {
  sentiment_phase: { title: '市场情绪状态相图', hint: '趋势情绪 × 短线情绪 · 气泡为涨停家数', group: 'state' },
  liquidity_participation: { title: '流动性—参与度四象限', hint: '全市场成交额 × 上涨家数占比', group: 'state' },
  risk_transmission: { title: '风险传导链', hint: '集中度、扩散、炸板、梯队与热度的当日传导', group: 'state', span: 'xl:[grid-column:span_10/span_10]' },
  state_transition: { title: '市场状态转移矩阵', hint: '245 日五状态条件转移概率', group: 'state', span: 'xl:[grid-column:span_6/span_6]' },
  anomaly_calendar: { title: '近半年异常交易日', hint: '仅保留周一至周五 · 综合收益、广度、涨停与成交额', group: 'state', span: 'xl:[grid-column:span_10/span_10]' },
  return_distribution: { title: '全市场收益分布剖面', hint: '当日全 A 收益横截面与中位数', group: 'state', span: 'xl:[grid-column:span_6/span_6]' },
  advance_decline: { title: 'A/D 累积线与指数背离', hint: '涨跌家数差累积 vs 中证全指 · 阴影标出背离区间', group: 'state', span: 'xl:[grid-column:span_9/span_9]' },
  turnover_lorenz: { title: '成交额洛伦兹曲线与 Gini', hint: '交易集中度；虚线为完全均等', group: 'state', span: 'xl:[grid-column:span_7/span_7]' },
  sector_diffusion: { title: '申万行业宽度扩散地图', hint: '切换一级/二级行业及 MA5 / MA10 / MA20', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]' },
  theme_river: { title: '题材排名河流图', hint: '近 20 日真实排名轨迹 · 第 1 名位于上方', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]' },
  industry_correlation: { title: '行业收益相关性矩阵', hint: '当前申万一级成分的近 35 日收益相关性', group: 'rotation' },
  mainline_waterfall: { title: '主线强度贡献瀑布', hint: '涨停广度、连板高度与梯队完整度综合得分', group: 'rotation' },
  theme_ladder_sunburst: { title: '题材—连板层级旭日图', hint: '当日题材 → 连板高度（悬停查看合并个股）', group: 'rotation', span: 'xl:[grid-column:span_8/span_8]' },
  rps_rotation_clock: { title: '行业 RPS 轮动时钟', hint: '近 5 日动量 × 相对前 5 日加速度', group: 'rotation', span: 'xl:[grid-column:span_8/span_8]' },
  promotion_funnel: { title: '连板晋级漏斗', hint: '近 75 日逐层晋级样本与转化率', group: 'structure', span: 'xl:[grid-column:span_9/span_9]' },
  turnover_return_density: { title: '换手—收益拥挤密度', hint: '当日换手率 × 收益率二维密度', group: 'structure', span: 'xl:[grid-column:span_7/span_7]' },
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

function optionFor(key: string, data: Record<string, any>, ct: ChartTheme, selection: ChartSelection = {}): any {
  const common = base(ct)
  if (key === 'sentiment_phase' || key === 'liquidity_participation') {
    const points = data.points || []
    const isPhase = key === 'sentiment_phase'
    return { ...common, grid: { left: 12, right: 12, top: 28, bottom: 18, containLabel: true }, xAxis: { type: 'value', name: isPhase ? '趋势情绪' : '成交额(亿)', nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text, hideOverlap: true, margin: 8 }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', name: isPhase ? '短线情绪' : '上涨占比%', nameLocation: 'middle', nameGap: 34, nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text, hideOverlap: true, margin: 8 }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'scatter', symbolSize: (value: number[]) => Math.max(7, Math.min(28, 6 + Math.sqrt(value[2] || 0) * 1.7)), data: points.map((row: any, index: number) => ({ value: [row.x, row.y, row.size, row.heat], name: row.date, itemStyle: { color: index === points.length - 1 ? RED : BLUE, opacity: index === points.length - 1 ? 1 : 0.45 } })), tooltip: { formatter: (p: any) => `${p.name}<br/>${isPhase ? '趋势情绪' : '成交额'}：${p.value[0]}<br/>${isPhase ? '短线情绪' : '上涨占比'}：${p.value[1]}<br/>涨停：${p.value[2]}<br/>热度：${p.value[3]}` }, markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: ct.border, type: 'dashed' }, data: isPhase ? [{ xAxis: 50 }, { yAxis: 50 }] : [{ xAxis: data.amount_mid }, { yAxis: 50 }] } }] }
  }
  if (key === 'risk_transmission') {
    const nodes = data.nodes || []
    const wrappedLabels: Record<string, string> = { 流动性集中: '流动性\n集中', 炸板亏钱效应: '炸板亏钱\n效应' }
    return { ...common, series: [{ type: 'graph', layout: 'none', roam: false, left: 64, right: 96, top: 28, bottom: 28, symbol: 'roundRect', symbolKeepAspect: true, symbolSize: [92, 54], label: { show: true, color: ct.textStrong, width: 82, overflow: 'break', lineHeight: 14, align: 'center', formatter: (p: any) => `${wrappedLabels[p.name] || p.name}\n${p.value}` }, edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 8, lineStyle: { color: ORANGE, width: 2, curveness: 0.08, opacity: 0.7 }, data: nodes.map((node: any, index: number) => ({ ...node, x: 80 + (index % 3) * 180, y: 70 + Math.floor(index / 3) * 130, itemStyle: { color: [BLUE, PURPLE, ORANGE, GREEN, YELLOW, RED][index] } })), links: data.links || [] }] }
  }
  if (key === 'state_transition') {
    const matrix = data.matrix || []
    const values = matrix.flatMap((row: number[], y: number) => row.map((value, x) => [x, y, value]))
    const visualMax = data.visual_max || Math.max(5, ...values.map((row: number[]) => row[2]))
    return { ...common, grid: { left: 10, right: 12, top: 15, bottom: 50, containLabel: true }, xAxis: { type: 'category', data: data.labels || [], axisLabel: { color: ct.text, hideOverlap: true } }, yAxis: { type: 'category', data: data.labels || [], axisLabel: { color: ct.text, hideOverlap: true } }, visualMap: { ...heatVisual(visualMax), min: 0, max: visualMax, precision: 0 }, series: [{ type: 'heatmap', data: values, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 2 }, label: { show: true, color: ct.textStrong, formatter: (p: any) => `${p.value[2]}%` }, tooltip: { formatter: (p: any) => `${data.labels[p.value[1]]} → ${data.labels[p.value[0]]}<br/>概率：${p.value[2]}%<br/>样本：${data.counts?.[p.value[1]]?.[p.value[0]] ?? 0} 次` } }] }
  }
  if (key === 'sector_diffusion') {
    const dimension = selection.sectorDimension || data.default_dimension || 'sw_level1'
    const window = selection.sectorWindow || data.default_window || 20
    const view = data.views?.[dimension] || { sectors: data.sectors || [], metrics: { '20': data.values || [] } }
    const dates = view.dates || data.dates || []
    const matrix = view.metrics?.[String(window)] || []
    const values = matrix.flatMap((row: Array<number | null>, y: number) => row.map((value, x) => [x, y, value]))
    return { ...common, grid: { left: 10, right: 12, top: 10, bottom: 50, containLabel: true }, xAxis: { type: 'category', data: dates, axisLabel: { color: ct.text, rotate: 35, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'category', data: view.sectors || [], axisLabel: { color: ct.text, width: dimension === 'sw_level2' ? 92 : 72, overflow: 'truncate', fontSize: 9 } }, visualMap: { ...heatVisual(100), min: 0, max: 100 }, series: [{ type: 'heatmap', data: values, progressive: 1000, tooltip: { formatter: (p: any) => `${dates[p.value[0]]}<br/>${view.sectors[p.value[1]]}<br/>MA${window} 宽度：${p.value[2] ?? '--'}%` } }] }
  }
  if (key === 'theme_river') {
    return { ...common, color: PALETTE, legend: { type: 'scroll', top: 0, left: 8, right: 8, textStyle: { color: ct.text, fontSize: 9 } }, grid: { left: 10, right: 12, top: 45, bottom: 20, containLabel: true }, xAxis: { type: 'category', data: data.dates || [], boundaryGap: false, axisLabel: { color: ct.text, rotate: 30, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'value', inverse: true, min: 1, max: Math.max(10, data.rank_max || 10), axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: (data.themes || []).map((name: string, index: number) => ({ name, type: 'line', connectNulls: false, symbol: 'circle', symbolSize: 3, lineStyle: { width: 1.8 }, emphasis: { focus: 'series', lineStyle: { width: 3 } }, data: data.values[index] })) }
  }
  if (key === 'promotion_funnel') {
    return { ...common, series: [{ type: 'funnel', left: '7%', right: '22%', top: 18, bottom: 18, minSize: '30%', maxSize: '100%', sort: 'none', gap: 3, label: { color: ct.textStrong, width: 118, overflow: 'break', formatter: (p: any) => `${p.name}  ${p.data.promoted}/${p.data.pool}  ${p.data.rate}%` }, labelLine: { length: 10, length2: 8 }, itemStyle: { borderColor: ct.border, borderWidth: 1 }, data: (data.stages || []).map((row: any) => ({ ...row, value: row.pool })) }] }
  }
  if (key === 'anomaly_calendar') {
    const records = data.records || []
    const max = Math.max(1, ...records.map((row: any) => row.value || 0))
    const start = new Date(`${data.start_date || records[0]?.date}T00:00:00`)
    const firstMonday = new Date(start)
    firstMonday.setDate(start.getDate() - ((start.getDay() + 6) % 7))
    const positioned = records.map((row: any) => {
      const day = new Date(`${row.date}T00:00:00`)
      const week = Math.floor((day.getTime() - firstMonday.getTime()) / 604800000)
      return { ...row, value: [week, (day.getDay() + 6) % 7, row.value] }
    })
    const weekCount = Math.max(1, ...positioned.map((row: any) => row.value[0] + 1))
    const weekLabels = Array.from({ length: weekCount }, (_, index) => { const day = new Date(firstMonday); day.setDate(day.getDate() + index * 7); return day.toISOString().slice(5, 10) })
    return { ...common, tooltip: { formatter: (p: any) => `${p.data.date}<br/>异常强度：${p.value[2]}<br/>指数收益：${p.data.return_pct}%<br/>状态：${p.data.state || '--'}` }, grid: { left: 12, right: 12, top: 18, bottom: 54, containLabel: true }, xAxis: { type: 'category', data: weekLabels, axisLabel: { color: ct.text, fontSize: 9, interval: 3 }, splitArea: { show: true, areaStyle: { color: [ct.tooltipBg, ct.tooltipBg] } } }, yAxis: { type: 'category', inverse: true, data: ['周一', '周二', '周三', '周四', '周五'], axisLabel: { color: ct.text, fontSize: 9 }, splitArea: { show: true, areaStyle: { color: [ct.tooltipBg, ct.tooltipBg] } } }, visualMap: { ...heatVisual(max), max }, series: [{ type: 'heatmap', data: positioned, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 2 } }] }
  }
  if (key === 'return_distribution') {
    return { ...common, grid: { left: 10, right: 12, top: 24, bottom: 16, containLabel: true }, xAxis: { type: 'category', data: data.bins || [], axisLabel: { color: ct.text, rotate: 35, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'value', axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'bar', data: (data.counts || []).map((value: number, index: number) => ({ value, itemStyle: { color: index < 5 ? GREEN : index > 5 ? RED : ct.text } })), barMaxWidth: 34, label: { show: true, position: 'top', color: ct.text, fontSize: 9 } }] }
  }
  if (key === 'advance_decline') {
    const divergences = data.divergences || []
    const markAreas = divergences.map((row: any) => ([{ xAxis: row.start_date, itemStyle: { color: row.type === 'bearish' ? 'rgba(248,81,73,.12)' : 'rgba(63,185,80,.12)' }, label: { show: false } }, { xAxis: row.end_date }]))
    const markPoints = divergences.map((row: any) => { const index = (data.dates || []).indexOf(row.end_date); return { name: row.label, coord: [row.end_date, data.ad_line?.[index]], symbol: 'pin', symbolSize: 34, itemStyle: { color: row.type === 'bearish' ? RED : GREEN }, label: { show: false } } })
    return { ...common, legend: { data: ['A/D 累积线', data.index_symbol || '指数'], textStyle: { color: ct.text } }, grid: { left: 10, right: 10, top: 36, bottom: 16, containLabel: true }, xAxis: { type: 'category', data: data.dates || [], boundaryGap: false, axisLabel: { color: ct.text, fontSize: 9, hideOverlap: true } }, yAxis: [{ type: 'value', axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, { type: 'value', axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { show: false } }], series: [{ name: 'A/D 累积线', type: 'line', symbol: 'none', data: data.ad_line || [], lineStyle: { color: ORANGE, width: 2 }, markArea: { silent: true, data: markAreas }, markPoint: { tooltip: { formatter: '{b}' }, data: markPoints } }, { name: data.index_symbol || '指数', type: 'line', yAxisIndex: 1, symbol: 'none', data: data.index_close || [], lineStyle: { color: BLUE, width: 1.5 } }] }
  }
  if (key === 'turnover_lorenz') {
    const points = data.points || []
    return { ...common, title: { text: `Gini ${data.gini ?? '--'}`, left: 'center', top: 2, textStyle: { color: ct.textStrong, fontSize: 11, fontWeight: 500 } }, grid: { left: 10, right: 12, top: 34, bottom: 16, containLabel: true }, xAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'line', symbol: 'none', data: points.map((row: any) => [row.population_pct, row.amount_pct]), lineStyle: { color: ORANGE, width: 2 }, areaStyle: { color: 'rgba(247,129,102,.12)' } }, { type: 'line', symbol: 'none', data: [[0, 0], [100, 100]], lineStyle: { color: ct.text, type: 'dashed' } }] }
  }
  if (key === 'industry_correlation') {
    const matrix = data.matrix || []
    const values = matrix.flatMap((row: Array<number | null>, y: number) => row.map((value, x) => [x, y, value]))
    return { ...common, grid: { left: 10, right: 12, top: 10, bottom: 78, containLabel: true }, xAxis: { type: 'category', data: data.industries || [], axisLabel: { color: ct.text, rotate: 50, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'category', data: data.industries || [], axisLabel: { color: ct.text, width: 72, overflow: 'truncate', fontSize: 9 } }, visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, inRange: { color: [GREEN, '#172033', RED] }, textStyle: { color: ct.text } }, series: [{ type: 'heatmap', data: values, tooltip: { formatter: (p: any) => `${data.industries[p.value[1]]} × ${data.industries[p.value[0]]}<br/>相关系数：${p.value[2] ?? '--'}` } }] }
  }
  if (key === 'mainline_waterfall') {
    const components = data.components || []
    let cumulative = 0
    const baseValues = components.map((row: any) => { const value = cumulative; cumulative += row.value || 0; return value })
    const labels = [...components.map((row: any) => row.name), '综合得分']
    return { ...common, title: { text: data.focus || '', subtext: `${data.trade_date || ''} · ${data.score ?? '--'} 分`, left: 'center', textStyle: { color: ct.textStrong, fontSize: 12 }, subtextStyle: { color: ct.text, fontSize: 9 } }, grid: { left: 10, right: 12, top: 62, bottom: 16, containLabel: true }, xAxis: { type: 'category', data: labels, axisLabel: { color: ct.text, fontSize: 9, interval: 0, hideOverlap: true } }, yAxis: { type: 'value', max: 100, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ name: '基座', type: 'bar', stack: 'total', itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }, data: [...baseValues, 0] }, { name: '贡献', type: 'bar', stack: 'total', data: [...components.map((row: any, index: number) => ({ value: row.value, raw: row.raw, itemStyle: { color: PALETTE[index] } })), { value: data.score, itemStyle: { color: RED } }], label: { show: true, position: 'top', color: ct.textStrong, formatter: (p: any) => `${p.value}` }, tooltip: { formatter: (p: any) => p.name === '综合得分' ? `${data.focus}<br/>综合得分：${p.value}` : `${p.name}<br/>得分贡献：${p.value}<br/>原始值：${p.data.raw}` } }] }
  }
  if (key === 'theme_ladder_sunburst') {
    return { ...common, tooltip: { formatter: (p: any) => p.data.stocks ? `${p.data.name}<br/>${p.data.stocks.join('、')}` : `${p.name}<br/>${p.value || 0} 股` }, series: [{ type: 'sunburst', center: ['50%', '51%'], radius: ['7%', '97%'], sort: null, nodeClick: 'rootToNode', emphasis: { focus: 'ancestor' }, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 1 }, data: data.children || [], levels: [{}, { r0: '7%', r: '48%', label: { rotate: 0, color: ct.textStrong, fontSize: 9, width: 62, overflow: 'break', lineHeight: 11, formatter: (p: any) => String(p.name).replace(/(.{4})/g, '$1\n') } }, { r0: '48%', r: '97%', label: { rotate: 'tangential', color: ct.textStrong, fontSize: 9, minAngle: 5, width: 92, overflow: 'truncate' } }] }] }
  }
  if (key === 'rps_rotation_clock') {
    const points = data.points || []
    const xExtent = Math.max(0.5, ...points.map((row: any) => Math.abs(row.momentum || 0))) * 1.18
    const yExtent = Math.max(0.5, ...points.map((row: any) => Math.abs(row.acceleration || 0))) * 1.18
    return { ...common, graphic: [{ type: 'text', left: '12%', top: 25, silent: true, style: { text: '弱势修复 ↖', fill: 'rgba(63,185,80,.75)', fontSize: 10 } }, { type: 'text', right: '8%', top: 25, silent: true, style: { text: '强势加速 ↗', fill: 'rgba(248,81,73,.8)', fontSize: 10 } }, { type: 'text', left: '12%', bottom: 24, silent: true, style: { text: '弱势恶化 ↙', fill: 'rgba(248,81,73,.65)', fontSize: 10 } }, { type: 'text', right: '8%', bottom: 24, silent: true, style: { text: '强势减速 ↘', fill: 'rgba(210,153,34,.8)', fontSize: 10 } }], grid: { left: 12, right: 18, top: 20, bottom: 14, containLabel: true }, xAxis: { type: 'value', min: -xExtent, max: xExtent, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', min: -yExtent, max: yExtent, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ type: 'scatter', symbolSize: 14, data: points.map((row: any, index: number) => ({ name: row.name, value: [row.momentum, row.acceleration], itemStyle: { color: PALETTE[index % PALETTE.length] }, label: { show: index < 10, position: row.momentum > 0 ? 'left' : 'right' } })), label: { color: ct.text, fontSize: 9, formatter: '{b}' }, labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' }, markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: ct.border, type: 'dashed', width: 1.5 }, data: [{ xAxis: 0 }, { yAxis: 0 }] } }] }
  }
  const values = data.values || []
  return { ...common, grid: { left: 10, right: 12, top: 12, bottom: 55, containLabel: true }, xAxis: { type: 'category', data: data.x_bins || [], axisLabel: { color: ct.text, rotate: 40, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'category', data: data.y_bins || [], axisLabel: { color: ct.text, width: 72, overflow: 'truncate', fontSize: 9 } }, visualMap: heatVisual(Math.max(1, ...values.map((row: number[]) => row[2]))), series: [{ type: 'heatmap', data: values, label: { show: true, color: (p: any) => p.value[2] === 0 ? ct.text : ct.textStrong, fontSize: 8, formatter: (p: any) => String(p.value[2]) } }] }
}

function EChart({ chartKey, card, height = 320, selection }: { chartKey: string; card: QuantXAdvancedCard; height?: number; selection?: ChartSelection }) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<echarts.ECharts | null>(null)
  const theme = useChartTheme()
  const option = useMemo(() => optionFor(chartKey, card.data, theme, selection), [card.data, chartKey, selection, theme])

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
  const [sectorDimension, setSectorDimension] = useState('sw_level1')
  const [sectorWindow, setSectorWindow] = useState(20)
  const selection = useMemo(() => ({ sectorDimension, sectorWindow }), [sectorDimension, sectorWindow])
  const heightByKey: Record<string, number> = {
    sentiment_phase: 340,
    liquidity_participation: 340,
    risk_transmission: 360,
    state_transition: 360,
    anomaly_calendar: 390,
    return_distribution: 390,
    advance_decline: 340,
    turnover_lorenz: 340,
    sector_diffusion: 610,
    theme_river: 390,
    industry_correlation: 440,
    mainline_waterfall: 440,
    theme_ladder_sunburst: 380,
    rps_rotation_clock: 380,
    promotion_funnel: 350,
    turnover_return_density: 350,
  }
  const height = heightByKey[chartKey] ?? 320
  return (
    <section data-testid={`quantx-advanced-${chartKey}`} className={cn('min-w-0 overflow-hidden rounded-lg border border-border bg-elevated/25 xl:[grid-column:span_8/span_8]', meta.span)}>
      <header className="flex min-h-11 items-center gap-2 border-b border-border/70 px-3 py-1.5">
        <Activity className="h-3.5 w-3.5 shrink-0 text-accent" />
        <div className="min-w-0"><h3 className="truncate text-xs font-semibold">{meta.title}</h3><p className="truncate text-[9px] text-muted">{meta.hint}</p></div>
        {card.status === 'ok' && <span className="ml-auto shrink-0 rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[9px] text-accent">{card.rows ?? 0} 行</span>}
      </header>
      <div className="p-2">
        {chartKey === 'sector_diffusion' && card.status === 'ok' && <div data-testid="quantx-sector-diffusion-controls" className="mb-1.5 flex flex-wrap items-center justify-between gap-1.5 border-b border-border/60 pb-1.5"><div className="flex gap-1" role="group" aria-label="行业层级">{Object.entries(card.data.views || {}).map(([value, view]: [string, any]) => <button key={value} type="button" data-testid={`quantx-sector-dimension-${value}`} aria-pressed={sectorDimension === value} onClick={() => setSectorDimension(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors', sectorDimension === value ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted hover:text-foreground')}>{view.label || value}</button>)}</div><div className="flex gap-1" role="group" aria-label="均线窗口">{[5, 10, 20].map(value => <button key={value} type="button" data-testid={`quantx-sector-window-${value}`} aria-pressed={sectorWindow === value} onClick={() => setSectorWindow(value)} className={cn('cursor-pointer rounded border px-2 py-1 font-mono text-[9px] transition-colors', sectorWindow === value ? 'border-orange-400/60 bg-orange-400/10 text-orange-300' : 'border-border bg-base text-muted hover:text-foreground')}>MA{value}</button>)}</div></div>}
        {card.status === 'ok' ? <EChart chartKey={chartKey} card={card} height={height} selection={selection} /> : <div className="flex items-center justify-center text-xs text-muted" style={{ height }}><span>{card.reason || '暂无足够数据'}</span></div>}
        {chartKey === 'turnover_lorenz' && card.status === 'ok' && <p data-testid="quantx-lorenz-guide" className="border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-muted">看法：曲线越向右下弯、Gini 越高，成交越集中于少数个股；越接近虚线，市场成交越均衡。</p>}
        {chartKey === 'advance_decline' && card.status === 'ok' && <p data-testid="quantx-ad-divergence-guide" className="border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-muted">红色区间：指数走强但市场广度转弱；绿色区间：指数走弱但广度修复。图钉标记背离确认点。</p>}
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
