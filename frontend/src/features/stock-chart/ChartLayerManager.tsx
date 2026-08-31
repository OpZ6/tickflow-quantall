import { X } from 'lucide-react'

import type { AnnotationEvidence, ChartAnnotationLayer, ChartLayerCategory } from '@/lib/api'

type ManagerTab = 'technical' | 'chanlun' | 'pattern' | 'strategy' | 'event' | 'drawing'

const TABS: { id: ManagerTab; label: string }[] = [
  { id: 'technical', label: '技术指标' },
  { id: 'chanlun', label: '缠论' },
  { id: 'pattern', label: '形态' },
  { id: 'strategy', label: '策略' },
  { id: 'event', label: '事件' },
  { id: 'drawing', label: '画线' },
]

export function ChartLayerManager({
  open,
  tab,
  layers,
  enabledLayerIds,
  chanlunVisible,
  drawingCount,
  sourceStrategyIds,
  availableStrategyIds,
  strategyScope,
  selectedStrategyIds,
  strategyEventTypes,
  annotationDensity,
  onTabChange,
  onToggleLayer,
  onToggleChanlun,
  onOpenIndicators,
  onStrategyScopeChange,
  onToggleStrategy,
  onToggleStrategyEventType,
  onDensityChange,
  onClose,
}: {
  open: boolean
  tab: ManagerTab
  layers: ChartAnnotationLayer[]
  enabledLayerIds: Set<string>
  chanlunVisible: boolean
  drawingCount: number
  sourceStrategyIds: string[]
  availableStrategyIds: string[]
  strategyScope: 'source' | 'all'
  selectedStrategyIds: Set<string>
  strategyEventTypes: Set<string>
  annotationDensity: 'auto' | 'compact' | 'detailed'
  onTabChange: (tab: ManagerTab) => void
  onToggleLayer: (id: string) => void
  onToggleChanlun: () => void
  onOpenIndicators: () => void
  onStrategyScopeChange: (scope: 'source' | 'all') => void
  onToggleStrategy: (id: string) => void
  onToggleStrategyEventType: (eventType: string) => void
  onDensityChange: (density: 'auto' | 'compact' | 'detailed') => void
  onClose: () => void
}) {
  if (!open) return null
  const category = tab as ChartLayerCategory
  const categoryLayers = layers.filter(layer =>
    layer.category === category
    || (tab === 'strategy' && layer.id === 'plan.strategy')
    || (tab === 'technical' && layer.id === 'plan.key_levels'),
  )
  return (
    <div className="absolute left-3 top-12 z-40 w-[min(680px,calc(100%-1.5rem))] rounded-lg border border-border bg-surface/98 shadow-2xl backdrop-blur" data-testid="chart-layer-manager">
      <div className="flex items-center border-b border-border/60 px-2 pt-2">
        {TABS.map(item => (
          <button key={item.id} type="button" onClick={() => onTabChange(item.id)} className={`border-b-2 px-3 py-2 text-xs ${tab === item.id ? 'border-sky-400 text-sky-300' : 'border-transparent text-muted hover:text-foreground'}`}>
            {item.label}
          </button>
        ))}
        <button type="button" onClick={onClose} className="ml-auto p-2 text-muted hover:text-foreground" aria-label="关闭图层管理"><X className="h-4 w-4" /></button>
      </div>
      <div className="max-h-72 overflow-y-auto p-3 text-xs">
        {tab === 'technical' && <div className="space-y-2"><button type="button" onClick={onOpenIndicators} className="tool-btn">打开 20 个主图与 38 个副图指标目录</button>{categoryLayers.map(layer => <label key={layer.id} className="flex items-center gap-2 rounded border border-border/60 p-2"><input type="checkbox" checked={enabledLayerIds.has(layer.id)} onChange={() => onToggleLayer(layer.id)} />{layer.title}<span className="text-[10px] text-muted">统一图层 {layer.lines.length} 条</span></label>)}</div>}
        {tab === 'chanlun' && <label className="flex items-center gap-2"><input type="checkbox" checked={chanlunVisible} onChange={onToggleChanlun} />启用本地缠论结构层</label>}
        {tab === 'drawing' && <div className="text-secondary">当前上下文有 {drawingCount} 条画线；请使用顶部趋势线、水平线和文字工具编辑。</div>}
        {tab === 'strategy' && <div className="mb-3 space-y-3 rounded border border-border/60 bg-base/30 p-2">
          <div className="flex flex-wrap items-center gap-2"><span className="text-muted">范围</span><button type="button" data-testid="strategy-scope-source" onClick={() => onStrategyScopeChange('source')} className={`rounded px-2 py-1 ${strategyScope === 'source' ? 'bg-sky-400/15 text-sky-200' : 'text-muted'}`}>仅来源策略{sourceStrategyIds.length ? ` (${sourceStrategyIds.length})` : ''}</button><button type="button" data-testid="strategy-scope-all" onClick={() => onStrategyScopeChange('all')} className={`rounded px-2 py-1 ${strategyScope === 'all' ? 'bg-sky-400/15 text-sky-200' : 'text-muted'}`}>所有历史策略</button></div>
          {strategyScope === 'all' && availableStrategyIds.length > 0 && <div className="flex max-h-20 flex-wrap gap-1 overflow-y-auto">{availableStrategyIds.map(id => <label key={id} className="inline-flex items-center gap-1 rounded border border-border/50 px-1.5 py-1 font-mono text-[10px]"><input type="checkbox" checked={selectedStrategyIds.size === 0 || selectedStrategyIds.has(id)} onChange={() => onToggleStrategy(id)} />{id}</label>)}</div>}
          <div className="flex flex-wrap items-center gap-2"><span className="text-muted">事件</span>{([['candidate', '候选'], ['entry', '入场'], ['exit', '离场'], ['failure', '失效'], ['support', '守轴'], ['retrigger', '再触发']] as const).map(([id, label]) => <label key={id} className="inline-flex items-center gap-1"><input type="checkbox" checked={strategyEventTypes.has(id)} onChange={() => onToggleStrategyEventType(id)} />{label}</label>)}</div>
          <div className="flex items-center gap-2"><span className="text-muted">密度</span><button type="button" data-testid="annotation-density-auto" onClick={() => onDensityChange('auto')} className={annotationDensity === 'auto' ? 'text-sky-200' : 'text-muted'}>随缩放</button><button type="button" data-testid="annotation-density-compact" onClick={() => onDensityChange('compact')} className={annotationDensity === 'compact' ? 'text-sky-200' : 'text-muted'}>聚合</button><button type="button" data-testid="annotation-density-detailed" onClick={() => onDensityChange('detailed')} className={annotationDensity === 'detailed' ? 'text-sky-200' : 'text-muted'}>详细</button></div>
        </div>}
        {(['pattern', 'strategy', 'event'] as ManagerTab[]).includes(tab) && (
          <div className="grid gap-2 sm:grid-cols-2">
            {categoryLayers.map(layer => (
              <label key={layer.id} className="flex min-w-0 items-start gap-2 rounded border border-border/60 bg-base/40 p-2">
                <input type="checkbox" checked={enabledLayerIds.has(layer.id)} disabled={layer.status === 'unavailable'} onChange={() => onToggleLayer(layer.id)} />
                <span className="min-w-0"><span className="block text-foreground">{layer.title}</span><span className={`block truncate text-[10px] ${layer.status === 'error' ? 'text-danger' : 'text-muted'}`}>{layer.status === 'available' ? `${layer.markers.length + layer.lines.length + layer.zones.length + layer.segments.length} 个图形` : layer.warnings[0] ?? layer.status}</span></span>
              </label>
            ))}
            {categoryLayers.length === 0 && <span className="text-muted">当前没有可用图层。</span>}
          </div>
        )}
      </div>
    </div>
  )
}

