import { build } from 'esbuild'

const bundled = await build({
  entryPoints: ['src/features/stock-chart/chartPersistence.ts'],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
})
const moduleUrl = `data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`
const {
  DEFAULT_STOCK_CHART_LAYOUT,
  SYSTEM_INDICATOR_TEMPLATES,
  cloneIndicatorInstances,
  normalizeChartLayout,
} = await import(moduleUrl)

const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}

const legacy = normalizeChartLayout({
  version: 3,
  interval: '1w',
  adjustment: 'hfq',
  range: '3y',
  activeIndicators: ['vol', 'macd', 'unknown-indicator'],
  paneHeights: { macd: 144 },
  collapsedIndicators: ['macd'],
  chanlun: { visible: true, showBi: false },
  keyLevelsVisible: true,
  activeLevelTypes: ['sr', 'gap'],
  customPresets: { 我的复盘: ['vol', 'rsi'] },
})
assert(legacy.version === 4, 'legacy layout did not migrate to v4')
assert(legacy.indicators.some(item => item.indicatorId === 'chanlun' && item.enabled), 'chanlun config was not migrated')
assert(legacy.indicators.some(item => item.indicatorId === 'macd' && item.pane.height === 144 && item.pane.collapsed), 'pane layout was not migrated')
assert(legacy.templates.some(item => !item.system && item.name === '我的复盘'), 'custom preset was not migrated')
assert(legacy.migrationWarnings.some(item => item.includes('unknown-indicator')), 'unknown legacy indicator was not reported')

const duplicate = cloneIndicatorInstances(DEFAULT_STOCK_CHART_LAYOUT.indicators)
duplicate.push({ ...duplicate[0], params: { ...duplicate[0].params } })
duplicate.push({ ...duplicate[0], instanceId: 'unknown.1', indicatorId: 'not-registered' })
const corrupt = normalizeChartLayout({
  ...DEFAULT_STOCK_CHART_LAYOUT,
  indicators: duplicate,
  templates: [{
    ...SYSTEM_INDICATOR_TEMPLATES[0],
    name: '伪造系统模板',
    indicators: [],
  }],
})
assert(corrupt.indicators.length === DEFAULT_STOCK_CHART_LAYOUT.indicators.length, 'duplicate or unknown instance was not rejected')
assert(corrupt.templates.length === SYSTEM_INDICATOR_TEMPLATES.length, 'persisted system template should be replaced by authoritative definitions')
assert(corrupt.templates[0].name === SYSTEM_INDICATOR_TEMPLATES[0].name, 'system template was overwritten from storage')
assert(corrupt.migrationWarnings.length >= 2, 'corrupt layout warnings are missing')

const invalidParams = cloneIndicatorInstances(DEFAULT_STOCK_CHART_LAYOUT.indicators)
const macd = invalidParams.find(item => item.indicatorId === 'macd')
macd.params = { n: Number.NaN, injected: 123 }
const normalized = normalizeChartLayout({ ...DEFAULT_STOCK_CHART_LAYOUT, indicators: invalidParams })
const normalizedMacd = normalized.indicators.find(item => item.indicatorId === 'macd')
assert(normalizedMacd && !Object.hasOwn(normalizedMacd.params, 'injected'), 'unknown technical parameter was retained')

const clone = cloneIndicatorInstances(DEFAULT_STOCK_CHART_LAYOUT.indicators)
clone[0].params.changed = true
assert(!Object.hasOwn(DEFAULT_STOCK_CHART_LAYOUT.indicators[0].params, 'changed'), 'template clone shares nested params')

console.log(`CHART_WORKSPACE_OK=layout-v4 templates=${SYSTEM_INDICATOR_TEMPLATES.length}`)
