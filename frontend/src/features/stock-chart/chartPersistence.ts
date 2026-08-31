import { storage } from '@/lib/storage'
import { DEFAULT_CHANLUN_CONFIG } from '@/components/EChartsCandlestick'
import type { StockChartLayout, UserDrawing } from './chartTypes'

export const DEFAULT_STOCK_CHART_LAYOUT: StockChartLayout = {
  version: 3,
  interval: '1d',
  adjustment: 'qfq',
  range: '1y',
  activeIndicators: ['vol', 'macd'],
  collapsedIndicators: [],
  paneHeights: {},
  chanlun: { ...DEFAULT_CHANLUN_CONFIG, showMerged: false, showFenxing: true, bspMode: 'all' },
  keyLevelsVisible: true,
  activeLevelTypes: ['sr', 'pivot', 'keltner_s'],
  enabledLayerIds: ['event.market', 'pattern.classic', 'pattern.vcp'],
  strategyScope: 'source',
  strategyEventTypes: ['candidate', 'entry', 'exit', 'failure', 'support', 'retrigger'],
  annotationDensity: 'auto',
  customPresets: {},
}

export function loadChartLayout(): StockChartLayout {
  const stored = storage.stockChartLayout.get(null) as (Partial<StockChartLayout> & { version?: number; pattern?: string }) | null
  if (!stored || ![1, 2, 3].includes(stored.version ?? 0)) return DEFAULT_STOCK_CHART_LAYOUT
  return {
    ...DEFAULT_STOCK_CHART_LAYOUT,
    ...stored,
    version: 3,
    activeIndicators: Array.isArray(stored.activeIndicators) ? stored.activeIndicators : DEFAULT_STOCK_CHART_LAYOUT.activeIndicators,
    paneHeights: stored.paneHeights ?? {},
    chanlun: { ...DEFAULT_STOCK_CHART_LAYOUT.chanlun, ...(stored.chanlun ?? {}) },
    enabledLayerIds: Array.isArray(stored.enabledLayerIds)
      ? stored.enabledLayerIds
      : [...DEFAULT_STOCK_CHART_LAYOUT.enabledLayerIds, ...(stored.pattern ? ['pattern.classic'] : [])],
  }
}

export function saveChartLayout(layout: StockChartLayout): void {
  storage.stockChartLayout.set(layout)
}

export function loadChartDrawings(): Record<string, UserDrawing[]> {
  const stored = storage.stockChartDrawings.get({})
  if (!stored || typeof stored !== 'object') return {}
  return Object.fromEntries(Object.entries(stored).filter(([, value]) => Array.isArray(value))) as Record<string, UserDrawing[]>
}

export function saveChartDrawings(drawings: Record<string, UserDrawing[]>): void {
  storage.stockChartDrawings.set(drawings)
}
