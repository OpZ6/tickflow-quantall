import { DEFAULT_CHANLUN_CONFIG } from '@/components/EChartsCandlestick'
import { getParams } from '@/lib/indicator-params'
import { storage } from '@/lib/storage'
import { INDICATOR_REGISTRY } from './indicatorRegistry'
import type { ChartIndicatorInstance, ChartIndicatorTemplate, StockChartLayout, UserDrawing } from './chartTypes'

const SYSTEM_TIME = 'system'
const RETIRED_PATTERN_LAYER_IDS = new Set(['pattern.vcp', 'pattern.cup_handle', 'pattern.high_tight_flag', 'pattern.pullback_absorb'])

function technicalInstance(key: string, order: number): ChartIndicatorInstance {
  const definition = INDICATOR_REGISTRY.find(item => item.key === key)
  return {
    instanceId: `technical.${key}`, indicatorId: key, kind: 'technical', enabled: true,
    params: getParams(key), style: {},
    pane: {
      placement: definition?.category === 'pane' ? 'sub' : 'main', order,
      ...(definition?.category === 'pane' ? { height: definition.defaultHeight ?? 96, collapsed: false } : {}),
    },
  }
}

function structureInstances(): ChartIndicatorInstance[] {
  return [
    { instanceId: 'structure.chanlun', indicatorId: 'chanlun', kind: 'structure', enabled: false, params: { ...DEFAULT_CHANLUN_CONFIG, showMerged: false, showFenxing: true, bspMode: 'all' }, style: {}, pane: { placement: 'main', order: 100 } },
    { instanceId: 'structure.key-levels', indicatorId: 'key-levels', kind: 'structure', enabled: true, params: { activeLevelTypes: ['sr', 'pivot', 'keltner_s'] }, style: {}, pane: { placement: 'main', order: 101 } },
    { instanceId: 'pattern.classic', indicatorId: 'patterns', kind: 'pattern', enabled: true, params: { layerIds: ['pattern.classic'] }, style: {}, pane: { placement: 'main', order: 102 } },
    { instanceId: 'event.market', indicatorId: 'events', kind: 'event', enabled: true, params: { layerIds: ['event.market'] }, style: {}, pane: { placement: 'main', order: 103 } },
    { instanceId: 'strategy.signals', indicatorId: 'strategies', kind: 'strategy', enabled: false, params: { layerIds: ['strategy.signals', 'plan.strategy'], strategyScope: 'source', eventTypes: ['candidate', 'entry', 'exit', 'failure', 'support', 'retrigger'] }, style: {}, pane: { placement: 'main', order: 104 } },
  ]
}

function systemTemplate(id: string, name: string, keys: string[], structures: string[] = []): ChartIndicatorTemplate {
  return {
    id, name, system: true, schemaVersion: 1,
    indicators: [...keys.map(technicalInstance), ...structureInstances().map(item => ({ ...item, enabled: structures.includes(item.indicatorId) }))],
    annotationDensity: 'auto', createdAt: SYSTEM_TIME, updatedAt: SYSTEM_TIME,
  }
}

export const SYSTEM_INDICATOR_TEMPLATES: ChartIndicatorTemplate[] = [
  systemTemplate('system.basic', '基础', ['vol']),
  systemTemplate('system.trend', '趋势', ['ema', 'supertrend', 'macd']),
  systemTemplate('system.oscillation', '震荡', ['boll', 'kdj', 'rsi']),
  systemTemplate('system.chanlun', '缠论分析', ['macd'], ['chanlun']),
  systemTemplate('system.levels', '关键价位', ['vol'], ['key-levels']),
]

export const DEFAULT_STOCK_CHART_LAYOUT: StockChartLayout = {
  version: 4, interval: '1d', adjustment: 'qfq', range: '1y',
  indicators: [...['vol', 'macd'].map(technicalInstance), ...structureInstances()],
  annotationDensity: 'auto', templates: SYSTEM_INDICATOR_TEMPLATES,
  activeTemplateId: undefined, activeIndicatorSummaryVisible: true,
}

export function cloneIndicatorInstances(items: ChartIndicatorInstance[]): ChartIndicatorInstance[] {
  return items.map(item => ({ ...item, params: structuredClone(item.params), style: structuredClone(item.style), pane: { ...item.pane } }))
}

function cloneTemplates(items: ChartIndicatorTemplate[]): ChartIndicatorTemplate[] {
  return items.map(item => ({ ...item, indicators: cloneIndicatorInstances(item.indicators), preferences: item.preferences ? { ...item.preferences } : undefined }))
}

function safeDefault(warnings: string[] = []): StockChartLayout {
  return {
    ...DEFAULT_STOCK_CHART_LAYOUT,
    indicators: cloneIndicatorInstances(DEFAULT_STOCK_CHART_LAYOUT.indicators),
    templates: cloneTemplates(SYSTEM_INDICATOR_TEMPLATES),
    migrationWarnings: warnings,
  }
}

