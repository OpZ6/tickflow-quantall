/**
 * 单日复盘 — 七区确定性数据 + 情绪嵌入 s3 + 全量 ECharts 图表。
 * A-share 色彩: 红=涨/正, 绿=跌/负。固定范围, 无 dataZoom。
 * 不读取 HTML 报告，也不渲染或请求 LLM 分析内容。
 */
import { useMemo, useRef, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts'
import {
  ChevronLeft, ChevronRight, CalendarDays, Loader2,
  Activity, Flame, AlertTriangle, CheckCircle2, XCircle,
  Zap, Gauge, FileText, Layers3, TrendingUp, BookOpenCheck, LayoutGrid,
} from 'lucide-react'
import { quantxApi } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { useChartTheme } from '@/lib/theme'
import { cn } from '@/lib/cn'

const RED = '#f85149'
const GREEN = '#3fb950'
const ORANGE = '#f78166'
const CYAN = '#58a6ff'
const PURPLE = '#bc8cff'
const YELLOW = '#d2991d'

const SECTION_TITLES = {
  s0: '一、顶部决断',
  s1: '二、大盘环境',
  s2: '三、主线题材',
  s3: '四、连板情绪',
  s4: '五、资金生态与趋势容量',
  s5: '六、关注名单',
  s6: '七、次日预案与复盘校验',
} as const

function scoreColor(score: number): string {
  if (score >= 70) return RED
  if (score >= 60) return '#f97316'
  if (score >= 40) return CYAN
  if (score >= 30) return '#6b7280'
  return '#1e40af'
}

function useEChart(option: any, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null)
  const instRef = useRef<echarts.ECharts | null>(null)
  const ct = useChartTheme()
  useEffect(() => {
    if (!ref.current) return
    if (!instRef.current) instRef.current = echarts.init(ref.current)
    const inst = instRef.current
    if (option) inst.setOption(option, true)
  }, [...deps, ct.text])
  useEffect(() => {
    const ro = new ResizeObserver(() => instRef.current?.resize())
    if (ref.current) ro.observe(ref.current)
    return () => { ro.disconnect(); instRef.current?.dispose(); instRef.current = null }
  }, [])
  return ref
}

function DateNav({ date, dates }: { date: string; dates: string[] }) {
  const navigate = useNavigate()
  const sorted = useMemo(() => [...dates].sort(), [dates])
  const idx = sorted.indexOf(date)
  const prev = idx > 0 ? sorted[idx - 1] : null
  const next = idx < sorted.length - 1 ? sorted[idx + 1] : null
  const latest = sorted[sorted.length - 1] || date
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button aria-label="前一交易日" disabled={!prev} onClick={() => prev && navigate(`/quantx/${prev}`)} className="rounded-btn border border-border p-1.5 hover:bg-elevated disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
      <div className="relative">
        <CalendarDays className="h-4 w-4 text-muted absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        <select aria-label="交易日" value={date} onChange={(e) => navigate(`/quantx/${e.target.value}`)} className="appearance-none rounded-btn border border-border bg-elevated pl-8 pr-7 py-1.5 text-sm font-semibold focus:border-accent outline-none cursor-pointer">
          {sorted.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>
      <button aria-label="后一交易日" disabled={!next} onClick={() => next && navigate(`/quantx/${next}`)} className="rounded-btn border border-border p-1.5 hover:bg-elevated disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
      <button onClick={() => navigate(`/quantx/${latest}`)} className="rounded-btn border border-border px-2.5 py-1.5 text-xs text-muted hover:bg-elevated">最新</button>
      <button onClick={() => navigate('/quantx')} className="ml-auto rounded-btn border border-border px-2.5 py-1.5 text-xs text-muted hover:bg-elevated flex items-center gap-1"><LayoutGrid className="h-3 w-3" />驾驶舱</button>
    </div>
  )
}

export function ScoreBar({ label, score, zone }: { label: string; score: number; zone: string }) {
  const color = scoreColor(score)
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 text-sm text-foreground/80 shrink-0">{label}</span>
      <div className="flex-1 h-6 bg-elevated rounded-full overflow-hidden border border-border"><div className="h-full rounded-full transition-all duration-500" style={{ width: `${score}%`, backgroundColor: color }} /></div>
      <span className="w-8 text-right font-bold text-sm" style={{ color }}>{score}</span>
      <span className="w-12 text-xs text-muted">{zone}</span>
    </div>
  )
}

function SectionTitle({ icon: Icon, children }: { icon: typeof Activity; children: React.ReactNode }) {
  return <h2 className="flex items-center gap-2 text-lg font-semibold border-b border-border pb-2 mb-4 mt-8"><Icon className="h-5 w-5 text-accent" />{children}</h2>
}

// ═══ 图表组件 ═══

