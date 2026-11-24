/** 缠论图层的纯数据映射（本地增强，独立于上游图表组件）。
 *
 * 这些函数只做"后端缠论结果 → 图表索引"的转换，不含 React / ECharts，
 * 放在 custom/ 下便于复用与单测，也让上游 EChartsCandlestick.tsx 少承载
 * 一百多行本地代码（上游同步时少一片冲突面）。
 */

import type { ChanlunAnalysis } from '@/custom/api'

import type { OHLC } from '@/lib/chart-types'

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

