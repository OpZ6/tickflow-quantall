import { useEffect, useRef, useCallback, useMemo } from 'react'
import { chartTheme, getTheme, useTheme } from '@/lib/theme'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import type { ChanlunAnalysis } from '@/lib/api'
import { getParams } from '@/lib/indicator-params'
import {
  calcATR, calcAO, calcAroon, calcADL, calcBIAS, calcBRAR, calcCCI, calcChaikinOsc,
  calcCMF, calcCMO, calcCR, calcDMA, calcDPO, calcDMI, calcElderRay, calcEMV,
  calcForceIndex, calcMFI, calcMTM, calcOBV, calcPPO, calcPSY, calcROC,
  calcSTC, calcStoch, calcStochRSI, calcTRIX, calcTSI, calcTTMSqueeze, calcUO,
  calcVR, calcVortex, calcWR, calcBOLL, calcBBI, calcZigZag, calcSAR, calcTEMA, calcDEMA,
  calcHMA, calcWMA, calcVWMA, calcVWAP, calcSupertrend, calcDonchian, calcKeltner,
  calcIchimoku, calcAlligator, calcLinRegChannel, calcEMA, calcSMA, calcChop, calcPVT,
  calcKDJChannel, calcWRChannel,
} from '@/lib/indicator-formulas'

export interface OHLC {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  ma5?: number | null
  ma10?: number | null
  ma20?: number | null
  ma60?: number | null
  macd_dif?: number | null
  macd_dea?: number | null
  macd_hist?: number | null
  rsi_6?: number | null
  rsi_14?: number | null
  rsi_24?: number | null
  kdj_k?: number | null
  kdj_d?: number | null
  kdj_j?: number | null
  boll_upper?: number | null
  boll_lower?: number | null
}

export interface ChartMarker {
  id?: string
  date: string
  kind: 'buy' | 'sell' | 'neutral'
  label?: string
  /** 若为 true，标记放在蜡烛上方（如涨停连板标签）。 */
  above?: boolean
  /** 自定义标签颜色，覆盖默认的 kind 对应色。 */
  color?: string
  evidenceId?: string
  symbol?: 'arrow' | 'triangle' | 'diamond' | 'circle' | 'pin'
}

export interface ChartRange {
  start: string
  end: string
  label?: string
  color?: string
  low?: number | null
  high?: number | null
  evidenceId?: string
}

export interface ChartPriceLine {
  value: number
  endValue?: number
  label?: string
  color?: string
  start?: string
  end?: string
}

export interface StockInfo {
  name?: string
  total_shares?: number
  float_shares?: number
  /** 扩展数据（key: configId__fieldName），来自 klineDaily 的 ext_columns */
  ext?: Record<string, unknown>
}

export interface VolumeCompareConfig {
  enabled: boolean
  days: number
}

// ===== 缠论 (Chan Theory) 图层 =====

export interface ChanlunLayerConfig {
  /** 缠论总开关 */
  visible: boolean
  showBi: boolean
  showSegments: boolean
  showZhongshu: boolean
  showBsp: boolean
  /** 展示包含关系处理后的合并 K 线区间。 */
  showMerged?: boolean
  /** 展示顶/底分型。 */
  showFenxing?: boolean
  /** 叠加 ZenChart 官方图层 (红色系, 需传入 chanlunOfficial) */
  showOfficial: boolean
}

export const DEFAULT_CHANLUN_CONFIG: ChanlunLayerConfig = {
  visible: false, showBi: true, showSegments: true, showZhongshu: true, showBsp: true,
  showOfficial: false,
}

/** 已映射到本图 K 线索引的缠论数据 (index 与 data 数组一一对应) */
export interface ChanlunMappedLayer {
  merged: { startIdx: number | null; endIdx: number | null; low: number; high: number; direction: string }[]
  fenxing: { idx: number | null; type: 'bottom' | 'top'; value: number }[]
  bi: {
    startIdx: number | null; endIdx: number | null
    startPrice: number; endPrice: number
    direction: 'up' | 'down'; isSure: boolean
  }[]
  segments: {
    startIdx: number | null; endIdx: number | null
    startPrice: number; endPrice: number
    direction: 'up' | 'down'
  }[]
  zhongshu: { startIdx: number | null; endIdx: number | null; low: number; high: number }[]
  bsp: { idx: number | null; direction: 'buy' | 'sell'; type: string; price: number }[]
}

/**
 * 将后端缠论分析结果映射到图表数据索引。
 * 要求 candles 与 data 同序同长（发送分析请求时由同一 rows 数组生成）。
 */
export function mapChanlunData(
  chanlun: ChanlunAnalysis | null | undefined,
  timeToIndex: Map<number, number>,
): ChanlunMappedLayer | null {
  if (!chanlun) return null
  const idx = (t: number | undefined | null): number | null =>
    t == null ? null : (timeToIndex.get(t) ?? null)
  return {
    merged: (chanlun.merged_klines ?? []).map(item => ({
      startIdx: idx(item.start_time), endIdx: idx(item.end_time),
      low: item.low, high: item.high, direction: item.dir,
    })),
    fenxing: (chanlun.fenxing ?? []).map(item => ({
      idx: idx(item.time), type: item.type, value: item.value,
    })),
    bi: (chanlun.bi ?? []).map(b => ({
      startIdx: idx(b.start_time), endIdx: idx(b.end_time),
      startPrice: b.start_price, endPrice: b.end_price,
      direction: b.direction, isSure: b.is_sure !== false,
    })),
    segments: (chanlun.segments ?? []).map(s => ({
      startIdx: idx(s.start_time), endIdx: idx(s.end_time),
      startPrice: s.start_price, endPrice: s.end_price,
      direction: s.direction,
    })),
    zhongshu: (chanlun.zhongshu ?? []).map(z => ({
      startIdx: idx(z.start_time), endIdx: idx(z.end_time),
      low: z.low, high: z.high,
    })),
    bsp: (chanlun.bsp ?? [])
      .filter(b => b.level === 'bi')
      .map(b => ({ idx: idx(b.time), direction: b.direction, type: b.type, price: b.price })),
  }
}

/** 日期字符串 → 当日本地午夜 unix 秒 (与后端 candle.time 约定一致) */
export function candleTimeOf(date: string): number {
  return Math.floor(new Date(date.includes('T') ? date : `${date}T00:00:00`).getTime() / 1000)
}

/** 由图表 rows 构建时间→索引映射 (配合 mapChanlunData 使用) */
export function buildTimeIndex(rows: { date: string }[]): Map<number, number> {
  const m = new Map<number, number>()
  rows.forEach((r, i) => m.set(candleTimeOf(r.date), i))
  return m
}

/** 由图表 rows 生成缠论分析请求的 candle 数组 (同序同长，保证索引对齐) */
export function toChanlunCandles(rows: OHLC[]): { time: number; open: number; high: number; low: number; close: number; volume?: number }[] {
  return rows.map(r => ({
    time: candleTimeOf(r.date),
    open: r.open, high: r.high, low: r.low, close: r.close,
    volume: r.volume,
  }))
}

interface SubChartContext {
  compact: boolean
  volumeCompare: VolumeCompareConfig
  /** 指标参数 (key: 指标 key, value: { 参数名: 值 }) */
  params: Record<string, Record<string, number>>
}

/** 子图定义 */
export interface SubChartDef {
  key: string
  label: string
  /** 子图固定高度 px */
  height: number
  /** 构建 series 数组 */
  buildSeries: (data: OHLC[], context: SubChartContext) => any[]
  /** 构建信息栏文字 (当前数据行 + 数据集/索引 -> 显示内容; 前端计算型指标需要 data+idx) */
  buildInfo: (d: OHLC | null, data?: OHLC[], idx?: number) => { label: string; color: string; value: string }[]
  /** Y 轴特殊配置 */
  yAxisConfig?: Record<string, any>
  /** 水平参考线 (如 RSI 的 30/70) */
  refLines?: number[]
}

// ===== 成交量 N 日均量 =====
function volMaN(data: OHLC[], n: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < n - 1) { result.push(null); continue }
    let sum = 0
    for (let j = i - n + 1; j <= i; j++) sum += data[j].volume ?? 0
    result.push(sum / n)
  }
  return result
}