function migrateLegacy(stored: any): StockChartLayout {
  const warnings: string[] = []
  const active = Array.isArray(stored.activeIndicators) ? stored.activeIndicators : ['vol', 'macd']
  active.filter((key: unknown) => typeof key !== 'string' || !INDICATOR_REGISTRY.some(item => item.key === key)).forEach((key: unknown) => warnings.push(`已忽略未知旧指标：${String(key)}`))
  const technical = active
    .filter((key: string) => INDICATOR_REGISTRY.some(item => item.key === key && item.category !== 'structure'))
    .map((key: string, index: number) => {
      const item = technicalInstance(key, index)
      return { ...item, pane: { ...item.pane, height: stored.paneHeights?.[key] ?? item.pane.height, collapsed: Array.isArray(stored.collapsedIndicators) && stored.collapsedIndicators.includes(key) } }
    })
  const layerIds = (Array.isArray(stored.enabledLayerIds) ? stored.enabledLayerIds : ['event.market', 'pattern.classic'])
    .filter((id: string) => !RETIRED_PATTERN_LAYER_IDS.has(id))
  const structures = structureInstances().map(item => {
    if (item.indicatorId === 'chanlun') return { ...item, enabled: !!stored.chanlun?.visible, params: { ...item.params, ...(stored.chanlun ?? {}) } }
    if (item.indicatorId === 'key-levels') return { ...item, enabled: stored.keyLevelsVisible !== false, params: { activeLevelTypes: stored.activeLevelTypes ?? item.params.activeLevelTypes } }
    if (item.indicatorId === 'strategies') return { ...item, enabled: layerIds.some((id: string) => id.startsWith('strategy.') || id === 'plan.strategy'), params: { ...item.params, layerIds: layerIds.filter((id: string) => id.startsWith('strategy.') || id === 'plan.strategy'), strategyScope: stored.strategyScope ?? 'source', eventTypes: stored.strategyEventTypes ?? item.params.eventTypes } }
    const ownLayerIds = item.params.layerIds as string[]
    return { ...item, enabled: ownLayerIds.some(id => layerIds.includes(id)) }
  })
  const customTemplates = Object.entries(stored.customPresets ?? {}).map(([name, keys], index) => ({
    ...systemTemplate(`custom.migrated.${index}`, name, Array.isArray(keys) ? (keys as string[]).filter(key => INDICATOR_REGISTRY.some(item => item.key === key)) : []),
    system: false, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
  }))
  return {
    ...DEFAULT_STOCK_CHART_LAYOUT,
    interval: stored.interval ?? '1d', adjustment: stored.adjustment ?? 'qfq', range: stored.range ?? '1y',
    indicators: [...technical, ...structures], annotationDensity: stored.annotationDensity ?? 'auto',
    templates: [...cloneTemplates(SYSTEM_INDICATOR_TEMPLATES), ...customTemplates], migrationWarnings: warnings,
  }
}

function normalizeInstance(value: unknown, seen: Set<string>, warnings: string[]): ChartIndicatorInstance | null {
  if (!value || typeof value !== 'object') { warnings.push('已忽略损坏的指标实例'); return null }
  const item = value as Partial<ChartIndicatorInstance>
  const definition = INDICATOR_REGISTRY.find(entry => entry.key === item.indicatorId)
  if (!definition) { warnings.push(`已忽略未知指标：${String(item.indicatorId)}`); return null }
  if (typeof item.instanceId !== 'string' || !item.instanceId.trim() || seen.has(item.instanceId)) {
    warnings.push(`已忽略重复或无效实例：${String(item.instanceId)}`)
    return null
  }
  seen.add(item.instanceId)
  const rawParams = item.params && typeof item.params === 'object' && !Array.isArray(item.params) ? item.params : {}
  const params = definition.kind === 'technical'
    ? Object.fromEntries(definition.paramSchema.map(param => {
      const candidate = Number((rawParams as Record<string, unknown>)[param.key] ?? param.defaultValue)
      const value = Number.isFinite(candidate) && candidate >= param.min && candidate <= param.max ? candidate : param.defaultValue
      if (value !== candidate) warnings.push(`${definition.label}.${param.label} 参数无效，已恢复默认值`)
      return [param.key, value]
    }))
    : structuredClone(rawParams)
  const pane = item.pane && typeof item.pane === 'object' ? item.pane : { placement: definition.placement, order: seen.size - 1 }
  return {
    instanceId: item.instanceId,
    indicatorId: definition.key,
    kind: definition.kind,
    enabled: item.enabled === true,
    params,
    style: item.style && typeof item.style === 'object' && !Array.isArray(item.style) ? structuredClone(item.style) : {},
    pane: {
      placement: pane.placement === 'sub' || pane.placement === 'main' ? pane.placement : definition.placement,
      order: Number.isFinite(pane.order) ? Number(pane.order) : seen.size - 1,
      ...(Number.isFinite(pane.height) ? { height: Math.max(48, Math.min(480, Number(pane.height))) } : {}),
      ...(typeof pane.collapsed === 'boolean' ? { collapsed: pane.collapsed } : {}),
    },
  }
}

