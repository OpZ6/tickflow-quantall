import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Camera, ChevronDown, ChevronUp, Crosshair, Expand, Gauge, Layers3, Loader2, Play, Redo2, RefreshCw, Settings2, Trash2, Undo2, X } from 'lucide-react'

import {
  EChartsCandlestick, buildTimeIndex, mapChanlunData, toChanlunCandles,
  type ChartMarker, type ChartPriceLine, type OHLC,
} from '@/components/EChartsCandlestick'
import type { LevelType, PriceLevel } from '@/components/stock-analysis/AnalysisKChart'
import { api, type AnnotationEvidence, type ChartAdjustment, type ChartInterval, type ChartLayerCategory, type ChartRangeName } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { toast } from '@/components/Toast'
import { INDICATOR_REGISTRY, PANE_REGISTRY } from './indicatorRegistry'
import { IndicatorDrawer } from './IndicatorDrawer'
import { IndicatorParamEditor } from './IndicatorParamEditor'
import { ChartLayerManager, EvidenceDrawer, type ManagerTab } from './ChartLayerManager'
import { buildAnnotationVisuals } from './annotationLayers'
import { loadChartDrawings, loadChartLayout, saveChartDrawings, saveChartLayout } from './chartPersistence'
import type { StockChartLayout, UserDrawing } from './chartTypes'
import { rowsAtReplay } from './replay'