function fmtVol(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

function volumeRatioAt(data: OHLC[], index: number, days: number): number | null {
  const window = Math.max(1, Math.min(20, Math.round(days)))
  if (index < window) return null
  let sum = 0
  for (let offset = 1; offset <= window; offset++) {
    const volume = data[index - offset]?.volume
    if (volume == null || !Number.isFinite(volume)) return null
    sum += volume
  }
  const average = sum / window
  const current = data[index]?.volume
  if (current == null || !Number.isFinite(current) || average <= 0) return null
  return current / average
}

function fmtVolumeRatio(value: number | null, digits = 2): string {
  return value == null ? '—' : `${value.toFixed(digits)}x`
}

const CORE_SUB_CHARTS: SubChartDef[] = [
  {
    key: 'vol',
    label: '成交量',
    height: 84,
    yAxisConfig: { min: 0 },
    buildSeries: (data, context) => {
      const ma5Data = volMaN(data, 5)
      const ma10Data = volMaN(data, 10)
      const compareDays = context.volumeCompare.days
      return [
        {
          name: '成交量',
          type: 'bar',
          data: data.map((d, index) => {
            const ratio = volumeRatioAt(data, index, compareDays)
            return {
              value: d.volume ?? 0,
              volumeRatioLabel: ratio == null ? '' : fmtVolumeRatio(ratio, 1),
              itemStyle: {
                color: d.close >= d.open ? 'rgba(240,68,56,0.6)' : 'rgba(18,183,106,0.6)',
              },
            }
          }),
          barWidth: '60%',
          label: {
            show: context.volumeCompare.enabled && !context.compact,
            position: 'top',
            distance: 2,
            color: CT().text,
            fontSize: 8,
            fontFamily: 'JetBrains Mono, monospace',
            formatter: (params: any) => params.data?.volumeRatioLabel ?? '',
          },
          labelLayout: { hideOverlap: true },
          animation: false,
        },
        {
          name: 'VOL5',
          type: 'line',
          data: ma5Data,
          smooth: true, symbol: 'none', animation: false,
          lineStyle: { width: 1, color: '#FACC15' },
          itemStyle: { color: '#FACC15' },
        },
        {
          name: 'VOL10',
          type: 'line',
          data: ma10Data,
          smooth: true, symbol: 'none', animation: false,
          lineStyle: { width: 1, color: '#8B5CF6' },
          itemStyle: { color: '#8B5CF6' },
        },
      ]
    },
    buildInfo: (d) => {
      if (!d) return []
      return [
        { label: '量', color: d.close >= d.open ? '#C74040' : '#2D9B65', value: fmtVol(d.volume) },
      ]
    },
  },
  {
    key: 'macd',
    label: 'MACD',
    height: 72,
    buildSeries: (data) => [
      {
        name: 'DIF',
        type: 'line',
        data: data.map(d => d.macd_dif != null ? Number(d.macd_dif) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#FACC15' },
        itemStyle: { color: '#FACC15' },
      },
      {
        name: 'DEA',
        type: 'line',
        data: data.map(d => d.macd_dea != null ? Number(d.macd_dea) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#8B5CF6' },
        itemStyle: { color: '#8B5CF6' },
      },
      {
        name: 'MACD',
        type: 'bar',
        data: data.map(d => {
          const v = d.macd_hist
          if (v == null) return '-'
          return {
            value: Number(v),
            itemStyle: { color: Number(v) >= 0 ? 'rgba(240,68,56,0.6)' : 'rgba(18,183,106,0.6)' },
          }
        }),
        barWidth: '40%',
        animation: false,
      },
    ],
    buildInfo: (d) => {
      if (!d) return []
      return [
        { label: 'DIF', color: '#FACC15', value: d.macd_dif != null ? d.macd_dif.toFixed(3) : '—' },
        { label: 'DEA', color: '#8B5CF6', value: d.macd_dea != null ? d.macd_dea.toFixed(3) : '—' },
        { label: 'MACD', color: d.macd_hist != null && d.macd_hist >= 0 ? '#C74040' : '#2D9B65', value: d.macd_hist != null ? d.macd_hist.toFixed(3) : '—' },
      ]
    },
  },
  {
    key: 'rsi',
    label: 'RSI',
    height: 72,
    yAxisConfig: { min: 0, max: 100 },
    buildSeries: (data) => [
      {
        name: 'RSI6',
        type: 'line',
        data: data.map(d => d.rsi_6 != null ? Number(d.rsi_6) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#FACC15' },
        itemStyle: { color: '#FACC15' },
      },
      {
        name: 'RSI14',
        type: 'line',
        data: data.map(d => d.rsi_14 != null ? Number(d.rsi_14) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#3B82F6' },
        itemStyle: { color: '#3B82F6' },
      },
      {
        name: 'RSI24',
        type: 'line',
        data: data.map(d => d.rsi_24 != null ? Number(d.rsi_24) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#8B5CF6' },
        itemStyle: { color: '#8B5CF6' },
      },
    ],
    buildInfo: (d) => {
      if (!d) return []
      return [
        { label: 'RSI6', color: '#FACC15', value: d.rsi_6 != null ? d.rsi_6.toFixed(1) : '—' },
        { label: 'RSI14', color: '#3B82F6', value: d.rsi_14 != null ? d.rsi_14.toFixed(1) : '—' },
        { label: 'RSI24', color: '#8B5CF6', value: d.rsi_24 != null ? d.rsi_24.toFixed(1) : '—' },
      ]
    },
  },
  {
    key: 'kdj',
    label: 'KDJ',
    height: 72,
    buildSeries: (data) => [
      {
        name: 'K',
        type: 'line',
        data: data.map(d => d.kdj_k != null ? Number(d.kdj_k) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#FACC15' },
        itemStyle: { color: '#FACC15' },
      },
      {
        name: 'D',
        type: 'line',
        data: data.map(d => d.kdj_d != null ? Number(d.kdj_d) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#3B82F6' },
        itemStyle: { color: '#3B82F6' },
      },
      {
        name: 'J',
        type: 'line',
        data: data.map(d => d.kdj_j != null ? Number(d.kdj_j) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: '#8B5CF6' },
        itemStyle: { color: '#8B5CF6' },
      },
    ],
    buildInfo: (d) => {
      if (!d) return []
      return [
        { label: 'K', color: '#FACC15', value: d.kdj_k != null ? d.kdj_k.toFixed(1) : '—' },
        { label: 'D', color: '#3B82F6', value: d.kdj_d != null ? d.kdj_d.toFixed(1) : '—' },
        { label: 'J', color: '#8B5CF6', value: d.kdj_j != null ? d.kdj_j.toFixed(1) : '—' },
      ]
    },
  },
]

// ===== 扩展副图指标 (前端计算, 公式移植自 openclarr-chanlun) =====

type LineDef = { name: string; color: string; values: (number | null)[] }

/** 按 data 引用 + 参数签名缓存计算结果，避免鼠标移动时重复计算 */
const subComputeCache = new WeakMap<OHLC[], Map<string, LineDef[]>>()

function cachedLines(
  data: OHLC[], cacheKey: string, params: Record<string, number>,
  compute: (C: OHLC[], p: Record<string, number>) => LineDef[],
): LineDef[] {
  let m = subComputeCache.get(data)
  if (!m) { m = new Map(); subComputeCache.set(data, m) }
  const sig = JSON.stringify(params)
  const fullKey = `${cacheKey}|${sig}`
  const hit = m.get(fullKey)
  if (hit) return hit
  for (const k of [...m.keys()]) if (k.startsWith(`${cacheKey}|`)) m.delete(k)
  const out = compute(data, params)
  m.set(fullKey, out)
  return out
}

/** 标准多线副图工厂 */
function makeLinesSub(
  key: string,
  label: string,
  compute: (data: OHLC[], p: Record<string, number>) => LineDef[],
  opts?: {
    height?: number
    yAxisConfig?: Record<string, any>
    refLines?: number[]
    zeroLine?: boolean
    barLine?: (lines: LineDef[], data: OHLC[]) => any[] | null
  },
): SubChartDef {
  const refLines = [...(opts?.refLines ?? []), ...(opts?.zeroLine ? [0] : [])]
  return {
    key,
    label,
    height: opts?.height ?? 72,
    ...(opts?.yAxisConfig ? { yAxisConfig: opts.yAxisConfig } : {}),
    ...(refLines.length > 0 ? { refLines } : {}),
    buildSeries: (data, _context) => {
      const lines = cachedLines(data, key, getParams(key), compute)
      const series: any[] = lines.map(l => ({
        name: l.name, type: 'line',
        data: l.values.map(v => v != null ? Number(v) : '-'),
        smooth: true, symbol: 'none', animation: false,
        lineStyle: { width: 1, color: l.color }, itemStyle: { color: l.color },
      }))
      if (opts?.barLine) {
        const extra = opts.barLine(lines, data)
        if (extra) series.push(...extra)
      }
      if (refLines.length > 0 && series.length > 0) {
        series[0] = {
          ...series[0],
          markLine: {
            silent: true, symbol: 'none', animation: false,
            lineStyle: { color: 'rgba(255,255,255,0.14)', type: 'dashed', width: 1 },
            label: { show: false },
            data: refLines.map(v => ({ yAxis: v })),
          },
        }
      }
      return series
    },
    buildInfo: (d, data, idx) => {
      if (!d || !data || idx == null || idx < 0 || idx >= data.length) return []
      const lines = cachedLines(data, key, getParams(key), compute)
      const fmt = (v: number | null) => v == null ? '—' : Math.abs(v) >= 1e5 ? (v / 1e4).toFixed(0) + '万' : v.toFixed(2)
      return lines.map(l => ({ label: l.name, color: l.color, value: fmt(l.values[idx]) }))
    },
  }
}

const EXTENDED_SUB_CHARTS: SubChartDef[] = [
  makeLinesSub('wr', 'WR', (d, p) => [{ name: 'WR', color: '#3B82F6', values: calcWR(d, p.p) }], { yAxisConfig: { min: 0, max: 100 }, refLines: [20, 80] }),
  makeLinesSub('cci', 'CCI', (d, p) => [{ name: 'CCI', color: '#ff9800', values: calcCCI(d, p.p) }], { refLines: [-100, 100] }),
  makeLinesSub('bias', 'BIAS', d => [
    { name: 'BIAS6', color: '#8B5CF6', values: calcBIAS(d, 6) },
    { name: 'BIAS12', color: '#3B82F6', values: calcBIAS(d, 12) },
    { name: 'BIAS24', color: '#22c55e', values: calcBIAS(d, 24) },
  ], { zeroLine: true }),
  makeLinesSub('obv', 'OBV', d => [{ name: 'OBV', color: '#ff9800', values: calcOBV(d) }]),
  makeLinesSub('vr', 'VR', (d, p) => [{ name: 'VR', color: '#8B5CF6', values: calcVR(d, p.n) }], { refLines: [40, 150] }),
  makeLinesSub('atr', 'ATR', (d, p) => [{ name: 'ATR', color: '#ff9800', values: calcATR(d, p.n) }], { height: 56 }),
  makeLinesSub('dmi', 'DMI', (d, p) => {
    const r = calcDMI(d, p.n, p.m)
    return [
      { name: 'PDI', color: '#f43f5e', values: r.pdi },
      { name: 'MDI', color: '#3B82F6', values: r.mdi },
      { name: 'ADX', color: '#ff9800', values: r.adx },
      { name: 'ADXR', color: '#22c55e', values: r.adxr },
    ]
  }),
  makeLinesSub('mtm', 'MTM', (d, p) => {
    const r = calcMTM(d, p.n, p.m)
    return [
      { name: 'MTM', color: '#3B82F6', values: r.mtm },
      { name: 'MTMMA', color: '#f43f5e', values: r.mamtm },
    ]
  }, { zeroLine: true }),
  makeLinesSub('roc', 'ROC', (d, p) => {
    const r = calcROC(d, p.n, p.m)
    return [
      { name: 'ROC', color: '#3B82F6', values: r.roc },
      { name: 'ROAMA', color: '#f43f5e', values: r.maroc },
    ]
  }, { zeroLine: true }),
  makeLinesSub('mfi', 'MFI', (d, p) => [{ name: 'MFI', color: '#8B5CF6', values: calcMFI(d, p.n) }], { yAxisConfig: { min: 0, max: 100 }, refLines: [20, 80] }),
  makeLinesSub('cmf', 'CMF', (d, p) => [{ name: 'CMF', color: '#3B82F6', values: calcCMF(d, p.n) }], { zeroLine: true }),
  makeLinesSub('cmo', 'CMO', (d, p) => [{ name: 'CMO', color: '#ff9800', values: calcCMO(d, p.n) }], { refLines: [-50, 50] }),
  makeLinesSub('trix', 'TRIX', (d, p) => {
    const r = calcTRIX(d, p.n, p.m)
    return [
      { name: 'TRIX', color: '#3B82F6', values: r.trix },
      { name: 'MATRIX', color: '#f43f5e', values: r.matrix },
    ]
  }, { zeroLine: true }),
  makeLinesSub('tsi', 'TSI', (d, p) => {
    const r = calcTSI(d, p.r, p.s, p.sig)
    return [
      { name: 'TSI', color: '#3B82F6', values: r.tsi },
      { name: 'SIGNAL', color: '#f43f5e', values: r.signal },
    ]
  }, { zeroLine: true }),
  makeLinesSub('stoch', 'Stoch', (d, p) => {
    const r = calcStoch(d, p.n, p.sk, p.sd)
    return [
      { name: 'K', color: '#3B82F6', values: r.k },
      { name: 'D', color: '#f43f5e', values: r.d },
    ]
  }, { yAxisConfig: { min: 0, max: 100 }, refLines: [20, 80] }),
  makeLinesSub('stochrsi', 'StochRSI', (d, p) => {
    const r = calcStochRSI(d, p.rn, p.sn, p.sk, p.sd)
    return [
      { name: 'K', color: '#3B82F6', values: r.k },
      { name: 'D', color: '#f43f5e', values: r.d },
    ]
  }, { yAxisConfig: { min: 0, max: 100 }, refLines: [20, 80] }),
  makeLinesSub('ppo', 'PPO', (d, p) => {
    const r = calcPPO(d, p.f, p.s, p.sig)
    return [
      { name: 'PPO', color: '#3B82F6', values: r.ppo },
      { name: 'SIGNAL', color: '#f43f5e', values: r.signal },
    ]
  }, { zeroLine: true }),
  makeLinesSub('dma', 'DMA', (d, p) => {
    const r = calcDMA(d, p.n1, p.n2, p.m)
    return [
      { name: 'DDD', color: '#3B82F6', values: r.ddd },
      { name: 'AMA', color: '#f43f5e', values: r.ama },
    ]
  }, { zeroLine: true }),
  makeLinesSub('uo', 'UO', (d, p) => [{ name: 'UO', color: '#8B5CF6', values: calcUO(d, p.s, p.m, p.l) }], { yAxisConfig: { min: 0, max: 100 }, refLines: [30, 70] }),
  makeLinesSub('vortex', 'Vortex', (d, p) => {
    const r = calcVortex(d, p.n)
    return [
      { name: 'VI+', color: '#22c55e', values: r.plus },
      { name: 'VI-', color: '#f43f5e', values: r.minus },
    ]
  }),
  makeLinesSub('psy', 'PSY', (d, p) => {
    const r = calcPSY(d, p.n, p.m)
    return [
      { name: 'PSY', color: '#3B82F6', values: r.psy },
      { name: 'PSYMA', color: '#f43f5e', values: r.psyma },
    ]
  }, { yAxisConfig: { min: 0, max: 100 }, refLines: [50] }),
  makeLinesSub('chop', 'Chop', (d, p) => [{ name: 'CHOP', color: '#ff9800', values: calcChop(d, p.n) }], { yAxisConfig: { min: 0, max: 100 }, refLines: [38.2, 61.8] }),
  makeLinesSub('ao', 'AO', (d, p) => [{ name: 'AO', color: '#3B82F6', values: calcAO(d, p.fast, p.slow) }], {
    zeroLine: true,
    barLine: (lines, data) => [{
      name: 'AOBAR', type: 'bar', barWidth: '40%', animation: false,
      data: data.map((_, i) => {
        const v = lines[0].values[i]
        if (v == null) return '-'
        return { value: v, itemStyle: { color: v >= 0 ? 'rgba(240,68,56,0.55)' : 'rgba(18,183,106,0.55)' } }
      }),
    }],
  }),
  makeLinesSub('aroon', 'Aroon', (d, p) => {
    const r = calcAroon(d, p.n)
    return [
      { name: 'UP', color: '#22c55e', values: r.up },
      { name: 'DOWN', color: '#f43f5e', values: r.dn },
    ]
  }, { yAxisConfig: { min: 0, max: 100 } }),
  makeLinesSub('pvt', 'PVT', d => [{ name: 'PVT', color: '#ff9800', values: calcPVT(d) }]),
  makeLinesSub('dpo', 'DPO', (d, p) => [{ name: 'DPO', color: '#3B82F6', values: calcDPO(d, p.n) }], { zeroLine: true }),
  makeLinesSub('forceindex', 'Force', (d, p) => [{ name: 'FORCE', color: '#8B5CF6', values: calcForceIndex(d, p.n) }], { zeroLine: true, height: 56 }),
  makeLinesSub('emv', 'EMV', (d, p) => {
    const r = calcEMV(d, p.n, p.m)
    return [
      { name: 'EMV', color: '#3B82F6', values: r.emv },
      { name: 'MAEMV', color: '#f43f5e', values: r.maemv },
    ]
  }, { zeroLine: true }),
  makeLinesSub('adl', 'ADL', d => [{ name: 'ADL', color: '#ff9800', values: calcADL(d) }]),
  makeLinesSub('chaikinosc', 'Chaikin', (d, p) => [{ name: 'CHAIKIN', color: '#3B82F6', values: calcChaikinOsc(d, p.fast, p.slow) }], { zeroLine: true }),
  makeLinesSub('elderray', 'ElderRay', (d, p) => {
    const r = calcElderRay(d, p.n)
    return [
      { name: 'BULL', color: '#22c55e', values: r.bull },
      { name: 'BEAR', color: '#f43f5e', values: r.bear },
    ]
  }, { zeroLine: true }),
  makeLinesSub('ttmsqueeze', 'TTM', (d, p) => [{ name: 'SRC', color: '#3B82F6', values: calcTTMSqueeze(d, p.n, p.bbMult, p.kcMult).src }], { zeroLine: true }),
  makeLinesSub('stc', 'STC', (d, p) => [{ name: 'STC', color: '#ff9800', values: calcSTC(d, p.f, p.s, p.cyc) }], { yAxisConfig: { min: 0, max: 100 } }),
  makeLinesSub('cr', 'CR', (d, p) => [{ name: 'CR', color: '#ff9800', values: calcCR(d, p.n) }], { refLines: [40, 200] }),
  makeLinesSub('brar', 'BRAR', (d, p) => {
    const r = calcBRAR(d, p.n)
    return [
      { name: 'AR', color: '#3B82F6', values: r.ar },
      { name: 'BR', color: '#f43f5e', values: r.br },
    ]
  }, { refLines: [100] }),
]

/** 全部可用副图 (核心 + 扩展) */
export const SUB_CHARTS: SubChartDef[] = [...CORE_SUB_CHARTS, ...EXTENDED_SUB_CHARTS]

/** 向后兼容的 INDICATORS 导出 (不含 vol) */
export const INDICATORS = SUB_CHARTS.filter(s => s.key !== 'vol')

/** 主图叠加指标 (画在 K 线上方, 不占副图空间) — 全部前端计算, 移植自 openclarr-chanlun */
export const OVERLAY_INDICATORS: { key: string; label: string }[] = [
  { key: 'boll', label: 'BOLL' },
  { key: 'ema', label: 'EMA' },
  { key: 'sma', label: 'SMA' },
  { key: 'bbi', label: 'BBI' },
  { key: 'sar', label: 'SAR' },
  { key: 'zigzag', label: 'ZIGZAG' },
  { key: 'tema', label: 'TEMA' },
  { key: 'dema', label: 'DEMA' },
  { key: 'hma', label: 'HMA' },
  { key: 'wma', label: 'WMA' },
  { key: 'vwma', label: 'VWMA' },
  { key: 'vwap', label: 'VWAP' },
  { key: 'supertrend', label: 'Supertrend' },
  { key: 'donchian', label: 'Donchian' },
  { key: 'keltner', label: 'Keltner' },
  { key: 'ichimoku', label: 'Ichimoku' },
  { key: 'alligator', label: 'Alligator' },
  { key: 'linreg', label: 'LinReg' },
  { key: 'kdjch', label: 'KDJ通道' },
  { key: 'wrch', label: 'WR通道' },
]

const OVERLAY_KEYS = new Set(OVERLAY_INDICATORS.map(o => o.key))

function reportIndicatorError(key: string, error: unknown): void {
  console.error(`[stock-chart] 指标 ${key} 计算失败`, error)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('stock-chart-indicator-error', { detail: { key } }))
  }
}

/** 主图叠加指标的 line series 快捷构造 */
function ovLine(name: string, color: string, values: (number | null)[], dashed = false) {
  return {
    name, type: 'line',
    data: values.map(v => v != null ? Number(v) : '-'),
    smooth: false, symbol: 'none', animation: false, silent: true,
    lineStyle: { width: 1.2, color, ...(dashed ? { type: 'dashed' as const } : {}) },
    itemStyle: { color },
  }
}

/** 由公式库构建主图叠加 series (boll 走数据字段单独处理) */
function buildOverlaySeries(key: string, data: OHLC[]): any[] {
  const p = getParams(key)
  switch (key) {
    case 'ema': return [ovLine(`EMA${p.p}`, '#ff9800', calcEMA(data, p.p))]
    case 'sma': return [ovLine(`SMA${p.p}`, '#facc15', calcSMA(data, p.p))]
    case 'bbi': return [ovLine('BBI', '#9c27b0', calcBBI(data, p.p1, p.p2, p.p3, p.p4))]
    case 'sar': {
      const pts = calcSAR(data, p.step, p.maxAF)
      const dates = data.map(d => d.date)
      const mk = (up: boolean) => pts
        .map((pt, i) => (pt && pt.up === up ? [dates[i], pt.value] as [string, number] : null))
        .filter((x): x is [string, number] => x != null)
      return [
        { name: 'SAR-UP', type: 'scatter', data: mk(true), symbolSize: 3, itemStyle: { color: '#f23645' }, silent: true, animation: false },
        { name: 'SAR-DN', type: 'scatter', data: mk(false), symbolSize: 3, itemStyle: { color: '#22c55e' }, silent: true, animation: false },
      ]
    }
    case 'zigzag': return [ovLine('ZIGZAG', '#fde047', calcZigZag(data, p.dev), true)]
    case 'tema': return [ovLine(`TEMA${p.n}`, '#00bcd4', calcTEMA(data, p.n))]
    case 'dema': return [ovLine(`DEMA${p.n}`, '#00bcd4', calcDEMA(data, p.n))]
    case 'hma': return [ovLine(`HMA${p.p}`, '#7c4dff', calcHMA(data, p.p))]
    case 'wma': return [ovLine(`WMA${p.p}`, '#8d6e63', calcWMA(data, p.p))]
    case 'vwma': return [ovLine(`VWMA${p.p}`, '#8d6e63', calcVWMA(data, p.p))]
    case 'vwap': return [ovLine('VWAP', '#607d8b', calcVWAP(data))]
    case 'supertrend': {
      const r = calcSupertrend(data, p.n, p.mult)
      return [ovLine('ST-UP', '#2bc983', r.up), ovLine('ST-DN', '#f23645', r.down)]
    }
    case 'donchian': {
      const [up, mid, dn] = calcDonchian(data, p.n)
      return [ovLine('DC-UP', '#e53935', up), ovLine('DC-MID', '#2962ff', mid, true), ovLine('DC-DN', '#43a047', dn)]
    }
    case 'keltner': {
      const [up, mid, dn] = calcKeltner(data, p.n, p.m)
      return [ovLine('KC-UP', '#e53935', up), ovLine('KC-MID', '#2962ff', mid, true), ovLine('KC-DN', '#43a047', dn)]
    }
    case 'ichimoku': {
      const r = calcIchimoku(data, p.conv, p.base, p.span, p.disp)
      return [
        ovLine('转换', '#2962ff', r.tenkan), ovLine('基准', '#e53935', r.kijun),
        ovLine('先行A', '#43a047', r.spanA), ovLine('先行B', '#ff9800', r.spanB),
      ]
    }
    case 'alligator':
      return calcAlligator(data, p.jawN, p.jawShift, p.teethN, p.teethShift, p.lipsN, p.lipsShift)
        .map(m => ovLine(m.color === '#2962ff' ? '颚' : m.color === '#e53935' ? '牙' : '唇', m.color, m.data))
    case 'linreg': {
      const [up, mid, dn] = calcLinRegChannel(data, p.len, p.mult)
      return [ovLine('LR-UP', '#ab47bc', up, true), ovLine('LR-MID', '#ab47bc', mid), ovLine('LR-DN', '#ab47bc', dn, true)]
    }
    case 'kdjch': {
      const channel = calcKDJChannel(data, p.n, p.m1, p.m2)
      return [
        ovLine(`HH(${p.n})`, 'rgba(224,168,48,0.65)', channel.upper),
        ovLine(`LL(${p.n})`, 'rgba(224,168,48,0.65)', channel.lower),
      ]
    }
    case 'wrch': {
      const channel = calcWRChannel(data, p.p)
      return [
        ovLine(`HH(${p.p})`, 'rgba(224,168,48,0.55)', channel.upper),
        ovLine(`LL(${p.p})`, 'rgba(224,168,48,0.55)', channel.lower),
      ]
    }
    default: return []
  }
}

interface Props {
  data: OHLC[]
  /** 隐藏预热 + 可见区间，仅供指标公式计算；图表仍只绘制 data。 */
  analysisData?: OHLC[]
  markers?: ChartMarker[]
  ranges?: ChartRange[]
  priceLines?: ChartPriceLine[]
  height?: number
  showMA?: boolean
  showInfoBar?: boolean
  showMarkers?: boolean
  onToggleMarkers?: () => void
  stockInfo?: StockInfo
  symbol?: string
  linkedPrice?: number | null
  onDateClick?: (date: string) => void
  onMarkerClick?: (evidenceId: string) => void
  /** 当前缩放窗口内的 K 线根数发生变化。 */
  onVisibleBarsChange?: (count: number) => void
  /** 用户把可见窗口拖到左边界时，请求更早的历史。 */
  onRequestOlder?: (oldestVisibleDate: string) => void
  canLoadOlder?: boolean
  loadingOlder?: boolean
  onChartPointClick?: (date: string, price: number) => void
  onPriceDoubleClick?: (price: number, currentPrice: number) => void
  /** 默认可见蜡烛根数, 默认 60 */
  visibleBars?: number
  /** 已激活的子图 key 列表 (含 vol, 按点击顺序) */
  activeIndicators?: string[]
  /** 用户为各副图保存的高度。 */
  paneHeights?: Record<string, number>
  /** 指标实例样式，由统一指标工作区提供。 */
  indicatorStyles?: Record<string, Record<string, unknown>>
  /** 独立浏览器验收时用于定位唯一图表实例。 */
  testId?: string
  /** 成交量柱相对前 N 个交易日均量的显示设置 */
  volumeCompare?: VolumeCompareConfig
  /** 缠论图层 (笔/线段/中枢/买卖点), 已映射到本图索引 */
  chanlunData?: ChanlunMappedLayer | null
  /** 缠论图层开关配置 */
  chanlunConfig?: ChanlunLayerConfig
  /** ZenChart 官方图层 (showOfficial 开启时叠加, 红色系) */
  chanlunOfficial?: ChanlunMappedLayer | null
}

// 序列颜色 (双主题通用); 画布轴/网格/文字等主题相关色走 CT() 动态取
const THEME = {
  bull: '#C74040',
  bear: '#2D9B65',
  bullAlpha: 'rgba(240,68,56,0.7)',
  bearAlpha: 'rgba(18,183,106,0.7)',
  ma5: '#A1A1AA',
  ma10: '#3B82F6',
  ma20: '#F97316',
  ma60: '#8B5CF6',
  bg: 'transparent',
}

/** 当前主题的图表调色板 (buildOption/信息栏在渲染时调用; 主题切换由组件 effect 触发重建)。 */
const CT = () => chartTheme(getTheme())

/** 可见蜡烛超过此数量时，涨停/炸板标签切换为小圆点。 */
const COMPACT_THRESHOLD = 60

/** 子图上方信息栏高度 (px) */
const INFO_BAR_H = 16
/** 子图之间的间距 (px) */
const SUB_GAP_PX = 4
const HISTORY_NAVIGATOR_SPACE = 30

function buildSubInfoGraphics(
  data: OHLC[],
  infoIdx: number,
  activeIndicators: string[],
  subStartTop: number,
  volumeCompare: VolumeCompareConfig,
  paneHeights: Record<string, number> = {},
): any[] {
  const d = infoIdx >= 0 && infoIdx < data.length ? data[infoIdx] : null
  const graphics: any[] = []
  let curTop = subStartTop

  activeIndicators.forEach((key) => {
    const def = SUB_CHARTS.find(s => s.key === key)
    if (!def) return

    const items = def.buildInfo(d, data, infoIdx)
    if (def.key === 'vol' && d) {
      const calcVolMa = (n: number) => {
        if (infoIdx < n - 1) return null
        let sum = 0
        for (let j = infoIdx - n + 1; j <= infoIdx; j++) sum += data[j].volume ?? 0
        return sum / n
      }
      const vol5 = calcVolMa(5)
      const vol10 = calcVolMa(10)
      items.push({ label: 'VOL5', color: '#FACC15', value: fmtVol(vol5) })
      items.push({ label: 'VOL10', color: '#8B5CF6', value: fmtVol(vol10) })
      if (volumeCompare.enabled) {
        const ratio = volumeRatioAt(data, infoIdx, volumeCompare.days)
        items.push({
          label: `量比${volumeCompare.days}`,
          color: ratio != null && ratio >= 1 ? '#C74040' : '#2D9B65',
          value: fmtVolumeRatio(ratio),
        })
      }
    }

    // 每个元素加固定 id，确保 ECharts 增量更新时能正确匹配
    graphics.push({
      id: `sub-sep-${key}`,
      type: 'line',
      shape: { x1: 0, y1: curTop, x2: 2000, y2: curTop },
      style: { stroke: 'rgba(255,255,255,0.08)', lineWidth: 1 },
      silent: true, z: 0,
    })
    graphics.push({
      id: `sub-label-${key}`,
      type: 'text',
      style: {
        text: def.label,
        x: 4, y: curTop + 4,
        fill: '#8E8E96',
        fontSize: 10, fontFamily: 'JetBrains Mono, monospace',
        fontWeight: 'bold',
      },
      silent: true, z: 10,
    })

    const richTextParts: string[] = []
    const rich: Record<string, any> = {}
    items.forEach((item, idx) => {
      const styleKey = `s${idx}`
      richTextParts.push(`{${styleKey}|${item.label}:${item.value}}`)
      rich[styleKey] = {
        fill: item.color,
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace',
      }
    })
    graphics.push({
      id: `sub-val-${key}`,
      type: 'text',
      right: 24,
      style: {
        text: richTextParts.join(`{gap|  }`),
        y: curTop + 3,
        rich: {
          gap: { fill: 'transparent', fontSize: 10 },
          ...rich,
        },
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace',
        textAlign: 'right',
        textVerticalAlign: 'top',
      },
      silent: true, z: 10,
    })

    curTop += INFO_BAR_H + (paneHeights[key] ?? def.height) + SUB_GAP_PX
  })

  return graphics
}

function visibleAnalysisOffset(data: OHLC[], analysisData: OHLC[]): number {
  if (analysisData.length === 0 || data.length === 0) return 0
  const exact = analysisData.findIndex(item => item.date === data[0].date)
  return exact >= 0 ? exact : Math.max(0, analysisData.length - data.length)
}

function buildOption(
  data: OHLC[],
  analysisData: OHLC[],
  dates: string[],
  dateIndexMap: Map<string, number>,
  markers: ChartMarker[] | undefined,
  ranges: ChartRange[] | undefined,
  priceLines: ChartPriceLine[] | undefined,
  showMA: boolean,
  compact: boolean,
  activeIndicators: string[],
  containerHeight: number,
  infoIdx: number,
  linkedPrice: number | null | undefined,
  volumeCompare: VolumeCompareConfig,
  chanlunData?: ChanlunMappedLayer | null,
  chanlunCfg?: ChanlunLayerConfig,
  chanlunOff?: ChanlunMappedLayer | null,
  paneHeights: Record<string, number> = {},
  indicatorStyles: Record<string, Record<string, unknown>> = {},
): EChartsOption {
  const candleData = data.map(d => [d.open, d.close, d.low, d.high])
  const calculationData = analysisData.length > 0 ? analysisData : data
  const offset = visibleAnalysisOffset(data, calculationData)
  const visibleSlice = <T,>(values: T[]): T[] => values.slice(offset, offset + data.length)
  const trimSeries = (item: any) => Array.isArray(item?.data)
    ? { ...item, data: visibleSlice(item.data) }
    : item
  const styleSeries = (key: string, item: any) => {
    const color = indicatorStyles[key]?.color
    if (typeof color !== 'string' || !color) return item
    return {
      ...item,
      lineStyle: { ...(item.lineStyle ?? {}), color },
      itemStyle: { ...(item.itemStyle ?? {}), color },
    }
  }

  const hasMA = showMA && data.some(d => d.ma5 != null || d.ma10 != null || d.ma20 != null || d.ma60 != null)

  const markPointData: any[] = []
  if (markers && markers.length > 0) {
    for (const m of markers) {
      const idx = dateIndexMap.get(m.date)
      if (idx == null) continue
      const d = data[idx]
      const isBuy = m.kind === 'buy'
      const isSell = m.kind === 'sell'

      if (m.above) {
        const dotColor = m.color ?? (isBuy ? '#FACC15' : CT().text)
        if (compact) {
          markPointData.push({
            name: m.date, coord: [m.date, d.high],
            symbol: 'circle', symbolSize: 4, symbolOffset: [0, -10],
            itemStyle: { color: dotColor, cursor: 'pointer' },
            evidenceId: m.evidenceId,
            label: { show: false }, z: 100, zlevel: 10,
          })
        } else {
          markPointData.push({
            name: m.date, coord: [m.date, d.high],
            symbol: 'circle', symbolSize: 12, symbolOffset: [0, -2],
            itemStyle: { color: 'transparent' },
            evidenceId: m.evidenceId,
            label: {
              show: true, formatter: m.label ?? '', position: 'top', distance: 0,
              color: dotColor, fontSize: 10, fontWeight: 'normal',
              fontFamily: 'JetBrains Mono, monospace',
            },
            z: 100, zlevel: 10,
          })
        }
      } else {
        markPointData.push({
          name: m.date,
          coord: [m.date, isBuy ? d.low : d.high],
          symbol: m.symbol ?? 'arrow', symbolSize: m.symbol === 'diamond' ? 13 : 12,
          symbolRotate: isBuy ? 0 : 180,
          symbolOffset: isBuy ? [0, '60%'] : [0, '-60%'],
          itemStyle: { color: m.color ?? (isBuy ? THEME.bull : isSell ? THEME.bear : CT().text) },
          evidenceId: m.evidenceId,
          label: {
            show: !compact && !!m.label, formatter: m.label ?? '',
            position: isBuy ? 'bottom' : 'top', distance: 8,
            color: CT().text, fontSize: 10,
            fontFamily: 'JetBrains Mono, monospace',
          },
        })
      }
    }
  }

  // ====== 布局计算 ======
  const left = 60
  const right = 20
  const topPad = 8
  const candleBottomPad = 22

  let subTotalH = 0
  const activeSubDefs: SubChartDef[] = []
  activeIndicators.forEach(key => {
    const def = SUB_CHARTS.find(s => s.key === key)
    if (!def) return
    const configured = { ...def, height: paneHeights[key] ?? def.height }
    activeSubDefs.push(configured)
    subTotalH += INFO_BAR_H + configured.height
  })
  if (activeSubDefs.length > 0) subTotalH += activeSubDefs.length * SUB_GAP_PX

  const candleAvail = Math.max(containerHeight - topPad - candleBottomPad - HISTORY_NAVIGATOR_SPACE - subTotalH, 100)

  const grids: any[] = []
  const xAxes: any[] = []
  const yAxes: any[] = []
  const series: any[] = []
  const xAxisIndices: number[] = []

  const priceLineValues = (priceLines ?? [])
    .map(line => line.value)
    .filter(value => Number.isFinite(value) && value > 0)
  const axisMin = priceLineValues.length > 0
    ? ({ min, max }: { min: number; max: number }) => {
        const nextMin = Math.min(min, ...priceLineValues)
        const nextMax = Math.max(max, ...priceLineValues)
        return nextMin - Math.max((nextMax - nextMin) * 0.03, nextMax * 0.001)
      }
    : undefined
  const axisMax = priceLineValues.length > 0
    ? ({ min, max }: { min: number; max: number }) => {
        const nextMin = Math.min(min, ...priceLineValues)
        const nextMax = Math.max(max, ...priceLineValues)
        return nextMax + Math.max((nextMax - nextMin) * 0.03, nextMax * 0.001)
      }
    : undefined

  // ===== grid 0: K线主图 =====
  grids.push({ left, right, top: topPad, height: candleAvail })
  xAxes.push({
    type: 'category', data: dates, boundaryGap: true,
    axisLine: { lineStyle: { color: CT().border } },
    axisLabel: { color: CT().text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    axisTick: { show: false },
    splitLine: { show: false },
  })
  yAxes.push({
    scale: true,
    min: axisMin,
    max: axisMax,
    // 上下各留 3% 边距: 防止最高/最低点的蜡烛贴边, 涨停/炸板标签被遮挡
    boundaryGap: [0.03, 0.03],
    splitArea: { show: false },
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: { lineStyle: { color: CT().grid } },
    axisLabel: { color: CT().text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
  })
  xAxisIndices.push(0)

  const markAreaData: any[] = (ranges ?? [])
    .filter(r => dateIndexMap.has(r.start) && dateIndexMap.has(r.end))
    .map(r => ([
      {
        name: r.label ?? '',
        xAxis: r.start,
        ...(r.high != null ? { yAxis: r.high } : {}),
        evidenceId: r.evidenceId,
        itemStyle: { color: r.color ?? 'rgba(59,130,246,0.08)' },
        label: {
          show: !!r.label,
          position: 'insideTop',
          distance: 8,
          color: CT().tooltipText,
          backgroundColor: CT().tooltipBg,
          borderColor: 'rgba(59,130,246,0.35)',
          borderWidth: 1,
          borderRadius: 4,
          padding: [2, 6],
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
        },
      },
      { xAxis: r.end, ...(r.low != null ? { yAxis: r.low } : {}) },
    ]))

  // 包含处理后的合并 K 线以极淡竖区间显示；它是结构层，不替换原始蜡烛。
  if (chanlunData && chanlunCfg?.visible && chanlunCfg.showMerged) {
    for (const item of chanlunData.merged) {
      if (item.startIdx == null || item.endIdx == null) continue
      if (item.startIdx === item.endIdx || item.startIdx >= data.length || item.endIdx < 0) continue
      markAreaData.push([
        {
          xAxis: dates[Math.max(0, item.startIdx)],
          yAxis: item.high,
          itemStyle: { color: item.direction === 'up' ? 'rgba(43,201,131,0.045)' : 'rgba(242,54,69,0.045)' },
          label: { show: false },
        },
        { xAxis: dates[Math.min(data.length - 1, item.endIdx)], yAxis: item.low },
      ])
    }
  }

  // 缠论中枢 → 半透明矩形 (叠加到 K 系列 markArea; 本地紫 / 官方红)
  if (chanlunCfg?.visible && chanlunCfg.showZhongshu !== false) {
    const zsLayers: { data: ChanlunMappedLayer['zhongshu']; fill: string; border: string }[] = []
    if (chanlunData) zsLayers.push({ data: chanlunData.zhongshu, fill: 'rgba(165,94,234,0.13)', border: 'rgba(165,94,234,0.6)' })
    if (chanlunCfg.showOfficial && chanlunOff) {
      zsLayers.push({ data: chanlunOff.zhongshu, fill: 'rgba(242,54,69,0.07)', border: 'rgba(242,54,69,0.45)' })
    }
    for (const layer of zsLayers) {
      for (const z of layer.data) {
        const si = z.startIdx, ei = z.endIdx
        if (si == null || ei == null || si >= data.length || ei < 0) continue
        markAreaData.push([
          {
            xAxis: dates[Math.max(0, si)],
            yAxis: z.high,
            itemStyle: { color: layer.fill, borderColor: layer.border, borderWidth: 1 },
          },
          { xAxis: dates[Math.min(data.length - 1, ei)], yAxis: z.low },
        ])
      }
    }
  }

  const markLineData: any[] = (priceLines ?? [])
    .filter(line => Number.isFinite(line.value))
    .map(line => {
      const lineStyle = {
        color: line.color ?? CT().text,
        type: 'dashed' as const,
        width: 1,
        opacity: 0.92,
      }
      const label = {
        show: !!line.label,
        formatter: line.label ?? '',
        position: 'insideEndTop' as const,
        color: line.color ?? CT().text,
        backgroundColor: CT().tooltipBg,
        borderRadius: 4,
        padding: [2, 6],
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace',
      }
      if (line.start && line.end && dateIndexMap.has(line.start) && dateIndexMap.has(line.end)) {
        return [
          { xAxis: line.start, yAxis: line.value },
          { xAxis: line.end, yAxis: line.endValue ?? line.value, lineStyle, label, symbol: 'none' },
        ]
      }
      return { yAxis: line.value, lineStyle, label, symbol: 'none' }
    })

  if (linkedPrice != null) {
    markLineData.push({
      yAxis: linkedPrice,
      lineStyle: { color: '#3B82F6', type: 'dashed', width: 1, opacity: 0.7 },
      label: {
        show: true,
        formatter: linkedPrice.toFixed(2),
        position: 'insideEndTop',
        color: '#3B82F6',
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace',
        backgroundColor: CT().tooltipBg,
        borderColor: '#3B82F6',
        borderWidth: 1,
        padding: [1, 4],
        borderRadius: 2,
      },
      symbol: 'none',
    })
  }

  // 缠论买卖点 → 三角标记 (叠加到 K 系列 markPoint; name=日期以复用点击回调)
  if (chanlunData && chanlunCfg?.visible && chanlunCfg.showBsp !== false) {
    for (const b of chanlunData.bsp) {
      const idx = b.idx
      if (idx == null || idx < 0 || idx >= data.length) continue
      const d = data[idx]
      const isBuy = b.direction === 'buy'
      const color = isBuy ? '#2bc983' : '#f23645'
      markPointData.push({
        name: d.date,
        coord: [d.date, isBuy ? d.low : d.high],
        symbol: 'triangle', symbolSize: 10,
        symbolRotate: isBuy ? 0 : 180,
        symbolOffset: isBuy ? [0, '70%'] : [0, '-70%'],
        itemStyle: { color },
        label: {
          show: !compact && !!b.type,
          formatter: b.type ?? '',
          position: isBuy ? 'bottom' : 'top', distance: 7,
          color, fontSize: 9,
          fontFamily: 'JetBrains Mono, monospace',
        },
        z: 100, zlevel: 10,
      })
    }
  }

  if (chanlunData && chanlunCfg?.visible && chanlunCfg.showFenxing) {
    for (const point of chanlunData.fenxing) {
      if (point.idx == null || point.idx < 0 || point.idx >= data.length) continue
      const row = data[point.idx]
      const isTop = point.type === 'top'
      markPointData.push({
        name: row.date,
        coord: [row.date, point.value],
        symbol: 'diamond', symbolSize: 7,
        symbolOffset: isTop ? [0, '-45%'] : [0, '45%'],
        itemStyle: { color: isTop ? '#fb7185' : '#34d399', borderColor: '#0b0c0f', borderWidth: 1 },
        label: { show: false },
        z: 98,
      })
    }
  }

  series.push({
    name: 'K', type: 'candlestick', data: candleData,
    animation: false,
    itemStyle: {
      color: THEME.bull, color0: THEME.bear,
      borderColor: THEME.bull, borderColor0: THEME.bear,
      cursor: 'pointer',
    },
    markPoint: markPointData.length > 0 ? { data: markPointData, animation: false } : undefined,
    markArea: markAreaData.length > 0 ? { silent: true, data: markAreaData } : undefined,
    markLine: markLineData.length > 0 ? { silent: true, symbol: 'none', data: markLineData, animation: false } : undefined,
  })

  if (hasMA) {
    const maLine = (key: keyof OHLC, color: string, name: string) => ({
      name, type: 'line',
      data: data.map(d => (d[key] != null ? Number(d[key]) : '-')),
      smooth: true, symbol: 'none', animation: false,
      silent: true,
      lineStyle: { width: 1, color }, itemStyle: { color },
    })
    series.push(maLine('ma5', THEME.ma5, 'MA5'))
    series.push(maLine('ma10', THEME.ma10, 'MA10'))
    series.push(maLine('ma20', THEME.ma20, 'MA20'))
    series.push(maLine('ma60', THEME.ma60, 'MA60'))
  }

  // BOLL 布林带 — 需在 activeIndicators 中激活
  const showBOLL = activeIndicators.includes('boll') && data.some(d => d.boll_upper != null || d.boll_lower != null)
  if (showBOLL) {
    const bollLine = (key: keyof OHLC, color: string, name: string) => ({
      name, type: 'line',
      data: data.map(d => (d[key] != null ? Number(d[key]) : '-')),
      smooth: true, symbol: 'none', animation: false,
      silent: true,
      lineStyle: { width: 1, color, type: 'dashed' as const }, itemStyle: { color },
    })
    series.push(bollLine('boll_upper', '#E879F9', 'BOLL上'))
    series.push(bollLine('boll_lower', '#E879F9', 'BOLL下'))
  }
  // BOLL 无数据字段时回退到公式计算
  else if (activeIndicators.includes('boll')) {
    const bp = getParams('boll')
    const [up, , dn] = calcBOLL(calculationData, bp.p, bp.sd)
    series.push(ovLine('BOLL上', '#E879F9', visibleSlice(up), true))
    series.push(ovLine('BOLL下', '#E879F9', visibleSlice(dn), true))
  }

  // 其余主图叠加指标 (前端公式计算)
  for (const ov of activeIndicators) {
    if (ov === 'boll' || ov === 'vol') continue
    if (!OVERLAY_KEYS.has(ov)) continue
    try {
      series.push(...buildOverlaySeries(ov, calculationData).map(trimSeries).map(item => styleSeries(ov, item)))
    } catch (error) {
      // 公式错误必须可观察，不能让某个指标在图上无声消失。
      reportIndicatorError(ov, error)
    }
  }

  // ===== 缠论笔 / 线段 (line series 折线) =====
  // 注: 不用 custom series —— 在多 grid + dataZoom 组合下 renderItem 坐标解析会静默失败;
  // 笔/线段端点本身首尾相连, 用普通折线即可, 且与缩放/联动完全兼容。
  if (chanlunCfg?.visible) {
    const toPts = (list: { startIdx: number | null; endIdx: number | null; startPrice: number; endPrice: number; isSure?: boolean }[], sureOnly: boolean | null): (any[] | '-')[] => {
      const pts: any[] = []
      let prevEnd: string | null = null
      for (const s of list) {
        if (sureOnly !== null && !!s.isSure !== sureOnly) continue
        if (s.startIdx == null || s.endIdx == null || s.startIdx >= dates.length || s.endIdx >= dates.length) continue
        const p: [string, number] = [dates[s.startIdx], s.startPrice]
        const q: [string, number] = [dates[s.endIdx], s.endPrice]
        // 折线断链: 与上一段不连续时插入空档
        if (pts.length > 0 && prevEnd !== p[0]) pts.push('-')
        pts.push(p, q)
        prevEnd = q[0]
      }
      return pts
    }

    // ----- 本地图层 (chanlunData 存在才画; 仅官方模式下为 null) -----
    if (chanlunData) {
      if (chanlunCfg.showSegments !== false && chanlunData.segments.length > 0) {
        series.push({
          name: '缠论-线段', type: 'line',
          data: toPts(chanlunData.segments as any, null),
          silent: true, z: 9, animation: false,
          symbol: 'none',
          lineStyle: { color: '#ff9f43', width: 2.5, opacity: 0.85 },
          itemStyle: { color: '#ff9f43' },
        })
      }
      if (chanlunCfg.showBi !== false && chanlunData.bi.length > 0) {
        series.push({
          name: '缠论-笔', type: 'line',
          data: toPts(chanlunData.bi as any, true),
          silent: true, z: 10, animation: false,
          symbol: 'circle', symbolSize: 3.5, showSymbol: true,
          lineStyle: { color: '#19d3ff', width: 1.6 },
          itemStyle: { color: '#19d3ff' },
        })
        // 未确认笔: 虚线半透明
        const unsure = toPts(chanlunData.bi.filter(b => !b.isSure) as any, null)
        if (unsure.length > 0) {
          series.push({
            name: '缠论-笔(未确认)', type: 'line',
            data: unsure,
            silent: true, z: 10, animation: false,
            symbol: 'circle', symbolSize: 3,
            lineStyle: { color: '#19d3ff', width: 1.2, type: 'dashed', opacity: 0.45 },
            itemStyle: { color: '#19d3ff', opacity: 0.45 },
          })
        }
      }
    }

    // ----- 官方图层 (独立开关, 与本地图层互不依赖) -----
    if (chanlunCfg.showOfficial && chanlunOff) {
      if (chanlunCfg.showSegments !== false && chanlunOff.segments.length > 0) {
        series.push({
          name: '官方-线段', type: 'line',
          data: toPts(chanlunOff.segments as any, null),
          silent: true, z: 8, animation: false,
          symbol: 'none',
          lineStyle: { color: '#f23645', width: 2, opacity: 0.55 },
          itemStyle: { color: '#f23645' },
        })
      }
      if (chanlunCfg.showBi !== false && chanlunOff.bi.length > 0) {
        series.push({
          name: '官方-笔', type: 'line',
          data: toPts(chanlunOff.bi as any, null),
          silent: true, z: 9, animation: false,
          symbol: 'none',
          lineStyle: { color: '#f23645', width: 1.2, type: 'dashed', opacity: 0.6 },
          itemStyle: { color: '#f23645' },
        })
      }
    }
  }

  // ===== 子图区域 =====
  let curTop = topPad + candleAvail + candleBottomPad

  activeSubDefs.forEach((def, i) => {
    const gridIdx = i + 1
    const xAxisIdx = i + 1
    const yAxisIdx = i + 1

    const chartTop = curTop + INFO_BAR_H
    grids.push({
      left, right,
      top: chartTop,
      height: def.height,
      show: true,
      borderColor: CT().grid,
      borderWidth: 1,
    })

    xAxes.push({
      type: 'category', gridIndex: gridIdx, data: dates, boundaryGap: true,
      axisLine: { show: false }, axisLabel: { show: false },
      axisTick: { show: false }, splitLine: { show: false },
      axisPointer: { label: { show: false } },
    })

    const isFixedRange = !!def.yAxisConfig
    yAxes.push({
      scale: !isFixedRange,
      ...(def.yAxisConfig ?? {}),
      gridIndex: gridIdx,
      splitNumber: 2,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: CT().grid } },
      axisLabel: {
        show: true, color: CT().text, fontSize: 9,
        fontFamily: 'JetBrains Mono, monospace',
      },
    })

    xAxisIndices.push(xAxisIdx)

    let subSeries: any[] = []
    try {
      subSeries = def.buildSeries(calculationData, { compact, volumeCompare, params: {} }).map(trimSeries).map(item => styleSeries(def.key, item))
    } catch (error) {
      reportIndicatorError(def.key, error)
    }
    subSeries.forEach((s: any) => {
      series.push({ ...s, xAxisIndex: xAxisIdx, yAxisIndex: yAxisIdx })
    })

    curTop += INFO_BAR_H + def.height + SUB_GAP_PX
  })

  // 子图信息栏 graphic
  const subStartTop = topPad + candleAvail + candleBottomPad
  const infoGraphics = buildSubInfoGraphics(calculationData, offset + infoIdx, activeIndicators, subStartTop, volumeCompare, paneHeights)

  return {
    animation: false,
    backgroundColor: THEME.bg,
    tooltip: {
      trigger: 'axis',
      // The chart uses its own information bar. Keeping tooltip rendering on
      // canvas avoids ECharts' detached HTML tooltip race during history prepend.
      renderMode: 'richText',
      axisPointer: { type: 'cross', crossStyle: { color: CT().crosshair } },
      backgroundColor: 'transparent',
      borderWidth: 0,
      textStyle: { fontSize: 0 },
      formatter: () => '',
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: {
        backgroundColor: CT().crosshairLabelBg,
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 10,
      },
    },
    graphic: infoGraphics.length > 0 ? infoGraphics : undefined,
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: xAxisIndices,
        start: 0,
        end: 100,
        moveOnMouseMove: true,
        zoomOnMouseWheel: true,
      },
      {
        type: 'slider',
        xAxisIndex: xAxisIndices,
        left,
        right,
        bottom: 3,
        height: 17,
        start: 0,
        end: 100,
        showDataShadow: false,
        showDetail: true,
        brushSelect: false,
        borderColor: CT().border,
        backgroundColor: 'rgba(15,23,42,0.35)',
        fillerColor: 'rgba(56,189,248,0.14)',
        handleStyle: {
          color: CT().text,
          borderColor: '#38bdf8',
        },
        moveHandleStyle: {
          color: '#38bdf8',
          opacity: 0.55,
        },
        textStyle: {
          color: CT().text,
          fontSize: 9,
          fontFamily: 'JetBrains Mono, monospace',
        },
      },
    ],
    series,
  }
}


export function EChartsCandlestick({
  data,
  analysisData = data,
  markers,
  ranges,
  priceLines,
  height = 480,
  showMA = true,
  showInfoBar = true,
  showMarkers: showMarkersProp = true,
  onToggleMarkers: _onToggleMarkers,
  stockInfo,
  symbol: _symbol,
  linkedPrice,
  onDateClick,
  onMarkerClick,
  onVisibleBarsChange,
  onRequestOlder,
  canLoadOlder = false,
  loadingOlder = false,
  onChartPointClick,
  onPriceDoubleClick,
  visibleBars = 60,
  activeIndicators = [],
  paneHeights = {},
  indicatorStyles = {},
  testId,
  volumeCompare = { enabled: true, days: 1 },
  chanlunData = null,
  chanlunConfig,
  chanlunOfficial = null,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ECharts | null>(null)
  const dataRef = useRef(data)
  dataRef.current = data
  const analysisDataRef = useRef(analysisData)
  analysisDataRef.current = analysisData
  const onDateClickRef = useRef(onDateClick)
  onDateClickRef.current = onDateClick
  const onMarkerClickRef = useRef(onMarkerClick)
  onMarkerClickRef.current = onMarkerClick
  const onVisibleBarsChangeRef = useRef(onVisibleBarsChange)
  onVisibleBarsChangeRef.current = onVisibleBarsChange
  const onRequestOlderRef = useRef(onRequestOlder)
  onRequestOlderRef.current = onRequestOlder
  const canLoadOlderRef = useRef(canLoadOlder)
  canLoadOlderRef.current = canLoadOlder
  const loadingOlderRef = useRef(loadingOlder)
  loadingOlderRef.current = loadingOlder
  const onChartPointClickRef = useRef(onChartPointClick)
  onChartPointClickRef.current = onChartPointClick
  const onPriceDoubleClickRef = useRef(onPriceDoubleClick)
  onPriceDoubleClickRef.current = onPriceDoubleClick
  // 主题: buildOption/信息栏内部通过 CT() 动态取调色板, 这里只负责切换时触发重建
  const theme = useTheme()

  // --- 全部用 ref，避免高频交互触发 React 重渲染 ---
  const infoIdxRef = useRef<number>(data.length - 1)
  const compactRef = useRef(false)
  const userZoomRef = useRef<{ start: number; end: number; startDate?: string; endDate?: string } | null>(null)
  const dataBoundsRef = useRef<{ first?: string; last?: string }>({})
  const suppressOlderRequestRef = useRef(false)
  const requestedOldestRef = useRef<string>()

  // 需要在闭包中访问最新值的变量 — 先声明占位，后面赋值
  const activeIndicatorsRef = useRef(activeIndicators)
  activeIndicatorsRef.current = activeIndicators
  const volumeCompareRef = useRef(volumeCompare)
  volumeCompareRef.current = volumeCompare
  const paneHeightsRef = useRef(paneHeights)
  paneHeightsRef.current = paneHeights
  const chartHeightRef = useRef(300)
  const subTotalHRef = useRef(0)
  const getInfoBarHTMLRef = useRef<() => string>(() => '')

  // 强制刷新信息栏 DOM 的回调
  const infoBarRef = useRef<HTMLDivElement>(null)
  const triggerInfoBarUpdate = useRef(() => {
    const idx = infoIdxRef.current
    const curData = dataRef.current
    const d = idx >= 0 && idx < curData.length ? curData[idx] : null
    if (!d) return
    const calculationData = analysisDataRef.current.length > 0 ? analysisDataRef.current : curData
    const calculationIndex = visibleAnalysisOffset(curData, calculationData) + idx
    const chart = chartRef.current
    if (!chart) return
    const subStartTop = chartHeightRef.current - subTotalHRef.current
    const infoGraphics = buildSubInfoGraphics(
      calculationData,
      calculationIndex,
      activeIndicatorsRef.current,
      subStartTop,
      volumeCompareRef.current,
      paneHeightsRef.current,
    )
    if (infoGraphics.length > 0) {
      chart.setOption({ graphic: infoGraphics }, { lazyUpdate: true })
    }
  }).current

  // 计算子图总高度
  const activeSubDefs = activeIndicators
    .map(key => {
      const def = SUB_CHARTS.find(s => s.key === key)
      return def ? { ...def, height: paneHeights[key] ?? def.height } : undefined
    })
    .filter((d): d is SubChartDef => !!d)

  let subTotalH = 0
  activeSubDefs.forEach(def => { subTotalH += INFO_BAR_H + def.height })
  if (activeSubDefs.length > 0) subTotalH += activeSubDefs.length * SUB_GAP_PX

  const mainInfoBarH = showInfoBar ? 40 : 0
  const minCandleH = 120

  const chartHeight = Math.max(height - mainInfoBarH, 8 + minCandleH + 14 + HISTORY_NAVIGATOR_SPACE + subTotalH)
  chartHeightRef.current = chartHeight
  subTotalHRef.current = subTotalH

  // 预计算 date→index Map (O(1) 查找)
  const dates = useMemo(() => data.map(d => d.date), [data])
  const dateIndexMap = useMemo(() => {
    const m = new Map<string, number>()
    dates.forEach((d, i) => m.set(d, i))
    return m
  }, [dates])

  // 计算 dataZoom 初始范围
  const initialZoom = useMemo(() => ({
    start: Math.max(0, 100 - (visibleBars / Math.max(data.length, 1)) * 100),
    end: 100,
  }), [visibleBars, data.length])

  // ===== 信息栏 HTML 内容 (基于 infoIdxRef.current) =====
  const getInfoBarHTML = useCallback(() => {
    let idx = infoIdxRef.current
    let d = idx >= 0 && idx < data.length ? data[idx] : null
    // fallback: 如果当前 idx 无数据，取最后一根 K 线
    if (!d && data.length > 0) {
      idx = data.length - 1
      d = data[idx]
    }
    if (!d) return ''
    const prev = idx > 0 ? data[idx - 1] : null
    const chg = prev ? d.close - prev.close : 0
    const isUp = chg >= 0
    const clr = isUp ? THEME.bull : THEME.bear
    const floatShares = stockInfo?.float_shares
    const turnoverRate = floatShares && d.volume ? (d.volume * 100 / floatShares * 100) : null

    let html = `<div style="display:flex;align-items:center;gap:6px;padding:0 8px;font:11px 'JetBrains Mono',monospace;select:none;height:20px;flex-wrap:wrap">`
    html += `<span style="color:${CT().text}">${d.date}</span>`
    html += `<span style="color:${CT().text}">开</span>`
    html += `<span style="color:${d.open >= d.close ? THEME.bear : THEME.bull}">${d.open.toFixed(2)}</span>`
    html += `<span style="color:${CT().text}">高</span>`
    html += `<span style="color:${THEME.bull}">${d.high.toFixed(2)}</span>`
    html += `<span style="color:${CT().text}">低</span>`
    html += `<span style="color:${THEME.bear}">${d.low.toFixed(2)}</span>`
    html += `<span style="color:${CT().text}">收</span>`
    html += `<span style="color:${clr};font-weight:600">${d.close.toFixed(2)}</span>`
    // 涨跌幅 (收盘后, 换手前; 和收间隔一些距离)
    if (prev) {
      const chgPct = (chg / prev.close * 100)
      html += `<span style="color:${clr};margin-left:8px">${isUp ? '+' : ''}${chgPct.toFixed(2)}%</span>`
    }
    if (turnoverRate != null) {
      html += `<span style="color:${CT().text}">换手</span>`
      html += `<span style="color:${CT().text}">${turnoverRate.toFixed(2)}%</span>`
    }
    html += `</div>`

    // 第二行: MA + BOLL
    if (showMA) {
      html += `<div style="display:flex;align-items:center;gap:10px;padding:0 8px;font:11px 'JetBrains Mono',monospace;select:none;height:20px;flex-wrap:wrap">`
      if (d.ma5 != null) html += `<span style="color:${THEME.ma5}">MA5:${Number(d.ma5).toFixed(2)}</span>`
      if (d.ma10 != null) html += `<span style="color:${THEME.ma10}">MA10:${Number(d.ma10).toFixed(2)}</span>`
      if (d.ma20 != null) html += `<span style="color:${THEME.ma20}">MA20:${Number(d.ma20).toFixed(2)}</span>`
      if (d.ma60 != null) html += `<span style="color:${THEME.ma60}">MA60:${Number(d.ma60).toFixed(2)}</span>`
      if (d.boll_upper != null && activeIndicators.includes('boll')) {
        html += `<span style="color:#E879F9">BOLL:${Number(d.boll_upper).toFixed(2)}/${Number(d.ma20).toFixed(2)}/${Number(d.boll_lower).toFixed(2)}</span>`
      }
      html += `</div>`
    }

    return html
  }, [data, stockInfo, showMA, activeIndicators])
  getInfoBarHTMLRef.current = getInfoBarHTML

  // 普通上下文切换重置缩放；向序列左侧前插历史时保留日期锚点。
  const dataFirstDate = data[0]?.date
  const dataLastDate = data.at(-1)?.date
  useEffect(() => {
    const previous = dataBoundsRef.current
    const first = dataFirstDate
    const last = dataLastDate
    const prepended = !!previous.first && !!previous.last && previous.last === last && !!first && first < previous.first
    infoIdxRef.current = data.length - 1
    compactRef.current = false
    if (!prepended) userZoomRef.current = null
    if (first !== previous.first) requestedOldestRef.current = undefined
    dataBoundsRef.current = { first, last }
  }, [data.length, dataFirstDate, dataLastDate])

  // ===== 初始化 chart (只在 chartHeight 变化时重建) =====
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const chart = echarts.init(el, undefined, { renderer: 'canvas' })
    chartRef.current = chart

    // 鼠标移动 → 只更新 ref + DOM，不触发 React re-render
    // 设计原则: 找不到有效数据时保持上次显示，永远不清空信息栏
    chart.on('updateAxisPointer', (event: any) => {
      const axesInfo = event.axesInfo
      if (!axesInfo) return // 鼠标移出图表区域，保持当前显示
      for (const info of Object.values(axesInfo)) {
        const val = (info as any)?.value
        if (val == null) continue
        const d = dataRef.current
        const idx = typeof val === 'number' ? val : d.findIndex(x => x.date === val)
        if (idx >= 0 && idx < d.length) {
          if (infoIdxRef.current === idx) return
          infoIdxRef.current = idx

          // 直接更新信息栏 DOM (通过 ref 读取最新的生成函数)
          const infoEl = infoBarRef.current
          if (infoEl) {
            const html = getInfoBarHTMLRef.current()
            if (html) infoEl.innerHTML = html  // 只在有内容时更新
          }

          // 更新子图 graphic
          triggerInfoBarUpdate()
          return
        }
      }
      // 没有找到有效数据 — 不做任何操作，保持上次显示
    })

    chart.on('click', (params: any) => {
      if (params.componentType === 'markPoint' && params.name) {
        const evidenceId = params.data?.evidenceId
        if (evidenceId) onMarkerClickRef.current?.(evidenceId)
        onDateClickRef.current?.(params.name)
        return
      }
      if (params.seriesName !== 'K' || params.dataIndex == null) return
      const d = dataRef.current
      const idx = params.dataIndex
      if (idx >= 0 && idx < d.length) {
        onDateClickRef.current?.(d[idx].date)
        onChartPointClickRef.current?.(d[idx].date, d[idx].close)
      }
    })

    const handlePriceDoubleClick = (event: { offsetX: number; offsetY: number }) => {
      const pixel: [number, number] = [event.offsetX, event.offsetY]
      if (!chart.containPixel({ gridIndex: 0 }, pixel)) return
      const coordinate = chart.convertFromPixel({ xAxisIndex: 0, yAxisIndex: 0 }, pixel)
      const price = Array.isArray(coordinate) ? Number(coordinate[1]) : NaN
      const currentPrice = dataRef.current[dataRef.current.length - 1]?.close
      if (Number.isFinite(price) && price > 0 && Number.isFinite(currentPrice) && currentPrice > 0) {
        onPriceDoubleClickRef.current?.(price, currentPrice)
      }
    }
    chart.getZr().on('dblclick', handlePriceDoubleClick)

    // dataZoom → 只更新 ref，不触发 React re-render
    // compact 变化时需要增量更新 markPoint
    chart.on('dataZoom', () => {
      const opt = chart.getOption() as any
      const zoom = opt?.dataZoom?.[0]
      if (!zoom) return
      const d = dataRef.current
      const total = d.length
      const startIndex = Math.max(0, Math.min(total - 1, Math.floor(total * zoom.start / 100)))
      const endIndex = Math.max(startIndex, Math.min(total - 1, Math.ceil(total * zoom.end / 100) - 1))
      userZoomRef.current = {
        start: zoom.start,
        end: zoom.end,
        startDate: d[startIndex]?.date,
        endDate: d[endIndex]?.date,
      }
      const visibleCount = Math.round(total * (zoom.end - zoom.start) / 100)
      onVisibleBarsChangeRef.current?.(visibleCount)
      if (
        !suppressOlderRequestRef.current
        && zoom.start <= 15
        && canLoadOlderRef.current
        && !loadingOlderRef.current
        && d[0]?.date
        && requestedOldestRef.current !== d[0].date
      ) {
        requestedOldestRef.current = d[0].date
        onRequestOlderRef.current?.(d[0].date)
      }
      const newCompact = visibleCount > COMPACT_THRESHOLD
      if (newCompact !== compactRef.current) {
        compactRef.current = newCompact
        updateCompactPresentation()
      }
    })

    const ro = new ResizeObserver(() => { chart.resize() })
    ro.observe(el)

    return () => {
      chart.off('updateAxisPointer')
      chart.off('click')
      chart.off('dataZoom')
      chart.getZr().off('dblclick', handlePriceDoubleClick)
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [chartHeight]) // eslint-disable-line react-hooks/exhaustive-deps

  // 缩放跨过紧凑阈值时，仅增量更新标签，不重建整张图。
  function updateCompactPresentation() {
    const chart = chartRef.current
    if (!chart) return
    const mkrs = showMarkersProp ? markers : undefined
    const compact = compactRef.current
    const seriesUpdates: any[] = []
    const markPointData: any[] = []
    for (const m of mkrs ?? []) {
      const idx = dateIndexMap.get(m.date)
      if (idx == null) continue
      const d = data[idx]
      const isBuy = m.kind === 'buy'
      const isSell = m.kind === 'sell'
      if (m.above) {
        const dotColor = m.color ?? (isBuy ? '#FACC15' : CT().text)
        if (compact) {
          markPointData.push({
            name: m.date, coord: [m.date, d.high],
            symbol: 'circle', symbolSize: 4, symbolOffset: [0, -10],
            itemStyle: { color: dotColor, cursor: 'pointer' },
            label: { show: false }, z: 100, zlevel: 10,
          })
        } else {
          markPointData.push({
            name: m.date, coord: [m.date, d.high],
            symbol: 'circle', symbolSize: 12, symbolOffset: [0, -2],
            itemStyle: { color: 'transparent' },
            label: {
              show: true, formatter: m.label ?? '', position: 'top', distance: 0,
              color: dotColor, fontSize: 10, fontWeight: 'normal',
              fontFamily: 'JetBrains Mono, monospace',
            },
            z: 100, zlevel: 10,
          })
        }
      } else {
        markPointData.push({
          name: m.date,
          coord: [m.date, isBuy ? d.low : d.high],
          symbol: m.symbol ?? 'arrow', symbolSize: m.symbol === 'diamond' ? 13 : 12,
          symbolRotate: isBuy ? 0 : 180,
          symbolOffset: isBuy ? [0, '60%'] : [0, '-60%'],
          itemStyle: { color: m.color ?? (isBuy ? THEME.bull : isSell ? THEME.bear : CT().text) },
          evidenceId: m.evidenceId,
          label: {
            show: !compact && !!m.label, formatter: m.label ?? '',
            position: isBuy ? 'bottom' : 'top', distance: 8,
            color: CT().text, fontSize: 10,
            fontFamily: 'JetBrains Mono, monospace',
          },
        })
      }
    }
    if (mkrs?.length) {
      seriesUpdates.push({
        name: 'K',
        markPoint: markPointData.length > 0 ? { data: markPointData, animation: false } : undefined,
      })
    }
    if (activeIndicatorsRef.current.includes('vol')) {
      seriesUpdates.push({
        name: '成交量',
        label: { show: volumeCompareRef.current.enabled && !compact },
      })
    }
    if (seriesUpdates.length > 0) chart.setOption({ series: seriesUpdates })
  }

  // ===== 核心: 仅在数据/配置变更时全量 setOption =====
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    const option = buildOption(
      data, analysisData, dates, dateIndexMap,
      showMarkersProp ? markers : undefined,
      ranges,
      priceLines,
      showMA, compactRef.current,
      activeIndicators, chartHeight,
      infoIdxRef.current,
      linkedPrice,
      volumeCompare,
      chanlunData,
      chanlunConfig,
      chanlunOfficial,
      paneHeights,
      indicatorStyles,
    )

    chart.setOption(option, true)

    // 恢复用户缩放位置
    const zoom = userZoomRef.current
    if (zoom) {
      suppressOlderRequestRef.current = true
      const datesStillPresent = !!zoom.startDate && !!zoom.endDate && dateIndexMap.has(zoom.startDate) && dateIndexMap.has(zoom.endDate)
      chart.dispatchAction(datesStillPresent
        ? { type: 'dataZoom', startValue: zoom.startDate, endValue: zoom.endDate }
        : { type: 'dataZoom', start: zoom.start, end: zoom.end })
    } else {
      suppressOlderRequestRef.current = true
      chart.dispatchAction({ type: 'dataZoom', start: initialZoom.start, end: initialZoom.end })
    }
    queueMicrotask(() => { suppressOlderRequestRef.current = false })

    // 初始信息栏
    const infoEl = infoBarRef.current
    if (infoEl) {
      infoEl.innerHTML = getInfoBarHTML()
    }
  }, [data, analysisData, markers, ranges, priceLines, linkedPrice, showMA, showMarkersProp, activeIndicators, volumeCompare, chartHeight, dates, dateIndexMap, initialZoom, getInfoBarHTML, theme, chanlunData, chanlunConfig, chanlunOfficial, paneHeights, indicatorStyles])

  // 渲染信息栏容器 (内容由 JS 直接写入)
  const initialHTML = useMemo(() => {
    const idx = data.length - 1
    const d = idx >= 0 && idx < data.length ? data[idx] : null
    if (!d) return ''
    const floatShares = stockInfo?.float_shares
    const turnoverRate = floatShares && d.volume ? (d.volume * 100 / floatShares * 100) : null
    let html = `<div style="display:flex;align-items:center;gap:6px;padding:0 8px;font:11px 'JetBrains Mono',monospace;height:20px;flex-wrap:wrap">`
    html += `<span style="color:${CT().text}">${d.date}</span>`
    html += `<span style="color:${CT().text}">开</span>`
    html += `<span style="color:${d.open >= d.close ? THEME.bear : THEME.bull}">${d.open.toFixed(2)}</span>`
    html += `<span style="color:${CT().text}">高</span>`
    html += `<span style="color:${THEME.bull}">${d.high.toFixed(2)}</span>`
    html += `<span style="color:${CT().text}">低</span>`
    html += `<span style="color:${THEME.bear}">${d.low.toFixed(2)}</span>`
    html += `<span style="color:${CT().text}">收</span>`
    const prevClose0 = data[idx-1]?.close ?? d.close
    const clr0 = d.close >= prevClose0 ? THEME.bull : THEME.bear
    html += `<span style="color:${clr0};font-weight:600">${d.close.toFixed(2)}</span>`
    // 涨跌幅 (收盘后, 换手前; 和收间隔一些距离)
    if (idx > 0) {
      const chgPct0 = ((d.close - prevClose0) / prevClose0 * 100)
      html += `<span style="color:${clr0};margin-left:8px">${chgPct0 >= 0 ? '+' : ''}${chgPct0.toFixed(2)}%</span>`
    }
    if (turnoverRate != null) {
      html += `<span style="color:${CT().text}">换手</span>`
      html += `<span style="color:${CT().text}">${turnoverRate.toFixed(2)}%</span>`
    }
    html += `</div>`
    if (showMA) {
      html += `<div style="display:flex;align-items:center;gap:10px;padding:0 8px;font:11px 'JetBrains Mono',monospace;height:20px;flex-wrap:wrap">`
      if (d.ma5 != null) html += `<span style="color:${THEME.ma5}">MA5:${Number(d.ma5).toFixed(2)}</span>`
      if (d.ma10 != null) html += `<span style="color:${THEME.ma10}">MA10:${Number(d.ma10).toFixed(2)}</span>`
      if (d.ma20 != null) html += `<span style="color:${THEME.ma20}">MA20:${Number(d.ma20).toFixed(2)}</span>`
      if (d.ma60 != null) html += `<span style="color:${THEME.ma60}">MA60:${Number(d.ma60).toFixed(2)}</span>`
      if (d.boll_upper != null && activeIndicators.includes('boll')) {
        html += `<span style="color:#E879F9">BOLL:${Number(d.boll_upper).toFixed(2)}/${Number(d.ma20).toFixed(2)}/${Number(d.boll_lower).toFixed(2)}</span>`
      }
      html += `</div>`
    }
    return html
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="w-full">
      {/* 主图信息栏 — 内容由 JS 直接操作 innerHTML */}
      {showInfoBar && (
        <div ref={infoBarRef} style={{ backgroundColor: CT().infoBarBg }}
          dangerouslySetInnerHTML={{ __html: initialHTML }} />
      )}

      {/* ECharts canvas */}
      <div
        ref={containerRef}
        data-testid={testId}
        data-row-count={data.length}
        data-visible-bars={visibleBars}
        data-initial-zoom-start={initialZoom.start.toFixed(4)}
        data-can-load-older={canLoadOlder ? 'true' : 'false'}
        data-loading-older={loadingOlder ? 'true' : 'false'}
        className="w-full"
        style={{ height: chartHeight }}
      />
    </div>
  )
}
