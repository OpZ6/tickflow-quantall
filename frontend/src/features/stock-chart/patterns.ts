import type { ChanlunMappedLayer } from '@/components/EChartsCandlestick'

export type PatternType = 'HST' | 'HSB' | 'DT' | 'DB' | 'Tri'

interface Swing {
  idx: number
  price: number
  type: 'high' | 'low'
}

export interface DetectedPattern {
  type: PatternType
  label: string
  points: Swing[]
  neckline?: [Swing, Swing]
}

/**
 * 原型 V61 形态算法的自包含移植。输入仅使用当前屏幕 candles 计算出的本地笔，
 * 因而切换周期、复权或回放位置都会重新识别，不存在目录外运行时依赖。
 */
export function detectPatterns(layer: ChanlunMappedLayer | null | undefined): DetectedPattern[] {
  if (!layer || layer.bi.length < 5) return []
  const swings: Swing[] = layer.bi.flatMap(stroke => {
    if (stroke.endIdx == null) return []
    return [{
      idx: stroke.endIdx,
      price: stroke.endPrice,
      type: stroke.direction === 'up' ? 'high' as const : 'low' as const,
    }]
  })
  const patterns: DetectedPattern[] = []

  for (let i = 2; i < swings.length - 2; i += 1) {
    const [left, leftNeck, head, rightNeck, right] = swings.slice(i - 2, i + 3)
    if (left.type === 'high' && head.type === 'high' && right.type === 'high'
      && head.price > left.price * 1.01 && head.price > right.price * 1.01
      && leftNeck.price < head.price && rightNeck.price < head.price) {
      patterns.push({ type: 'HST', label: '头肩顶', points: [left, head, right], neckline: [leftNeck, rightNeck] })
    }
    if (left.type === 'low' && head.type === 'low' && right.type === 'low'
      && head.price < left.price * 0.99 && head.price < right.price * 0.99) {
      patterns.push({ type: 'HSB', label: '头肩底', points: [left, head, right], neckline: [leftNeck, rightNeck] })
    }
  }

  for (let i = 0; i < swings.length - 2; i += 1) {
    for (let j = i + 2; j < Math.min(swings.length, i + 7); j += 1) {
      const first = swings[i]
      const second = swings[j]
      if (first.type !== second.type) continue
      if (Math.abs(first.price - second.price) > Math.max(first.price, second.price) * 0.02) continue
      patterns.push({
        type: first.type === 'high' ? 'DT' : 'DB',
        label: first.type === 'high' ? '双顶' : '双底',
        points: [first, second],
      })
      break
    }
  }

  for (let i = 0; i + 5 < swings.length; i += 1) {
    const window = swings.slice(i, i + 6)
    const highs = window.filter(point => point.type === 'high')
    const lows = window.filter(point => point.type === 'low')
    if (highs.length < 2 || lows.length < 2) continue
    const highSlope = (highs.at(-1)!.price - highs[0].price) / (highs.length - 1)
    const lowSlope = (lows.at(-1)!.price - lows[0].price) / (lows.length - 1)
    const converging = (highSlope < 0 && lowSlope > 0)
      || (Math.abs(highSlope) < highs[0].price * 0.01 && lowSlope > 0)
      || (highSlope < 0 && Math.abs(lowSlope) < lows[0].price * 0.01)
    if (converging) {
      patterns.push({
        type: 'Tri', label: '三角形',
        points: [highs[0], lows[0], highs.at(-1)!, lows.at(-1)!],
      })
    }
  }
  return patterns
}