const INTERVALS: { value: ChartInterval; label: string }[] = [
  ['1m', '1分'], ['5m', '5分'], ['15m', '15分'], ['30m', '30分'], ['60m', '60分'],
  ['1d', '日K'], ['1w', '周K'], ['1mo', '月K'],
].map(([value, label]) => ({ value: value as ChartInterval, label }))
const RANGES: { value: ChartRangeName; label: string }[] = [
  ['1m', '1月'], ['3m', '3月'], ['6m', '半年'], ['1y', '1年'], ['3y', '3年'], ['5y', '5年'], ['all', '全部'], ['custom', '自定义'],
].map(([value, label]) => ({ value: value as ChartRangeName, label }))
const LEVEL_COLORS: Record<string, string> = {
  sr: '#F97316', pivot: '#8B5CF6', extreme: '#EAB308', boll: '#F97316',
  keltner_s: '#06B6D4', keltner_m: '#3B82F6', keltner_l: '#8B5CF6', atr_stop: '#EF4444',
  gap: '#EC4899', fib: '#14B8A6', round: '#94A3B8',
}
const PRESETS: Record<string, string[]> = {
  基础: ['vol'], 趋势: ['ema', 'supertrend', 'macd'], 震荡: ['boll', 'kdj', 'rsi'],
  缠论: ['macd'], 价位: ['vol'],
}
const LEVEL_LABELS: Record<string, string> = {
  sr: '支撑阻力', pivot: '枢轴', extreme: '极值', boll: '布林', keltner_s: '短 KC',
  keltner_m: '中 KC', keltner_l: '长 KC', atr_stop: 'ATR 止损', gap: '缺口', fib: '斐波那契', round: '整数关口',
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

const ALL_LAYER_CATEGORIES: ChartLayerCategory[] = ['pattern', 'strategy', 'event', 'plan']

export function UnifiedStockChart({ symbol, height = 680, strategyContext }: Props) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [layout, setLayout] = useState<StockChartLayout>(loadChartLayout)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [paramKey, setParamKey] = useState<string | null>(null)
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
  const [layerManagerTab, setLayerManagerTab] = useState<ManagerTab>('pattern')
  const [selectedEvidence, setSelectedEvidence] = useState<AnnotationEvidence | null>(null)
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<Set<string>>(new Set())
  const [knownStrategyIds, setKnownStrategyIds] = useState<string[]>([])
  const [visibleAnnotationBars, setVisibleAnnotationBars] = useState(60)

  const sourceStrategyIds = useMemo(() => {
    const ids = strategyContext?.strategyIds?.length ? strategyContext.strategyIds : strategyContext?.strategyId ? [strategyContext.strategyId] : []
    return [...new Set(ids)]
  }, [strategyContext?.strategyId, strategyContext?.strategyIds])
  const requestedStrategyIds = layout.strategyScope === 'source'
    ? sourceStrategyIds
    : [...selectedStrategyIds]

  const drawingKey = `${symbol}|${layout.interval}|${layout.adjustment}`
  const drawings = drawingsByContext[drawingKey] ?? []

  useEffect(() => saveChartLayout(layout), [layout])
  useEffect(() => {
    if (sourceStrategyIds.length === 0) return
    setLayout(current => ({
      ...current,
      strategyScope: 'source',
      enabledLayerIds: current.enabledLayerIds.includes('strategy.signals')
        ? current.enabledLayerIds
        : [...current.enabledLayerIds, 'strategy.signals', 'plan.strategy'],
    }))
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
  useEffect(() => { setKnownStrategyIds([]); setSelectedStrategyIds(new Set()) }, [symbol])
  useEffect(() => { setDrawingUndo([]); setDrawingRedo([]); setDrawMode('none') }, [drawingKey])

  const requestEnd = layout.range === 'custom' ? customEnd : strategyContext?.asOf ?? ''
  const layerKey = ALL_LAYER_CATEGORIES.join(',')
  const strategyKey = requestedStrategyIds.join(',')
  const exactSourceRunId = layout.strategyScope === 'source' ? strategyContext?.sourceRunId : undefined
  const exactParamsFingerprint = layout.strategyScope === 'source' ? strategyContext?.paramsFingerprint : undefined
  const chartQuery = useQuery({
    queryKey: QK.klineChart(symbol, '', layout.interval, layout.adjustment, layout.range, customStart, requestEnd, layerKey, strategyKey, exactSourceRunId ?? '', exactParamsFingerprint ?? ''),
    queryFn: () => api.klineChart({
      symbol, interval: layout.interval, adjustment: layout.adjustment, range: layout.range,
      ...(layout.range === 'custom' && customStart ? { startDate: customStart } : {}),
      ...(requestEnd ? { endDate: requestEnd } : {}),
      layers: ALL_LAYER_CATEGORIES,
      strategyIds: requestedStrategyIds,
      sourceRunId: exactSourceRunId,
      paramsFingerprint: exactParamsFingerprint,
    }),
    enabled: !!symbol && (layout.range !== 'custom' || !!customStart),
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
      toast(`分钟历史补齐完成：${result.rows} 行`, 'success')
      chartQuery.refetch()
    },
    onError: error => toast(error instanceof Error ? error.message : '分钟历史补齐失败', 'error'),
  })
  const allRows = (chartQuery.data?.rows ?? []) as OHLC[]
  useEffect(() => {
    if (chartQuery.data?.asset_type === 'index' && layout.adjustment !== 'none') {
      setLayout(current => ({ ...current, adjustment: 'none' }))
    }
  }, [chartQuery.data?.asset_type, layout.adjustment])
  const rows = rowsAtReplay(allRows, replayIndex)
  const chanlunQuery = useQuery({
    queryKey: ['stock-chart', 'chanlun', symbol, layout.interval, layout.adjustment, rows.length, rows.at(-1)?.date ?? ''],
    queryFn: () => api.chanlunAnalyze(toChanlunCandles(rows)),
    enabled: layout.chanlun.visible && rows.length >= 10,
    staleTime: 60_000,
  })
  const officialQuery = useQuery({
    queryKey: ['stock-chart', 'official', symbol, layout.interval],
    queryFn: () => api.chanlunOfficial(symbol.split('.')[0], layout.interval === '1d' ? 'D1' : layout.interval.toUpperCase(), Math.min(1000, rows.length)),
    enabled: layout.chanlun.visible && layout.chanlun.showOfficial && layout.interval === '1d', retry: false, staleTime: 300_000,
  })
  const timeIndex = useMemo(() => buildTimeIndex(rows), [rows])
  const chanlun = useMemo(() => {
    const mapped = mapChanlunData(chanlunQuery.data, timeIndex)
    if (!mapped || layout.chanlun.bspMode === 'all') return mapped
    // 本地 BSP v5 中 1/1p 是背驰直接产生的一类点，2/2s/3a 是后续确认型点。
    return { ...mapped, bsp: mapped.bsp.filter(point => point.type.startsWith('1')) }
  }, [chanlunQuery.data, timeIndex, layout.chanlun.bspMode])
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

  const annotationLayers = chartQuery.data?.annotation_layers ?? []
  const availableStrategyIds = useMemo(() => [...new Set(annotationLayers
    .filter(layer => layer.category === 'strategy')
    .flatMap(layer => layer.evidence.flatMap(item => {
      const ids = Array.isArray(item.metadata.strategy_ids) ? item.metadata.strategy_ids.map(String) : []
      const id = item.metadata.strategy_id
      return id ? [String(id), ...ids] : ids
    })))].sort(), [annotationLayers])
  useEffect(() => {
    if (availableStrategyIds.length === 0) return
    setKnownStrategyIds(current => [...new Set([...current, ...availableStrategyIds])].sort())
  }, [availableStrategyIds])
  const enabledLayerIds = useMemo(() => new Set(layout.enabledLayerIds), [layout.enabledLayerIds])
  const replayDate = replayIndex == null ? undefined : rows.at(-1)?.date
  const effectiveAnnotationDensity = layout.annotationDensity === 'auto'
    ? (visibleAnnotationBars > 80 ? 'compact' : 'detailed')
    : layout.annotationDensity
  const annotationVisuals = useMemo(
    () => buildAnnotationVisuals(annotationLayers, enabledLayerIds, replayDate, {
      strategyIds: layout.strategyScope === 'all' ? selectedStrategyIds : new Set(sourceStrategyIds),
      strategyEventTypes: new Set(layout.strategyEventTypes),
      density: effectiveAnnotationDensity,
    }),
    [annotationLayers, enabledLayerIds, replayDate, layout.strategyScope, layout.strategyEventTypes, effectiveAnnotationDensity, selectedStrategyIds, sourceStrategyIds],
  )

  const levels = (chartQuery.data?.levels ?? {}) as Record<LevelType, PriceLevel[]>
  const userLines: ChartPriceLine[] = drawings
    .filter(item => item.adjustment === layout.adjustment && item.interval === layout.interval && item.kind !== 'text')
    .map(item => item.kind === 'horizontal'
      ? { value: item.price!, label: '手动画线', color: '#38bdf8' }
      : { value: item.start!.price, endValue: item.end!.price, start: item.start!.date, end: item.end!.date, label: '趋势线', color: '#38bdf8' })
  const textMarkers: ChartMarker[] = drawings.filter(item => item.kind === 'text' && item.start).map(item => ({ date: item.start!.date, kind: 'neutral', label: item.text, above: true, color: '#38bdf8' }))
  const enabledIndicators = layout.activeIndicators.filter(key => !layout.collapsedIndicators.includes(key))
  const visibleBars = ({ '1m': 240, '5m': 240, '15m': 200, '30m': 180, '60m': 160, '1d': 250, '1w': 156, '1mo': 120 } as const)[layout.interval]
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
  const toggleIndicator = (key: string) => updateLayout({ activeIndicators: layout.activeIndicators.includes(key) ? layout.activeIndicators.filter(item => item !== key) : [...layout.activeIndicators, key] })
  const toggleLayer = (id: string) => updateLayout({ enabledLayerIds: enabledLayerIds.has(id) ? layout.enabledLayerIds.filter(item => item !== id) : [...layout.enabledLayerIds, id] })
  const movePane = (key: string, direction: -1 | 1) => {
    const next = [...layout.activeIndicators]
    const index = next.indexOf(key)
    const target = index + direction
    if (index < 0 || target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    updateLayout({ activeIndicators: next })
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
      <div className="flex flex-wrap items-center gap-2 border-b border-border/50 px-3 py-2 text-xs">
        <select aria-label="复权" value={layout.adjustment} disabled={chartQuery.data?.asset_type === 'index'} onChange={event => updateLayout({ adjustment: event.target.value as ChartAdjustment })} className="rounded border border-border bg-base px-2 py-1.5 text-secondary"><option value="none">不复权</option><option value="qfq">前复权</option><option value="hfq">后复权</option></select>
        <select aria-label="周期" value={layout.interval} onChange={event => updateLayout({ interval: event.target.value as ChartInterval })} className="rounded border border-border bg-base px-2 py-1.5 text-secondary">{INTERVALS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        <select aria-label="范围" value={layout.range} onChange={event => updateLayout({ range: event.target.value as ChartRangeName })} className="rounded border border-border bg-base px-2 py-1.5 text-secondary">{RANGES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
        {layout.range === 'custom' && <><input aria-label="开始日期" type="date" value={customStart} onChange={event => setCustomStart(event.target.value)} className="rounded border border-border bg-base px-2 py-1 text-secondary" /><input aria-label="结束日期" type="date" value={customEnd} onChange={event => setCustomEnd(event.target.value)} className="rounded border border-border bg-base px-2 py-1 text-secondary" /></>}
        <button type="button" onClick={() => chartQuery.refetch()} className="tool-btn"><RefreshCw className={`h-3.5 w-3.5 ${chartQuery.isFetching ? 'animate-spin' : ''}`} />刷新</button>
        <button type="button" onClick={() => setDrawerOpen(true)} className="tool-btn"><Settings2 className="h-3.5 w-3.5" />指标管理</button>
        <button type="button" onClick={() => setLayerManagerOpen(value => !value)} className={`tool-btn ${layerManagerOpen ? 'text-sky-300' : ''}`}><Layers3 className="h-3.5 w-3.5" />图层管理</button>
        <button type="button" onClick={() => updateLayout({ keyLevelsVisible: !layout.keyLevelsVisible })} className={`tool-btn ${layout.keyLevelsVisible ? 'text-sky-300' : ''}`}><Gauge className="h-3.5 w-3.5" />关键价位</button>
        <button type="button" onClick={() => updateLayout({ chanlun: { ...layout.chanlun, visible: !layout.chanlun.visible } })} className={`tool-btn ${layout.chanlun.visible ? 'text-cyan-300' : ''}`}><Layers3 className="h-3.5 w-3.5" />缠论</button>
        <button type="button" onClick={() => setDrawMode(drawMode === 'trend' ? 'none' : 'trend')} className={`tool-btn ${drawMode === 'trend' ? 'text-sky-300' : ''}`}><Crosshair className="h-3.5 w-3.5" />趋势线</button>
        <button type="button" onClick={() => setDrawMode(drawMode === 'horizontal' ? 'none' : 'horizontal')} className={`tool-btn ${drawMode === 'horizontal' ? 'text-sky-300' : ''}`}>水平线</button>
        <button type="button" onClick={() => setDrawMode('text')} className="tool-btn">文字</button>
        <button type="button" onClick={undoDrawing} disabled={!drawingUndo.length} className="tool-btn disabled:opacity-30" aria-label="撤销画线"><Undo2 className="h-3.5 w-3.5" /></button>
        <button type="button" onClick={redoDrawing} disabled={!drawingRedo.length} className="tool-btn disabled:opacity-30" aria-label="重做画线"><Redo2 className="h-3.5 w-3.5" /></button>
        <button type="button" onClick={() => setReplayIndex(replayIndex == null ? Math.max(0, allRows.length - 30) : null)} className={`tool-btn ${replayIndex != null ? 'text-amber-300' : ''}`}><Play className="h-3.5 w-3.5" />回放</button>
        <button type="button" onClick={screenshot} className="tool-btn"><Camera className="h-3.5 w-3.5" />截图</button>
        <button type="button" onClick={() => rootRef.current?.requestFullscreen()} className="tool-btn"><Expand className="h-3.5 w-3.5" />全屏</button>
      </div>

      {sourceStrategyIds.length > 0 && <div className="flex flex-wrap items-center gap-2 border-b border-emerald-400/20 bg-emerald-400/[0.05] px-3 py-2 text-[11px]" data-testid="strategy-chart-context"><span className="font-medium text-emerald-300">来源策略</span><span className="font-mono text-secondary">{sourceStrategyIds.join(' + ')}</span>{strategyContext?.asOf && <span className="text-muted">信号日 {strategyContext.asOf}</span>}{strategyContext?.sourceRunId && <span className="text-muted">批次 {strategyContext.sourceRunId.slice(0, 12)}</span>}<span className="text-muted">策略信号层已自动激活</span><Link to={strategyContext?.returnTo || `/screener?strategyId=${encodeURIComponent(sourceStrategyIds[0])}${strategyContext?.asOf ? `&asOf=${encodeURIComponent(strategyContext.asOf)}` : ''}`} className="ml-auto text-sky-300 hover:text-sky-200">返回策略面板</Link></div>}

      <ChartLayerManager open={layerManagerOpen} tab={layerManagerTab} layers={annotationLayers} enabledLayerIds={enabledLayerIds} chanlunVisible={layout.chanlun.visible} drawingCount={drawings.length} sourceStrategyIds={sourceStrategyIds} availableStrategyIds={knownStrategyIds} strategyScope={layout.strategyScope} selectedStrategyIds={selectedStrategyIds} strategyEventTypes={new Set(layout.strategyEventTypes)} annotationDensity={layout.annotationDensity} onTabChange={setLayerManagerTab} onToggleLayer={toggleLayer} onToggleChanlun={() => updateLayout({ chanlun: { ...layout.chanlun, visible: !layout.chanlun.visible } })} onOpenIndicators={() => { setDrawerOpen(true); setLayerManagerOpen(false) }} onStrategyScopeChange={scope => { updateLayout({ strategyScope: scope }); setSelectedStrategyIds(new Set()) }} onToggleStrategy={id => setSelectedStrategyIds(current => { const next = new Set(current.size === 0 ? knownStrategyIds : current); if (next.has(id)) next.delete(id); else next.add(id); return next })} onToggleStrategyEventType={eventType => updateLayout({ strategyEventTypes: layout.strategyEventTypes.includes(eventType) ? layout.strategyEventTypes.filter(item => item !== eventType) : [...layout.strategyEventTypes, eventType] })} onDensityChange={density => updateLayout({ annotationDensity: density })} onClose={() => setLayerManagerOpen(false)} />

      <div className="flex flex-wrap items-center gap-1.5 border-b border-border/40 px-3 py-2">
        {Object.entries(PRESETS).map(([name, indicators]) => <button key={name} type="button" onClick={() => updateLayout({ activeIndicators: indicators, chanlun: { ...layout.chanlun, visible: name === '缠论' }, keyLevelsVisible: name === '价位' })} className="rounded border border-border/60 bg-base/40 px-2 py-1 text-[10px] text-muted hover:text-foreground">{name}</button>)}
        {Object.entries(layout.customPresets).map(([name, indicators]) => <button key={`custom-${name}`} type="button" onClick={() => updateLayout({ activeIndicators: indicators })} className="rounded border border-violet-400/30 bg-violet-400/[0.06] px-2 py-1 text-[10px] text-violet-200">{name}</button>)}
        <button type="button" onClick={() => { const name = window.prompt('自定义预设名称')?.trim(); if (name) updateLayout({ customPresets: { ...layout.customPresets, [name]: [...layout.activeIndicators] } }) }} className="rounded border border-border/60 bg-base/40 px-2 py-1 text-[10px] text-muted hover:text-foreground">+ 保存预设</button>
        <span className="mx-1 h-4 w-px bg-border" />
        {layout.activeIndicators.map(key => {
          const definition = INDICATOR_REGISTRY.find(item => item.key === key)
          if (!definition) return null
          const collapsed = layout.collapsedIndicators.includes(key)
          return <span key={key} className="inline-flex items-center rounded border border-sky-400/25 bg-sky-400/[0.07] text-[10px] text-sky-200"><button type="button" onClick={() => setParamKey(definition.paramSchema.length ? key : null)} className="px-2 py-1">{definition.label}</button>{definition.category === 'pane' && <><button type="button" onClick={() => movePane(key, -1)} className="p-1 text-muted hover:text-foreground"><ChevronUp className="h-3 w-3" /></button><button type="button" onClick={() => movePane(key, 1)} className="p-1 text-muted hover:text-foreground"><ChevronDown className="h-3 w-3" /></button><button type="button" onClick={() => updateLayout({ collapsedIndicators: collapsed ? layout.collapsedIndicators.filter(item => item !== key) : [...layout.collapsedIndicators, key] })} className="p-1 text-muted hover:text-foreground">{collapsed ? '+' : '−'}</button><input aria-label={`${definition.label}高度`} type="range" min="56" max="240" value={layout.paneHeights[key] ?? definition.defaultHeight ?? 96} onChange={event => updateLayout({ paneHeights: { ...layout.paneHeights, [key]: Number(event.target.value) } })} className="w-14" /></>}<button type="button" onClick={() => toggleIndicator(key)} className="p-1 text-muted hover:text-danger"><X className="h-3 w-3" /></button></span>
        })}
      </div>

      {layout.chanlun.visible && <div className="flex flex-wrap items-center gap-3 border-b border-border/40 bg-cyan-400/[0.03] px-3 py-2 text-[10px] text-muted">
        {([['showMerged', '包含处理'], ['showFenxing', '分型'], ['showBi', '笔'], ['showSegments', '线段'], ['showZhongshu', '中枢'], ['showBsp', '买卖点']] as const).map(([key, label]) => <label key={key} className="inline-flex items-center gap-1"><input type="checkbox" checked={layout.chanlun[key] !== false} onChange={event => updateLayout({ chanlun: { ...layout.chanlun, [key]: event.target.checked } })} />{label}</label>)}
        <select value={layout.chanlun.bspMode} onChange={event => updateLayout({ chanlun: { ...layout.chanlun, bspMode: event.target.value as 'all' | 'divergence' } })} className="rounded border border-border bg-base px-1.5 py-1"><option value="all">全部买卖点</option><option value="divergence">仅背驰</option></select>
        <label className="inline-flex items-center gap-1"><input type="checkbox" checked={layout.chanlun.showOfficial} disabled={layout.interval !== '1d'} onChange={event => updateLayout({ chanlun: { ...layout.chanlun, showOfficial: event.target.checked } })} />官方对照</label>
        <span>默认本地算法 {chanlunQuery.data?._meta ? `${chanlunQuery.data._meta.version} · 指纹 ${chanlunQuery.data._meta.data_fingerprint} · ${chanlunQuery.data._meta.final_confirmed ? '末笔已确认' : '末笔未确认'}` : ''} · 最后一笔/段可能随新 K 线修订</span>
      </div>}

      {layout.keyLevelsVisible && <div className="flex flex-wrap items-center gap-2 border-b border-border/40 bg-orange-400/[0.025] px-3 py-1.5 text-[10px] text-muted"><span>关键价位：</span>{Object.entries(LEVEL_LABELS).map(([key, label]) => <label key={key} className="inline-flex items-center gap-1"><input type="checkbox" checked={layout.activeLevelTypes.includes(key)} onChange={event => updateLayout({ activeLevelTypes: event.target.checked ? [...layout.activeLevelTypes, key] : layout.activeLevelTypes.filter(item => item !== key) })} />{label}</label>)}</div>}

      {layout.chanlun.showOfficial && officialResult.warning && <div className="border-b border-amber-400/20 bg-amber-400/[0.06] px-3 py-1.5 text-[10px] text-amber-200">{officialResult.warning}</div>}

      {chartQuery.data?.meta.warnings.length ? <div className="flex items-center gap-2 border-b border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-[10px] text-amber-200"><AlertTriangle className="h-3 w-3 shrink-0" /><span className="flex-1">{chartQuery.data.meta.warnings.join('；')}</span>{layout.interval.endsWith('m') && chartQuery.data.asset_type !== 'index' && !chartQuery.data.meta.complete && <button type="button" onClick={() => minuteBackfill.mutate()} disabled={minuteBackfill.isPending} className="tool-btn border-amber-300/30 text-amber-100 disabled:opacity-50">{minuteBackfill.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}补齐该股分钟历史</button>}</div> : null}
      {indicatorErrors.length > 0 && <div className="flex items-center gap-2 border-b border-danger/30 bg-danger/[0.06] px-3 py-1.5 text-[10px] text-danger"><span className="flex-1">指标计算失败：{indicatorErrors.join('、')}</span><button type="button" onClick={() => setIndicatorErrors([])}>关闭</button></div>}
      {drawMode !== 'none' && <div className="bg-sky-400/[0.06] px-3 py-1.5 text-[10px] text-sky-200">{drawMode === 'trend' ? (trendStart ? '点击第二根 K 线完成趋势线' : '依次点击两根 K 线绘制趋势线') : drawMode === 'horizontal' ? '点击 K 线放置水平线' : '点击 K 线添加文字'}</div>}

      {drawings.length > 0 && <div className="flex flex-wrap items-center gap-1 border-b border-border/40 px-3 py-1.5 text-[10px] text-muted"><span>画线：</span>{drawings.map((item, index) => <span key={item.id} className="inline-flex items-center gap-1 rounded border border-border/70 px-1.5 py-0.5"><span>{index + 1}.{item.kind === 'horizontal' ? '水平线' : item.kind === 'trend' ? '趋势线' : item.text || '文字'}</span><button type="button" aria-label={`删除画线 ${index + 1}`} onClick={() => commitDrawings(drawings.filter(drawing => drawing.id !== item.id))} className="hover:text-danger"><X className="h-2.5 w-2.5" /></button></span>)}<button type="button" onClick={() => commitDrawings([])} className="ml-1 inline-flex items-center gap-1 hover:text-danger"><Trash2 className="h-3 w-3" />全部清除</button></div>}

      {rows.length === 0 ? <div className="grid min-h-[480px] place-items-center text-sm text-muted">当前组合没有可用 K 线；请补齐数据或缩短范围。</div> : <EChartsCandlestick data={rows} symbol={symbol} height={chartHeight} visibleBars={visibleBars} activeIndicators={enabledIndicators} paneHeights={layout.paneHeights} markers={[...textMarkers, ...annotationVisuals.markers]} ranges={annotationVisuals.ranges} priceLines={[...(layout.keyLevelsVisible ? levelLines(levels, layout.activeLevelTypes) : []), ...userLines, ...annotationVisuals.lines]} chanlunData={chanlun} chanlunConfig={layout.chanlun} chanlunOfficial={officialResult.layer} onMarkerClick={evidenceId => setSelectedEvidence(annotationVisuals.evidence.get(evidenceId) ?? null)} onVisibleBarsChange={setVisibleAnnotationBars} onChartPointClick={onChartPoint} onPriceDoubleClick={(price) => commitDrawings([...drawings, { id: crypto.randomUUID(), kind: 'horizontal', price, adjustment: layout.adjustment, interval: layout.interval }])} testId="unified-stock-chart-instance" />}

      {replayIndex != null && allRows.length > 0 && <div className="sticky bottom-0 z-20 flex items-center gap-3 border-t border-border bg-surface/95 px-3 py-2"><Play className="h-3.5 w-3.5 text-amber-300" /><input aria-label="逐根回放" type="range" min="9" max={allRows.length - 1} value={replayIndex} onChange={event => setReplayIndex(Number(event.target.value))} className="flex-1" /><span className="w-28 font-mono text-[10px] text-muted">{allRows[replayIndex]?.date}</span><button type="button" onClick={() => setReplayIndex(index => Math.min(allRows.length - 1, (index ?? 0) + 1))} className="tool-btn">下一根</button><button type="button" onClick={() => setReplayIndex(null)} className="tool-btn">退出</button></div>}

      <IndicatorDrawer open={drawerOpen} active={layout.activeIndicators} onToggle={toggleIndicator} onConfigure={setParamKey} onClose={() => setDrawerOpen(false)} />
      <IndicatorParamEditor indicatorKey={paramKey} onChanged={() => setLayout(current => ({ ...current, activeIndicators: [...current.activeIndicators] }))} onClose={() => setParamKey(null)} />
      <EvidenceDrawer evidence={selectedEvidence} onClose={() => setSelectedEvidence(null)} />
    </div>
  )
}
