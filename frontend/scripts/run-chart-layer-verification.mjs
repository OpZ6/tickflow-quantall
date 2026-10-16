import { build } from 'esbuild'

const bundled = await build({
  entryPoints: ['src/features/stock-chart/annotationLayers.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
})
const moduleUrl = `data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`
const { buildAnnotationVisuals } = await import(moduleUrl)

const evidence = { id: 'future', title: 'fixture', summary: '', metrics: [], reason_codes: [], warnings: [], metadata: {} }
const layer = {
  schema_version: 1,
  id: 'pattern.fixture',
  category: 'pattern',
  title: 'fixture',
  status: 'available',
  algorithm_version: 'fixture-v1',
  input_fingerprint: 'fixture',
  price_basis: 'qfq',
  markers: [{ id: 'future', layer_id: 'pattern.fixture', date: '2026-08-28', role: 'pattern_anchor', label: 'future', evidence_id: 'future', detected_at: '2026-08-28', confirmed_at: '2026-08-28', count: 1 }],
  lines: [],
  zones: [{ id: 'zone', layer_id: 'pattern.fixture', role: 'consolidation', start_date: '2026-08-20', end_date: '2026-08-28', low: 9, high: 10, label: 'zone', evidence_id: 'future', confirmed_at: '2026-08-28' }],
  segments: [],
  evidence: [evidence],
  warnings: [],
}

const hidden = buildAnnotationVisuals([layer], new Set([layer.id]), '2026-08-27')
if (hidden.markers.length !== 0 || hidden.ranges.length !== 0) {
  throw new Error('future-confirmed annotations leaked into replay')
}
const visible = buildAnnotationVisuals([layer], new Set([layer.id]), '2026-08-28')
if (visible.markers.length !== 1 || visible.ranges.length !== 1 || visible.evidence.size !== 1) {
  throw new Error('confirmed annotations were not rendered with evidence')
}
console.log('CHART_LAYER_REPLAY_OK=1')