export function EvidenceDrawer({ evidence, onClose }: { evidence: AnnotationEvidence | null; onClose: () => void }) {
  if (!evidence) return null
  return (
    <aside className="absolute bottom-0 right-0 top-0 z-50 w-[min(420px,92vw)] overflow-y-auto border-l border-border bg-surface/98 p-4 shadow-2xl backdrop-blur" data-testid="chart-evidence-drawer" aria-label="图表证据">
      <div className="flex items-start gap-3"><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold text-foreground">{evidence.title}</h3><p className="mt-1 text-xs leading-5 text-secondary">{evidence.summary}</p></div><button type="button" onClick={onClose} aria-label="关闭证据" className="p-1 text-muted hover:text-foreground"><X className="h-4 w-4" /></button></div>
      <div className="mt-4 rounded border border-amber-400/20 bg-amber-400/[0.06] p-2 text-[11px] leading-5 text-amber-100">策略信号是算法条件成立记录，形态是客观结构识别；二者均不代表真实账户成交。回测成交与实时监控触发会使用独立名称和标记。</div>
      {evidence.reason_codes.length > 0 && <section className="mt-4"><h4 className="text-[11px] font-semibold text-muted">命中条件</h4><div className="mt-2 flex flex-wrap gap-1">{evidence.reason_codes.map(code => <span key={code} className="rounded bg-sky-400/10 px-2 py-1 font-mono text-[10px] text-sky-200">{code}</span>)}</div></section>}
      {evidence.metrics.length > 0 && <section className="mt-4"><h4 className="text-[11px] font-semibold text-muted">指标证据</h4><div className="mt-2 divide-y divide-border/40 rounded border border-border/60">{evidence.metrics.map((metric, index) => <div key={`${metric.name}-${index}`} className="grid grid-cols-[1fr_auto] gap-3 px-2 py-1.5 text-[11px]"><span className="text-secondary">{metric.name}</span><span className={`font-mono ${metric.passed === false ? 'text-danger' : metric.passed === true ? 'text-emerald-300' : 'text-foreground'}`}>{String(metric.value ?? '—')}{metric.unit ? ` ${metric.unit}` : ''}{metric.threshold != null ? ` / 阈值 ${String(metric.threshold)}` : ''}</span></div>)}</div></section>}
      <section className="mt-4"><h4 className="text-[11px] font-semibold text-muted">版本与来源</h4><dl className="mt-2 space-y-1 text-[10px]">{Object.entries(evidence.metadata).map(([key, value]) => <div key={key} className="grid grid-cols-[120px_1fr] gap-2"><dt className="text-muted">{key}</dt><dd className="break-all font-mono text-secondary">{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl></section>
      {[...evidence.warnings].map(warning => <div key={warning} className="mt-3 text-xs text-danger">{warning}</div>)}
    </aside>
  )
}

export type { ManagerTab }
