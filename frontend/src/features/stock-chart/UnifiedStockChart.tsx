import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, CalendarDays, Camera, Crosshair, Expand, Loader2, MoreHorizontal, Play, Redo2, RefreshCw, Settings2, Trash2, Undo2, X } from 'lucide-react'

import {
  EChartsCandlestick, buildTimeIndex, mapChanlunData, toChanlunCandles,
  type ChartMarker, type ChartPriceLine, type OHLC,
} from '@/components/EChartsCandlestick'
import type { LevelType, PriceLevel } from '@/components/stock-analysis/AnalysisKChart'
import { api, type AnnotationEvidence, type ChartAdjustment, type ChartInterval, type ChartLayerCategory, type ChartRangeName, type StrategyDetail } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { toast } from '@/components/Toast'
import { setParams } from '@/lib/indicator-params'
import { INDICATOR_REGISTRY, PANE_REGISTRY } from './indicatorRegistry'
import { ChartLayerManager, EvidenceDrawer, type ManagerTab } from './ChartLayerManager'
import { buildAnnotationVisuals } from './annotationLayers'
import { cloneIndicatorInstances, loadChartDrawings, loadChartLayout, saveChartDrawings, saveChartLayout } from './chartPersistence'
import type { ChartIndicatorInstance, ChartIndicatorTemplate, StockChartLayout, UserDrawing } from './chartTypes'
import { rowsAtReplay } from './replay'

const INTERVALS: { value: ChartInterval; label: string }[] = [
  ['1m', '1分'], ['5m', '5分'], ['15m', '15分'], ['30m', '30分'], ['60m', '60分'],
  ['1d', '日K'], ['1w', '周K'], ['1mo', '月K'],
].map(([value, label]) => ({ value: value as ChartInterval, label }))
const RANGES: { value: ChartRangeName; label: string }[] = [
  ['1m', '1月'], ['3m', '3月'], ['6m', '半年'], ['1y', '1年'], ['3y', '3年'], ['5y', '5年'], ['all', '全部'], ['custom', '自定义'],
].map(([value, label]) => ({ value: value as ChartRangeName, label }))
const RANGE_CALENDAR_DAYS: Partial<Record<ChartRangeName, number>> = {
  '1m': 31, '3m': 93, '6m': 186, '1y': 366, '3y': 1096, '5y': 1827,
}
const HISTORY_PAGE_DAYS: Record<ChartInterval, number> = {
  '1m': 14, '5m': 31, '15m': 62, '30m': 93, '60m': 186,
  '1d': 366, '1w': 1096, '1mo': 3653,
}

