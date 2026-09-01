import type { ChartAdjustment, ChartInterval, ChartRangeName } from '@/lib/api'

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
  id: string
  key: string
  version: number
  label: string
  category: IndicatorCategory
  kind: ChartIndicatorKind
  placement: 'main' | 'sub'
  calculation: 'client' | 'server' | 'repository'
  group: string
  requiredFields: string[]
  warmupBars: number
  supportedIntervals: ChartInterval[]
  defaultParams: Record<string, number>
  paramSchema: ParamDefinition[]
  styleSchema: ParamDefinition[]
  defaultHeight?: number
}

export type ChartIndicatorKind = 'technical' | 'structure' | 'pattern' | 'strategy' | 'event'

export interface ChartIndicatorInstance {
  instanceId: string
  indicatorId: string
  kind: ChartIndicatorKind
  enabled: boolean
  params: Record<string, unknown>
  style: Record<string, unknown>
  pane: {
    placement: 'main' | 'sub'
    order: number
    height?: number
    collapsed?: boolean
  }
}

export interface ChartIndicatorTemplate {
  id: string
  name: string
  system: boolean
  schemaVersion: 1
  indicators: ChartIndicatorInstance[]
  annotationDensity: 'auto' | 'compact' | 'detailed'
  preferences?: {
    interval?: ChartInterval
    adjustment?: ChartAdjustment
    range?: ChartRangeName
    activeIndicatorSummaryVisible?: boolean
  }
  createdAt: string
  updatedAt: string
}

export interface StockChartLayout {
  version: 4
  interval: ChartInterval
  adjustment: ChartAdjustment
  range: ChartRangeName
  indicators: ChartIndicatorInstance[]
  annotationDensity: 'auto' | 'compact' | 'detailed'
  activeTemplateId?: string
  templates: ChartIndicatorTemplate[]
  activeIndicatorSummaryVisible: boolean
  migrationWarnings?: string[]
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