export function IndexChart({ indexes, height = 300 }: { indexes: any[]; height?: number }) {
  const ct = useChartTheme()
  const option = useMemo(() => ({
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
    tooltip: { trigger: 'axis', formatter: (p: any) => `<b>${p[0].name}</b><br/>涨跌幅: ${p[0].value > 0 ? '+' : ''}${p[0].value.toFixed(2)}%` },
    xAxis: { type: 'category', data: indexes.map(i => i.name), axisLabel: { color: ct.text, fontSize: 11, rotate: 30 }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: { type: 'value', axisLabel: { color: ct.text, fontSize: 11, formatter: '{value}%' }, splitLine: { lineStyle: { color: ct.grid } } },
    series: [{
      type: 'bar', data: indexes.map(i => ({ value: i.pct_chg, itemStyle: { color: i.pct_chg >= 0 ? RED : GREEN } })), barWidth: '50%',
      label: { show: true, position: 'top', formatter: (p: any) => `${p.value > 0 ? '+' : ''}${p.value.toFixed(2)}%`, fontSize: 11, color: ct.textStrong, fontWeight: 'bold' },
    }],
  }), [indexes, ct.text, ct.textStrong, ct.border, ct.grid])
  const ref = useEChart(option, [indexes, ct.text])
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function KlineChart({ history, height = 520 }: { history: any[]; height?: number }) {
  const ct = useChartTheme()
  const option = useMemo(() => {
    const dates = history.map(d => d.date)
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          const d = history[params[0].dataIndex]; if (!d) return ''
          let h = `<div style="font-size:12px"><b>${d.date}</b><br>`
          h += `开:${d.open?.toFixed(2)} 高:${d.high?.toFixed(2)} 低:${d.low?.toFixed(2)} 收:<b>${d.close?.toFixed(2)}</b><br>`
          h += `CCI5:${(d.cci5 || 0).toFixed(1)} MA5:${d.ma5 ?? '-'} MA10:${d.ma10 ?? '-'} MA20:${d.ma20 ?? '-'}`
          return h + '</div>'
        }
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [{ left: '8%', right: '3%', top: '5%', height: '55%' }, { left: '8%', right: '3%', top: '66%', height: '22%' }],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: ct.border } }, axisLabel: { show: false } },
        { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: ct.border } }, axisLabel: { color: ct.text, fontSize: 9 } },
      ],
      yAxis: [
        { scale: true, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } }, axisLabel: { color: ct.text, fontSize: 10 } },
        { scale: true, gridIndex: 1, splitNumber: 3, min: -200, max: 200, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } }, axisLabel: { color: ct.text, fontSize: 9 } },
      ],
      series: [
        { name: 'K线', type: 'candlestick', data: history.map(d => [d.open, d.close, d.low, d.high]), itemStyle: { color: RED, color0: GREEN, borderColor: RED, borderColor0: GREEN } },
        { name: 'MA5', type: 'line', data: history.map(d => d.ma5), smooth: true, lineStyle: { color: ORANGE, width: 1 }, itemStyle: { color: ORANGE }, symbol: 'none' },
        { name: 'MA10', type: 'line', data: history.map(d => d.ma10), smooth: true, lineStyle: { color: CYAN, width: 1 }, itemStyle: { color: CYAN }, symbol: 'none' },
        { name: 'MA20', type: 'line', data: history.map(d => d.ma20), smooth: true, lineStyle: { color: PURPLE, width: 1 }, itemStyle: { color: PURPLE }, symbol: 'none' },
        { name: 'CCI5', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: history.map(d => d.cci5 || 0), lineStyle: { color: YELLOW, width: 1 }, symbol: 'none',
          markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { type: 'dashed', color: YELLOW }, data: [{ yAxis: 100 }, { yAxis: -100 }, { yAxis: 0, lineStyle: { color: ct.border } }] } },
      ],
    }
  }, [history, ct.text, ct.border, ct.grid])
  const ref = useEChart(option, [history, ct.text])
  if (!history.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function UpCountChart({ history, height = 400 }: { history: any[]; height?: number }) {
  const ct = useChartTheme()
  const valid = useMemo(() => history.filter(d => d.date && d.up_count > 0), [history])
  const option = useMemo(() => ({
    legend: { data: ['上涨', '下跌'], textStyle: { color: ct.text, fontSize: 10 }, top: 0 },
    grid: { left: 45, right: 20, top: 30, bottom: 35 },
    tooltip: { trigger: 'axis', formatter: (p: any) => {
      const d = valid[p[0].dataIndex]; if (!d) return ''
      return `<b>${d.date}</b><br>上涨: <span style="color:${RED}">${d.up_count}</span><br>下跌: <span style="color:${GREEN}">${d.down_count}</span>`
    } },
    xAxis: { type: 'category', data: valid.map(d => d.date), axisLabel: { color: ct.text, fontSize: 9, rotate: 30 }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: { type: 'value', name: '家数', axisLabel: { color: ct.text, fontSize: 10 }, splitLine: { lineStyle: { color: ct.grid } }, axisLine: { lineStyle: { color: ct.border } } },
    series: [
      { name: '上涨', type: 'bar', stack: 'bd', data: valid.map(d => d.up_count), itemStyle: { color: RED },
        markLine: { silent: true, symbol: 'none',
          lineStyle: { type: 'solid', color: YELLOW, width: 2 },
          label: { color: YELLOW, fontSize: 11, fontWeight: 'bold' },
          data: [{ yAxis: 1100, label: { formatter: '冰点 1100' } },
                 { yAxis: 4100, label: { formatter: '亢奋 4100' } }] } },
      { name: '下跌', type: 'bar', stack: 'bd', data: valid.map(d => -d.down_count), itemStyle: { color: GREEN } },
    ],
  }), [valid, ct.text, ct.border, ct.grid])
  const ref = useEChart(option, [valid, ct.text])
  if (!valid.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function SectorBreadthHeatmap({ data, maxRows, height }: { data: any[]; maxRows?: number; height?: number }) {
  const ct = useChartTheme()
  const rows = useMemo(
    () => [...data].sort((a, b) => Number(b.ma20 || 0) - Number(a.ma20 || 0)).slice(0, maxRows),
    [data, maxRows],
  )
  const windows = ['MA5', 'MA10', 'MA20', 'MA60']
  const values = useMemo(
    () => rows.flatMap((row, rowIndex) => windows.map((window, columnIndex) => [
      columnIndex,
      rowIndex,
      Number(row[window.toLowerCase()] || 0),
    ])),
    [rows],
  )
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 92, right: 72, top: 16, bottom: 36 },
    tooltip: {
      position: 'top',
      formatter: (p: any) => {
        const row = rows[p.value[1]]
        return `<b>${row?.name || row?.code || '-'}</b><br>${windows[p.value[0]]}: <b>${Number(p.value[2]).toFixed(1)}%</b><br><span style="color:${ct.text}">成分股收盘价站上该均线的占比</span>`
      },
    },
    xAxis: { type: 'category', data: windows, splitArea: { show: true }, axisLabel: { color: ct.text }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: { type: 'category', inverse: true, data: rows.map(row => row.name || row.code), splitArea: { show: true }, axisLabel: { color: ct.text, fontSize: 10 }, axisLine: { lineStyle: { color: ct.border } } },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: 'vertical',
      right: 4,
      top: 'center',
      text: ['强', '弱'],
      textStyle: { color: ct.text },
      inRange: { color: [GREEN, '#243447', YELLOW, ORANGE, RED] },
    },
    series: [{
      name: '站上均线占比',
      type: 'heatmap',
      data: values,
      label: { show: true, color: '#fff', fontSize: 9, formatter: (p: any) => `${Number(p.value[2]).toFixed(0)}%` },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.45)' } },
    }],
  }), [rows, values, ct.text, ct.border])
  const ref = useEChart(option, [rows, values, ct.text])
  if (!rows.length) return null
  return <div ref={ref} className="w-full" style={{ height: height ?? Math.max(480, rows.length * 22 + 70) }} />
}

