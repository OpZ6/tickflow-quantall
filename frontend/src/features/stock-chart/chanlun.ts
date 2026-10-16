import type { OHLC } from '@/components/EChartsCandlestick'
import type { ChanlunAnalysis } from '@/custom/api'

/**
 * 缠论 (Chan theory) 图层的数据类型与映射工具。
 *
 * 原先内联在 components/EChartsCandlestick.tsx 中, 随上游该组件重构易产生
 * 大面积冲突; 抽为本模块后核心组件零改动, 仅本地自研的图表工作台引用。
 */
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

export const DEFAULT_CHANLUN_CONFIG: ChanlunLayerConfig = {
  visible: false, showBi: true, showSegments: true, showZhongshu: true, showBsp: true,
  showOfficial: false,
}

export function buildTimeIndex(rows: { date: string }[]): Map<number, number> {
  const m = new Map<number, number>()
  rows.forEach((r, i) => m.set(candleTimeOf(r.date), i))
  return m
}

export function candleTimeOf(date: string): number {
  return Math.floor(new Date(date.includes('T') ? date : `${date}T00:00:00`).getTime() / 1000)
}

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

export function toChanlunCandles(rows: OHLC[]): { time: number; open: number; high: number; low: number; close: number; volume?: number }[] {
  return rows.map(r => ({
    time: candleTimeOf(r.date),
    open: r.open, high: r.high, low: r.low, close: r.close,
    volume: r.volume,
  }))
}
