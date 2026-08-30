import { createHash } from 'node:crypto'
import * as F from '../src/lib/indicator-formulas'
import { rowsAtReplay } from '../src/features/stock-chart/replay'
import { detectPatterns } from '../src/features/stock-chart/patterns'

const candles = Array.from({ length: 180 }, (_, index) => {
  const trend = 20 + index * 0.035
  const wave = Math.sin(index / 5) * 1.7 + Math.cos(index / 13) * 0.8
  const open = trend + wave
  const close = open + Math.sin(index / 3) * 0.55
  return {
    date: `2026-01-${String(index + 1).padStart(3, '0')}`,
    open, close,
    high: Math.max(open, close) + 0.4 + (index % 5) * 0.03,
    low: Math.min(open, close) - 0.35 - (index % 7) * 0.02,
    volume: 100_000 + index * 317 + (index % 11) * 4_000,
  }
})

const results: Record<string, unknown> = {
  sma: F.calcSMA(candles, 20), ema: F.calcEMA(candles, 20), boll: F.calcBOLL(candles, 20, 2),
  bbi: F.calcBBI(candles, 3, 6, 12, 24), zigzag: F.calcZigZag(candles, 5), sar: F.calcSAR(candles, 0.02, 0.2),
  tema: F.calcTEMA(candles, 12), dema: F.calcDEMA(candles, 12), hma: F.calcHMA(candles, 16),
  wma: F.calcWMA(candles, 20), vwma: F.calcVWMA(candles, 20), vwap: F.calcVWAP(candles),
  supertrend: F.calcSupertrend(candles, 10, 3), donchian: F.calcDonchian(candles, 20),
  keltner: F.calcKeltner(candles, 20, 2), ichimoku: F.calcIchimoku(candles, 9, 26, 52, 26),
  alligator: F.calcAlligator(candles, 13, 8, 8, 5, 5, 3), linreg: F.calcLinRegChannel(candles, 20, 2),
  kdjChannel: F.calcKDJChannel(candles, 9, 3, 3), wrChannel: F.calcWRChannel(candles, 14),
  kdj: F.calcKDJ(candles, 9, 3, 3), rsi: F.calcRSI(candles, 14), wr: F.calcWR(candles, 14),
  cci: F.calcCCI(candles, 14), bias: F.calcBIAS(candles, 6), obv: F.calcOBV(candles), vr: F.calcVR(candles, 26),
  atr: F.calcATR(candles, 14), dmi: F.calcDMI(candles, 14, 6), mtm: F.calcMTM(candles, 12, 6),
  roc: F.calcROC(candles, 12, 6), mfi: F.calcMFI(candles, 14), cmf: F.calcCMF(candles, 20),
  cmo: F.calcCMO(candles, 14), trix: F.calcTRIX(candles, 12, 9), tsi: F.calcTSI(candles, 25, 13, 7),
  stoch: F.calcStoch(candles, 14, 3, 3), stochRsi: F.calcStochRSI(candles, 14, 14, 3, 3),
  ppo: F.calcPPO(candles, 12, 26, 9), dma: F.calcDMA(candles, 10, 50, 10), uo: F.calcUO(candles, 7, 14, 28),
  vortex: F.calcVortex(candles, 14), psy: F.calcPSY(candles, 12, 6), chop: F.calcChop(candles, 14),
  ao: F.calcAO(candles, 5, 34), aroon: F.calcAroon(candles, 25), pvt: F.calcPVT(candles),
  dpo: F.calcDPO(candles, 20), force: F.calcForceIndex(candles, 13), emv: F.calcEMV(candles, 14, 9),
  adl: F.calcADL(candles), chaikin: F.calcChaikinOsc(candles, 3, 10), elder: F.calcElderRay(candles, 13),
  ttm: F.calcTTMSqueeze(candles, 20, 2, 1.5), stc: F.calcSTC(candles, 23, 50, 10),
  cr: F.calcCR(candles, 26), brar: F.calcBRAR(candles, 26),
}

function normalize(value: unknown): unknown {
  if (typeof value === 'number') return Number.isFinite(value) ? Number(value.toFixed(8)) : null
  if (Array.isArray(value)) return value.map(normalize)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(item)]))
  return value
}

const actual = Object.fromEntries(Object.entries(results).map(([key, value]) => [
  key,
  createHash('sha256').update(JSON.stringify(normalize(value))).digest('hex').slice(0, 16),
]))

