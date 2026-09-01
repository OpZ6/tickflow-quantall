import { ArrowDown, ArrowUp, Search, Settings2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import type { AnnotationEvidence, ChartAnnotationLayer, ChartLayerCategory, StrategyDetail } from '@/lib/api'
import { INDICATOR_REGISTRY } from './indicatorRegistry'
import type { ChartIndicatorInstance, ChartIndicatorTemplate } from './chartTypes'

type ManagerTab = 'technical' | 'structure' | 'pattern' | 'strategy' | 'event' | 'templates' | 'drawing'

const TABS: { id: ManagerTab; label: string }[] = [
  { id: 'technical', label: '技术指标' },
  { id: 'structure', label: '结构指标' },
  { id: 'pattern', label: '形态' },
  { id: 'strategy', label: '策略' },
  { id: 'event', label: '事件' },
  { id: 'templates', label: '模板' },
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
  previewStrategies,
  previewStrategyIds,
  previewLoading,
  previewError,
  indicators,
  templates,
  activeTemplateId,
  activeTemplateDeviated,
  actualWarmupBars,
  indicatorReadiness,
  focusedIndicatorId,
  summaryVisible,
  onUpdateIndicator,
  onMoveIndicator,
  onApplyTemplate,
  onSaveTemplate,
  onDeleteTemplate,
  onRenameTemplate,
  onCopyTemplate,
  onOverwriteTemplate,
  onSummaryVisibilityChange,
  onTabChange,
  onToggleLayer,
  onToggleChanlun,
  onStrategyScopeChange,
  onToggleStrategy,
  onToggleStrategyEventType,
  onDensityChange,
  onTogglePreviewStrategy,
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
  previewStrategies: StrategyDetail[]
  previewStrategyIds: Set<string>
  previewLoading: boolean
  previewError: string | null
  indicators: ChartIndicatorInstance[]
  templates: ChartIndicatorTemplate[]
  activeTemplateId?: string
  activeTemplateDeviated: boolean
  actualWarmupBars: number
  indicatorReadiness: Record<string, { required_warmup_bars: number; actual_warmup_bars: number; status: 'ready' | 'partial' }>
  focusedIndicatorId?: string
  summaryVisible: boolean
  onUpdateIndicator: (indicatorId: string, change: Partial<ChartIndicatorInstance>) => void
  onMoveIndicator: (instanceId: string, direction: -1 | 1) => void
  onApplyTemplate: (template: ChartIndicatorTemplate) => void
  onSaveTemplate: () => void
  onDeleteTemplate: (template: ChartIndicatorTemplate) => void
  onRenameTemplate: (template: ChartIndicatorTemplate) => void
  onCopyTemplate: (template: ChartIndicatorTemplate) => void
  onOverwriteTemplate: (template: ChartIndicatorTemplate) => void
  onSummaryVisibilityChange: (visible: boolean) => void
  onTabChange: (tab: ManagerTab) => void
  onToggleLayer: (id: string) => void
  onToggleChanlun: () => void
  onStrategyScopeChange: (scope: 'source' | 'all') => void
  onToggleStrategy: (id: string) => void
  onToggleStrategyEventType: (eventType: string) => void
  onDensityChange: (density: 'auto' | 'compact' | 'detailed') => void
  onTogglePreviewStrategy: (strategyId: string) => void
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showEnabledOnly, setShowEnabledOnly] = useState(false)
  useEffect(() => { if (open && focusedIndicatorId) setExpandedId(focusedIndicatorId) }, [focusedIndicatorId, open])
  const technicalDefinitions = useMemo(() => INDICATOR_REGISTRY.filter(item => item.category !== 'structure' && `${item.label} ${item.key} ${item.group}`.toLowerCase().includes(search.trim().toLowerCase()) && (!showEnabledOnly || indicators.some(instance => instance.indicatorId === item.key && instance.enabled))), [indicators, search, showEnabledOnly])
  if (!open) return null
  const category = tab as ChartLayerCategory
  const categoryLayers = layers.filter(layer =>
    layer.category === category
    || (tab === 'strategy' && layer.id === 'plan.strategy')
    || (tab === 'technical' && layer.id === 'plan.key_levels'),
  )
  return (
    <aside className="absolute inset-y-0 right-0 z-40 flex w-[min(480px,94vw)] flex-col border-l border-border bg-surface/98 shadow-2xl backdrop-blur" data-testid="chart-indicator-center" aria-label="指标中心">
      <div className="flex items-center overflow-x-auto border-b border-border/60 px-2 pt-2">
        <strong className="mr-2 shrink-0 pb-2 text-sm text-foreground">指标中心</strong>
        {TABS.map(item => (
          <button key={item.id} type="button" onClick={() => onTabChange(item.id)} className={`shrink-0 border-b-2 px-2.5 py-2 text-xs ${tab === item.id ? 'border-sky-400 text-sky-300' : 'border-transparent text-muted hover:text-foreground'}`}>
            {item.label}
          </button>
        ))}
        <button type="button" onClick={onClose} className="ml-auto p-2 text-muted hover:text-foreground" aria-label="关闭指标中心"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 text-xs">
        {tab === 'technical' && <div className="space-y-3">
          <div className="flex items-center gap-2"><label className="flex min-w-0 flex-1 items-center gap-2 rounded border border-border bg-base px-2 py-2"><Search className="h-3.5 w-3.5 text-muted" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索主图、副图或分类" className="min-w-0 flex-1 bg-transparent text-xs outline-none" /></label><label className="flex shrink-0 items-center gap-1 text-[10px] text-muted"><input type="checkbox" checked={showEnabledOnly} onChange={event => setShowEnabledOnly(event.target.checked)} />仅已启用</label></div>
          {technicalDefinitions.map(definition => {
            const instance = indicators.find(item => item.indicatorId === definition.key)
            const enabled = !!instance?.enabled
            const expanded = expandedId === definition.key
            return <section key={definition.key} className={`rounded border ${enabled ? 'border-sky-400/30 bg-sky-400/[0.05]' : 'border-border/60 bg-base/30'}`}>
              <div className="flex items-center gap-2 p-2"><input type="checkbox" checked={enabled} onChange={() => onUpdateIndicator(definition.key, { enabled: !enabled })} /><button type="button" onClick={() => setExpandedId(expanded ? null : definition.key)} className="min-w-0 flex-1 text-left"><span className="font-medium text-foreground">{definition.label}</span><span className="ml-2 text-[10px] text-muted">{definition.category === 'pane' ? '副图' : '主图'} · {definition.group} · 预热 {definition.warmupBars}</span></button><Settings2 className="h-3.5 w-3.5 text-muted" /></div>
              {expanded && instance && <div className="space-y-2 border-t border-border/50 p-2">
                {(() => { const readiness = indicatorReadiness[definition.key]; const required = readiness?.required_warmup_bars ?? definition.warmupBars; const actual = readiness?.actual_warmup_bars ?? actualWarmupBars; const ready = readiness?.status === 'ready' || actual >= required; return <div className="grid grid-cols-2 gap-2 rounded bg-base/60 p-2 text-[10px] text-muted"><span>位置：{definition.placement === 'sub' ? '副图' : '主图'}</span><span>计算：{definition.calculation === 'client' ? '本地' : definition.calculation === 'server' ? '服务端' : '数据仓库'}</span><span>周期：{definition.supportedIntervals.join(' / ')}</span><span className={ready ? 'text-emerald-300' : 'text-amber-300'}>预热：{Math.min(actual, required)}/{required}{ready ? ' 完整' : ' 部分'}</span></div> })()}
                {definition.paramSchema.map(param => <label key={param.key} className="grid grid-cols-[1fr_110px] items-center gap-2"><span className="text-secondary">{param.label}</span><input type="number" min={param.min} max={param.max} step={param.step} value={Number(instance.params[param.key] ?? param.defaultValue)} onChange={event => onUpdateIndicator(definition.key, { params: { ...instance.params, [param.key]: Number(event.target.value) } })} className="rounded border border-border bg-base px-2 py-1 font-mono" /></label>)}
                <label className="grid grid-cols-[1fr_110px] items-center gap-2"><span className="text-secondary">统一颜色</span><span className="flex items-center gap-2"><input type="color" value={String(instance.style.color ?? '#38bdf8')} onChange={event => onUpdateIndicator(definition.key, { style: { ...instance.style, color: event.target.value } })} className="h-7 w-10 rounded border border-border bg-base" /><button type="button" onClick={() => onUpdateIndicator(definition.key, { style: {} })} className="text-[10px] text-muted">默认</button></span></label>
                {definition.category === 'pane' && <><label className="grid grid-cols-[1fr_1fr] items-center gap-2"><span>副图高度</span><input type="range" min="56" max="240" value={instance.pane.height ?? definition.defaultHeight ?? 96} onChange={event => onUpdateIndicator(definition.key, { pane: { ...instance.pane, height: Number(event.target.value) } })} /></label><div className="flex items-center gap-2"><span className="mr-auto text-secondary">副图顺序</span><button type="button" onClick={() => onMoveIndicator(instance.instanceId, -1)} className="tool-btn" aria-label={`上移 ${definition.label}`}><ArrowUp className="h-3 w-3" />上移</button><button type="button" onClick={() => onMoveIndicator(instance.instanceId, 1)} className="tool-btn" aria-label={`下移 ${definition.label}`}><ArrowDown className="h-3 w-3" />下移</button></div><label className="flex items-center gap-2"><input type="checkbox" checked={!!instance.pane.collapsed} onChange={() => onUpdateIndicator(definition.key, { pane: { ...instance.pane, collapsed: !instance.pane.collapsed } })} />折叠副图</label></>}
              </div>}
            </section>
          })}
        </div>}
        {tab === 'structure' && <div className="space-y-3">
          {(() => { const item = indicators.find(value => value.indicatorId === 'chanlun'); if (!item) return null; const readiness=indicatorReadiness.chanlun; return <section className="rounded border border-cyan-400/25 p-3"><label className="flex items-center gap-2 font-medium"><input type="checkbox" checked={chanlunVisible} onChange={onToggleChanlun} />缠论结构指标<span className={`ml-auto text-[10px] ${readiness?.status === 'partial' ? 'text-amber-300' : 'text-emerald-300'}`}>{readiness ? `${readiness.actual_warmup_bars}/${readiness.required_warmup_bars} ${readiness.status === 'ready' ? '完整' : '部分'}` : '启用后检查预热'}</span></label><div className="mt-3 grid grid-cols-2 gap-2">{([['showMerged','包含处理'],['showFenxing','分型'],['showBi','笔'],['showSegments','线段'],['showZhongshu','中枢'],['showBsp','买卖点']] as const).map(([key,label]) => <label key={key} className="flex items-center gap-1"><input type="checkbox" checked={item.params[key] !== false} onChange={event => onUpdateIndicator('chanlun',{ params:{...item.params,[key]:event.target.checked} })} />{label}</label>)}</div><label className="mt-3 grid grid-cols-[1fr_160px] items-center"><span>买卖点模式</span><select value={String(item.params.bspMode ?? 'all')} onChange={event => onUpdateIndicator('chanlun',{params:{...item.params,bspMode:event.target.value}})} className="rounded border border-border bg-base px-2 py-1"><option value="all">全部买卖点</option><option value="divergence">仅背驰</option></select></label><label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={!!item.params.showOfficial} onChange={event => onUpdateIndicator('chanlun',{params:{...item.params,showOfficial:event.target.checked}})} />官方对照</label></section> })()}
          {(() => { const item = indicators.find(value => value.indicatorId === 'key-levels'); if (!item) return null; const selected=(item.params.activeLevelTypes as string[]|undefined)??[]; const readiness=indicatorReadiness['key-levels']; const labels:Record<string,string>={sr:'支撑阻力',pivot:'枢轴',extreme:'极值',boll:'布林',keltner_s:'短KC',keltner_m:'中KC',keltner_l:'长KC',atr_stop:'ATR止损',gap:'缺口',fib:'斐波那契',round:'整数关口'}; return <section className="rounded border border-orange-400/25 p-3"><label className="flex items-center gap-2 font-medium"><input type="checkbox" checked={item.enabled} onChange={() => onUpdateIndicator('key-levels',{enabled:!item.enabled})} />关键价位指标<span className={`ml-auto text-[10px] ${readiness?.status === 'partial' ? 'text-amber-300' : 'text-emerald-300'}`}>{readiness ? `${readiness.actual_warmup_bars}/${readiness.required_warmup_bars} ${readiness.status === 'ready' ? '完整' : '部分'}` : '启用后检查预热'}</span></label><div className="mt-3 grid grid-cols-2 gap-2">{Object.entries(labels).map(([key,label]) => <label key={key} className="flex items-center gap-1"><input type="checkbox" checked={selected.includes(key)} onChange={() => onUpdateIndicator('key-levels',{params:{...item.params,activeLevelTypes:selected.includes(key)?selected.filter(value=>value!==key):[...selected,key]}})} />{label}</label>)}</div></section> })()}
        </div>}
        {tab === 'templates' && <div className="space-y-2">
          <button type="button" onClick={onSaveTemplate} className="tool-btn w-full justify-center">保存当前工作区为新模板</button>
          <label className="flex items-center gap-2 rounded border border-border/60 p-2 text-secondary"><input type="checkbox" checked={summaryVisible} onChange={event => onSummaryVisibilityChange(event.target.checked)} />显示已启用指标摘要</label>
          {activeTemplateId && <div className={`rounded border px-2 py-1.5 text-[10px] ${activeTemplateDeviated ? 'border-amber-400/30 bg-amber-400/[0.06] text-amber-200' : 'border-emerald-400/30 bg-emerald-400/[0.06] text-emerald-200'}`}>{activeTemplateDeviated ? '当前工作区已偏离所应用模板，可重新应用恢复。' : '当前工作区与所应用模板一致。'}</div>}
          {templates.map(template => {
            const enabled = template.indicators.filter(item => item.enabled)
            return <section key={template.id} className={`rounded border p-2 ${activeTemplateId === template.id ? 'border-violet-400/40 bg-violet-400/[0.07]' : 'border-border/60'}`}>
              <div className="flex items-center gap-2"><button type="button" onClick={() => onApplyTemplate(template)} className="min-w-0 flex-1 text-left"><span className="font-medium text-foreground">{template.name}</span><span className="ml-2 text-[10px] text-muted">{template.system ? '系统' : '自定义'} · {enabled.length}项</span><span className="mt-1 block truncate text-[10px] text-muted">{enabled.slice(0, 6).map(item => INDICATOR_REGISTRY.find(definition => definition.key === item.indicatorId)?.label ?? item.indicatorId).join('、')}{enabled.length > 6 ? ` +${enabled.length - 6}` : ''}</span></button></div>
              <div className="mt-2 flex flex-wrap gap-2 text-[10px]"><button type="button" onClick={() => onApplyTemplate(template)} className="text-sky-300">应用/恢复</button><button type="button" onClick={() => onCopyTemplate(template)} className="text-secondary">复制</button>{!template.system && <><button type="button" onClick={() => onRenameTemplate(template)} className="text-secondary">重命名</button><button type="button" onClick={() => onOverwriteTemplate(template)} className="text-secondary">用当前覆盖</button><button type="button" onClick={() => onDeleteTemplate(template)} className="text-danger">删除</button></>}</div>
            </section>
          })}
        </div>}
        {tab === 'drawing' && <div className="text-secondary">当前上下文有 {drawingCount} 条画线；请使用顶部趋势线、水平线和文字工具编辑。</div>}
        {tab === 'strategy' && <div className="mb-3 space-y-3">
          <section className="rounded border border-sky-400/25 bg-sky-400/[0.045] p-2" data-testid="single-stock-strategy-preview">
            <div className="flex items-center justify-between gap-2"><span className="font-medium text-sky-100">即时策略标记</span>{previewLoading && <span className="text-[10px] text-sky-300">正在计算当前股票…</span>}</div>
            <p className="mt-1 text-[10px] leading-4 text-muted">仅计算当前股票的可见历史与预热K线，不执行全市场扫描，也不写入策略事件库。</p>
            {previewStrategies.length > 0 ? <div className="mt-2 flex max-h-28 flex-wrap gap-1 overflow-y-auto">{previewStrategies.map(strategy => <label key={strategy.id} className="inline-flex max-w-full items-center gap-1 rounded border border-sky-300/20 px-1.5 py-1 text-[10px] text-secondary"><input data-testid={`chart-preview-strategy-${strategy.id}`} type="checkbox" checked={previewStrategyIds.has(strategy.id)} onChange={() => onTogglePreviewStrategy(strategy.id)} />{strategy.name}<span className="font-mono text-muted">{strategy.id}</span></label>)}</div> : <p className="mt-2 text-[10px] text-muted">当前标的或 K 线周期没有声明可即时预览的正式策略。</p>}
            {previewError && <p className="mt-2 text-[10px] text-danger">即时预览失败：{previewError}</p>}
          </section>
          <section className="space-y-3 rounded border border-border/60 bg-base/30 p-2">
          <span className="text-[10px] font-medium text-secondary">已记录的策略事件</span>
          <div className="flex flex-wrap items-center gap-2"><span className="text-muted">范围</span><button type="button" data-testid="strategy-scope-source" onClick={() => onStrategyScopeChange('source')} className={`rounded px-2 py-1 ${strategyScope === 'source' ? 'bg-sky-400/15 text-sky-200' : 'text-muted'}`}>仅来源策略{sourceStrategyIds.length ? ` (${sourceStrategyIds.length})` : ''}</button><button type="button" data-testid="strategy-scope-all" onClick={() => onStrategyScopeChange('all')} className={`rounded px-2 py-1 ${strategyScope === 'all' ? 'bg-sky-400/15 text-sky-200' : 'text-muted'}`}>所有历史策略</button></div>
          {strategyScope === 'all' && availableStrategyIds.length > 0 && <div className="flex max-h-20 flex-wrap gap-1 overflow-y-auto">{availableStrategyIds.map(id => <label key={id} className="inline-flex items-center gap-1 rounded border border-border/50 px-1.5 py-1 font-mono text-[10px]"><input type="checkbox" checked={selectedStrategyIds.size === 0 || selectedStrategyIds.has(id)} onChange={() => onToggleStrategy(id)} />{id}</label>)}</div>}
          <div className="flex flex-wrap items-center gap-2"><span className="text-muted">事件</span>{([['candidate', '候选'], ['entry', '入场'], ['exit', '离场'], ['failure', '失效'], ['support', '守轴'], ['retrigger', '再触发']] as const).map(([id, label]) => <label key={id} className="inline-flex items-center gap-1"><input type="checkbox" checked={strategyEventTypes.has(id)} onChange={() => onToggleStrategyEventType(id)} />{label}</label>)}</div>
          <div className="flex items-center gap-2"><span className="text-muted">密度</span><button type="button" data-testid="annotation-density-auto" onClick={() => onDensityChange('auto')} className={annotationDensity === 'auto' ? 'text-sky-200' : 'text-muted'}>随缩放</button><button type="button" data-testid="annotation-density-compact" onClick={() => onDensityChange('compact')} className={annotationDensity === 'compact' ? 'text-sky-200' : 'text-muted'}>聚合</button><button type="button" data-testid="annotation-density-detailed" onClick={() => onDensityChange('detailed')} className={annotationDensity === 'detailed' ? 'text-sky-200' : 'text-muted'}>详细</button></div>
          </section>
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
    </aside>
  )
}

export function EvidenceDrawer({ evidence, onClose }: { evidence: AnnotationEvidence | null; onClose: () => void }) {
  if (!evidence) return null
  return (
    <aside className="absolute bottom-0 right-0 top-0 z-50 w-[min(420px,92vw)] overflow-y-auto border-l border-border bg-surface/98 p-4 shadow-2xl backdrop-blur" data-testid="chart-evidence-drawer" aria-label="图表证据">
      <div className="flex items-start gap-3"><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold text-foreground">{evidence.title}</h3><p className="mt-1 text-xs leading-5 text-secondary">{evidence.summary}</p></div><button type="button" onClick={onClose} aria-label="关闭证据" className="p-1 text-muted hover:text-foreground"><X className="h-4 w-4" /></button></div>
      <div className="mt-4 rounded border border-amber-400/20 bg-amber-400/[0.06] p-2 text-[11px] leading-5 text-amber-100">策略标记只来自已注册策略：可以是已记录的策略事件，也可以是当前股票的即时只读预览。形态仅作观察结构，不会直接生成买卖信号。两者均不代表真实账户成交，回测成交与实时监控触发会使用独立名称和标记。</div>
      {evidence.reason_codes.length > 0 && <section className="mt-4"><h4 className="text-[11px] font-semibold text-muted">命中条件</h4><div className="mt-2 flex flex-wrap gap-1">{evidence.reason_codes.map(code => <span key={code} className="rounded bg-sky-400/10 px-2 py-1 font-mono text-[10px] text-sky-200">{code}</span>)}</div></section>}
      {evidence.metrics.length > 0 && <section className="mt-4"><h4 className="text-[11px] font-semibold text-muted">指标证据</h4><div className="mt-2 divide-y divide-border/40 rounded border border-border/60">{evidence.metrics.map((metric, index) => <div key={`${metric.name}-${index}`} className="grid grid-cols-[1fr_auto] gap-3 px-2 py-1.5 text-[11px]"><span className="text-secondary">{metric.name}</span><span className={`font-mono ${metric.passed === false ? 'text-danger' : metric.passed === true ? 'text-emerald-300' : 'text-foreground'}`}>{String(metric.value ?? '—')}{metric.unit ? ` ${metric.unit}` : ''}{metric.threshold != null ? ` / 阈值 ${String(metric.threshold)}` : ''}</span></div>)}</div></section>}
      <section className="mt-4"><h4 className="text-[11px] font-semibold text-muted">版本与来源</h4><dl className="mt-2 space-y-1 text-[10px]">{Object.entries(evidence.metadata).map(([key, value]) => <div key={key} className="grid grid-cols-[120px_1fr] gap-2"><dt className="text-muted">{key}</dt><dd className="break-all font-mono text-secondary">{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl></section>
      {[...evidence.warnings].map(warning => <div key={warning} className="mt-3 text-xs text-danger">{warning}</div>)}
    </aside>
  )
}

export type { ManagerTab }
