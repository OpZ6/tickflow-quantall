// 指标参数默认值与持久化 — 对齐 openclarr-chanlun paramDefs
import { storage } from '@/lib/storage'

export type IndicatorParams = Record<string, Record<string, number>>

/** 各指标可调参数及默认值 (key 与 SUB_CHARTS/OVERLAY_INDICATORS 的 key 一致) */
export const PARAM_DEFS: Record<string, Record<string, number>> = {
  // 主图叠加
  boll: { p: 20, sd: 2 },
  ema: { p: 20 },
  sma: { p: 20 },
  bbi: { p1: 3, p2: 6, p3: 12, p4: 24 },
  sar: { step: 0.02, maxAF: 0.2 },
  zigzag: { dev: 5 },
  tema: { n: 12 },
  dema: { n: 12 },
  hma: { p: 20 },
  wma: { p: 20 },
  vwma: { p: 20 },
  supertrend: { n: 10, mult: 3 },
  donchian: { n: 20 },
  keltner: { n: 20, m: 2 },
  ichimoku: { conv: 9, base: 26, span: 52, disp: 26 },
  alligator: { jawN: 13, jawShift: 8, teethN: 8, teethShift: 5, lipsN: 5, lipsShift: 3 },
  linreg: { len: 100, mult: 2 },
  kdjch: { n: 9, m1: 3, m2: 3 },
  wrch: { p: 14 },
  // 副图
  kdj: { n: 9, m1: 3, m2: 3 },
  wr: { p: 14 },
  cci: { p: 14 },
  bias: { p1: 6, p2: 12, p3: 24 },
  vr: { n: 26 },
  atr: { n: 14 },
  dmi: { n: 14, m: 6 },
  mtm: { n: 12, m: 6 },
  roc: { n: 12, m: 6 },
  mfi: { n: 14 },
  cmf: { n: 20 },
  cmo: { n: 10 },
  trix: { n: 12, m: 9 },
  tsi: { r: 25, s: 13, sig: 13 },
  stoch: { n: 14, sk: 3, sd: 3 },
  stochrsi: { rn: 14, sn: 14, sk: 3, sd: 3 },
  ppo: { f: 12, s: 26, sig: 9 },
  dma: { n1: 10, n2: 50, m: 10 },
  uo: { s: 7, m: 14, l: 28 },
  vortex: { n: 14 },
  psy: { n: 12, m: 6 },
  chop: { n: 14 },
  ao: { fast: 5, slow: 34 },
  aroon: { n: 14 },
  dpo: { n: 20 },
  forceindex: { n: 2 },
  emv: { n: 14, m: 9 },
  chaikinosc: { fast: 3, slow: 10 },
  elderray: { n: 13 },
  ttmsqueeze: { n: 20, bbMult: 2, kcMult: 1.5 },
  stc: { f: 12, s: 26, cyc: 50 },
  cr: { n: 26 },
  brar: { n: 26 },
}

/** 取某指标的当前参数（用户覆盖值 + 默认值合并） */
export function getParams(key: string): Record<string, number> {
  const stored = storage.indicatorParams.get({})
  return { ...(PARAM_DEFS[key] ?? {}), ...(stored[key] ?? {}) }
}

/** 覆盖某指标的单个参数并持久化 */
export function setParam(key: string, name: string, value: number): void {
  const stored = storage.indicatorParams.get({})
  storage.indicatorParams.set({ ...stored, [key]: { ...(stored[key] ?? {}), [name]: value } })
}

/** 原子覆盖某指标的完整参数，供工作区模板应用和 v4 布局恢复。 */
export function setParams(key: string, values: Record<string, number>): void {
  const stored = storage.indicatorParams.get({})
  storage.indicatorParams.set({ ...stored, [key]: { ...values } })
}

/** 重置某指标参数为默认 */
export function resetParam(key: string): void {
  const stored = storage.indicatorParams.get({})
  const next = { ...stored }
  delete next[key]
  storage.indicatorParams.set(next)
}