const golden: Record<string, string> = {
  sma: '0d5d795683fb472b', ema: '4a0c9853b3a5c61e', boll: 'b8d3e71675a4a9bb',
  bbi: 'cac9f173157524b7', zigzag: 'b6d4ad7e0ab00c85', sar: '858fcb6cc17c832e',
  tema: 'c9c09e005435e18c', dema: 'b76be10c02708d6e', hma: 'e2f58bc6567cedaa',
  wma: '46744c2f9c08cf0f', vwma: '232ef5c824d34df9', vwap: '25bc6afcc93286c8',
  supertrend: '98afb49c88b6e8af', donchian: '865cfb3347a4b96a', keltner: 'c72141031bfa4f11',
  ichimoku: '0291c3942aaf9672', alligator: 'f634e21303e11829', linreg: 'ebf562f8c909a017',
  kdjChannel: 'ed5bb451d7c4dc2e', wrChannel: 'dcb89269bd91bfbb', kdj: '25db80b6ee0c3791',
  rsi: '524e15f162dfafbb', wr: 'e62f408f9c254059', cci: 'c4050adeca7c1973',
  bias: '7b80aa27ebf452ae', obv: '3afbff27ca1941c2', vr: '84842205ad18ce5a',
  atr: '8146af07c28bd891', dmi: 'de689aab75fa6aea', mtm: '224094ac9be4cc89',
  roc: '4b0d02c754ca1c96', mfi: '640300c348500806', cmf: '96f675d53b5ebad9',
  cmo: 'b66dbc0a153e1b28', trix: '14b8559dc7ac6888', tsi: '621e3835ca49d904',
  stoch: '8c583d549e138fcd', stochRsi: '0b0f1db95ac2d945', ppo: '80f792a30bb995a7',
  dma: '5a50ee3a8f45c023', uo: 'aefea611640f3b5a', vortex: 'f31d9fa44357315c',
  psy: 'dc4bfc1ec40ff7e3', chop: 'd8dfafcd0c24b768', ao: 'f4f56cf59f0b97aa',
  aroon: 'b7ed29d01e364203', pvt: '5d10144018700b2e', dpo: '23aa6805c340a885',
  force: '78a91b31f7ce4b06', emv: '9e38d7f300d5b5dd', adl: 'e8ed837349ccb68a',
  chaikin: '0122cd7388f1235e', elder: '19db6c74844d8a82', ttm: '4d84b4473e24e40e',
  stc: '7f1baeb2bf4b74b3', cr: '6fe79bf6509401fc', brar: '3f66027d814da7cd',
}

const replaySource = [{ close: 1 }, { close: 2 }, { close: 999 }]
const replayVisible = rowsAtReplay(replaySource, 1)
if (replayVisible.length !== 2 || replayVisible.some(row => row.close === 999)) {
  throw new Error('回放向计算函数泄漏了未来 K 线')
}

function patternLayer(prices: number[], first: 'high' | 'low') {
  return {
    merged: [], fenxing: [], segments: [], zhongshu: [], bsp: [],
    bi: prices.map((price, index) => {
      const type = index % 2 === 0 ? first : first === 'high' ? 'low' : 'high'
      return {
        startIdx: Math.max(0, index - 1), endIdx: index,
        startPrice: prices[Math.max(0, index - 1)], endPrice: price,
        direction: type === 'high' ? 'up' as const : 'down' as const, isSure: true,
      }
    }),
  }
}

const hst = detectPatterns(patternLayer([10, 7, 12, 8, 10], 'high'))
const hsb = detectPatterns(patternLayer([10, 13, 8, 12, 10], 'low'))
const triangle = detectPatterns(patternLayer([12, 8, 11, 9, 10, 9.5], 'high'))
for (const [type, found] of [['HST', hst], ['DT', hst], ['HSB', hsb], ['DB', hsb], ['Tri', triangle]] as const) {
  if (!found.some(pattern => pattern.type === type)) throw new Error(`形态识别固定样本失败: ${type}`)
}

if (JSON.stringify(actual) !== JSON.stringify(golden)) {
  console.error(JSON.stringify(actual, null, 2))
  throw new Error('指标固定样本与黄金值不一致')
}
console.log(`INDICATOR_FORMULAS_OK=${Object.keys(actual).length}`)