function normalizeCustomTemplates(values: unknown, warnings: string[]): ChartIndicatorTemplate[] {
  if (!Array.isArray(values)) return []
  const ids = new Set<string>()
  const names = new Set<string>()
  const result: ChartIndicatorTemplate[] = []
  for (const value of values) {
    if (!value || typeof value !== 'object' || (value as ChartIndicatorTemplate).system) continue
    const item = value as Partial<ChartIndicatorTemplate>
    const normalizedName = typeof item.name === 'string' ? item.name.trim() : ''
    if (typeof item.id !== 'string' || !item.id.startsWith('custom.') || !normalizedName || ids.has(item.id) || names.has(normalizedName.toLocaleLowerCase())) {
      warnings.push(`已忽略损坏或重名的自定义模板：${normalizedName || String(item.id)}`)
      continue
    }
    const seenInstances = new Set<string>()
    const indicators = Array.isArray(item.indicators) ? item.indicators.map(entry => normalizeInstance(entry, seenInstances, warnings)).filter((entry): entry is ChartIndicatorInstance => !!entry) : []
    if (indicators.length === 0) { warnings.push(`模板“${normalizedName}”没有有效指标，已忽略`); continue }
    ids.add(item.id); names.add(normalizedName.toLocaleLowerCase())
    result.push({
      id: item.id, name: normalizedName, system: false, schemaVersion: 1, indicators,
      annotationDensity: item.annotationDensity === 'compact' || item.annotationDensity === 'detailed' ? item.annotationDensity : 'auto',
      preferences: item.preferences && typeof item.preferences === 'object' ? { ...item.preferences } : undefined,
      createdAt: typeof item.createdAt === 'string' ? item.createdAt : new Date().toISOString(),
      updatedAt: typeof item.updatedAt === 'string' ? item.updatedAt : new Date().toISOString(),
    })
  }
  return result
}

export function normalizeChartLayout(stored: unknown): StockChartLayout {
  if (!stored || typeof stored !== 'object') return safeDefault(['布局数据损坏，已使用安全默认布局'])
  const value = stored as any
  if (value.version !== 4 || !Array.isArray(value.indicators)) return migrateLegacy(value)
  const warnings: string[] = []
  const seen = new Set<string>()
  const indicators = value.indicators.map((item: unknown) => normalizeInstance(item, seen, warnings)).filter((item: ChartIndicatorInstance | null): item is ChartIndicatorInstance => !!item)
  if (indicators.length === 0) return safeDefault([...warnings, '布局没有有效指标，已使用安全默认布局'])
  const custom = normalizeCustomTemplates(value.templates, warnings)
  const activeTemplateId = typeof value.activeTemplateId === 'string' && [...SYSTEM_INDICATOR_TEMPLATES, ...custom].some(item => item.id === value.activeTemplateId) ? value.activeTemplateId : undefined
  return {
    ...safeDefault(),
    interval: value.interval ?? DEFAULT_STOCK_CHART_LAYOUT.interval,
    adjustment: value.adjustment ?? DEFAULT_STOCK_CHART_LAYOUT.adjustment,
    range: value.range ?? DEFAULT_STOCK_CHART_LAYOUT.range,
    indicators,
    annotationDensity: value.annotationDensity === 'compact' || value.annotationDensity === 'detailed' ? value.annotationDensity : 'auto',
    activeTemplateId,
    templates: [...cloneTemplates(SYSTEM_INDICATOR_TEMPLATES), ...custom],
    activeIndicatorSummaryVisible: value.activeIndicatorSummaryVisible !== false,
    migrationWarnings: warnings,
  }
}

export function loadChartLayout(): StockChartLayout {
  const stored = storage.stockChartLayout.get(null) as any
  if (!stored) return safeDefault()
  return normalizeChartLayout(stored)
}

export function saveChartLayout(layout: StockChartLayout): boolean { return storage.stockChartLayout.set(layout) }

export function loadChartDrawings(): Record<string, UserDrawing[]> {
  const stored = storage.stockChartDrawings.get({})
  if (!stored || typeof stored !== 'object') return {}
  return Object.fromEntries(Object.entries(stored).filter(([, value]) => Array.isArray(value))) as Record<string, UserDrawing[]>
}

export function saveChartDrawings(drawings: Record<string, UserDrawing[]>): void { storage.stockChartDrawings.set(drawings) }