export function CongestionGauge({ pct, height = 200 }: { pct: number; height?: number }) {
  const ct = useChartTheme()
  const option = useMemo(() => ({
    series: [{
      type: 'gauge', min: 0, max: 100,
      axisLine: { lineStyle: { width: 14, color: [[0.3, CYAN], [0.5, YELLOW], [0.7, ORANGE], [1, RED]] } },
      pointer: { width: 5, length: '60%' }, axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { color: ct.text, fontSize: 9, distance: -22 },
      detail: { formatter: '{value}%', color: ct.textStrong, fontSize: 18, fontWeight: 'bold', offsetCenter: [0, '55%'] },
      data: [{ value: pct }],
    }],
  }), [pct, ct.text, ct.textStrong])
  const ref = useEChart(option, [pct, ct.text])
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function MarginChart({ history, height = 400 }: { history: any[]; height?: number }) {
  const ct = useChartTheme()
  const rows = useMemo(() => [...history].sort((a, b) => (a.date || '').localeCompare(b.date || '')), [history])
  const option = useMemo(() => ({
    legend: { data: ['融资余额', '净买入'], textStyle: { color: ct.text, fontSize: 10 }, top: 0 },
    grid: { left: 50, right: 55, top: 30, bottom: 35 },
    tooltip: { trigger: 'axis', formatter: (p: any) => {
      const d = rows[p[0].dataIndex]; if (!d) return ''
      return `<b>${d.date}</b><br>融资余额: ${d.rzye_yi?.toFixed(0)}亿<br>净买入: ${d.rz_net_buy_yi >= 0 ? '+' : ''}${d.rz_net_buy_yi?.toFixed(1)}亿`
    } },
    xAxis: { type: 'category', data: rows.map(r => r.date), axisLabel: { color: ct.text, fontSize: 9, rotate: 30 }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: [
      { type: 'value', name: '余额(亿)', axisLabel: { color: ct.text, fontSize: 10 }, splitLine: { lineStyle: { color: ct.grid } }, axisLine: { lineStyle: { color: ct.border } } },
      { type: 'value', name: '净买(亿)', axisLabel: { color: ct.text, fontSize: 10 }, splitLine: { show: false }, axisLine: { lineStyle: { color: ct.border } } },
    ],
    series: [
      { name: '融资余额', type: 'line', data: rows.map(r => r.rzye_yi), smooth: true, lineStyle: { color: CYAN, width: 2 }, itemStyle: { color: CYAN }, areaStyle: { color: 'rgba(88,166,255,0.1)' } },
      { name: '净买入', type: 'bar', yAxisIndex: 1, data: rows.map(r => ({ value: r.rz_net_buy_yi, itemStyle: { color: r.rz_net_buy_yi >= 0 ? RED : GREEN } })) },
    ],
  }), [rows, ct.text, ct.border, ct.grid])
  const ref = useEChart(option, [rows, ct.text])
  if (!rows.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function HeightChart({ history, height = 280 }: { history: any[]; height?: number }) {
  const ct = useChartTheme()
  const rows = useMemo(() => [...history].sort((a, b) => (a.date || '').localeCompare(b.date || '')), [history])
  const option = useMemo(() => ({
    tooltip: { trigger: 'axis', extraCssText: 'max-width:320px;word-break:break-all;white-space:normal',
      formatter: (params: any) => {
        const d = rows[params[0].dataIndex] || {}
        let html = `<div style="font-size:12px"><b>${d.date || '-'}</b><br>`
        html += `最高连板: <b>${d.height ?? '-'}</b>板<br>`
        html += `高度股: ${d.name || '-'}<br>`
        if (d.second_height != null && d.second_height > 0) {
          html += `次高板: <b>${d.second_height}板</b>`
          if (d.second_names?.length) html += ` (${d.second_names.join(', ')})`
          html += '<br>'
        }
        if (d.turnover_pct != null) html += `换手率: ${d.turnover_pct}%<br>`
        if (d.amount_yi != null) html += `成交额: ${d.amount_yi}亿`
        return html + '</div>'
      }
    },
    grid: { left: '7%', right: '4%', top: '10%', bottom: '18%' },
    xAxis: { type: 'category', data: rows.map(r => r.date), axisLine: { lineStyle: { color: ct.border } }, axisLabel: { color: ct.text, fontSize: 10 } },
    yAxis: { type: 'value', minInterval: 1, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } }, axisLabel: { color: ct.text, fontSize: 10 } },
    series: [
      { name: '最高连板', type: 'line', data: rows.map(r => r.height || 0), lineStyle: { color: ORANGE, width: 2 }, itemStyle: { color: ORANGE }, symbol: 'circle', symbolSize: 5,
        markLine: { silent: true, lineStyle: { type: 'dashed', color: YELLOW, width: 1 }, data: [{ yAxis: 3 }, { yAxis: 5 }] } },
      { name: '次高板', type: 'line', data: rows.map(r => r.second_height || 0), lineStyle: { color: YELLOW, width: 2, type: 'dashed' }, itemStyle: { color: YELLOW }, symbol: 'diamond', symbolSize: 5 },
    ],
  }), [rows, ct.text, ct.border, ct.grid])
  const ref = useEChart(option, [rows, ct.text])
  if (!rows.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function AdvanceRateChart({ history, height = 280 }: { history: any[]; height?: number }) {
  const ct = useChartTheme()
  const rows = useMemo(() => [...history].sort((a, b) => (a.date || '').localeCompare(b.date || '')), [history])
  const option = useMemo(() => {
    const premiumVals = rows.map(d => d.premium_rate).filter(v => v != null)
    const premiumBound = Math.max(5, Math.ceil(Math.max(...premiumVals.map(Math.abs), 0)) + 1)
    const limitUpMax = Math.max(1, Math.ceil(Math.max(...rows.map(d => d.limit_up_count || 0)) * 1.15))
    return {
      tooltip: { trigger: 'axis',
        formatter: (params: any) => {
          const d = rows[params[0].dataIndex] || {}
          let html = `<div style="font-size:12px"><b>${d.date || '-'}</b><br>`
          html += `晋级率: <b>${d.advance_rate != null ? d.advance_rate + '%' : '-'}</b><br>`
          html += `溢价率: <b>${d.premium_rate != null ? d.premium_rate + '%' : '-'}</b><br>`
          html += `涨停数: <b>${d.limit_up_count ?? '-'}</b><br>`
          html += `最高板: <b>${d.max_board ?? '-'}</b>`
          return html + '</div>'
        }
      },
      legend: { data: ['晋级率', '溢价率', '涨停数'], textStyle: { color: ct.text, fontSize: 10 }, top: 0 },
      grid: { left: 8, right: 8, top: '10%', bottom: '18%', containLabel: true },
      xAxis: { type: 'category', data: rows.map(r => r.date), axisLine: { lineStyle: { color: ct.border } }, axisLabel: { color: ct.text, fontSize: 10, rotate: 35 } },
      yAxis: [
        { type: 'value', min: 0, max: 100, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } }, axisLabel: { color: ct.text, formatter: '{value}%' } },
        { type: 'value', min: -premiumBound, max: premiumBound, position: 'right', axisLine: { show: true, lineStyle: { color: GREEN } }, splitLine: { show: false }, axisLabel: { color: GREEN, formatter: '{value}%' } },
        { type: 'value', min: 0, max: limitUpMax, show: false },
      ],
      series: [
        { name: '晋级率', type: 'line', yAxisIndex: 0, connectNulls: false, data: rows.map(d => d.advance_rate ?? null), lineStyle: { color: CYAN, width: 2 }, itemStyle: { color: CYAN }, symbol: 'circle', symbolSize: 5 },
        { name: '溢价率', type: 'line', yAxisIndex: 1, connectNulls: false, data: rows.map(d => d.premium_rate ?? null), lineStyle: { color: GREEN, width: 2 }, itemStyle: { color: GREEN }, symbol: 'diamond', symbolSize: 5 },
        { name: '涨停数', type: 'bar', yAxisIndex: 2, data: rows.map(d => d.limit_up_count ?? null), barWidth: '40%', itemStyle: { color: ct.border } },
      ],
    }
  }, [rows, ct.text, ct.border, ct.grid])
  const ref = useEChart(option, [rows, ct.text])
  if (!rows.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function EmotionTrendChart({ dates, scores, height = 300 }: { dates: string[]; scores: { heat: number[]; short: number[]; trend: number[] }; height?: number }) {
  const ct = useChartTheme()
  const option = useMemo(() => ({
    legend: { data: ['市场热度', '短线情绪', '趋势情绪'], textStyle: { color: ct.text, fontSize: 10 }, top: 0 },
    grid: { left: 35, right: 20, top: 30, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: dates, axisLabel: { color: ct.text, fontSize: 9 }, axisLine: { lineStyle: { color: ct.border } } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: ct.text, fontSize: 10 }, splitLine: { lineStyle: { color: ct.grid } }, axisLine: { lineStyle: { color: ct.border } } },
    series: [
      { name: '市场热度', type: 'line', data: scores.heat, smooth: true, lineStyle: { color: RED, width: 2 }, itemStyle: { color: RED } },
      { name: '短线情绪', type: 'line', data: scores.short, smooth: true, lineStyle: { color: ORANGE, width: 2 }, itemStyle: { color: ORANGE } },
      { name: '趋势情绪', type: 'line', data: scores.trend, smooth: true, lineStyle: { color: CYAN, width: 2 }, itemStyle: { color: CYAN } },
    ],
  }), [dates, scores, ct.text, ct.border, ct.grid])
  const ref = useEChart(option, [dates, scores, ct.text])
  if (!dates.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function SectorFlowChart({ topIn, topOut, height = 400 }: { topIn: any[]; topOut: any[]; height?: number }) {
  const ct = useChartTheme()
  const option = useMemo(() => {
    const all = [
      ...topIn.map(s => ({ name: s.name, value: s.net_inflow_yi })),
      ...topOut.map(s => ({ name: s.name, value: s.net_inflow_yi })),
    ].sort((a, b) => b.value - a.value)
    return {
      grid: { left: 120, right: 60, top: 10, bottom: 30 },
      tooltip: { trigger: 'axis', formatter: (p: any) => `<b>${p[0].name}</b><br>净流入: ${p[0].value?.toFixed(2)}亿` },
      xAxis: { type: 'value', axisLabel: { color: ct.text, fontSize: 10, formatter: '{value}亿' }, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } } },
      yAxis: { type: 'category', data: all.map(a => a.name), axisLabel: { color: ct.text, fontSize: 11 }, axisLine: { lineStyle: { color: ct.border } } },
      series: [{
        type: 'bar', data: all.map(a => ({ value: a.value, itemStyle: { color: a.value >= 0 ? RED : GREEN } })), barWidth: '60%',
        label: { show: true, position: 'right', formatter: (p: any) => `${p.value > 0 ? '+' : ''}${p.value?.toFixed(1)}亿`, fontSize: 10, color: ct.textStrong },
      }],
    }
  }, [topIn, topOut, ct.text, ct.textStrong, ct.border, ct.grid])
  const ref = useEChart(option, [topIn, topOut, ct.text])
  if (!topIn.length && !topOut.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function SectorTreemapChart({ data, height = 560 }: { data: any[]; height?: number }) {
  const ct = useChartTheme()
  const inflow = useMemo(() => data.filter(d => d.value >= 0).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)), [data])
  const outflow = useMemo(() => data.filter(d => d.value < 0).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)), [data])
  const option = useMemo(() => ({
    tooltip: { formatter: (p: any) => `${p.name}<br>净流入: ${(p.data?.net ?? p.value)?.toFixed(2)}亿<br>涨跌幅: ${p.data?.pct_chg?.toFixed(2) ?? '-'}%` },
    title: [
      { text: '净流入 (红)', left: '2%', top: 2, textStyle: { color: RED, fontSize: 12, fontWeight: 'bold' } },
      { text: '净流出 (绿)', left: '52%', top: 2, textStyle: { color: GREEN, fontSize: 12, fontWeight: 'bold' } },
    ],
    series: [
      {
        type: 'treemap', roam: false, nodeClick: false,
        top: 25, bottom: 5, left: '2%', width: '46%',
        label: { show: true, formatter: (p: any) => `${p.name}\n+${(p.data?.net ?? p.value)?.toFixed(1)}亿`, fontSize: 11, fontWeight: 'bold', color: '#fff' },
        itemStyle: { borderColor: ct.border, borderWidth: 1, gapWidth: 3 },
        data: inflow.map(d => ({ name: d.name, value: Math.abs(d.value), net: d.value, pct_chg: d.pct_chg, itemStyle: { color: 'rgba(248,81,73,0.85)', borderColor: RED } })),
      },
      {
        type: 'treemap', roam: false, nodeClick: false,
        top: 25, bottom: 5, left: '52%', width: '46%',
        label: { show: true, formatter: (p: any) => `${p.name}\n${(p.data?.net ?? p.value)?.toFixed(1)}亿`, fontSize: 11, fontWeight: 'bold', color: '#fff' },
        itemStyle: { borderColor: ct.border, borderWidth: 1, gapWidth: 3 },
        data: outflow.map(d => ({ name: d.name, value: Math.abs(d.value), net: d.value, pct_chg: d.pct_chg, itemStyle: { color: 'rgba(63,185,80,0.85)', borderColor: GREEN } })),
      },
    ],
  }), [inflow, outflow, ct.border])
  const ref = useEChart(option, [inflow, outflow, ct.border])
  if (!data.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

export function SectorScatterChart({ data, height = 480 }: { data: any[]; height?: number }) {
  const ct = useChartTheme()
  const option = useMemo(() => ({
    grid: { left: 54, right: 36, top: 20, bottom: 42 },
    tooltip: { formatter: (p: any) => `<b>${p.data[2]}</b><br>涨跌幅: ${p.value[0]?.toFixed(2)}%<br>净流入: ${p.value[1]?.toFixed(2)}亿` },
    xAxis: { type: 'value', name: '涨跌幅 %', nameLocation: 'middle', nameGap: 25, nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text, fontSize: 10, formatter: '{value}%' }, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } } },
    yAxis: { type: 'value', name: '净流入(亿)', nameTextStyle: { color: ct.text }, axisLabel: { color: ct.text, fontSize: 10 }, axisLine: { lineStyle: { color: ct.border } }, splitLine: { lineStyle: { color: ct.grid } } },
    series: [{
      type: 'scatter',
      data: data.map(d => [d.pct_chg, d.value, d.name]),
      symbolSize: (val: any) => Math.max(7, Math.min(32, Math.sqrt(Math.abs(Number(val[1] || 0.1))) * 3.5)),
      itemStyle: { color: (p: any) => p.value[1] >= 0 ? RED : GREEN, opacity: 0.84 },
      label: { show: true, position: 'right', color: ct.textStrong, fontSize: 9, formatter: (p: any) => p.data[2] },
      labelLayout: { hideOverlap: true },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#6e7681', type: 'dashed' }, data: [{ xAxis: 0 }, { yAxis: 0 }] },
    }],
  }), [data, ct.text, ct.textStrong, ct.border, ct.grid])
  const ref = useEChart(option, [data, ct.text])
  if (!data.length) return null
  return <div ref={ref} className="w-full" style={{ height }} />
}

