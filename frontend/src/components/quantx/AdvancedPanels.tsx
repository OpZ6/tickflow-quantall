import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { Activity, ChartPie, GitBranch, Loader2, Orbit, Radar, Table2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
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
type ChartSelection = { sectorDimension?: string; sectorWindow?: number; correlationDimension?: string; mainlineFocus?: string; promotionWindow?: string; rotationTrail?: 'focus' | 'all' | 'off'; stateTransitionWindow?: '500' | 'all' }
export type AdvancedCardLayout = { span?: 6 | 7 | 8 | 9 | 10 | 16; height?: number }

const SPAN_CLASSES: Record<NonNullable<AdvancedCardLayout['span']>, string> = {
  6: 'xl:[grid-column:span_6/span_6]',
  7: 'xl:[grid-column:span_7/span_7]',
  8: 'xl:[grid-column:span_8/span_8]',
  9: 'xl:[grid-column:span_9/span_9]',
  10: 'xl:[grid-column:span_10/span_10]',
  16: 'xl:[grid-column:span_16/span_16]',
}

const CARD_META: Record<string, { title: string; hint: string; group: 'state' | 'rotation' | 'structure'; span?: string; caveat?: string }> = {
  sentiment_phase: { title: '市场情绪状态相图', hint: '趋势情绪 × 短线情绪 · 气泡为涨停家数', group: 'state' },
  liquidity_participation: { title: '流动性—参与度四象限', hint: '全市场成交额 × 上涨家数占比', group: 'state' },
  state_transition: { title: '市场状态转移矩阵', hint: '五状态的下一交易日条件转移概率 · 色阶上限 50%', group: 'state', span: 'xl:[grid-column:span_6/span_6]' },
  anomaly_calendar: { title: '2026 年异常交易日', hint: '年初至今 · 仅显示交易日 · 综合收益、广度、涨停与成交额', group: 'state', span: 'xl:[grid-column:span_10/span_10]' },
  return_distribution: { title: '全市场收益分布剖面', hint: '当日全 A 收益横截面与中位数', group: 'state', span: 'xl:[grid-column:span_6/span_6]' },
  advance_decline: { title: 'A/D 累积线与指数背离', hint: '涨跌家数差累积 vs 中证全指 · 阴影标出背离区间', group: 'state', span: 'xl:[grid-column:span_9/span_9]' },
  turnover_lorenz: { title: '成交额洛伦兹曲线与 Gini', hint: '实线为当日；虚线对比昨日、前 20 个交易日均值', group: 'state', span: 'xl:[grid-column:span_7/span_7]' },
  sector_diffusion: { title: '申万行业宽度扩散地图', hint: '切换一级/二级行业及 MA5 / MA10 / MA20', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]' },
  theme_river: { title: '题材单源排名演进', hint: '近 20 日同一榜单逐日名次 · 数字越小、颜色越热；不与多源强度混算', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]' },
  industry_correlation: { title: '行业收益相关性矩阵', hint: '切换同花顺一级/二级行业 · 近 35 日收益相关性', group: 'rotation', span: 'xl:[grid-column:span_16/span_16]', caveat: '行业收益按当前行业成分回看历史计算，不是历史时点成分；越接近当前日期越可靠。' },
  mainline_waterfall: { title: '主线强度贡献瀑布', hint: '切换各条主线，细分涨停广度、连板高度与梯队完整度', group: 'rotation', caveat: '主线历史按当前概念成分回看历史计算，不是历史时点成分；越接近当前日期越可靠。' },
  theme_ladder_sunburst: { title: '题材—连板梯队', hint: '旭日图看核心题材，梯队表核对全部涨停', group: 'rotation', span: 'xl:[grid-column:span_8/span_8]' },
  rps_rotation_clock: { title: '行业 RPS 轮动时钟', hint: '行业横截面相对强度 × 排名加速度 · 中心为行业中位数', group: 'rotation', span: 'xl:[grid-column:span_8/span_8]', caveat: '行业收益按当前行业成分回看历史计算，不是历史时点成分；越接近当前日期越可靠。' },
  promotion_funnel: { title: '连板晋级阶梯', hint: '当天 / 5日 / 20日晋级效率 · 全样本基线始终对照', group: 'structure', span: 'xl:[grid-column:span_9/span_9]' },
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
  if (key === 'state_transition') {
    const windowKey = selection.stateTransitionWindow || data.default_view || '500'
    const view = data.views?.[windowKey] || data
    const matrix = view.matrix || []
    const values = matrix.flatMap((row: number[], y: number) => row.map((value, x) => [x, y, value]))
    const visualMax = view.visual_max || Math.max(5, ...values.map((row: number[]) => row[2]))
    return { ...common, grid: { left: 10, right: 12, top: 15, bottom: 50, containLabel: true }, xAxis: { type: 'category', data: view.labels || [], axisLabel: { color: ct.text, hideOverlap: true } }, yAxis: { type: 'category', data: view.labels || [], axisLabel: { color: ct.text, hideOverlap: true } }, visualMap: { ...heatVisual(visualMax), min: 0, max: visualMax, precision: 0 }, series: [{ type: 'heatmap', data: values, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 2 }, label: { show: true, color: ct.textStrong, formatter: (p: any) => `${p.value[2]}%` }, tooltip: { formatter: (p: any) => `${view.labels[p.value[1]]} → ${view.labels[p.value[0]]}<br/>概率：${p.value[2]}%<br/>样本：${view.counts?.[p.value[1]]?.[p.value[0]] ?? 0} 次` } }] }
  }
  if (key === 'sector_diffusion') {
    const dimension = selection.sectorDimension || data.default_dimension || 'sw_level1'
    const window = selection.sectorWindow || data.default_window || 20
    const view = data.views?.[dimension] || { sectors: data.sectors || [], metrics: { '20': data.values || [] } }
    const dates = view.dates || data.dates || []
    const matrix = view.metrics?.[String(window)] || []
    const values = matrix.flatMap((row: Array<number | null>, y: number) => row.map((value, x) => [x, y, value]))
    const sectors = view.sectors || []
    const zoom = sectors.length > 48 ? [{ type: 'inside', yAxisIndex: 0, startValue: 0, endValue: 47 }, { type: 'slider', yAxisIndex: 0, right: 2, width: 10, startValue: 0, endValue: 47, textStyle: { color: ct.text }, borderColor: ct.border }] : []
    return { ...common, grid: { left: 10, right: sectors.length > 48 ? 34 : 12, top: 10, bottom: 50, containLabel: true }, dataZoom: zoom, xAxis: { type: 'category', data: dates, axisLabel: { color: ct.text, rotate: 35, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'category', data: sectors, axisLabel: { color: ct.text, width: dimension === 'sw_level2' ? 104 : 76, overflow: 'truncate', fontSize: 9 } }, visualMap: { ...heatVisual(100), min: 0, max: 100 }, series: [{ type: 'heatmap', data: values, progressive: 1000, tooltip: { formatter: (p: any) => `${dates[p.value[0]]}<br/>${sectors[p.value[1]]}<br/>MA${window} 宽度：${p.value[2] ?? '--'}%` } }] }
  }
  if (key === 'theme_river') {
    const themes = data.themes || []
    const dates = data.dates || []
    const values = (data.values || []).flatMap((row: Array<number | null>, y: number) => row.flatMap((value, x) => value == null ? [] : [[x, y, value]]))
    return { ...common, grid: { left: 10, right: 12, top: 10, bottom: 52, containLabel: true }, xAxis: { type: 'category', data: dates, axisLabel: { color: ct.text, rotate: 30, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'category', inverse: true, data: themes, axisLabel: { color: ct.textStrong, width: 112, overflow: 'truncate', fontSize: 10 } }, visualMap: { min: 1, max: Math.max(10, data.rank_max || 10), calculable: true, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, inverse: true, text: ['靠后', '第1名'], inRange: { color: [RED, ORANGE, '#244b75', '#101a2d'] }, textStyle: { color: ct.text, fontSize: 9 } }, series: [{ type: 'heatmap', data: values, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 1 }, label: { show: true, color: ct.textStrong, fontSize: 8, textBorderColor: 'rgba(0,0,0,.8)', textBorderWidth: 2, formatter: (p: any) => String(p.value[2]) }, tooltip: { formatter: (p: any) => `${themes[p.value[1]]}<br/>${dates[p.value[0]]}<br/>${data.source || '单一来源'}排名：第 ${p.value[2]} 名` } }] }
  }
  if (key === 'promotion_funnel') {
    const windowKey = selection.promotionWindow || data.default_view || 'current'
    const view = data.views?.[windowKey] || { label: '全样本', stages: data.stages || [], sample_days: data.sample_days }
    const stages = view.stages || []
    const baseline = data.baseline?.stages || data.stages || []
    const baselineByName = new Map<string, any>(baseline.map((row: any): [string, any] => [row.name, row]))
    const selectedLabel = `${view.label || windowKey}晋级率`
    return {
      ...common,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: any[]) => {
          const index = params.find(param => param.dataIndex != null)?.dataIndex ?? 0
          const row = stages[index] || {}
          const baseRow: any = baselineByName.get(row.name) || {}
          const selectedRate = row.rate == null ? '无样本' : `${row.rate}%`
          const baselineRate = baseRow.rate == null ? '无样本' : `${baseRow.rate}%`
          return `${row.name}<br/>${row.basis === 'same_day_seal' ? '当日首板尝试' : '前一交易日该高度样本'}：${row.pool || 0}<br/>晋级/封板：${row.promoted || 0}<br/>${selectedLabel}：${selectedRate}<br/>全样本基线：${baselineRate}`
        },
      },
      legend: { top: 0, data: [selectedLabel, '未晋级（含炸板）', '全样本基线'], textStyle: { color: ct.text, fontSize: 9 } },
      grid: { left: 12, right: 92, top: 32, bottom: 12, containLabel: true },
      xAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: ct.text, formatter: '{value}%' }, splitLine: { lineStyle: { color: ct.grid } } },
      yAxis: { type: 'category', inverse: true, data: stages.map((row: any) => row.name), axisLabel: { color: ct.textStrong, fontSize: 10 } },
      series: [
        { name: selectedLabel, type: 'bar', stack: 'conversion', barWidth: 18, data: stages.map((row: any, index: number) => ({ value: row.rate, itemStyle: { color: index === 0 ? ORANGE : RED, borderRadius: [3, 0, 0, 3] } })) },
        { name: '未晋级（含炸板）', type: 'bar', stack: 'conversion', barWidth: 18, data: stages.map((row: any) => ({ value: row.rate == null ? null : Math.max(0, 100 - row.rate), itemStyle: { color: ct.grid, borderRadius: [0, 3, 3, 0] } })), label: { show: true, position: 'right', color: ct.textStrong, fontSize: 9, formatter: (p: any) => { const row = stages[p.dataIndex]; return row.rate == null ? '-- · 无样本' : `${row.promoted}/${row.pool} · ${row.rate}%` } } },
        { name: '全样本基线', type: 'line', symbol: 'diamond', symbolSize: 9, data: stages.map((row: any) => [baselineByName.get(row.name)?.rate ?? null, row.name]), lineStyle: { color: BLUE, width: 1.5, type: 'dashed' }, itemStyle: { color: BLUE }, z: 5 },
      ],
    }
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
    const weekLabels = Array.from({ length: weekCount }, (_, index) => { if (index === 0 && data.start_date) return String(data.start_date).slice(5); const day = new Date(firstMonday); day.setDate(day.getDate() + index * 7); return day.toISOString().slice(5, 10) })
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
    const previous = data.previous || {}
    const periodMean = data.period_mean || {}
    const previousName = previous.date ? `昨日 ${String(previous.date).slice(5)}` : '昨日'
    const periodName = periodMean.days ? `前 ${periodMean.days} 日均值` : '近期均值'
    const subtitle = [previous.gini != null ? `昨日 ${previous.gini}` : null, periodMean.gini != null ? `前${periodMean.days}日均值 ${periodMean.gini}` : null].filter(Boolean).join(' · ')
    return {
      ...common,
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${Number(value).toFixed(2)}%` },
      title: { text: `当日 Gini ${data.gini ?? '--'}`, subtext: subtitle, left: 'center', top: 0, textStyle: { color: ct.textStrong, fontSize: 11, fontWeight: 500 }, subtextStyle: { color: ct.text, fontSize: 9 } },
      legend: { top: 38, data: ['当日', previousName, periodName, '完全均等'], textStyle: { color: ct.text, fontSize: 9 }, itemWidth: 18, itemHeight: 8 },
      grid: { left: 10, right: 12, top: 70, bottom: 16, containLabel: true },
      xAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: ct.text, formatter: '{value}%', hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } },
      yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: ct.text, formatter: '{value}%', hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } },
      series: [
        { name: '当日', type: 'line', symbol: 'none', data: points.map((row: any) => [row.population_pct, row.amount_pct]), lineStyle: { color: ORANGE, width: 2.5 }, areaStyle: { color: 'rgba(247,129,102,.10)' }, z: 4 },
        { name: previousName, type: 'line', symbol: 'none', data: (previous.points || []).map((row: any) => [row.population_pct, row.amount_pct]), lineStyle: { color: BLUE, width: 1.5, type: 'dashed' }, z: 3 },
        { name: periodName, type: 'line', symbol: 'none', data: (periodMean.points || []).map((row: any) => [row.population_pct, row.amount_pct]), lineStyle: { color: PURPLE, width: 1.5, type: 'dashed' }, z: 2 },
        { name: '完全均等', type: 'line', symbol: 'none', data: [[0, 0], [100, 100]], lineStyle: { color: ct.text, width: 1, type: 'dotted', opacity: 0.65 }, z: 1 },
      ],
    }
  }
  if (key === 'industry_correlation') {
    const dimension = selection.correlationDimension || data.default_dimension || 'industry_level1'
    const view = data.views?.[dimension] || data
    const industries = view.industries || []
    const matrix = view.matrix || []
    const values = matrix.flatMap((row: Array<number | null>, y: number) => row.map((value, x) => [x, y, value]))
    const zoomed = industries.length > 50
    const dataZoom = zoomed ? [{ type: 'inside', xAxisIndex: 0, startValue: 0, endValue: 49 }, { type: 'slider', xAxisIndex: 0, bottom: 30, height: 10, startValue: 0, endValue: 49, textStyle: { color: ct.text }, borderColor: ct.border }, { type: 'inside', yAxisIndex: 0, startValue: 0, endValue: 49 }, { type: 'slider', yAxisIndex: 0, right: 2, width: 10, startValue: 0, endValue: 49, textStyle: { color: ct.text }, borderColor: ct.border }] : []
    return { ...common, grid: { left: 10, right: zoomed ? 34 : 12, top: 10, bottom: zoomed ? 96 : 78, containLabel: true }, dataZoom, xAxis: { type: 'category', data: industries, triggerEvent: true, axisLabel: { color: ct.text, rotate: 50, fontSize: 8, hideOverlap: true } }, yAxis: { type: 'category', data: industries, triggerEvent: true, axisLabel: { color: ct.text, width: 92, overflow: 'truncate', fontSize: 8 } }, visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, inRange: { color: [GREEN, '#172033', RED] }, textStyle: { color: ct.text } }, series: [{ type: 'heatmap', data: values, progressive: 10000, tooltip: { formatter: (p: any) => `${industries[p.value[1]]} × ${industries[p.value[0]]}<br/>相关系数：${p.value[2] ?? '--'}<br/>样本：${view.sample_days || 0} 日<br/>点击聚焦：${industries[p.value[1]]}` } }] }
  }
  if (key === 'mainline_waterfall') {
    const selected = (data.mainlines || []).find((row: any) => row.focus === selection.mainlineFocus) || (data.mainlines || [])[0] || data
    const components = selected.components || []
    let cumulative = 0
    const baseValues = components.map((row: any) => { const value = cumulative; cumulative += row.value || 0; return value })
    const labels = [...components.map((row: any) => row.name), '综合得分']
    return { ...common, title: { text: selected.focus || '', subtext: `${data.trade_date || ''} · 第 ${selected.rank ?? '--'} 名 · ${selected.score ?? '--'} 分${selected.leader_symbol ? ` · 龙头 ${selected.leader_symbol}` : ''}`, left: 'center', textStyle: { color: ct.textStrong, fontSize: 12 }, subtextStyle: { color: ct.text, fontSize: 9 } }, grid: { left: 10, right: 12, top: 62, bottom: 16, containLabel: true }, xAxis: { type: 'category', data: labels, axisLabel: { color: ct.text, fontSize: 9, interval: 0, hideOverlap: true } }, yAxis: { type: 'value', max: 100, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: [{ name: '基座', type: 'bar', stack: 'total', itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }, data: [...baseValues, 0] }, { name: '贡献', type: 'bar', stack: 'total', data: [...components.map((row: any, index: number) => ({ value: row.value, raw: row.raw, itemStyle: { color: PALETTE[index] } })), { value: selected.score, itemStyle: { color: RED } }], label: { show: true, position: 'top', color: ct.textStrong, formatter: (p: any) => `${p.value}` }, tooltip: { formatter: (p: any) => p.name === '综合得分' ? `${selected.focus}<br/>综合得分：${p.value}` : `${p.name}<br/>得分贡献：${p.value}<br/>原始值：${p.data.raw}` } }] }
  }
  if (key === 'theme_ladder_sunburst') {
    return { ...common, tooltip: { formatter: (p: any) => p.data.stocks ? `${p.data.name}<br/>${p.data.stocks.join('、')}` : `${p.name}<br/>${p.value || 0} 股` }, series: [{ type: 'sunburst', center: ['50%', '51%'], radius: ['7%', '97%'], sort: null, nodeClick: 'rootToNode', emphasis: { focus: 'ancestor' }, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 1 }, data: data.children || [], levels: [{}, { r0: '7%', r: '48%', label: { rotate: 0, color: ct.textStrong, fontSize: 9, width: 62, overflow: 'break', lineHeight: 11, formatter: (p: any) => String(p.name).replace(/(.{4})/g, '$1\n') } }, { r0: '48%', r: '97%', label: { rotate: 'tangential', color: ct.textStrong, fontSize: 9, minAngle: 5, width: 92, overflow: 'truncate' } }] }] }
  }
  if (key === 'rps_rotation_clock') {
    const points = data.points || []
    const trailMode = selection.rotationTrail || 'focus'
    const rankedMovers = [...points].filter((row: any) => row.previous_momentum != null && row.previous_acceleration != null).sort((a: any, b: any) => (b.movement || 0) - (a.movement || 0))
    const trailedNames = new Set((trailMode === 'all' ? rankedMovers : trailMode === 'focus' ? rankedMovers.slice(0, 8) : []).map((row: any) => row.name))
    const visibleTrails = points.filter((row: any) => trailedNames.has(row.name))
    const xExtent = Math.max(0.5, ...points.flatMap((row: any) => [Math.abs(row.momentum || 0), Math.abs(row.previous_momentum || 0)])) * 1.18
    const yExtent = Math.max(0.5, ...points.flatMap((row: any) => [Math.abs(row.acceleration || 0), Math.abs(row.previous_acceleration || 0)])) * 1.18
    return { ...common, graphic: [{ type: 'text', left: '12%', top: 25, silent: true, style: { text: '弱势修复 ↖', fill: 'rgba(63,185,80,.8)', fontSize: 10 } }, { type: 'text', right: '8%', top: 25, silent: true, style: { text: '强势加速 ↗', fill: 'rgba(248,81,73,.9)', fontSize: 10 } }, { type: 'text', left: '12%', bottom: 28, silent: true, style: { text: '弱势恶化 ↙', fill: 'rgba(248,81,73,.75)', fontSize: 10 } }, { type: 'text', right: '8%', bottom: 28, silent: true, style: { text: '强势减速 ↘', fill: 'rgba(210,153,34,.9)', fontSize: 10 } }], grid: { left: 12, right: 18, top: 20, bottom: 18, containLabel: true }, xAxis: { type: 'value', name: '相对强度', nameTextStyle: { color: ct.text, fontSize: 9 }, min: -xExtent, max: xExtent, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, yAxis: { type: 'value', name: '排名加速度', nameTextStyle: { color: ct.text, fontSize: 9 }, min: -yExtent, max: yExtent, axisLabel: { color: ct.text, hideOverlap: true }, splitLine: { lineStyle: { color: ct.grid } } }, series: [
      { name: '昨日位置', type: 'scatter', silent: true, symbol: 'emptyCircle', symbolSize: 9, data: visibleTrails.map((row: any) => ({ name: row.name, value: [row.previous_momentum, row.previous_acceleration], itemStyle: { color: ct.text, opacity: 0.18 } })), z: 1 },
      { name: '昨日到今日', type: 'lines', coordinateSystem: 'cartesian2d', silent: true, symbol: ['none', 'arrow'], symbolSize: [0, 6], lineStyle: { color: ct.text, width: 1, opacity: 0.28 }, data: visibleTrails.map((row: any) => ({ name: row.name, coords: [[row.previous_momentum, row.previous_acceleration], [row.momentum, row.acceleration]] })), z: 2 },
      { type: 'scatter', symbolSize: 13, data: points.map((row: any, index: number) => ({ name: row.name, value: [row.momentum, row.acceleration, row.recent_rps, row.recent_return_pct, row.movement], itemStyle: { color: PALETTE[index % PALETTE.length] }, label: { show: Math.abs(row.momentum || 0) + Math.abs(row.acceleration || 0) >= 48, position: row.momentum > 0 ? 'left' : 'right' } })), label: { color: ct.textStrong, fontSize: 9, formatter: '{b}' }, labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' }, tooltip: { formatter: (p: any) => `${p.name}<br/>当前 RPS：${p.value[2]}<br/>排名加速度：${p.value[1]}<br/>近 5 日收益：${p.value[3]}%<br/>较昨日位移：${p.value[4] ?? '--'}` }, markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: ct.border, type: 'dashed', width: 1.5 }, data: [{ xAxis: 0 }, { yAxis: 0 }] }, z: 3 },
    ] }
  }
  const values = data.values || []
  return { ...common, grid: { left: 10, right: 12, top: 12, bottom: 55, containLabel: true }, xAxis: { type: 'category', data: data.x_bins || [], axisLabel: { color: ct.text, rotate: 40, fontSize: 9, hideOverlap: true } }, yAxis: { type: 'category', data: data.y_bins || [], axisLabel: { color: ct.text, width: 72, overflow: 'truncate', fontSize: 9 } }, visualMap: heatVisual(Math.max(1, ...values.map((row: number[]) => row[2]))), series: [{ type: 'heatmap', data: values, itemStyle: { borderColor: ct.tooltipBg, borderWidth: 1 }, label: { show: true, color: '#ffffff', backgroundColor: 'rgba(0,0,0,.66)', borderRadius: 2, padding: [1, 3], fontSize: 8, formatter: (p: any) => String(p.value[2]) }, tooltip: { formatter: (p: any) => `${data.x_bins[p.value[0]]} 换手<br/>${data.y_bins[p.value[1]]} 收益<br/>股票数：${p.value[2]}` } }] }
}

function EChart({ chartKey, card, height = 320, selection, onClick }: { chartKey: string; card: QuantXAdvancedCard; height?: number; selection?: ChartSelection; onClick?: (params: any) => void }) {
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
    const chart = instance.current
    if (!chart) return
    chart.off('click')
    if (onClick) chart.on('click', onClick)
    return () => { chart.off('click') }
  }, [onClick])

  useEffect(() => {
    const observer = new ResizeObserver(() => instance.current?.resize())
    if (container.current) observer.observe(container.current)
    return () => { observer.disconnect(); instance.current?.dispose(); instance.current = null }
  }, [])

  return <div ref={container} role="img" aria-label={CARD_META[chartKey].title} className="w-full" style={{ height }} />
}

type CorrelationPair = { left: string; right: string; correlation: number }

function correlationRankings(view: Record<string, any>, selectedIndustry: string): { highest: CorrelationPair[]; lowest: CorrelationPair[] } {
  const industries: string[] = view.industries || []
  const matrix: Array<Array<number | null>> = view.matrix || []
  const pairs: CorrelationPair[] = []
  if (selectedIndustry) {
    const selectedIndex = industries.indexOf(selectedIndustry)
    if (selectedIndex >= 0) industries.forEach((industry, index) => {
      if (index === selectedIndex) return
      const value = matrix[selectedIndex]?.[index] ?? matrix[index]?.[selectedIndex]
      if (typeof value === 'number' && Number.isFinite(value)) pairs.push({ left: selectedIndustry, right: industry, correlation: value })
    })
  } else {
    industries.forEach((left, leftIndex) => industries.slice(leftIndex + 1).forEach((right, offset) => {
      const rightIndex = leftIndex + offset + 1
      const value = matrix[leftIndex]?.[rightIndex] ?? matrix[rightIndex]?.[leftIndex]
      if (typeof value === 'number' && Number.isFinite(value)) pairs.push({ left, right, correlation: value })
    }))
  }
  if (!pairs.length && !selectedIndustry) {
    pairs.push(...(view.pair_rankings?.highest || []), ...(view.pair_rankings?.lowest || []))
  }
  return {
    highest: [...pairs].sort((left, right) => right.correlation - left.correlation).slice(0, 10),
    lowest: [...pairs].sort((left, right) => left.correlation - right.correlation).slice(0, 10),
  }
}

function CorrelationPairRankings({ view, selectedIndustry, onSelectIndustry }: { view: Record<string, any>; selectedIndustry: string; onSelectIndustry: (industry: string) => void }) {
  const rankings = useMemo(() => correlationRankings(view, selectedIndustry), [selectedIndustry, view])
  const groups: Array<[string, string, any[]]> = [
    ['highest', selectedIndustry ? `与${selectedIndustry}相关度前 10` : '全市场相关度前 10', rankings.highest],
    ['lowest', selectedIndustry ? `与${selectedIndustry}相关度后 10` : '全市场相关度后 10', rankings.lowest],
  ]
  return <section data-testid="quantx-correlation-pair-rankings" className="mt-2 border-t border-border/60 pt-2">
    <div className="mb-1.5 flex flex-wrap items-center gap-2"><div className="mr-auto"><h4 className="text-[10px] font-semibold">行业组合相关度排行</h4><p className="text-[9px] text-muted">近 {view.sample_days || 0} 日 Pearson 系数 · 点击矩阵、行业名或下拉框聚焦</p></div><label className="flex items-center gap-1.5 text-[9px] text-muted">聚焦行业<select data-testid="quantx-correlation-industry-select" aria-label="选择行业查看相关度排行" value={selectedIndustry} onChange={event => onSelectIndustry(event.target.value)} className="max-w-48 cursor-pointer rounded border border-border bg-base px-2 py-1 text-[10px] text-foreground"><option value="">全部行业（总排名）</option>{(view.industries || []).map((industry: string) => <option key={industry} value={industry}>{industry}</option>)}</select></label>{selectedIndustry && <button type="button" data-testid="quantx-correlation-clear-industry" onClick={() => onSelectIndustry('')} className="cursor-pointer rounded border border-border bg-base px-2 py-1 text-[9px] text-muted transition-colors hover:text-foreground">恢复总排名</button>}</div>
    <div data-testid="quantx-correlation-ranking-context" aria-live="polite" className="mb-1.5 rounded border border-border/60 bg-base/25 px-2 py-1 text-[9px] text-muted">{selectedIndustry ? <>当前聚焦 <b className="text-accent">{selectedIndustry}</b>，共对比 {rankings.highest.length || rankings.lowest.length ? Math.max(0, (view.industries?.length || 1) - 1) : 0} 个其他行业</> : <>当前显示全部行业组合总排名，共 {Math.max(0, ((view.industries?.length || 0) * ((view.industries?.length || 0) - 1)) / 2)} 组</>}</div>
    <div className="grid gap-2 md:grid-cols-2">{groups.map(([key, title, rows]) => <div key={key} className="rounded border border-border/60 bg-base/25 p-2"><h5 className="mb-1 text-[10px] font-semibold text-muted">{title}</h5><div className="space-y-1">{rows.map((row, index) => <div key={`${row.left}-${row.right}`} data-testid={`quantx-correlation-pair-${key}`} className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-1.5 text-[9px]"><span className="font-mono text-muted">{index + 1}</span><span className="flex min-w-0 items-center gap-1"><button type="button" data-industry={row.left} onClick={() => onSelectIndustry(row.left)} className={cn('min-w-0 flex-1 cursor-pointer truncate transition-colors hover:text-accent', selectedIndustry === row.left && 'text-accent')} title={`聚焦 ${row.left}`}>{row.left}</button><span className="shrink-0 text-muted">×</span><button type="button" data-industry={row.right} onClick={() => onSelectIndustry(row.right)} className={cn('min-w-0 flex-1 cursor-pointer truncate transition-colors hover:text-accent', selectedIndustry === row.right && 'text-accent')} title={`聚焦 ${row.right}`}>{row.right}</button></span><span className={cn('font-mono tabular-nums', row.correlation < 0 ? 'text-green-300' : 'text-red-300')}>{row.correlation > 0 ? '+' : ''}{row.correlation.toFixed(3)}</span></div>)}{!rows.length && <div className="py-3 text-center text-[9px] text-muted">暂无足够样本</div>}</div></div>)}</div>
    <p className="mt-1.5 text-[9px] leading-4 text-muted">高正相关表示近期走势更同步；低值或负相关表示分化更明显。相关性描述共同波动，不代表因果关系或未来收益。</p>
  </section>
}

type LadderMember = {
  symbol: string
  name: string
  height: number
  theme: string
  category: string
  exchange: string
  source: string
  is_supplemental: boolean
  is_fallback: boolean
  board_kind: '10cm' | '20cm' | '30cm'
  matrix_theme: string
  subtheme: string
  limit_reason: string
  theme_reason: string
  interpretation: string
  reason: string
  reason_kind: '个股解读' | '涨停理由' | '题材催化' | '暂无理由'
  classification_basis?: 'ladder' | 'previous_ladder' | 'limit_reason' | 'unclassified'
}

type LadderTheme = { name: string; category: string; count: number; max_height: number; subthemes: string[] }

function LadderMatrix({ data }: { data: Record<string, any> }) {
  const navigate = useNavigate()
  const [detailMode, setDetailMode] = useState<'compact' | 'detailed'>('compact')
  const members = (data.members || []) as LadderMember[]
  const themes = (data.matrix?.themes || []) as LadderTheme[]
  const heights = (data.matrix?.heights || []) as number[]
  const coverage = data.coverage || {}
  const cells = useMemo(() => {
    const result = new Map<string, LadderMember[]>()
    members.forEach(member => {
      const key = `${member.height}::${member.matrix_theme || member.theme}`
      const rows = result.get(key) || []
      rows.push(member)
      result.set(key, rows)
    })
    return result
  }, [members])
  const stockClass = (member: LadderMember) => cn(
    'group flex w-full cursor-pointer items-center gap-1 rounded px-1.5 py-1 text-left text-[10px] leading-4 transition-colors hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent',
    member.board_kind === '30cm' ? 'text-fuchsia-300' : member.board_kind === '20cm' ? 'text-blue-300' : 'text-red-300',
    member.is_supplemental && 'border border-dashed border-orange-400/50 bg-orange-400/5',
  )
  if (!themes.length || !heights.length) return <div className="flex h-72 items-center justify-center text-xs text-muted">暂无可展示的涨停梯队</div>
  return <div data-testid="quantx-ladder-matrix" className="space-y-2">
    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
      {[
        ['涨停总数', coverage.limit_up_count],
        ['主源梯队', coverage.ladder_count],
        ['补录', coverage.supplemental_count],
        ['已归类', coverage.classified_count],
        ['待归类', coverage.unclassified_count],
        ['旭日图覆盖', coverage.sunburst_count],
      ].map(([label, value]) => <div key={String(label)} className="rounded border border-border/70 bg-base/35 px-2 py-1.5"><div className="text-[9px] text-muted">{label}</div><div className="font-mono text-sm font-semibold tabular-nums text-foreground">{value ?? 0}<span className="ml-0.5 text-[9px] font-normal text-muted">只</span></div></div>)}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-border/70 bg-base/25 px-2 py-1.5">
      <p className="text-[9px] text-muted">简洁模式看梯队，详细模式展开逐股真实理由与催化依据。</p>
      <div className="flex gap-1" role="group" aria-label="梯队表信息密度">
        {([['compact', '简洁'], ['detailed', '详细']] as const).map(([value, label]) => <button key={value} type="button" data-testid={`quantx-ladder-detail-${value}`} aria-pressed={detailMode === value} onClick={() => setDetailMode(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent', detailMode === value ? 'border-purple-400/60 bg-purple-400/10 text-purple-300' : 'border-border bg-base text-muted hover:text-foreground')}>{label}</button>)}
      </div>
    </div>
    <div data-testid="quantx-ladder-scroll-region" className="max-w-full overflow-x-auto overflow-y-visible rounded border border-border" tabIndex={0} aria-label="题材与连板高度梯队表，仅横向滚动查看全部题材">
      <table className="border-separate border-spacing-0 text-[10px]" style={{ minWidth: `${Math.max(900, 74 + themes.length * 126)}px` }}>
        <thead>
          <tr>
            <th className="sticky left-0 top-0 z-30 w-[74px] border-b border-r border-border bg-elevated px-2 py-2 text-center font-semibold text-foreground">连板高度</th>
            {themes.map(theme => <th key={theme.name} className="sticky top-0 z-20 min-w-[126px] border-b border-r border-border bg-elevated px-2 py-1.5 text-center align-top">
              <span className={cn('mb-0.5 block text-[8px] font-normal', theme.category === '待归类' ? 'text-orange-300' : theme.category === '公告/事件' ? 'text-purple-300' : 'text-muted')}>{theme.category}</span>
              <span className="block truncate font-semibold text-foreground" title={theme.name}>{theme.name}</span>
              <span className="font-mono text-[8px] font-normal text-muted">最高{theme.max_height}板 · {theme.count}只</span>
            </th>)}
          </tr>
        </thead>
        <tbody>
          {heights.map(heightValue => <tr key={heightValue}>
            <th className={cn('sticky left-0 z-10 border-b border-r border-border px-2 py-2 text-center font-mono font-semibold', heightValue >= 3 ? 'bg-red-500/10 text-red-300' : heightValue === 2 ? 'bg-orange-400/10 text-orange-300' : 'bg-elevated text-muted')}>{heightValue === 1 ? '首板' : `${heightValue}连板`}</th>
            {themes.map(theme => {
              const stocks = cells.get(`${heightValue}::${theme.name}`) || []
              return <td key={`${heightValue}-${theme.name}`} className={cn('border-b border-r border-border/70 p-1 align-top', heightValue >= 2 ? 'bg-blue-400/[0.035]' : 'bg-base/20')}>
                <div className="space-y-0.5">{stocks.map(member => <button
                  key={member.symbol}
                  type="button"
                  className={stockClass(member)}
                  title={`${member.name} ${member.symbol} · ${member.height}板 · ${member.theme} · 来源 ${member.source || '--'}${member.is_supplemental ? ` · 事件补录${member.classification_basis === 'limit_reason' ? '/按涨停理由归类' : '/待归类'}` : member.classification_basis === 'previous_ladder' ? ' · 连板题材沿用前一交易日' : ''}`}
                  onClick={() => navigate(`/stock-analysis?symbol=${encodeURIComponent(member.symbol)}&name=${encodeURIComponent(member.name)}`)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{member.name}</span>
                    {member.subtheme && <span className="block truncate text-[8px] leading-3 text-purple-300" title={`独立逻辑子类：${member.subtheme}`}>{member.subtheme}</span>}
                    {detailMode === 'detailed' && <span data-testid="quantx-ladder-stock-reason" className="mt-0.5 block whitespace-normal text-[8px] leading-3 text-muted">
                      <b className={cn('mr-1 font-normal', member.reason ? 'text-orange-300' : 'text-muted')}>{member.reason_kind || '暂无理由'}</b>{member.reason || '上游未提供涨停理由'}
                      {member.theme_reason && member.theme_reason !== member.reason && <span className="mt-0.5 block text-blue-300">题材催化 · {member.theme_reason}</span>}
                      {member.limit_reason && member.limit_reason !== member.reason && <span className="mt-0.5 block text-purple-300">来源归因 · {member.limit_reason}</span>}
                    </span>}
                  </span>
                  {member.board_kind !== '10cm' && <span className="shrink-0 rounded bg-current/10 px-1 font-mono text-[7px]">{member.board_kind}</span>}
                  {member.is_supplemental && <span className="shrink-0 rounded bg-orange-400/15 px-1 text-[7px] text-orange-300">{member.classification_basis === 'limit_reason' ? '理由归类' : '补录'}</span>}
                  {member.classification_basis === 'previous_ladder' && <span className="shrink-0 rounded bg-blue-400/15 px-1 text-[7px] text-blue-300">历史沿用</span>}
                </button>)}</div>
              </td>
            })}
          </tr>)}
        </tbody>
        <tfoot>
          <tr>
            <th className="sticky bottom-0 left-0 z-30 border-r border-t border-border bg-elevated px-2 py-2 font-semibold text-foreground">合计 {coverage.limit_up_count ?? members.length}</th>
            {themes.map(theme => <td key={theme.name} className="sticky bottom-0 z-20 border-r border-t border-border bg-elevated px-2 py-2 text-center font-mono font-semibold text-foreground">{theme.count}</td>)}
          </tr>
        </tfoot>
      </table>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 text-[9px] leading-4 text-muted">
      <p>列按最高连板、涨停家数排序；所有单股题材合并到“独立逻辑”并保留原板块子类；每只股票仅计数一次。</p>
      <p><span className="text-red-300">10cm</span> · <span className="text-blue-300">20cm</span> · <span className="text-fuchsia-300">30cm</span> · <span className="text-orange-300">虚线框为事件补录；优先按真实涨停理由进入主题</span></p>
    </div>
  </div>
}

function AdvancedCard({ chartKey, card, layout }: { chartKey: string; card: QuantXAdvancedCard; layout?: AdvancedCardLayout }) {
  const meta = CARD_META[chartKey]
  const [sectorDimension, setSectorDimension] = useState('sw_level1')
  const [sectorWindow, setSectorWindow] = useState(20)
  const [correlationDimension, setCorrelationDimension] = useState('industry_level1')
  const [correlationIndustry, setCorrelationIndustry] = useState('')
  const [mainlineFocus, setMainlineFocus] = useState('')
  const [promotionWindow, setPromotionWindow] = useState('current')
  const [ladderView, setLadderView] = useState<'sunburst' | 'matrix'>('sunburst')
  const [rotationTrail, setRotationTrail] = useState<'focus' | 'all' | 'off'>('focus')
  const [stateTransitionWindow, setStateTransitionWindow] = useState<'500' | 'all'>('500')
  const selection = useMemo(() => ({ sectorDimension, sectorWindow, correlationDimension, mainlineFocus, promotionWindow, rotationTrail, stateTransitionWindow }), [correlationDimension, mainlineFocus, promotionWindow, rotationTrail, sectorDimension, sectorWindow, stateTransitionWindow])
  useEffect(() => setCorrelationIndustry(''), [correlationDimension])
  useEffect(() => {
    if (chartKey !== 'mainline_waterfall') return
    const mainlines = card.data.mainlines || []
    setMainlineFocus(current => mainlines.some((row: any) => row.focus === current) ? current : mainlines[0]?.focus || card.data.focus || '')
  }, [card.data, chartKey])
  const heightByKey: Record<string, number> = {
    sentiment_phase: 340,
    liquidity_participation: 340,
    state_transition: 360,
    anomaly_calendar: 390,
    return_distribution: 390,
    advance_decline: 340,
    turnover_lorenz: 340,
    sector_diffusion: 690,
    theme_river: 390,
    industry_correlation: 620,
    mainline_waterfall: 440,
    theme_ladder_sunburst: 380,
    rps_rotation_clock: 380,
    promotion_funnel: 350,
    turnover_return_density: 350,
  }
  const height = layout?.height ?? (chartKey === 'promotion_funnel'
    ? Math.max(350, ((card.data.stages || []).length * 32) + 88)
    : heightByKey[chartKey] ?? 320)
  const caveat = card.note || meta.caveat
  const correlationView = card.data.views?.[correlationDimension] || card.data
  const stateTransitionView = card.data.views?.[stateTransitionWindow] || card.data
  const handleChartClick = useCallback((params: any) => {
    if (chartKey !== 'industry_correlation') return
    const industries: string[] = correlationView.industries || []
    const industry = params.componentType === 'xAxis' || params.componentType === 'yAxis'
      ? String(params.value ?? params.name ?? '')
      : params.seriesType === 'heatmap' ? industries[Number(params.value?.[1])] : ''
    if (industries.includes(industry)) setCorrelationIndustry(industry)
  }, [chartKey, correlationView])
  const spanClass = chartKey === 'theme_ladder_sunburst' && ladderView === 'matrix'
    ? SPAN_CLASSES[16]
    : layout?.span ? SPAN_CLASSES[layout.span] : meta.span || SPAN_CLASSES[8]
  return (
    <section data-testid={`quantx-advanced-${chartKey}`} className={cn('min-w-0 overflow-hidden rounded-lg border border-border bg-elevated/25', spanClass)}>
      <header className="flex min-h-11 items-center gap-2 border-b border-border/70 px-3 py-1.5">
        <Activity className="h-3.5 w-3.5 shrink-0 text-accent" />
        <div className="min-w-0"><h3 className="truncate text-xs font-semibold">{meta.title}</h3><p className="truncate text-[9px] text-muted">{meta.hint}</p></div>
        {chartKey === 'theme_river' && card.status === 'ok' && card.data.source && <span className="ml-auto shrink-0 rounded border border-border bg-base px-1.5 py-0.5 font-mono text-[9px] text-muted">来源 {card.data.source}</span>}
        {card.status === 'ok' && <span className={cn('shrink-0 rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[9px] text-accent', (chartKey !== 'theme_river' || !card.data.source) && 'ml-auto')}>{card.rows ?? 0} 行</span>}
      </header>
      <div className="p-2">
        {chartKey === 'state_transition' && card.status === 'ok' && <div data-testid="quantx-state-transition-controls" className="mb-1.5 flex gap-1 border-b border-border/60 pb-1.5" role="group" aria-label="市场状态矩阵统计窗口">{(['500', 'all'] as const).map(value => { const view = card.data.views?.[value] || {}; return <button key={value} type="button" data-testid={`quantx-state-transition-window-${value}`} aria-pressed={stateTransitionWindow === value} onClick={() => setStateTransitionWindow(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors', stateTransitionWindow === value ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted hover:text-foreground')}>{view.label || (value === '500' ? '近500日' : '全历史')}<span className="ml-1 font-mono text-muted">{view.sample_days || 0}日</span></button> })}</div>}
        {chartKey === 'sector_diffusion' && card.status === 'ok' && <div data-testid="quantx-sector-diffusion-controls" className="mb-1.5 flex flex-wrap items-center justify-between gap-1.5 border-b border-border/60 pb-1.5"><div className="flex gap-1" role="group" aria-label="行业层级">{Object.entries(card.data.views || {}).map(([value, view]: [string, any]) => <button key={value} type="button" data-testid={`quantx-sector-dimension-${value}`} aria-pressed={sectorDimension === value} onClick={() => setSectorDimension(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors', sectorDimension === value ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted hover:text-foreground')}>{view.label || value} · {view.sectors?.length || 0} 行业 / {view.dates?.length || 0} 日</button>)}</div><div className="flex gap-1" role="group" aria-label="均线窗口">{[5, 10, 20].map(value => <button key={value} type="button" data-testid={`quantx-sector-window-${value}`} aria-pressed={sectorWindow === value} onClick={() => setSectorWindow(value)} className={cn('cursor-pointer rounded border px-2 py-1 font-mono text-[9px] transition-colors', sectorWindow === value ? 'border-orange-400/60 bg-orange-400/10 text-orange-300' : 'border-border bg-base text-muted hover:text-foreground')}>MA{value}</button>)}</div></div>}
        {chartKey === 'industry_correlation' && card.status === 'ok' && <div data-testid="quantx-correlation-controls" className="mb-1.5 flex gap-1 border-b border-border/60 pb-1.5" role="group" aria-label="相关性行业层级">{Object.entries(card.data.views || {}).map(([value, view]: [string, any]) => <button key={value} type="button" data-testid={`quantx-correlation-dimension-${value}`} aria-pressed={correlationDimension === value} onClick={() => setCorrelationDimension(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors', correlationDimension === value ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted hover:text-foreground')}>{view.label || value} · {view.industries?.length || 0} 行业</button>)}</div>}
        {chartKey === 'promotion_funnel' && card.status === 'ok' && <div data-testid="quantx-promotion-window-controls" className="mb-1.5 flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-1.5"><div className="flex gap-1" role="group" aria-label="连板晋级统计窗口">{['current', '5', '20'].map(value => { const view = card.data.views?.[value] || {}; return <button key={value} type="button" data-testid={`quantx-promotion-window-${value}`} aria-pressed={promotionWindow === value} onClick={() => setPromotionWindow(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors', promotionWindow === value ? 'border-orange-400/60 bg-orange-400/10 text-orange-300' : 'border-border bg-base text-muted hover:text-foreground')}>{view.label || value}<span className="ml-1 font-mono text-muted">{view.sample_days || 0}日</span></button> })}</div><span data-testid="quantx-promotion-baseline-label" className="text-[9px] text-blue-300">◆ 全样本基线 · {card.data.baseline?.sample_days || 0} 日</span></div>}
        {chartKey === 'mainline_waterfall' && card.status === 'ok' && <div data-testid="quantx-mainline-selector" className="mb-1.5 max-h-24 overflow-y-auto border-b border-border/60 pb-1.5"><div className="flex flex-wrap gap-1" role="group" aria-label="选择主线查看贡献细分">{(card.data.mainlines || []).map((row: any, index: number) => <button key={row.focus} type="button" data-testid={`quantx-mainline-option-${index}`} aria-pressed={mainlineFocus === row.focus} onClick={() => setMainlineFocus(row.focus)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px] transition-colors', mainlineFocus === row.focus ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted hover:text-foreground')}><span className="font-mono">{row.rank}</span> · {row.focus} <span className="font-mono">{row.score}</span></button>)}</div></div>}
        {chartKey === 'rps_rotation_clock' && card.status === 'ok' && <div data-testid="quantx-rps-trail-controls" className="mb-1.5 flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-1.5"><div className="flex gap-1" role="group" aria-label="昨日轨迹显示范围">{([['focus', '重点轨迹'], ['all', '全部轨迹'], ['off', '关闭轨迹']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={rotationTrail === value} onClick={() => setRotationTrail(value)} className={cn('cursor-pointer rounded border px-2 py-1 text-[9px]', rotationTrail === value ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted')}>{label}</button>)}</div><span className="text-[9px] text-muted">空心点为昨日 · 箭头指向今日</span></div>}
        {chartKey === 'theme_ladder_sunburst' && card.status === 'ok' && <div data-testid="quantx-ladder-view-controls" className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-2">
          <div className="flex gap-1" role="group" aria-label="题材连板梯队视图">
            {([['sunburst', '旭日图', ChartPie], ['matrix', '梯队表', Table2]] as const).map(([value, label, Icon]) => <button key={value} type="button" data-testid={`quantx-ladder-view-${value}`} aria-pressed={ladderView === value} onClick={() => setLadderView(value)} className={cn('flex cursor-pointer items-center gap-1 rounded border px-2 py-1 text-[9px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent', ladderView === value ? 'border-accent/60 bg-accent/15 text-accent' : 'border-border bg-base text-muted hover:text-foreground')}><Icon className="h-3 w-3" />{label}</button>)}
          </div>
          <span className="text-[9px] text-muted">旭日图核心 {card.data.coverage?.sunburst_count ?? 0}/{card.data.coverage?.limit_up_count ?? card.rows ?? 0} · 梯队表完整覆盖</span>
        </div>}
        {card.status === 'ok' ? chartKey === 'theme_ladder_sunburst' && ladderView === 'matrix'
          ? <LadderMatrix data={card.data} />
          : <EChart chartKey={chartKey} card={card} height={height} selection={selection} onClick={chartKey === 'industry_correlation' ? handleChartClick : undefined} />
          : <div className="flex items-center justify-center text-xs text-muted" style={{ height }}><span>{card.reason || '暂无足够数据'}</span></div>}
        {chartKey === 'industry_correlation' && card.status === 'ok' && <CorrelationPairRankings view={correlationView} selectedIndustry={correlationIndustry} onSelectIndustry={setCorrelationIndustry} />}
        {chartKey === 'state_transition' && card.status === 'ok' && <div data-testid="quantx-state-transition-guide" className="space-y-1 border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-muted"><p className="font-mono text-foreground">统计区间：{stateTransitionView.start_date || '--'}～{stateTransitionView.end_date || '--'} · {stateTransitionView.transition_count ?? 0} 次相邻交易日转移 · {stateTransitionView.label || '当前样本'}</p><p>读法：从左侧“当前状态”沿行读取到上方“下一交易日状态”，每行合计 100%。例如“震荡 → 偏强 20%”表示处于震荡后，次日转为偏强的历史概率为 20%。</p><p className="text-orange-300">模型边界：本矩阵来自 TickFlow Regime 四维模型；顶部市场热度、短线情绪和趋势情绪来自 QuantX market_state_daily，两套分值与状态不可直接互换。</p></div>}
        {chartKey === 'turnover_lorenz' && card.status === 'ok' && <div data-testid="quantx-lorenz-guide" className="space-y-1 border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-muted"><p><span className="text-foreground">怎么看：</span>横轴是按成交额从小到大排列的股票累计占比，纵轴是累计成交额；橙线越向右下弯，成交越集中在少数头部股票。蓝色虚线是昨日，紫色虚线是前 20 个交易日均值。</p><p><span className="text-foreground">有什么用：</span>当日曲线低于历史基线、Gini 更高，表示资金抱团较近期增强；更接近均等线则表示成交扩散。它描述资金结构，不判断市场涨跌方向。</p></div>}
        {chartKey === 'advance_decline' && card.status === 'ok' && <p data-testid="quantx-ad-divergence-guide" className="border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-muted">红色区间：指数走强但市场广度转弱；绿色区间：指数走弱但广度修复。图钉标记背离确认点。</p>}
        {chartKey === 'promotion_funnel' && card.status === 'ok' && <p data-testid="quantx-promotion-guide" className="border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-muted">当天显示目标交易日实际结果；5日、20日按窗口内成功数 ÷ 样本数计算加权均值。蓝色菱形虚线为当前快照全部历史样本基线，切换窗口时始终保留。0→1 使用首板封板率，其余层级使用次日晋级率。</p>}
        {caveat && <p data-testid={`quantx-advanced-caveat-${chartKey}`} className="border-t border-border/60 px-1 pt-1.5 text-[9px] leading-4 text-orange-300">口径提示：{caveat}</p>}
      </div>
    </section>
  )
}

const GROUPS = [
  { key: 'state', title: '市场状态与风险结构', hint: '先确认环境、异常、广度和流动性', icon: Radar },
  { key: 'rotation', title: '主线扩散与轮动结构', hint: '再定位行业、题材与连板主线', icon: Orbit },
  { key: 'structure', title: '接力效率与拥挤结构', hint: '最后检查晋级质量和交易拥挤', icon: GitBranch },
] as const

export function AdvancedPanels({ snapshot, loading, error, cardKeys, cardLayout, flat = false, testId = 'quantx-advanced-workspace' }: { snapshot?: QuantXAdvancedSnapshot; loading: boolean; error?: Error | null; cardKeys?: string[]; cardLayout?: Record<string, AdvancedCardLayout>; flat?: boolean; testId?: string }) {
  const loadingId = testId === 'quantx-advanced-workspace' ? 'quantx-advanced-loading' : `${testId}-loading`
  const errorId = testId === 'quantx-advanced-workspace' ? 'quantx-advanced-error' : `${testId}-error`
  if (loading) return <section data-testid={loadingId} className="flex items-center justify-center rounded-lg border border-border bg-elevated/20 py-20 text-xs text-muted"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在构建高级市场图谱</section>
  if (error || !snapshot) return <section data-testid={errorId} className="rounded-lg border border-orange-500/30 bg-orange-500/5 px-4 py-12 text-center text-xs text-orange-300">高级图谱暂不可用：{error?.message || '没有快照'}</section>
  const visibleKeys = cardKeys || Object.keys(CARD_META)
  return (
    <section data-testid={testId} className="space-y-5">
      {flat ? <div className="grid gap-2 xl:grid-cols-[repeat(16,minmax(0,1fr))]">{visibleKeys.map(key => <AdvancedCard key={key} chartKey={key} card={snapshot.cards[key]} layout={cardLayout?.[key]} />)}</div> : GROUPS.map(group => {
        const Icon = group.icon
        const keys = visibleKeys.filter(key => CARD_META[key]?.group === group.key)
        if (!keys.length) return null
        return <section key={group.key} data-testid={`quantx-advanced-group-${group.key}`}><div className="mb-2 flex items-center gap-2"><Icon className="h-3.5 w-3.5 text-accent" /><h3 className="text-xs font-semibold">{group.title}</h3><span className="text-[9px] text-muted">{group.hint}</span></div><div className="grid gap-2 xl:grid-cols-[repeat(16,minmax(0,1fr))]">{keys.map(key => <AdvancedCard key={key} chartKey={key} card={snapshot.cards[key]} layout={cardLayout?.[key]} />)}</div></section>
      })}
    </section>
  )
}
