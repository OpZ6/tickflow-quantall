import type { ChartAdjustment, ChartInterval, ChartRangeName } from '@/lib/api'
import type { ChanlunLayerConfig } from '@/components/EChartsCandlestick'

export type IndicatorCategory = 'overlay' | 'pane' | 'structure' | 'drawing'

export interface ParamDefinition {
  key: string
  label: string
  min: number
  max: number
  step: number
  defaultValue: number
}

export interface ChartIndicatorDefinition {
  key: string
  label: string
  category: IndicatorCategory
  group: string
  requiredFields: string[]
  warmupBars: number
  supportedIntervals: ChartInterval[]
  defaultParams: Record<string, number>
  paramSchema: ParamDefinition[]
  defaultHeight?: number
}

export interface StockChartLayout {
  version: 1
  interval: ChartInterval
  adjustment: ChartAdjustment
  range: ChartRangeName
  activeIndicators: string[]
  collapsedIndicators: string[]
  paneHeights: Record<string, number>
  chanlun: ChanlunLayerConfig & {
    showMerged: boolean
    showFenxing: boolean
    bspMode: 'all' | 'divergence'
  }
  keyLevelsVisible: boolean
  activeLevelTypes: string[]
  pattern: '' | 'HST' | 'HSB' | 'DT' | 'DB' | 'Tri'
  customPresets: Record<string, string[]>
}

export interface UserDrawing {
  id: string
  kind: 'horizontal' | 'trend' | 'text'
  price?: number
  start?: { date: string; price: number }
  end?: { date: string; price: number }
  text?: string
  adjustment: ChartAdjustment
  interval: ChartInterval
}