// ═══ 主页面 ═══

export function QuantXReview() {
  const { date = '' } = useParams()
  const navigate = useNavigate()
  const { data: catalog } = useQuery({ queryKey: QK.quantxCatalog, queryFn: () => quantxApi.getCatalog(), retry: false, staleTime: 0 })
  const dates = useMemo(() => (catalog?.records || []).map(r => r.trade_date), [catalog])
  const recentRecords = useMemo(() => (catalog?.records || []).slice(-20), [catalog])
  const { data, isLoading, error } = useQuery({ queryKey: QK.quantxReview(date), queryFn: () => quantxApi.getReviewData(date), retry: false, enabled: !!date, staleTime: 0 })
  const [sectorBreadthLevel, setSectorBreadthLevel] = useState<1 | 2>(1)

  if (isLoading) return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>
  if (error || !data) return (
    <div className="text-center py-12 space-y-3"><p className="text-muted text-sm">无 {date} 的复盘数据</p>
    <button onClick={() => navigate('/quantx')} className="text-accent text-sm hover:underline">返回驾驶舱</button></div>
  )

  const ms = data.metric_strip, em = data.emotion, s = data.sections
  const { s0, s1, s2, s3, s4, s5, s6 } = s
  const emotionTrendData = {
    dates: recentRecords.map(r => r.trade_date),
    scores: {
      heat: recentRecords.map(r => (r.metrics.market_heat_score as number) ?? 0),
      short: recentRecords.map(r => (r.metrics.short_term_sentiment_score as number) ?? 0),
      trend: recentRecords.map(r => (r.metrics.trend_sentiment_score as number) ?? 0),
    },
  }
  const congestionPct = s1?.congestion?.latest?.congestion_pct ?? 0
  const congestionTable = s1?.congestion?.table || []
  const sectorBreadth = sectorBreadthLevel === 2
    ? (s1.width_heat_level2 || [])
    : (s1.width_heat || [])

  if (data.data_foundation.canonical_fields.length === 0) {
    return (
      <div className="mx-auto max-w-6xl p-4 pb-20">
        <DateNav date={date} dates={dates} />
        <div data-testid="quantx-review-empty" className="mt-8 rounded-xl border border-border py-20 text-center text-sm text-muted">
          该交易日没有可用的标准事实数据
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl p-4 pb-20">
      <DateNav date={date} dates={dates} />
      {/* Metric strip */}
      <div className="flex gap-2 flex-wrap mt-4 mb-2">
        {ms.indexes.map(idx => {
          const pctChange = idx.pct_chg ?? 0
          return (
          <div key={idx.code} className={cn('rounded-lg border px-3 py-1.5 flex flex-col items-center flex-1 min-w-[80px]', pctChange > 0 ? 'border-red-500/30 bg-red-500/5' : pctChange < 0 ? 'border-green-500/30 bg-green-500/5' : 'border-border bg-elevated')}>
            <span className="text-[10px] text-muted">{idx.name}</span>
            <span className={cn('text-sm font-bold', pctChange > 0 ? 'text-red-400' : pctChange < 0 ? 'text-green-400' : '')}>{pctChange > 0 ? '+' : ''}{pctChange.toFixed(2)}%</span>
          </div>
          )
        })}
        <div className="rounded-lg border border-border px-3 py-1.5 flex flex-col items-center flex-1 min-w-[80px]"><span className="text-[10px] text-muted">涨跌平</span><span className="text-sm font-bold"><span className="text-red-400">{ms.up_count}</span>/<span className="text-green-400">{ms.down_count}</span>/{ms.flat_count}</span></div>
        <div className="rounded-lg border border-border px-3 py-1.5 flex flex-col items-center flex-1 min-w-[80px]"><span className="text-[10px] text-muted">成交额</span><span className="text-sm font-bold">{ms.total_amount_yi != null ? `${ms.total_amount_yi.toFixed(0)}亿` : '--'}</span></div>
        <div className="rounded-lg border border-border px-3 py-1.5 flex flex-col items-center flex-1 min-w-[80px]"><span className="text-[10px] text-muted">晋级率</span><span className="text-sm font-bold">{ms.advance_rate != null ? `${ms.advance_rate}%` : '--'}</span></div>
      </div>

      {/* s0 */}
      <SectionTitle icon={Zap}>{SECTION_TITLES.s0}</SectionTitle>
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-elevated/50 p-3"><h4 className="text-xs font-semibold text-muted mb-2">多维诊断</h4><div className="space-y-1">{s0.diagnosis?.map((d: any, i: number) => (<div key={i} className="flex justify-between text-xs"><span className="text-muted">{d.name}</span><span className="font-medium">{d.value} {d.zone}</span></div>))}</div></div>
        <div className="rounded-lg border border-border bg-elevated/50 p-3"><h4 className="text-xs font-semibold text-muted mb-2">风险清单</h4><div className="space-y-1">{s0.risks?.map((r: any, i: number) => (<div key={i} className="flex items-center gap-2 text-xs">{r.triggered ? <XCircle className="h-3 w-3 text-red-400 shrink-0" /> : <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0" />}<span className="text-foreground/80">{r.name}</span><span className="text-muted ml-auto">{r.status || (r.triggered ? '触发' : '未触发')}</span></div>))}</div></div>
      </div>

      {/* s1 */}
      <SectionTitle icon={TrendingUp}>{SECTION_TITLES.s1}</SectionTitle>
      {s1.indexes?.length > 0 && <IndexChart indexes={s1.indexes} />}
      {s1.kline_history?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4 mt-4"><h4 className="text-xs font-semibold text-muted mb-1">全A K线 + CCI5 (近{s1.kline_history.length}日)</h4><KlineChart history={s1.kline_history} /></div>)}
      {s1.up_count_history?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">涨跌家数 + 成交额 (近{s1.up_count_history.filter((d: any) => d.date && d.up_count > 0).length}日)</h4><UpCountChart history={s1.up_count_history} /></div>)}
      {(s1.width_heat?.length > 0 || s1.width_heat_level2?.length > 0) && (
        <div data-testid="sector-breadth-heatmap" className="rounded-lg border border-border bg-elevated/30 p-3 mb-4">
          <div className="mb-1 flex items-center justify-between gap-3">
            <h4 className="text-xs font-semibold text-muted">
              申万{sectorBreadthLevel === 1 ? '一级' : '二级'}行业均线宽度（站上均线成分股占比）
            </h4>
            <div className="flex rounded border border-border bg-surface p-0.5" aria-label="申万行业层级">
              {([1, 2] as const).map(level => (
                <button
                  key={level}
                  type="button"
                  disabled={level === 2 && !s1.width_heat_level2?.length}
                  onClick={() => setSectorBreadthLevel(level)}
                  className={cn(
                    'rounded px-2 py-1 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-35',
                    sectorBreadthLevel === level ? 'bg-accent/15 text-accent' : 'text-muted hover:text-foreground',
                  )}
                >
                  {level === 1 ? '一级行业' : '二级行业'}
                </button>
              ))}
            </div>
          </div>
          <SectorBreadthHeatmap data={sectorBreadth} />
        </div>
      )}
      {s1.margin_history?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">融资余额 + 净买入 (近{s1.margin_history.length}日)</h4><MarginChart history={s1.margin_history} /></div>)}
      {congestionPct > 0 && (
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div className="rounded-lg border border-border bg-elevated/30 p-3"><h4 className="text-xs font-semibold text-muted mb-1">拥挤度仪表盘</h4><CongestionGauge pct={congestionPct} /></div>
          <div className="rounded-lg border border-border bg-elevated/30 p-3"><h4 className="text-xs font-semibold text-muted mb-2">拥挤度历史</h4><table className="w-full text-[10px]"><thead><tr><th className="text-left text-muted">日期</th><th className="text-right text-muted">Top5额</th><th className="text-right text-muted">总额</th><th className="text-right text-muted">拥挤度</th></tr></thead><tbody>{congestionTable.slice(0, 8).map((row: any, i: number) => (<tr key={i} className="border-t border-border/50"><td className="py-0.5 text-muted">{row[0]}</td><td className="text-right">{parseFloat(row[2]).toFixed(0)}</td><td className="text-right">{parseFloat(row[3]).toFixed(0)}</td><td className="text-right font-medium" style={{ color: parseFloat(row[4]) > 55 ? RED : parseFloat(row[4]) > 45 ? YELLOW : CYAN }}>{parseFloat(row[4]).toFixed(1)}%</td></tr>))}</tbody></table></div>
        </div>
      )}

      {/* s2 */}
      <SectionTitle icon={Layers3}>{SECTION_TITLES.s2}</SectionTitle>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="rounded-lg border border-border bg-elevated/50 p-3"><h4 className="text-xs font-semibold text-muted mb-2">参与度: {s2.participation?.verdict} ({s2.participation?.satisfied}/{s2.participation?.total})</h4><div className="space-y-1">{s2.participation?.conditions?.map((c: any, i: number) => (<div key={i} className="flex justify-between text-xs"><span className="text-muted">{c.name}</span><span>{c.value} {c.ok === true ? '✓' : c.ok === false ? '✗' : '?'}</span></div>))}</div></div>
        <div className="rounded-lg border border-border bg-elevated/50 p-3"><h4 className="text-xs font-semibold text-muted mb-2">退潮: {s2.ebb_risk?.verdict} ({s2.ebb_risk?.signal_count}/4)</h4><p className="text-xs text-muted">详见连板情绪区</p></div>
      </div>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="rounded-lg border border-border bg-elevated/50 p-3"><h4 className="text-xs font-semibold text-muted mb-2">问财题材</h4>{s2.themes_pywencai?.map((t: any, i: number) => (<div key={i} className="flex justify-between text-xs"><span>{t.name}</span><span className="text-muted">{t.count}</span></div>))}</div>
        <div className="rounded-lg border border-border bg-elevated/50 p-3"><h4 className="text-xs font-semibold text-muted mb-2">同花顺热点</h4>{s2.themes_ths?.map((t: any, i: number) => (<div key={i} className="flex justify-between text-xs"><span>{t.tag}</span><span className="text-muted">{t.count}</span></div>))}</div>
      </div>
      {s2.new_high?.status === 'ok' && s2.new_high.stocks?.length > 0 && (<div className="mb-4"><h4 className="text-xs font-semibold text-muted mb-2">百日新高</h4><div className="flex flex-wrap gap-2">{s2.new_high.stocks.map((nh: any, i: number) => (<span key={i} className="rounded border border-border px-2 py-0.5 text-xs">{nh.name} {nh.pct_chg?.toFixed(1)}%</span>))}</div></div>)}

      {/* s3 */}
      <SectionTitle icon={Flame}>{SECTION_TITLES.s3}</SectionTitle>
      <div className="rounded-xl border border-border bg-elevated/30 p-4 mb-4 space-y-3"><div className="flex items-center gap-2 mb-2"><Activity className="h-4 w-4 text-accent" /><span className="text-sm font-semibold">情绪三件套</span></div><ScoreBar label="市场热度" score={s3.emotion_scores?.market_heat ?? 0} zone={s3.emotion_zones?.market_heat ?? ''} /><ScoreBar label="短线情绪" score={s3.emotion_scores?.short_term ?? 0} zone={s3.emotion_zones?.short_term ?? ''} /><ScoreBar label="趋势情绪" score={s3.emotion_scores?.trend ?? 0} zone={s3.emotion_zones?.trend ?? ''} /></div>
      {emotionTrendData.dates.length > 1 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">情绪趋势 (近{emotionTrendData.dates.length}日)</h4><EmotionTrendChart dates={emotionTrendData.dates} scores={emotionTrendData.scores} /></div>)}
      {s3.height_history?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">连板高度历史 (markLine: 3板/5板)</h4><HeightChart history={s3.height_history} /></div>)}
      {s3.advance_history?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">晋级率/溢价率/涨停数 (近{s3.advance_history.length}日, 3轴)</h4><AdvanceRateChart history={s3.advance_history} /></div>)}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className={cn('rounded-lg border p-3', (s3.ebb_signals || []).some((e: any) => e.triggered) ? 'border-orange-500/40 bg-orange-500/5' : 'border-border bg-elevated/50')}><h4 className="text-xs font-semibold mb-2">退潮信号</h4>{(s3.ebb_signals || []).map((e: any, i: number) => (<div key={i} className="flex items-center gap-2 text-xs">{e.triggered ? <AlertTriangle className="h-3 w-3 text-orange-400" /> : <CheckCircle2 className="h-3 w-3 text-green-400" />}<span>{e.name}</span><span className="ml-auto text-muted">{e.triggered ? '触发' : '未触发'}</span></div>))}</div>
        <div className={cn('rounded-lg border p-3', s3.crash_signals?.some((c: any) => c.triggered) ? 'border-red-500/40 bg-red-500/5' : 'border-border bg-elevated/50')}><h4 className="text-xs font-semibold mb-2">崩塌信号</h4>{(s3.crash_signals || []).map((c: any, i: number) => (<div key={i} className="flex items-center gap-2 text-xs">{c.triggered ? <XCircle className="h-3 w-3 text-red-400" /> : <CheckCircle2 className="h-3 w-3 text-green-400" />}<span>{c.name}</span><span className="ml-auto text-muted">{c.status}</span></div>))}</div>
      </div>
      <div className="grid grid-cols-4 gap-3 text-xs mb-4">
        <div className="rounded border border-border bg-elevated/30 p-2 text-center"><div className="text-muted text-[10px]">最高连板</div><div className="font-bold">{em.height_trend?.latest_max_board ?? '--'}</div></div>
        <div className="rounded border border-border bg-elevated/30 p-2 text-center"><div className="text-muted text-[10px]">5日前高</div><div className="font-bold">{em.height_trend?.previous_high_5d ?? '--'}</div></div>
        <div className="rounded border border-border bg-elevated/30 p-2 text-center"><div className="text-muted text-[10px]">晋级率</div><div className="font-bold">{s3.advance?.advance_rate ?? '--'}%</div></div>
        <div className="rounded border border-border bg-elevated/30 p-2 text-center"><div className="text-muted text-[10px]">溢价率</div><div className="font-bold">{s3.advance?.premium_rate ?? '--'}%</div></div>
      </div>

      {/* s4 */}
      <SectionTitle icon={Gauge}>{SECTION_TITLES.s4}</SectionTitle>
      <div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><SectorFlowChart topIn={s4.sector_flow?.top_in || []} topOut={s4.sector_flow?.top_out || []} /></div>
      {s4.sector_treemap?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">行业资金 treemap (红流入/绿流出)</h4><SectorTreemapChart data={s4.sector_treemap} /></div>)}
      {s4.sector_treemap?.length > 0 && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mb-4"><h4 className="text-xs font-semibold text-muted mb-1">行业散点 (涨跌幅 vs 净流入)</h4><SectorScatterChart data={s4.sector_treemap} /></div>)}

      {/* s5 */}
      <SectionTitle icon={FileText}>{SECTION_TITLES.s5}</SectionTitle>
      {s5.candidates?.length > 0 && (<div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">{s5.candidates.map((c: any, i: number) => (<div key={i} className="rounded-lg border border-border bg-elevated/50 p-3"><div className="flex items-center justify-between mb-1"><span className="font-semibold text-sm">{c.name}</span><span className="text-xs text-accent">{c.limit_times}板</span></div><div className="text-xs text-muted font-mono">{c.code}</div><div className="text-[10px] text-muted/70 mt-1">{c.reason}</div></div>))}</div>)}

      {/* s6 */}
      <SectionTitle icon={BookOpenCheck}>{SECTION_TITLES.s6}</SectionTitle>
      <div className="rounded-lg border border-border bg-elevated/50 p-4 mb-4"><div className="text-sm font-semibold mb-1">{s6.position?.band}</div><div className="text-xs text-muted">{s6.position?.action}</div></div>
      <div className="grid grid-cols-3 gap-3 mb-4">{s6.scenes?.map((sc: any, i: number) => (<div key={i} className={cn('rounded-lg border p-3 text-center', sc.tone === 'positive' ? 'border-red-500/30' : sc.tone === 'negative' ? 'border-green-500/30' : 'border-border')}><div className="text-sm font-semibold">{sc.name}</div><div className="text-[10px] text-muted mt-1">{sc.condition}</div></div>))}</div>
      {em.daily_summary && (<div className="rounded-lg border border-border bg-elevated/30 p-3 mt-6"><p className="text-sm text-foreground/80">{em.daily_summary}</p></div>)}
    </div>
  )
}
