import type { ChartMarker, ChartPriceLine, ChartRange } from '@/components/EChartsCandlestick'
import type { AnnotationEvidence, AnnotationMarker, ChartAnnotationLayer } from '@/lib/api'

export interface AnnotationVisuals {
  markers: ChartMarker[]
  lines: ChartPriceLine[]
  ranges: ChartRange[]
  evidence: Map<string, AnnotationEvidence>
}

const ROLE_COLOR: Record<string, string> = {
  strategy_entry: '#22c55e',
  strategy_exit: '#ef4444',
  failure: '#ef4444',
  support: '#3b82f6',
  retrigger: '#38bdf8',
  confluence: '#a855f7',
  candidate: '#f59e0b',
  backtest_entry: '#14b8a6',
  backtest_exit: '#f97316',
  realtime_trigger: '#eab308',
  market_event: '#facc15',
  pattern_anchor: '#f472b6',
  breakout: '#22c55e',
  impulse: '#fb7185',
  trigger: '#f59e0b',
  candidate_trigger: '#f59e0b',
  convergence_upper: '#f472b6',
  convergence_lower: '#38bdf8',
  support_line: '#3b82f6',
}

function isConfirmed(confirmedAt: string | null | undefined, replayDate?: string): boolean {
  return !replayDate || !confirmedAt || confirmedAt.slice(0, 10) <= replayDate.slice(0, 10)
}

function markerVisual(marker: AnnotationMarker): ChartMarker {
  const role = marker.role
  if (role === 'strategy_entry') return { id: marker.id, date: marker.date, kind: 'buy', label: marker.label, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'triangle' }
  if (role === 'strategy_exit') return { id: marker.id, date: marker.date, kind: 'sell', label: marker.label, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'triangle' }
  if (role === 'backtest_entry' || role === 'backtest_exit') return { id: marker.id, date: marker.date, kind: 'neutral', label: marker.label, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'diamond' }
  if (role === 'realtime_trigger') return { id: marker.id, date: marker.date, kind: 'neutral', label: marker.label, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'circle' }
  if (role === 'confluence') return { id: marker.id, date: marker.date, kind: 'neutral', label: `${marker.label} ×${marker.count}`, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'diamond' }
  if (role === 'failure') return { id: marker.id, date: marker.date, kind: 'sell', label: `失效 · ${marker.label}`, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'pin' }
  if (role === 'support' || role === 'retrigger') return { id: marker.id, date: marker.date, kind: 'buy', label: marker.label, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role], symbol: 'circle' }
  const above = role === 'market_event' || role === 'pattern_anchor' || role === 'breakout' || role === 'impulse'
  return { id: marker.id, date: marker.date, kind: 'neutral', label: marker.label, evidenceId: marker.evidence_id ?? undefined, color: ROLE_COLOR[role] ?? '#94a3b8', above, symbol: role === 'candidate' ? 'pin' : 'circle' }
}

export function buildAnnotationVisuals(
  layers: ChartAnnotationLayer[],
  enabledLayerIds: Set<string>,
  replayDate?: string,
  options: {
    strategyIds?: Set<string>
    strategyEventTypes?: Set<string>
    density?: 'compact' | 'detailed'
  } = {},
): AnnotationVisuals {
  const markers: ChartMarker[] = []
  const lines: ChartPriceLine[] = []
  const ranges: ChartRange[] = []
  const evidence = new Map<string, AnnotationEvidence>()

  for (const layer of layers) {
    if (!enabledLayerIds.has(layer.id) || layer.status !== 'available') continue
    const acceptedEvidence = new Set<string>()
    for (const item of layer.evidence) {
      const strategyId = String(item.metadata.strategy_id ?? '')
      const strategyIds = Array.isArray(item.metadata.strategy_ids) ? item.metadata.strategy_ids.map(String) : []
      const eventType = String(item.metadata.event_type ?? '')
      const isSingleAssetPreview = item.metadata.provenance === 'single_asset_preview'
      if (!isSingleAssetPreview && layer.category === 'strategy' && options.strategyIds?.size && !options.strategyIds.has(strategyId) && !strategyIds.some(id => options.strategyIds?.has(id))) continue
      if (!isSingleAssetPreview && layer.category === 'strategy' && options.strategyEventTypes?.size && eventType && eventType !== 'confluence' && !options.strategyEventTypes.has(eventType)) continue
      evidence.set(item.id, item)
      acceptedEvidence.add(item.id)
    }
    const confluenceDates = new Set(
      layer.markers.filter(marker => marker.role === 'confluence').map(marker => marker.date.slice(0, 10)),
    )
    const acceptedMarkers = layer.markers.filter(marker => {
      if (marker.evidence_id && !acceptedEvidence.has(marker.evidence_id)) return false
      return options.density !== 'compact' || marker.role === 'confluence' || !confluenceDates.has(marker.date.slice(0, 10))
    })
    const markerLimit = options.density === 'detailed' ? 300 : 80
    for (const marker of acceptedMarkers.slice(-markerLimit)) {
      if (isConfirmed(marker.confirmed_at, replayDate) && isConfirmed(marker.detected_at, replayDate)) {
        markers.push(markerVisual(marker))
      }
    }
    for (const line of layer.lines) {
      if (line.start_date && replayDate && line.start_date.slice(0, 10) > replayDate.slice(0, 10)) continue
      if (layer.category !== 'plan' && line.evidence_id && !acceptedEvidence.has(line.evidence_id)) continue
      lines.push({
        value: line.value,
        endValue: line.end_value ?? undefined,
        start: line.start_date ?? undefined,
        end: line.end_date && replayDate ? (line.end_date.slice(0, 10) > replayDate.slice(0, 10) ? replayDate : line.end_date) : line.end_date ?? undefined,
        label: line.label,
        color: ROLE_COLOR[line.role] ?? '#94a3b8',
      })
    }
    for (const zone of layer.zones) {
      if (layer.category !== 'plan' && zone.evidence_id && !acceptedEvidence.has(zone.evidence_id)) continue
      if (!isConfirmed(zone.confirmed_at, replayDate)) continue
      ranges.push({
        start: zone.start_date,
        end: replayDate && zone.end_date.slice(0, 10) > replayDate.slice(0, 10) ? replayDate : zone.end_date,
        low: zone.low,
        high: zone.high,
        label: zone.label,
        color: layer.category === 'pattern' ? 'rgba(244,114,182,0.08)' : 'rgba(59,130,246,0.08)',
        evidenceId: zone.evidence_id ?? undefined,
      })
    }
    for (const segment of layer.segments) {
      if (layer.category !== 'plan' && segment.evidence_id && !acceptedEvidence.has(segment.evidence_id)) continue
      if (!isConfirmed(segment.confirmed_at, replayDate)) continue
      for (let index = 0; index < segment.points.length - 1; index += 1) {
        const start = segment.points[index]
        const end = segment.points[index + 1]
        if (replayDate && end.date.slice(0, 10) > replayDate.slice(0, 10)) break
        lines.push({ value: start.price, endValue: end.price, start: start.date, end: end.date, label: index === 0 ? segment.label : '', color: ROLE_COLOR[segment.role] ?? '#f472b6' })
      }
    }
  }
  return { markers, lines, ranges, evidence }
}