function localIsoDate(): string {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

function subtractCalendarDays(value: string, days: number): string {
  const parsed = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return value
  parsed.setUTCDate(parsed.getUTCDate() - days)
  return parsed.toISOString().slice(0, 10)
}
const LEVEL_COLORS: Record<string, string> = {
  sr: '#F97316', pivot: '#8B5CF6', extreme: '#EAB308', boll: '#F97316',
  keltner_s: '#06B6D4', keltner_m: '#3B82F6', keltner_l: '#8B5CF6', atr_stop: '#EF4444',
  gap: '#EC4899', fib: '#14B8A6', round: '#94A3B8',
}

export interface StrategyChartContext {
  strategyId?: string
  strategyIds?: string[]
  asOf?: string
  sourceRunId?: string
  paramsFingerprint?: string
  signalDate?: string
  returnTo?: string
}

interface Props { symbol: string; height?: number; strategyContext?: StrategyChartContext }

function levelLines(levels: Record<LevelType, PriceLevel[]>, active: string[]): ChartPriceLine[] {
  return active.flatMap(type => (levels[type as LevelType] ?? []))
    .map(level => ({ value: level.value, label: level.label, color: LEVEL_COLORS[level.type] }))
}

function templateSnapshot(layout: StockChartLayout): string {
  return JSON.stringify({
    indicators: layout.indicators,
    annotationDensity: layout.annotationDensity,
    preferences: {
      interval: layout.interval,
      adjustment: layout.adjustment,
      range: layout.range,
      activeIndicatorSummaryVisible: layout.activeIndicatorSummaryVisible,
    },
  })
}

function storedTemplateSnapshot(template: ChartIndicatorTemplate, layout: StockChartLayout): string {
  return JSON.stringify({
    indicators: template.indicators,
    annotationDensity: template.annotationDensity,
    preferences: template.preferences ?? {
      interval: layout.interval,
      adjustment: layout.adjustment,
      range: layout.range,
      activeIndicatorSummaryVisible: layout.activeIndicatorSummaryVisible,
    },
  })
}

const ALL_LAYER_CATEGORIES: ChartLayerCategory[] = ['pattern', 'strategy', 'event', 'plan']

export function UnifiedStockChart({ symbol, height = 680, strategyContext }: Props) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [layout, setLayout] = useState<StockChartLayout>(loadChartLayout)
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [replayIndex, setReplayIndex] = useState<number | null>(null)
  const [drawMode, setDrawMode] = useState<'none' | 'horizontal' | 'trend' | 'text'>('none')
  const [trendStart, setTrendStart] = useState<{ date: string; price: number } | null>(null)
  const [drawingsByContext, setDrawingsByContext] = useState<Record<string, UserDrawing[]>>(loadChartDrawings)
  const [drawingUndo, setDrawingUndo] = useState<UserDrawing[][]>([])
  const [drawingRedo, setDrawingRedo] = useState<UserDrawing[][]>([])
  const [indicatorErrors, setIndicatorErrors] = useState<string[]>([])
  const [layerManagerOpen, setLayerManagerOpen] = useState(false)
  const [layerManagerTab, setLayerManagerTab] = useState<ManagerTab>('technical')
  const [selectedEvidence, setSelectedEvidence] = useState<AnnotationEvidence | null>(null)
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<Set<string>>(new Set())
  const [knownStrategyIds, setKnownStrategyIds] = useState<string[]>([])
  const [previewStrategyIds, setPreviewStrategyIds] = useState<Set<string>>(new Set())
  const [visibleAnnotationBars, setVisibleAnnotationBars] = useState(60)
  const [focusedIndicatorId, setFocusedIndicatorId] = useState<string>()
  const [drawMenuOpen, setDrawMenuOpen] = useState(false)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const [rangePanelOpen, setRangePanelOpen] = useState(false)
  const [draggedIndicatorId, setDraggedIndicatorId] = useState<string>()
  const [historyWindow, setHistoryWindow] = useState<{ context: string; start: string }>()
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyExhausted, setHistoryExhausted] = useState(false)
  const [historyNotice, setHistoryNotice] = useState('')
  const historyPreviousOldestRef = useRef<string>()

  const indicatorById = (id: string) => layout.indicators.find(item => item.indicatorId === id)
  const technicalIndicators = layout.indicators.filter(item => item.kind === 'technical' && item.enabled).sort((a, b) => a.pane.order - b.pane.order)
  const activeIndicatorKeys = technicalIndicators.map(item => item.indicatorId)
  const collapsedIndicatorKeys = technicalIndicators.filter(item => item.pane.collapsed).map(item => item.indicatorId)
  const paneHeights = Object.fromEntries(technicalIndicators.filter(item => item.pane.height != null).map(item => [item.indicatorId, item.pane.height!]))
  const indicatorStyles = Object.fromEntries(technicalIndicators.map(item => [item.indicatorId, item.style]))
  const chanlunInstance = indicatorById('chanlun')
  const chanlunConfig = { ...chanlunInstance?.params, visible: !!chanlunInstance?.enabled } as any
  const keyLevelsInstance = indicatorById('key-levels')
  const keyLevelsVisible = !!keyLevelsInstance?.enabled
  const activeLevelTypes = (keyLevelsInstance?.params.activeLevelTypes as string[] | undefined) ?? []
  const strategyInstance = indicatorById('strategies')
  const strategyScope = (strategyInstance?.params.strategyScope as 'source' | 'all' | undefined) ?? 'source'
  const strategyEventTypes = (strategyInstance?.params.eventTypes as string[] | undefined) ?? []
  const enabledLayerIdsArray = layout.indicators.filter(item => item.enabled).flatMap(item => (item.params.layerIds as string[] | undefined) ?? [])
  const activeTemplate = layout.templates.find(item => item.id === layout.activeTemplateId)
  const activeTemplateDeviated = !!activeTemplate && templateSnapshot(layout) !== storedTemplateSnapshot(activeTemplate, layout)

  const updateIndicator = (indicatorId: string, change: (item: ChartIndicatorInstance) => ChartIndicatorInstance) => {
    setLayout(current => ({ ...current, activeTemplateId: undefined, indicators: current.indicators.map(item => item.indicatorId === indicatorId ? change(item) : item) }))
  }

  const updateIndicatorConfig = (indicatorId: string, change: Partial<ChartIndicatorInstance>) => {
    const existing = indicatorById(indicatorId)
    if (change.params && (existing?.kind === 'technical' || (!existing && INDICATOR_REGISTRY.some(item => item.key === indicatorId && item.category !== 'structure')))) {
      const numericParams = Object.fromEntries(Object.entries(change.params).filter((entry): entry is [string, number] => typeof entry[1] === 'number'))
      setParams(indicatorId, numericParams)
    }
    if (existing) {
      updateIndicator(indicatorId, item => ({
        ...item,
        ...change,
        params: change.params ?? item.params,
        style: change.style ?? item.style,
        pane: change.pane ?? item.pane,
      }))
      return
    }
    const definition = INDICATOR_REGISTRY.find(item => item.key === indicatorId)
    if (!definition) return
    setLayout(current => ({
      ...current,
      activeTemplateId: undefined,
      indicators: [...current.indicators, {
        instanceId: `technical.${indicatorId}`,
        indicatorId,
        kind: 'technical',
        enabled: change.enabled ?? true,
        params: change.params ?? { ...definition.defaultParams },
        style: change.style ?? {},
        pane: change.pane ?? {
          placement: definition.category === 'pane' ? 'sub' : 'main',
          order: current.indicators.length,
          height: definition.defaultHeight,
          collapsed: false,
        },
      }],
    }))
  }

  const applyTemplate = (template: ChartIndicatorTemplate) => {
    const indicators = cloneIndicatorInstances(template.indicators)
    indicators.filter(item => item.kind === 'technical').forEach(item => {
      const numericParams = Object.fromEntries(Object.entries(item.params).filter((entry): entry is [string, number] => typeof entry[1] === 'number'))
      setParams(item.indicatorId, numericParams)
    })
    setLayout(current => ({
      ...current,
      indicators,
      annotationDensity: template.annotationDensity,
      interval: template.preferences?.interval ?? current.interval,
      adjustment: template.preferences?.adjustment ?? current.adjustment,
      range: template.preferences?.range ?? current.range,
      activeIndicatorSummaryVisible: template.preferences?.activeIndicatorSummaryVisible ?? current.activeIndicatorSummaryVisible,
      activeTemplateId: template.id,
    }))
  }

  const templateFromCurrent = (name: string, id = `custom.${crypto.randomUUID()}`, createdAt = new Date().toISOString()): ChartIndicatorTemplate => {
    const now = new Date().toISOString()
    return {
      id,
      name,
      system: false,
      schemaVersion: 1,
      indicators: cloneIndicatorInstances(layout.indicators),
      annotationDensity: layout.annotationDensity,
      preferences: {
        interval: layout.interval,
        adjustment: layout.adjustment,
        range: layout.range,
        activeIndicatorSummaryVisible: layout.activeIndicatorSummaryVisible,
      },
      createdAt,
      updatedAt: now,
    }
  }

  const templateNameAvailable = (name: string, excludeId?: string) => !layout.templates.some(item => item.id !== excludeId && item.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase())

  const saveTemplate = () => {
    const name = window.prompt('模板名称')?.trim()
    if (!name) return
    if (!templateNameAvailable(name)) return toast(`模板名称“${name}”已存在`, 'error')
    const template = templateFromCurrent(name)
    setLayout(current => ({ ...current, activeTemplateId: template.id, templates: [...current.templates, template] }))
    toast(`指标模板“${name}”已保存`, 'success')
  }

  const deleteTemplate = (template: ChartIndicatorTemplate) => {
    if (template.system || !window.confirm(`删除指标模板“${template.name}”？`)) return
    setLayout(current => ({
      ...current,
      activeTemplateId: current.activeTemplateId === template.id ? undefined : current.activeTemplateId,
      templates: current.templates.filter(item => item.id !== template.id),
    }))
  }

  const renameTemplate = (template: ChartIndicatorTemplate) => {
    if (template.system) return
    const name = window.prompt('新的模板名称', template.name)?.trim()
    if (!name || name === template.name) return
    if (!templateNameAvailable(name, template.id)) return toast(`模板名称“${name}”已存在`, 'error')
    setLayout(current => ({ ...current, templates: current.templates.map(item => item.id === template.id ? { ...item, name, updatedAt: new Date().toISOString() } : item) }))
  }

  const copyTemplate = (template: ChartIndicatorTemplate) => {
    const suggested = `${template.name} 副本`
    const name = window.prompt('副本名称', suggested)?.trim()
    if (!name) return
    if (!templateNameAvailable(name)) return toast(`模板名称“${name}”已存在`, 'error')
    const now = new Date().toISOString()
    const copy: ChartIndicatorTemplate = {
      ...template,
      id: `custom.${crypto.randomUUID()}`,
      name,
      system: false,
      indicators: cloneIndicatorInstances(template.indicators),
      createdAt: now,
      updatedAt: now,
    }
    setLayout(current => ({ ...current, templates: [...current.templates, copy] }))
  }

  const overwriteTemplate = (template: ChartIndicatorTemplate) => {
    if (template.system || !window.confirm(`使用当前工作区覆盖“${template.name}”？`)) return
    const replacement = templateFromCurrent(template.name, template.id, template.createdAt)
    setLayout(current => ({ ...current, activeTemplateId: template.id, templates: current.templates.map(item => item.id === template.id ? replacement : item) }))
  }

  const reorderIndicator = (sourceId: string, targetId: string) => {
    if (sourceId === targetId) return
    setLayout(current => {
      const ordered = [...current.indicators].sort((a, b) => a.pane.order - b.pane.order)
      const sourceIndex = ordered.findIndex(item => item.instanceId === sourceId)
      const targetIndex = ordered.findIndex(item => item.instanceId === targetId)
      if (sourceIndex < 0 || targetIndex < 0) return current
      const [source] = ordered.splice(sourceIndex, 1)
      ordered.splice(targetIndex, 0, source)
      return { ...current, activeTemplateId: undefined, indicators: ordered.map((item, order) => ({ ...item, pane: { ...item.pane, order } })) }
    })
  }

  const moveIndicator = (instanceId: string, direction: -1 | 1) => {
    setLayout(current => {
      const ordered = [...current.indicators].sort((a, b) => a.pane.order - b.pane.order)
      const sourceIndex = ordered.findIndex(item => item.instanceId === instanceId)
      const targetIndex = sourceIndex + direction
      if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= ordered.length) return current
      ;[ordered[sourceIndex], ordered[targetIndex]] = [ordered[targetIndex], ordered[sourceIndex]]
      return { ...current, activeTemplateId: undefined, indicators: ordered.map((item, order) => ({ ...item, pane: { ...item.pane, order } })) }
    })
  }

  const sourceStrategyIds = useMemo(() => {
    const ids = strategyContext?.strategyIds?.length ? strategyContext.strategyIds : strategyContext?.strategyId ? [strategyContext.strategyId] : []
    return [...new Set(ids)]
  }, [strategyContext?.strategyId, strategyContext?.strategyIds])
  const requestedStrategyIds = strategyScope === 'source'
    ? sourceStrategyIds
    : [...selectedStrategyIds]

  const drawingKey = `${symbol}|${layout.interval}|${layout.adjustment}`
  const drawings = drawingsByContext[drawingKey] ?? []

  useEffect(() => {
    if (!saveChartLayout(layout)) toast('指标工作区保存失败：浏览器本地存储不可用或空间不足', 'error')
  }, [layout])
  useEffect(() => {
    if (sourceStrategyIds.length === 0) return
    updateIndicator('strategies', item => ({ ...item, enabled: true, params: { ...item.params, strategyScope: 'source', layerIds: ['strategy.signals', 'plan.strategy'] } }))
  }, [sourceStrategyIds])
  useEffect(() => saveChartDrawings(drawingsByContext), [drawingsByContext])
  useEffect(() => {
    const listener = (event: Event) => {
      const key = (event as CustomEvent<{ key?: string }>).detail?.key
      if (key) setIndicatorErrors(current => current.includes(key) ? current : [...current, key])
    }
    window.addEventListener('stock-chart-indicator-error', listener)
    return () => window.removeEventListener('stock-chart-indicator-error', listener)
  }, [])
  useEffect(() => { setReplayIndex(null); setTrendStart(null) }, [symbol, layout.interval, layout.adjustment, layout.range])
  useEffect(() => { setKnownStrategyIds([]); setSelectedStrategyIds(new Set()); setPreviewStrategyIds(new Set()) }, [symbol])
  useEffect(() => { setDrawingUndo([]); setDrawingRedo([]); setDrawMode('none') }, [drawingKey])
  useEffect(() => {
    const closeTransientUi = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setLayerManagerOpen(false)
      setRangePanelOpen(false)
      setDrawMenuOpen(false)
      setMoreMenuOpen(false)
      setSelectedEvidence(null)
    }
    window.addEventListener('keydown', closeTransientUi)
    return () => window.removeEventListener('keydown', closeTransientUi)
  }, [])

  const requestEnd = layout.range === 'custom' ? customEnd : strategyContext?.asOf ?? ''
  const effectiveEnd = requestEnd || localIsoDate()
  const nominalStart = layout.range === 'custom'
    ? customStart
    : RANGE_CALENDAR_DAYS[layout.range]
      ? subtractCalendarDays(effectiveEnd, RANGE_CALENDAR_DAYS[layout.range]!)
      : ''
  // Keep one earlier page outside the initial viewport. This makes horizontal
  // dragging useful immediately while preserving the selected range on screen.
  const initialHistoryStart = nominalStart && layout.range !== 'all'
    ? subtractCalendarDays(nominalStart, HISTORY_PAGE_DAYS[layout.interval])
    : ''
  const historyContext = [symbol, layout.interval, layout.adjustment, layout.range, nominalStart, effectiveEnd].join('|')
  const historyStartOverride = historyWindow?.context === historyContext ? historyWindow.start : undefined
  const requestedStart = historyStartOverride ?? initialHistoryStart
  useEffect(() => {
    setHistoryWindow(undefined)
    setHistoryLoading(false)
    setHistoryExhausted(layout.range === 'all')
    setHistoryNotice('')
    historyPreviousOldestRef.current = undefined
  }, [historyContext, layout.range])
  const layerKey = ALL_LAYER_CATEGORIES.join(',')
  const strategyKey = requestedStrategyIds.join(',')
  const exactSourceRunId = strategyScope === 'source' ? strategyContext?.sourceRunId : undefined
  const exactParamsFingerprint = strategyScope === 'source' ? strategyContext?.paramsFingerprint : undefined
  const indicatorWarmups = Object.fromEntries(layout.indicators.filter(item => item.enabled).map(instance => {
    const definition = INDICATOR_REGISTRY.find(item => item.key === instance.indicatorId)
    const parameterWarmup = instance.kind === 'technical'
      ? Math.max(0, ...Object.values(instance.params).filter((value): value is number => typeof value === 'number' && Number.isFinite(value)).map(value => Math.ceil(value) * 3))
      : 0
    return [instance.indicatorId, Math.max(definition?.warmupBars ?? 0, parameterWarmup)]
  }))
  const indicatorWarmupSignature = Object.entries(indicatorWarmups).sort(([left], [right]) => left.localeCompare(right)).map(([id, bars]) => `${id}:${bars}`).join(',')
  const requiredWarmupBars = Math.max(160, ...Object.values(indicatorWarmups))
  const chartQuery = useQuery({
    queryKey: QK.klineChart(symbol, '', layout.interval, layout.adjustment, layout.range, requestedStart, requestEnd, layerKey, strategyKey, exactSourceRunId ?? '', exactParamsFingerprint ?? '', requiredWarmupBars, indicatorWarmupSignature),
    queryFn: () => api.klineChart({
      symbol, interval: layout.interval, adjustment: layout.adjustment, range: layout.range,
      ...(requestedStart ? { startDate: requestedStart } : {}),
      ...(requestEnd ? { endDate: requestEnd } : {}),
      layers: ALL_LAYER_CATEGORIES,
      strategyIds: requestedStrategyIds,
      sourceRunId: exactSourceRunId,
      paramsFingerprint: exactParamsFingerprint,
      warmupBars: requiredWarmupBars,
      indicatorWarmups,
    }),
    enabled: !!symbol && (layout.range !== 'custom' || !!customStart),
    placeholderData: previous => previous,
    staleTime: 60_000,
  })
  const previewAssetType = chartQuery.data?.asset_type
  const previewTimeframe = layout.interval === '1d' || layout.interval === '1m'
    ? layout.interval
    : null
  const previewCatalogQuery = useQuery({
    queryKey: QK.strategyChartPreviewCatalog(previewAssetType ?? 'stock', layout.interval),
    queryFn: () => api.strategyList(previewAssetType as 'stock' | 'etf', previewTimeframe ?? 'all'),
    enabled: (previewAssetType === 'stock' || previewAssetType === 'etf') && previewTimeframe !== null,
    staleTime: 60_000,
  })
  const previewStrategies = useMemo(
    () => (previewCatalogQuery.data?.strategies ?? []).filter((strategy: StrategyDetail) => strategy.chart_preview?.enabled),
    [previewCatalogQuery.data],
  )
  const previewCatalogSignature = previewStrategies.map(strategy => strategy.id).join(',')
  useEffect(() => {
    if (!previewCatalogQuery.data) return
    const supported = new Set(previewStrategies.map(strategy => strategy.id))
    setPreviewStrategyIds(current => new Set([...current].filter(strategyId => supported.has(strategyId))))
  }, [previewCatalogQuery.data, previewCatalogSignature, previewStrategies])
  // A period switch renders once before the next strategy catalog resolves.
  // Derive the executable selection from the *current* catalog so a daily-only
  // strategy never issues a stale weekly/monthly preview request during that render.
  const activePreviewStrategyIds = useMemo(() => {
    const supported = new Set(previewStrategies.map(strategy => strategy.id))
    return [...previewStrategyIds].filter(strategyId => supported.has(strategyId)).sort()
  }, [previewCatalogSignature, previewStrategies, previewStrategyIds])
  const previewStrategyKey = activePreviewStrategyIds.join(',')
  const previewStart = chartQuery.data?.meta.requested_start ?? ''
  const previewEnd = chartQuery.data?.meta.requested_end ?? ''
  const previewQuery = useQuery({
    queryKey: QK.strategyChartPreview(
      symbol,
      previewAssetType ?? 'stock',
      layout.interval,
      previewStart,
      previewEnd,
      previewStrategyKey,
      chartQuery.data?.meta.input_fingerprint ?? '',
    ),
    queryFn: () => api.strategyPreview({
      symbol,
      assetType: previewAssetType as 'stock' | 'etf' | 'index',
      timeframe: layout.interval,
      startDate: previewStart,
      endDate: previewEnd,
      strategyIds: activePreviewStrategyIds,
    }),
    enabled: activePreviewStrategyIds.length > 0 && !!previewAssetType && !!previewStart && !!previewEnd,
    placeholderData: previous => previous,
    staleTime: 60_000,
  })
  const minuteBackfill = useMutation({
    mutationFn: async () => {
      const start = chartQuery.data?.meta.requested_start
      const end = chartQuery.data?.meta.requested_end
      const days = start && end ? Math.min(1095, Math.max(1, Math.ceil((Date.parse(end) - Date.parse(start)) / 86_400_000) + 1)) : 30
      return api.syncMinuteSingle(symbol, days)
    },
    onSuccess: result => {
      setHistoryExhausted(false)
      setHistoryNotice('')
      toast(`分钟历史补齐完成：${result.rows} 行`, 'success')
      chartQuery.refetch()
    },
    onError: error => toast(error instanceof Error ? error.message : '分钟历史补齐失败', 'error'),
  })
  const dailyBackfill = useMutation({
    mutationFn: () => api.syncDailySingle(
      symbol,
      chartQuery.data?.meta.required_fetch_start ?? chartQuery.data?.meta.requested_start ?? '',
      chartQuery.data?.meta.requested_end ?? '',
    ),
    onSuccess: result => {
      setHistoryExhausted(false)
      setHistoryNotice('')
      toast(`日线历史补齐完成：${result.rows} 行${result.warning ? `；${result.warning}` : ''}`, result.warning ? 'error' : 'success')
      chartQuery.refetch()
    },
    onError: error => toast(error instanceof Error ? error.message : '日线历史补齐失败', 'error'),
  })
  const allRows = (chartQuery.data?.rows ?? []) as OHLC[]
  const analysisRows = (chartQuery.data?.analysis_rows ?? chartQuery.data?.rows ?? []) as OHLC[]
  useEffect(() => {
    if (chartQuery.data?.asset_type === 'index' && layout.adjustment !== 'none') {
      setLayout(current => ({ ...current, adjustment: 'none' }))
    }
  }, [chartQuery.data?.asset_type, layout.adjustment])
  const rows = rowsAtReplay(allRows, replayIndex)
  const requestOlderHistory = (oldestVisibleDate: string) => {
    if (historyLoading || historyExhausted || replayIndex != null || layout.range === 'all') return
    const currentStart = chartQuery.data?.meta.requested_start ?? requestedStart ?? oldestVisibleDate.slice(0, 10)
    const nextStart = subtractCalendarDays(currentStart, HISTORY_PAGE_DAYS[layout.interval])
    if (!nextStart || nextStart >= currentStart) return
    historyPreviousOldestRef.current = allRows[0]?.date
    setHistoryLoading(true)
    setHistoryNotice('')
    setHistoryWindow({ context: historyContext, start: nextStart })
  }
  useEffect(() => {
    if (!historyLoading || chartQuery.isFetching || !historyStartOverride) return
    if (chartQuery.data?.meta.requested_start !== historyStartOverride) return
    const previousOldest = historyPreviousOldestRef.current
    const nextOldest = allRows[0]?.date
    if (previousOldest && nextOldest && nextOldest < previousOldest) {
      setHistoryNotice(`已加载至 ${nextOldest.slice(0, 10)}`)
    } else {
      setHistoryExhausted(true)
      setHistoryNotice(chartQuery.data?.meta.complete
        ? '已到达本地最早历史'
        : '本地更早历史不足，请先使用上方补齐按钮')
    }
    setHistoryLoading(false)
  }, [allRows, chartQuery.data?.meta.complete, chartQuery.data?.meta.requested_start, chartQuery.isFetching, historyLoading, historyStartOverride])
  const analysisRowsAtReplay = useMemo(() => {
    const replayEnd = rows.at(-1)?.date
    return replayEnd ? analysisRows.filter(row => row.date <= replayEnd) : analysisRows
  }, [analysisRows, rows])
  const chanlunQuery = useQuery({
    queryKey: ['stock-chart', 'chanlun', symbol, layout.interval, layout.adjustment, analysisRowsAtReplay.length, rows.at(-1)?.date ?? ''],
    queryFn: () => api.chanlunAnalyze(toChanlunCandles(analysisRowsAtReplay)),
    enabled: chanlunConfig.visible && analysisRowsAtReplay.length >= 10,
    staleTime: 60_000,
  })
  const officialQuery = useQuery({
    queryKey: ['stock-chart', 'official', symbol, layout.interval],
    queryFn: () => api.chanlunOfficial(symbol.split('.')[0], layout.interval === '1d' ? 'D1' : layout.interval.toUpperCase(), Math.min(1000, rows.length)),
    enabled: chanlunConfig.visible && chanlunConfig.showOfficial && layout.interval === '1d', retry: false, staleTime: 300_000,
  })
  const timeIndex = useMemo(() => buildTimeIndex(rows), [rows])
  const chanlun = useMemo(() => {
    const mapped = mapChanlunData(chanlunQuery.data, timeIndex)
    if (!mapped || chanlunConfig.bspMode === 'all') return mapped
    // 本地 BSP v5 中 1/1p 是背驰直接产生的一类点，2/2s/3a 是后续确认型点。
    return { ...mapped, bsp: mapped.bsp.filter(point => point.type.startsWith('1')) }
  }, [chanlunQuery.data, timeIndex, chanlunConfig.bspMode])
  const officialResult = useMemo(() => {
    const layer = mapChanlunData(officialQuery.data?.official ? ({ ...officialQuery.data.official, merged_klines: [], fenxing: [], macd: [] } as any) : null, timeIndex)
    if (!layer) return { layer: null, warning: officialQuery.data?.detail ?? '' }
    const endpoints = [
      ...layer.bi.flatMap(item => [item.startIdx, item.endIdx]),
      ...layer.segments.flatMap(item => [item.startIdx, item.endIdx]),
      ...layer.zhongshu.flatMap(item => [item.startIdx, item.endIdx]),
      ...layer.bsp.map(item => item.idx),
    ]
    const missing = endpoints.filter(value => value == null).length
    if (missing > 0) return { layer: null, warning: `官方结构有 ${missing}/${endpoints.length} 个时间点无法与当前 K 线严格对齐，已拒绝叠加` }
    return { layer, warning: '' }
  }, [officialQuery.data, timeIndex])

  const persistedAnnotationLayers = chartQuery.data?.annotation_layers ?? []
  const previewLayers = activePreviewStrategyIds.length > 0 ? (previewQuery.data?.layers ?? []) : []
  const annotationLayers = [...persistedAnnotationLayers, ...previewLayers]
  const availableStrategyIds = useMemo(() => [...new Set(persistedAnnotationLayers
    .filter(layer => layer.category === 'strategy')
    .flatMap(layer => layer.evidence.flatMap(item => {
      const ids = Array.isArray(item.metadata.strategy_ids) ? item.metadata.strategy_ids.map(String) : []
      const id = item.metadata.strategy_id
      return id ? [String(id), ...ids] : ids
    })))].sort(), [persistedAnnotationLayers])
  useEffect(() => {
    if (availableStrategyIds.length === 0) return
    setKnownStrategyIds(current => [...new Set([...current, ...availableStrategyIds])].sort())
  }, [availableStrategyIds])
  const enabledLayerIds = useMemo(() => new Set(enabledLayerIdsArray), [enabledLayerIdsArray.join('|')])
  const replayDate = replayIndex == null ? undefined : rows.at(-1)?.date
  const effectiveAnnotationDensity = layout.annotationDensity === 'auto'
    ? (visibleAnnotationBars > 80 ? 'compact' : 'detailed')
    : layout.annotationDensity
  const annotationVisuals = useMemo(
    () => buildAnnotationVisuals(annotationLayers, enabledLayerIds, replayDate, {
      strategyIds: strategyScope === 'all' ? selectedStrategyIds : new Set(sourceStrategyIds),
      strategyEventTypes: new Set(strategyEventTypes),
      density: effectiveAnnotationDensity,
    }),
    [annotationLayers, enabledLayerIds, replayDate, strategyScope, strategyEventTypes, effectiveAnnotationDensity, selectedStrategyIds, sourceStrategyIds],
  )

  const levels = (chartQuery.data?.levels ?? {}) as Record<LevelType, PriceLevel[]>
  const userLines: ChartPriceLine[] = drawings
    .filter(item => item.adjustment === layout.adjustment && item.interval === layout.interval && item.kind !== 'text')
    .map(item => item.kind === 'horizontal'
      ? { value: item.price!, label: '手动画线', color: '#38bdf8' }
      : { value: item.start!.price, endValue: item.end!.price, start: item.start!.date, end: item.end!.date, label: '趋势线', color: '#38bdf8' })
  const textMarkers: ChartMarker[] = drawings.filter(item => item.kind === 'text' && item.start).map(item => ({ date: item.start!.date, kind: 'neutral', label: item.text, above: true, color: '#38bdf8' }))
  const enabledIndicators = activeIndicatorKeys.filter(key => !collapsedIndicatorKeys.includes(key))
  const selectedRangeRows = nominalStart
    ? allRows.filter(row => row.date.slice(0, 10) >= nominalStart).length
    : allRows.length
  // The API can preload older candles, but the viewport still represents the
  // range selected in the toolbar. The hidden left buffer is revealed by drag.
  const visibleBars = Math.max(selectedRangeRows, 1)
  const canLoadOlder = layout.range !== 'all' && replayIndex == null && !historyExhausted
  const currentRangeLabel = RANGES.find(item => item.value === layout.range)?.label ?? layout.range
  const chartHeight = Math.max(height, 340 + enabledIndicators.filter(key => PANE_REGISTRY.some(item => item.key === key)).length * 95)

  const updateLayout = (change: Partial<StockChartLayout>) => setLayout(current => ({ ...current, ...change }))
  const commitDrawings = (next: UserDrawing[]) => {
    setDrawingUndo(history => [...history.slice(-49), drawings])
    setDrawingRedo([])
    setDrawingsByContext(current => ({ ...current, [drawingKey]: next }))
  }
  const undoDrawing = () => {
    const previous = drawingUndo.at(-1)
    if (!previous) return
    setDrawingRedo(history => [...history.slice(-49), drawings])
    setDrawingUndo(history => history.slice(0, -1))
    setDrawingsByContext(current => ({ ...current, [drawingKey]: previous }))
  }
  const redoDrawing = () => {
    const next = drawingRedo.at(-1)
    if (!next) return
    setDrawingUndo(history => [...history.slice(-49), drawings])
    setDrawingRedo(history => history.slice(0, -1))
    setDrawingsByContext(current => ({ ...current, [drawingKey]: next }))
  }
  const toggleLayer = (id: string) => {
    const instance = layout.indicators.find(item => ((item.params.layerIds as string[] | undefined) ?? []).includes(id))
    if (instance) updateIndicator(instance.indicatorId, item => ({ ...item, enabled: !item.enabled }))
  }
  const togglePreviewStrategy = (strategyId: string) => {
    const layerId = `strategy.preview.${strategyId}`
    const selected = previewStrategyIds.has(strategyId)
    if (!selected && previewStrategyIds.size >= 3) {
      toast('即时策略标记最多同时选择 3 个', 'error')
      return
    }
    setPreviewStrategyIds(current => {
      const next = new Set(current)
      if (next.has(strategyId)) next.delete(strategyId)
      else next.add(strategyId)
      return next
    })
    updateIndicator('strategies', item => ({ ...item, enabled: true, params: { ...item.params, layerIds: selected ? ((item.params.layerIds as string[]) ?? []).filter(id => id !== layerId) : [...new Set([...(item.params.layerIds as string[] ?? []), layerId])] } }))
  }
  const onChartPoint = (date: string, price: number) => {
    if (drawMode === 'text') {
      const text = window.prompt('标注文字')?.trim()
      if (text) commitDrawings([...drawings, { id: crypto.randomUUID(), kind: 'text', start: { date, price }, text, adjustment: layout.adjustment, interval: layout.interval }])
      setDrawMode('none')
    } else if (drawMode === 'horizontal') {
      commitDrawings([...drawings, { id: crypto.randomUUID(), kind: 'horizontal', price, adjustment: layout.adjustment, interval: layout.interval }])
      setDrawMode('none')
    } else if (drawMode === 'trend') {
      if (!trendStart) setTrendStart({ date, price })
      else {
        commitDrawings([...drawings, { id: crypto.randomUUID(), kind: 'trend', start: trendStart, end: { date, price }, adjustment: layout.adjustment, interval: layout.interval }])
        setTrendStart(null); setDrawMode('none')
      }
    }
  }
  const screenshot = () => {
    const canvas = rootRef.current?.querySelector('canvas')
    if (!canvas) return toast('图表尚未渲染', 'error')
    const link = document.createElement('a'); link.download = `${symbol}-${layout.interval}.png`; link.href = canvas.toDataURL('image/png'); link.click()
  }

  if (chartQuery.isLoading && !chartQuery.data) return <div className="grid min-h-[520px] place-items-center"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
  if (chartQuery.isError) return <div className="grid min-h-[520px] place-items-center text-sm text-danger"><AlertTriangle className="mr-2 h-4 w-4" />K 线数据加载失败</div>

  return (
    <div ref={rootRef} className="relative" data-testid="unified-stock-chart">
      <div className="relative flex flex-nowrap items-center gap-2 overflow-x-auto border-b border-border/50 px-3 py-2 text-xs" data-testid="stock-chart-toolbar">
        <select aria-label="复权" value={layout.adjustment} disabled={chartQuery.data?.asset_type === 'index'} onChange={event => updateLayout({ adjustment: event.target.value as ChartAdjustment })} className="rounded border border-border bg-base px-2 py-1.5 text-secondary"><option value="none">不复权</option><option value="qfq">前复权</option><option value="hfq">后复权</option></select>
        <select aria-label="周期" value={layout.interval} onChange={event => updateLayout({ interval: event.target.value as ChartInterval })} className="rounded border border-border bg-base px-2 py-1.5 text-secondary">{INTERVALS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        <select aria-label="范围" value={layout.range} onChange={event => { const range = event.target.value as ChartRangeName; updateLayout({ range }); setRangePanelOpen(range === 'custom') }} className="rounded border border-border bg-base px-2 py-1.5 text-secondary">{RANGES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        {layout.range === 'custom' && <button type="button" onClick={() => setRangePanelOpen(value => !value)} className="tool-btn" aria-label="设置自定义日期"><CalendarDays className="h-3.5 w-3.5" />日期</button>}
        <button type="button" onClick={() => { setLayerManagerOpen(value => !value); setLayerManagerTab('technical'); setFocusedIndicatorId(undefined) }} className={`tool-btn ${layerManagerOpen ? 'text-sky-300' : ''}`} aria-label="指标中心"><Settings2 className="h-3.5 w-3.5" />指标 {layout.indicators.filter(item => item.enabled).length}</button>
        <button type="button" onClick={() => setDrawMenuOpen(value => !value)} className={`tool-btn ${drawMode !== 'none' ? 'text-sky-300' : ''}`} aria-label="画线工具"><Crosshair className="h-3.5 w-3.5" />画线</button>
        <button type="button" onClick={() => setReplayIndex(replayIndex == null ? Math.max(0, allRows.length - 30) : null)} className={`tool-btn ${replayIndex != null ? 'text-amber-300' : ''}`}><Play className="h-3.5 w-3.5" />回放</button>
        <button type="button" onClick={() => setMoreMenuOpen(value => !value)} className="tool-btn" aria-label="更多图表操作"><MoreHorizontal className="h-3.5 w-3.5" />更多</button>
      </div>
      {rangePanelOpen && layout.range === 'custom' && <div className="absolute left-3 top-12 z-30 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2 rounded border border-border bg-surface p-2 text-xs shadow-xl"><input aria-label="开始日期" type="date" value={customStart} onChange={event => setCustomStart(event.target.value)} className="rounded border border-border bg-base px-2 py-1 text-secondary" /><span className="text-muted">至</span><input aria-label="结束日期" type="date" value={customEnd} onChange={event => setCustomEnd(event.target.value)} className="rounded border border-border bg-base px-2 py-1 text-secondary" /><button type="button" onClick={() => setRangePanelOpen(false)} className="tool-btn">完成</button></div>}
      {drawMenuOpen && <div className="absolute left-48 top-12 z-30 grid min-w-40 gap-1 rounded border border-border bg-surface p-2 text-xs shadow-xl"><button type="button" onClick={() => { setDrawMode('trend'); setDrawMenuOpen(false) }} className="tool-btn justify-start"><Crosshair className="h-3.5 w-3.5" />趋势线</button><button type="button" onClick={() => { setDrawMode('horizontal'); setDrawMenuOpen(false) }} className="tool-btn justify-start">水平线</button><button type="button" onClick={() => { setDrawMode('text'); setDrawMenuOpen(false) }} className="tool-btn justify-start">文字</button><button type="button" onClick={undoDrawing} disabled={!drawingUndo.length} className="tool-btn justify-start disabled:opacity-30"><Undo2 className="h-3.5 w-3.5" />撤销</button><button type="button" onClick={redoDrawing} disabled={!drawingRedo.length} className="tool-btn justify-start disabled:opacity-30"><Redo2 className="h-3.5 w-3.5" />重做</button></div>}
      {moreMenuOpen && <div className="absolute right-3 top-12 z-30 grid min-w-36 gap-1 rounded border border-border bg-surface p-2 text-xs shadow-xl"><button type="button" onClick={() => chartQuery.refetch()} className="tool-btn justify-start"><RefreshCw className={`h-3.5 w-3.5 ${chartQuery.isFetching ? 'animate-spin' : ''}`} />刷新数据</button><button type="button" onClick={screenshot} className="tool-btn justify-start"><Camera className="h-3.5 w-3.5" />截图</button><button type="button" onClick={() => rootRef.current?.requestFullscreen()} className="tool-btn justify-start"><Expand className="h-3.5 w-3.5" />全屏</button><button type="button" onClick={() => updateLayout({ activeIndicatorSummaryVisible: !layout.activeIndicatorSummaryVisible })} className="tool-btn justify-start">{layout.activeIndicatorSummaryVisible ? '隐藏' : '显示'}指标摘要</button></div>}

      {sourceStrategyIds.length > 0 && <div className="flex flex-wrap items-center gap-2 border-b border-emerald-400/20 bg-emerald-400/[0.05] px-3 py-2 text-[11px]" data-testid="strategy-chart-context"><span className="font-medium text-emerald-300">来源策略</span><span className="font-mono text-secondary">{sourceStrategyIds.join(' + ')}</span>{strategyContext?.asOf && <span className="text-muted">信号日 {strategyContext.asOf}</span>}{strategyContext?.sourceRunId && <span className="text-muted">批次 {strategyContext.sourceRunId.slice(0, 12)}</span>}<span className="text-muted">策略信号层已自动激活</span><Link to={strategyContext?.returnTo || `/screener?strategyId=${encodeURIComponent(sourceStrategyIds[0])}${strategyContext?.asOf ? `&asOf=${encodeURIComponent(strategyContext.asOf)}` : ''}`} className="ml-auto text-sky-300 hover:text-sky-200">返回策略面板</Link></div>}
      {!!layout.migrationWarnings?.length && <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/[0.06] px-3 py-1.5 text-[10px] text-amber-200" data-testid="chart-layout-migration-warning"><AlertTriangle className="h-3 w-3 shrink-0" /><span className="flex-1">配置迁移：{layout.migrationWarnings.join('；')}</span><button type="button" onClick={() => updateLayout({ migrationWarnings: [] })} aria-label="关闭配置迁移提示">关闭</button></div>}

      <ChartLayerManager
        open={layerManagerOpen}
        tab={layerManagerTab}
        layers={annotationLayers}
        enabledLayerIds={enabledLayerIds}
        chanlunVisible={chanlunConfig.visible}
        drawingCount={drawings.length}
        sourceStrategyIds={sourceStrategyIds}
        availableStrategyIds={knownStrategyIds}
        strategyScope={strategyScope}
        selectedStrategyIds={selectedStrategyIds}
        strategyEventTypes={new Set(strategyEventTypes)}
        annotationDensity={layout.annotationDensity}
        previewStrategies={previewStrategies}
        previewStrategyIds={previewStrategyIds}
        previewLoading={previewQuery.isFetching}
        previewError={previewQuery.isError ? (previewQuery.error instanceof Error ? previewQuery.error.message : '请求失败') : null}
        indicators={layout.indicators}
        templates={layout.templates}
        activeTemplateId={layout.activeTemplateId}
        activeTemplateDeviated={activeTemplateDeviated}
        actualWarmupBars={chartQuery.data?.meta.actual_warmup_bars ?? 0}
        indicatorReadiness={chartQuery.data?.meta.indicator_readiness ?? {}}
        focusedIndicatorId={focusedIndicatorId}
        summaryVisible={layout.activeIndicatorSummaryVisible}
        onUpdateIndicator={updateIndicatorConfig}
        onMoveIndicator={moveIndicator}
        onApplyTemplate={applyTemplate}
        onSaveTemplate={saveTemplate}
        onDeleteTemplate={deleteTemplate}
        onRenameTemplate={renameTemplate}
        onCopyTemplate={copyTemplate}
        onOverwriteTemplate={overwriteTemplate}
        onSummaryVisibilityChange={visible => updateLayout({ activeIndicatorSummaryVisible: visible })}
        onTabChange={setLayerManagerTab}
        onToggleLayer={toggleLayer}
        onToggleChanlun={() => updateIndicator('chanlun', item => ({ ...item, enabled: !item.enabled }))}
        onStrategyScopeChange={scope => { updateIndicator('strategies', item => ({ ...item, enabled: true, params: { ...item.params, strategyScope: scope } })); setSelectedStrategyIds(new Set()) }}
        onToggleStrategy={id => setSelectedStrategyIds(current => { const next = new Set(current.size === 0 ? knownStrategyIds : current); if (next.has(id)) next.delete(id); else next.add(id); return next })}
        onToggleStrategyEventType={eventType => updateIndicator('strategies', item => { const events = (item.params.eventTypes as string[] | undefined) ?? []; return { ...item, params: { ...item.params, eventTypes: events.includes(eventType) ? events.filter(value => value !== eventType) : [...events, eventType] } } })}
        onDensityChange={density => updateLayout({ annotationDensity: density })}
        onTogglePreviewStrategy={togglePreviewStrategy}
        onClose={() => setLayerManagerOpen(false)}
      />

      {layout.activeIndicatorSummaryVisible && (() => { const enabled = layout.indicators.filter(item => item.enabled).sort((a, b) => a.pane.order - b.pane.order); const shown = enabled.slice(0, 8); return <div className="flex flex-nowrap items-center gap-1.5 overflow-hidden border-b border-border/40 px-3 py-1.5" data-testid="active-indicator-summary">
        <span className="shrink-0 text-[10px] text-muted">已启用</span>{shown.map(item => { const definition = INDICATOR_REGISTRY.find(entry => entry.key === item.indicatorId); const params = Object.entries(item.params).filter(([, value]) => typeof value === 'number').slice(0, 3).map(([, value]) => value).join(','); return <button key={item.instanceId} type="button" draggable onDragStart={() => setDraggedIndicatorId(item.instanceId)} onDragOver={event => event.preventDefault()} onDrop={() => { if (draggedIndicatorId) reorderIndicator(draggedIndicatorId, item.instanceId); setDraggedIndicatorId(undefined) }} onClick={() => { setFocusedIndicatorId(item.indicatorId); setLayerManagerOpen(true); setLayerManagerTab(item.kind === 'technical' ? 'technical' : item.kind === 'structure' ? 'structure' : item.kind === 'strategy' ? 'strategy' : item.kind === 'event' ? 'event' : 'pattern') }} className={`shrink-0 rounded border px-2 py-1 text-[10px] ${item.kind === 'technical' ? 'border-sky-400/25 bg-sky-400/[0.07] text-sky-200' : 'border-cyan-400/25 bg-cyan-400/[0.06] text-cyan-200'}`}>{definition?.label ?? item.indicatorId}{params ? `(${params})` : ''}</button> })}{enabled.length > shown.length && <button type="button" onClick={() => setLayerManagerOpen(true)} className="shrink-0 rounded border border-border px-2 py-1 text-[10px] text-muted">+{enabled.length - shown.length}</button>}
      </div> })()}

      {chanlunConfig.showOfficial && officialResult.warning && <div className="border-b border-amber-400/20 bg-amber-400/[0.06] px-3 py-1.5 text-[10px] text-amber-200">{officialResult.warning}</div>}

      {chartQuery.data?.meta.warnings.length ? <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-[10px] text-amber-200"><AlertTriangle className="h-3 w-3 shrink-0" /><span className="flex-1">{chartQuery.data.meta.warnings.join('；')}</span>{layout.interval.endsWith('m') && chartQuery.data.asset_type !== 'index' && (!chartQuery.data.meta.complete || !chartQuery.data.meta.warmup_complete) && <button type="button" onClick={() => minuteBackfill.mutate()} disabled={minuteBackfill.isPending} className="tool-btn border-amber-300/30 text-amber-100 disabled:opacity-50">{minuteBackfill.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}补齐该股分钟历史与预热</button>}{!layout.interval.endsWith('m') && chartQuery.data.asset_type !== 'index' && (!chartQuery.data.meta.complete || !chartQuery.data.meta.warmup_complete) && <button type="button" onClick={() => dailyBackfill.mutate()} disabled={dailyBackfill.isPending} className="tool-btn border-amber-300/30 text-amber-100 disabled:opacity-50">{dailyBackfill.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}补齐至 {chartQuery.data.meta.required_fetch_start ?? chartQuery.data.meta.requested_start}</button>}</div> : null}
      {indicatorErrors.length > 0 && <div className="flex items-center gap-2 border-b border-danger/30 bg-danger/[0.06] px-3 py-1.5 text-[10px] text-danger"><span className="flex-1">指标计算失败：{indicatorErrors.join('、')}</span><button type="button" onClick={() => setIndicatorErrors([])}>关闭</button></div>}
      {drawMode !== 'none' && <div className="bg-sky-400/[0.06] px-3 py-1.5 text-[10px] text-sky-200">{drawMode === 'trend' ? (trendStart ? '点击第二根 K 线完成趋势线' : '依次点击两根 K 线绘制趋势线') : drawMode === 'horizontal' ? '点击 K 线放置水平线' : '点击 K 线添加文字'}</div>}

      {drawings.length > 0 && <div className="flex flex-wrap items-center gap-1 border-b border-border/40 px-3 py-1.5 text-[10px] text-muted"><span>画线：</span>{drawings.map((item, index) => <span key={item.id} className="inline-flex items-center gap-1 rounded border border-border/70 px-1.5 py-0.5"><span>{index + 1}.{item.kind === 'horizontal' ? '水平线' : item.kind === 'trend' ? '趋势线' : item.text || '文字'}</span><button type="button" aria-label={`删除画线 ${index + 1}`} onClick={() => commitDrawings(drawings.filter(drawing => drawing.id !== item.id))} className="hover:text-danger"><X className="h-2.5 w-2.5" /></button></span>)}<button type="button" onClick={() => commitDrawings([])} className="ml-1 inline-flex items-center gap-1 hover:text-danger"><Trash2 className="h-3 w-3" />全部清除</button></div>}

      {(historyLoading || historyNotice) && <div className="flex items-center gap-1.5 border-b border-border/40 px-3 py-1 text-[10px] text-muted" data-testid="chart-history-load-status">{historyLoading && <Loader2 className="h-3 w-3 animate-spin" />}<span>{historyLoading ? '正在加载更早 K 线…' : historyNotice}</span></div>}
      {rows.length === 0 ? <div className="grid min-h-[480px] place-items-center text-sm text-muted">当前组合没有可用 K 线；请补齐数据或缩短范围。</div> : <EChartsCandlestick key={historyContext} data={rows} analysisData={analysisRowsAtReplay} symbol={symbol} height={chartHeight} visibleBars={visibleBars} activeIndicators={enabledIndicators} paneHeights={paneHeights} indicatorStyles={indicatorStyles} markers={[...textMarkers, ...annotationVisuals.markers]} ranges={annotationVisuals.ranges} priceLines={[...(keyLevelsVisible ? levelLines(levels, activeLevelTypes) : []), ...userLines, ...annotationVisuals.lines]} chanlunData={chanlun} chanlunConfig={chanlunConfig} chanlunOfficial={officialResult.layer} onMarkerClick={evidenceId => setSelectedEvidence(annotationVisuals.evidence.get(evidenceId) ?? null)} onVisibleBarsChange={setVisibleAnnotationBars} onRequestOlder={requestOlderHistory} canLoadOlder={canLoadOlder} loadingOlder={historyLoading} onChartPointClick={onChartPoint} onPriceDoubleClick={(price) => commitDrawings([...drawings, { id: crypto.randomUUID(), kind: 'horizontal', price, adjustment: layout.adjustment, interval: layout.interval }])} testId="unified-stock-chart-instance" />}
      {rows.length > 0 && <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border/40 px-3 py-1.5 text-[10px] text-muted" data-testid="chart-history-navigator-hint"><span>已载入 <span className="font-mono text-secondary">{allRows[0]?.date.slice(0, 10)} — {allRows.at(-1)?.date.slice(0, 10)}</span> · 当前窗口 {currentRangeLabel}</span><span className="flex items-center gap-2"><span className="text-sky-300">拖动图表底部蓝色时间窗查看历史</span>{canLoadOlder ? <button type="button" onClick={() => requestOlderHistory(allRows[0]?.date ?? '')} disabled={historyLoading} className="tool-btn border-sky-400/30 text-sky-200 disabled:opacity-50">{historyLoading && <Loader2 className="h-3 w-3 animate-spin" />}加载更早</button> : <span className="text-secondary">{layout.range === 'all' ? '已载入全部本地历史' : '已到本地最早历史'}</span>}</span></div>}

      {replayIndex != null && allRows.length > 0 && <div className="sticky bottom-0 z-20 flex items-center gap-3 border-t border-border bg-surface/95 px-3 py-2"><Play className="h-3.5 w-3.5 text-amber-300" /><input aria-label="逐根回放" type="range" min="9" max={allRows.length - 1} value={replayIndex} onChange={event => setReplayIndex(Number(event.target.value))} className="flex-1" /><span className="w-28 font-mono text-[10px] text-muted">{allRows[replayIndex]?.date}</span><button type="button" onClick={() => setReplayIndex(index => Math.min(allRows.length - 1, (index ?? 0) + 1))} className="tool-btn">下一根</button><button type="button" onClick={() => setReplayIndex(null)} className="tool-btn">退出</button></div>}

      <EvidenceDrawer evidence={selectedEvidence} onClose={() => setSelectedEvidence(null)} />
    </div>
  )
}
