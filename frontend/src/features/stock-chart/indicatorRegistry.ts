import { OVERLAY_INDICATORS, SUB_CHARTS } from '@/components/EChartsCandlestick'
import { PARAM_DEFS } from '@/lib/indicator-params'
import type { ChartIndicatorDefinition, ParamDefinition } from './chartTypes'

const ALL_INTERVALS = ['1m', '5m', '15m', '30m', '60m', '1d', '1w', '1mo'] as const

const GROUPS: Record<string, string> = {
  boll: '通道', ema: '趋势', sma: '趋势', bbi: '趋势', sar: '趋势', zigzag: '趋势',
  tema: '趋势', dema: '趋势', hma: '趋势', wma: '趋势', vwma: '量价', vwap: '量价',
  supertrend: '趋势', donchian: '通道', keltner: '通道', ichimoku: '趋势',
  alligator: '趋势', linreg: '通道', kdjch: '通道', wrch: '通道', vol: '成交量',
  macd: '动量', kdj: '动量', rsi: '动量', wr: '动量', cci: '动量', bias: '动量',
  obv: '成交量', vr: '成交量', atr: '波动', dmi: '趋势', mtm: '动量', roc: '动量',
  mfi: '成交量', cmf: '成交量', cmo: '动量', trix: '趋势', tsi: '动量', stoch: '动量',
  stochrsi: '动量', ppo: '动量', dma: '趋势', uo: '动量', vortex: '趋势', psy: '情绪',
  chop: '波动', ao: '动量', aroon: '趋势', pvt: '成交量', dpo: '动量', forceindex: '成交量',
  emv: '成交量', adl: '成交量', chaikinosc: '成交量', elderray: '趋势', ttmsqueeze: '波动',
  stc: '动量', cr: '情绪', brar: '情绪',
}

const LABELS: Record<string, string> = {
  p: '周期', n: '周期', m: '平滑', sd: '标准差倍数', step: '步长', maxAF: '最大加速',
  dev: '偏离%', mult: '倍数', len: '窗口', f: '快线', s: '慢线', sig: '信号',
  fast: '快线', slow: '慢线', cyc: '周期', bbMult: 'BOLL倍数', kcMult: 'KC倍数',
}

function paramsFor(key: string): ParamDefinition[] {
  return Object.entries(PARAM_DEFS[key] ?? {}).map(([name, value]) => {
    const decimal = !Number.isInteger(value)
    return {
      key: name,
      label: LABELS[name] ?? name.toUpperCase(),
      min: decimal ? 0.01 : 1,
      max: decimal ? Math.max(10, value * 10) : Math.max(500, value * 10),
      step: decimal ? 0.01 : 1,
      defaultValue: value,
    }
  })
}

function warmupFor(key: string): number {
  const params = Object.values(PARAM_DEFS[key] ?? {})
  return Math.max(2, ...params.filter(Number.isFinite).map(value => Math.ceil(value))) * 3
}

export const OVERLAY_REGISTRY: ChartIndicatorDefinition[] = OVERLAY_INDICATORS.map(item => ({
  ...item,
  id: item.key,
  version: 1,
  category: 'overlay',
  kind: 'technical',
  placement: 'main',
  calculation: 'client',
  group: GROUPS[item.key] ?? '趋势',
  requiredFields: item.key === 'vwma' || item.key === 'vwap' ? ['open', 'high', 'low', 'close', 'volume'] : ['open', 'high', 'low', 'close'],
  warmupBars: warmupFor(item.key),
  supportedIntervals: [...ALL_INTERVALS],
  defaultParams: { ...(PARAM_DEFS[item.key] ?? {}) },
  paramSchema: paramsFor(item.key),
  styleSchema: [],
}))

export const PANE_REGISTRY: ChartIndicatorDefinition[] = SUB_CHARTS.map(item => ({
  key: item.key,
  id: item.key,
  version: 1,
  label: item.label,
  category: 'pane',
  kind: 'technical',
  placement: 'sub',
  calculation: 'client',
  group: GROUPS[item.key] ?? '其他',
  requiredFields: ['open', 'high', 'low', 'close', ...(GROUPS[item.key] === '成交量' ? ['volume'] : [])],
  warmupBars: warmupFor(item.key),
  supportedIntervals: [...ALL_INTERVALS],
  defaultParams: { ...(PARAM_DEFS[item.key] ?? {}) },
  paramSchema: paramsFor(item.key),
  styleSchema: [],
  defaultHeight: item.height,
}))

export const STRUCTURE_REGISTRY: ChartIndicatorDefinition[] = [
  ['key-levels', '关键价位', '价位', 'structure', 'repository'],
  ['chanlun', '缠论结构', '缠论', 'structure', 'server'],
  ['patterns', '价格形态', '形态', 'pattern', 'repository'],
  ['strategies', '正式策略信号', '策略', 'strategy', 'repository'],
  ['events', '涨停/炸板/事件', '事件', 'event', 'repository'],
].map(([key, label, group, kind, calculation]) => ({
  id: key, key, version: 1, label, group, kind, calculation,
  category: 'structure', placement: 'main', requiredFields: ['date', 'open', 'high', 'low', 'close'],
  warmupBars: key === 'chanlun' ? 500 : key === 'patterns' || key === 'key-levels' ? 160 : 0,
  supportedIntervals: [...ALL_INTERVALS], defaultParams: {}, paramSchema: [], styleSchema: [],
})) as ChartIndicatorDefinition[]

export const INDICATOR_REGISTRY = [...OVERLAY_REGISTRY, ...PANE_REGISTRY, ...STRUCTURE_REGISTRY]

export const INDICATOR_COUNTS = {
  overlays: OVERLAY_REGISTRY.length,
  panes: PANE_REGISTRY.filter(item => item.key !== 'vol').length,
  volume: PANE_REGISTRY.some(item => item.key === 'vol') ? 1 : 0,
}

if (INDICATOR_COUNTS.overlays !== 20 || INDICATOR_COUNTS.panes !== 38 || INDICATOR_COUNTS.volume !== 1) {
  throw new Error(`指标注册表不完整: ${JSON.stringify(INDICATOR_COUNTS)}`)
}
