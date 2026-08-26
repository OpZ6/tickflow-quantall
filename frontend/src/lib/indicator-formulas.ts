// 技术指标公式库 — 移植自 openclarr-chanlun web/index.html
// 全部为纯函数：输入 K 线数组，输出逐 bar 计算结果（null 表示数据不足）

export interface Candle {
  /** unix 秒或毫秒均可；仅 VWAP 分组用 */
  time?: number
  date?: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

type Arr = (number | null)[]

// ===== 基础辅助 =====

export function hhv(C: Candle[], n: number, i: number): number {
  let h = -Infinity
  for (let j = Math.max(0, i - n + 1); j <= i; j++) if (C[j].high > h) h = C[j].high
  return h
}

export function llv(C: Candle[], n: number, i: number): number {
  let l = Infinity
  for (let j = Math.max(0, i - n + 1); j <= i; j++) if (C[j].low < l) l = C[j].low
  return l
}

/** 简单移动平均（窗口满 n 个值才出数） */
export function maArr(a: Arr, n: number): Arr {
  const o: Arr = []
  const q: number[] = []
  let s = 0
  for (let i = 0; i < a.length; i++) {
    const v = a[i]
    q.push(v ?? 0)
    s += v ?? 0
    if (q.length > n) s -= q.shift()!
    o.push(q.length >= n ? s / n : null)
  }
  return o
}

/** 指数移动平均（首值作种子） */
export function emaArr(a: Arr, p: number): Arr {
  const o: Arr = []
  const k = 2 / (p + 1)
  let e: number | null = null
  for (let i = 0; i < a.length; i++) {
    const v = a[i]
    if (v == null) { o.push(e); continue }
    e = e == null ? v : v * k + e * (1 - k)
    o.push(e)
  }
  return o
}

/** 中国式 SMA(X,N,1)，与通达信 SMA 对齐 */
function smaCN(a: Arr, n: number): Arr {
  const o: Arr = []
  let s = 0
  let c = 0
  for (let i = 0; i < a.length; i++) {
    s += a[i] ?? 0
    c++
    if (c > n) { s -= a[i - n] ?? 0; c-- }
    o.push(c >= n ? s / c : null)
  }
  return o
}

/** 滚动求和 */
function rsumArr(a: Arr, n: number): Arr {
  const o: Arr = []
  const q: number[] = []
  let s = 0
  for (let i = 0; i < a.length; i++) {
    const v = a[i] ?? 0
    q.push(v)
    s += v
    if (q.length > n) s -= q.shift()!
    o.push(q.length >= n ? s : null)
  }
  return o
}

/** 线性加权移动平均 */
function wmaArr(a: Arr, p: number): Arr {
  const o: Arr = []
  const dw = p * (p + 1) / 2
  for (let i = 0; i < a.length; i++) {
    if (i < p - 1) { o.push(null); continue }
    let s = 0
    let ok = true
    for (let k = 0; k < p; k++) {
      const v = a[i - p + 1 + k]
      if (v == null) { ok = false; break }
      s += v * (k + 1)
    }
    o.push(ok ? s / dw : null)
  }
  return o
}

const closeArr = (C: Candle[]): Arr => C.map(c => c.close)

// ===== 主图叠加指标 =====

export function calcSMA(C: Candle[], p: number): Arr {
  return maArr(closeArr(C), p)
}

export function calcEMA(C: Candle[], p: number): Arr {
  return emaArr(closeArr(C), p)
}

export function calcBOLL(C: Candle[], p: number, sd: number): [Arr, Arr, Arr] {
  const up: Arr = [], mb: Arr = [], dn: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < p - 1) { up.push(null); mb.push(null); dn.push(null); continue }
    let s = 0
    for (let j = i - p + 1; j <= i; j++) s += C[j].close
    const m = s / p
    let q = 0
    for (let j2 = i - p + 1; j2 <= i; j2++) q += (C[j2].close - m) ** 2
    const v = Math.sqrt(q / p)
    mb.push(m); up.push(m + sd * v); dn.push(m - sd * v)
  }
  return [up, mb, dn]
}

export function calcBBI(C: Candle[], p1: number, p2: number, p3: number, p4: number): Arr {
  const a = calcSMA(C, p1), b = calcSMA(C, p2), c2 = calcSMA(C, p3), d = calcSMA(C, p4)
  return a.map((v, i) => (a[i] == null || b[i] == null || c2[i] == null || d[i] == null) ? null : ((v! + b[i]! + c2[i]! + d[i]!) / 4))
}

export function calcZigZag(C: Candle[], dev: number): Arr {
  const n = C.length
  const out: Arr = new Array(n).fill(null)
  if (n < 2) return out
  const th = dev / 100
  const piv: { idx: number; price: number }[] = []
  let trend = 0, exIdx = 0, exPrice = C[0].close
  for (let i = 1; i < n; i++) {
    const hi = C[i].high, lo = C[i].low
    if (trend === 1) {
      if (hi >= exPrice) { exPrice = hi; exIdx = i }
      else if (lo <= exPrice * (1 - th)) { piv.push({ idx: exIdx, price: exPrice }); trend = -1; exPrice = lo; exIdx = i }
    } else if (trend === -1) {
      if (lo <= exPrice) { exPrice = lo; exIdx = i }
      else if (hi >= exPrice * (1 + th)) { piv.push({ idx: exIdx, price: exPrice }); trend = 1; exPrice = hi; exIdx = i }
    } else {
      if (hi >= C[0].low * (1 + th)) { trend = 1; piv.push({ idx: 0, price: C[0].low }); exPrice = hi; exIdx = i }
      else if (lo <= C[0].high * (1 - th)) { trend = -1; piv.push({ idx: 0, price: C[0].high }); exPrice = lo; exIdx = i }
    }
  }
  piv.push({ idx: exIdx, price: exPrice })
  for (let k = 1; k < piv.length; k++) {
    const a = piv[k - 1], b = piv[k]
    if (b.idx <= a.idx) continue
    for (let j = a.idx; j <= b.idx; j++) out[j] = a.price + (b.price - a.price) * ((j - a.idx) / (b.idx - a.idx))
  }
  return out
}

export interface SarPoint { value: number; up: boolean }

export function calcSAR(C: Candle[], step: number, maxAF: number): (SarPoint | null)[] {
  const n = C.length
  const o: (SarPoint | null)[] = new Array(n).fill(null)
  if (n < 2) return o
  let up = C[1].close >= C[0].close
  let af = step
  let ep = up ? C[0].high : C[0].low
  let sar = up ? C[0].low : C[0].high
  o[0] = { value: sar, up }
  for (let i = 1; i < n; i++) {
    const c = C[i], pr = C[i - 1], p2 = i > 1 ? C[i - 2] : pr
    const s1 = sar + af * (ep - sar)
    if (up) {
      const lim = Math.min(s1, pr.low, p2.low)
      if (c.low < lim) { up = false; sar = ep; ep = c.low; af = step }
      else { sar = lim; if (c.high > ep) { ep = c.high; af = Math.min(af + step, maxAF) } }
    } else {
      const lim2 = Math.max(s1, pr.high, p2.high)
      if (c.high > lim2) { up = true; sar = ep; ep = c.high; af = step }
      else { sar = lim2; if (c.low < ep) { ep = c.low; af = Math.min(af + step, maxAF) } }
    }
    o[i] = { value: sar, up }
  }
  return o
}

export function calcTEMA(C: Candle[], n: number): Arr {
  const cl = closeArr(C), e1 = emaArr(cl, n), e2 = emaArr(e1, n), e3 = emaArr(e2, n)
  return cl.map((_, i) => (e1[i] == null || e2[i] == null || e3[i] == null) ? null : 3 * e1[i]! - 3 * e2[i]! + e3[i]!)
}

export function calcDEMA(C: Candle[], n: number): Arr {
  const cl = closeArr(C), e1 = emaArr(cl, n), e2 = emaArr(e1, n)
  return cl.map((_, i) => (e1[i] == null || e2[i] == null) ? null : 2 * e1[i]! - e2[i]!)
}

export function calcHMA(C: Candle[], p: number): Arr {
  const cl = closeArr(C)
  const half = Math.max(1, Math.floor(p / 2))
  const sq = Math.max(1, Math.round(Math.sqrt(p)))
  const w1 = wmaArr(cl, half), w2 = wmaArr(cl, p)
  const raw: Arr = w1.map((_, i) => (w1[i] == null || w2[i] == null) ? null : 2 * w1[i]! - w2[i]!)
  return wmaArr(raw, sq)
}

export function calcWMA(C: Candle[], p: number): Arr {
  return wmaArr(closeArr(C), p)
}

export function calcVWMA(C: Candle[], p: number): Arr {
  const o: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < p - 1) { o.push(null); continue }
    let pv = 0, vv = 0
    for (let j = i - p + 1; j <= i; j++) { const v = C[j].volume ?? 0; pv += C[j].close * v; vv += v }
    o.push(vv > 0 ? pv / vv : null)
  }
  return o
}

export function calcVWAP(C: Candle[]): Arr {
  const o: Arr = []
  let pv = 0, vv = 0, curKey: number | null = null
  for (let i = 0; i < C.length; i++) {
    const c = C[i]
    let ts = c.time ?? Date.parse(c.date ?? '') / 1000
    if (ts > 1e12) ts = Math.floor(ts / 1000)
    const key = Math.floor(ts / 86400)
    if (key !== curKey) { curKey = key; pv = 0; vv = 0 }
    const tp = (c.high + c.low + c.close) / 3
    const v = c.volume ?? 0
    pv += tp * v
    vv += v
    o.push(vv > 0 ? pv / vv : null)
  }
  return o
}

export function calcSupertrend(C: Candle[], n: number, mult: number): { up: Arr; down: Arr } {
  const atr = calcATR(C, n)
  const fu: Arr = [], fl: Arr = [], st: Arr = [], dir: number[] = []
  for (let i = 0; i < C.length; i++) {
    if (atr[i] == null) { fu.push(null); fl.push(null); st.push(null); dir.push(i > 0 ? dir[i - 1] : 1); continue }
    const hl2 = (C[i].high + C[i].low) / 2
    const bu = hl2 + mult * atr[i]!, bl = hl2 - mult * atr[i]!
    const pfu = i > 0 ? fu[i - 1] : null, pfl = i > 0 ? fl[i - 1] : null
    fu.push(pfu == null || bu < pfu || C[i - 1].close > pfu ? bu : pfu)
    fl.push(pfl == null || bl > pfl || C[i - 1].close < pfl ? bl : pfl)
    const pd = i > 0 ? (dir[i - 1] || 1) : 1
    let d: number
    if (i === 0 || st[i - 1] == null) d = 1
    else if (pfu != null && C[i].close > pfu) d = 1
    else if (pfl != null && C[i].close < pfl) d = -1
    else d = pd
    dir.push(d)
    st.push(d === 1 ? fl[i] : fu[i])
  }
  const up: Arr = [], down: Arr = []
  for (let i = 0; i < C.length; i++) { up.push(dir[i] === 1 ? st[i] : null); down.push(dir[i] === -1 ? st[i] : null) }
  return { up, down }
}

export function calcDonchian(C: Candle[], n: number): [Arr, Arr, Arr] {
  const up: Arr = [], dn: Arr = [], mid: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < n - 1) { up.push(null); dn.push(null); mid.push(null); continue }
    let h = -Infinity, l = Infinity
    for (let j = i - n + 1; j <= i; j++) { if (C[j].high > h) h = C[j].high; if (C[j].low < l) l = C[j].low }
    up.push(h); dn.push(l); mid.push((h + l) / 2)
  }
  return [up, mid, dn]
}

export function calcKeltner(C: Candle[], n: number, m: number): [Arr, Arr, Arr] {
  const mid = calcEMA(C, n), atr = calcATR(C, n)
  const up: Arr = [], dn: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (mid[i] == null || atr[i] == null) { up.push(null); dn.push(null); continue }
    up.push(mid[i]! + m * atr[i]!); dn.push(mid[i]! - m * atr[i]!)
  }
  return [up, mid, dn]
}

export function calcIchimoku(C: Candle[], conv: number, base: number, span: number, disp: number) {
  const hh = (p: number, i: number) => { let m = -Infinity; for (let j = Math.max(0, i - p + 1); j <= i; j++) if (C[j].high > m) m = C[j].high; return m }
  const ll = (p: number, i: number) => { let m = Infinity; for (let j = Math.max(0, i - p + 1); j <= i; j++) if (C[j].low < m) m = C[j].low; return m }
  const tk: Arr = [], kj: Arr = [], sa: Arr = [], sb: Arr = []
  for (let i = 0; i < C.length; i++) {
    tk.push((hh(conv, i) + ll(conv, i)) / 2)
    kj.push((hh(base, i) + ll(base, i)) / 2)
    sa.push((tk[i]! + kj[i]!) / 2)
    sb.push((hh(span, i) + ll(span, i)) / 2)
  }
  const saP: Arr = new Array(C.length).fill(null)
  const sbP: Arr = new Array(C.length).fill(null)
  for (let i = disp; i < C.length; i++) { saP[i] = sa[i - disp]; sbP[i] = sb[i - disp] }
  return { tenkan: tk, kijun: kj, spanA: saP, spanB: sbP }
}

export function calcAlligator(C: Candle[], jawN: number, jawShift: number, teethN: number, teethShift: number, lipsN: number, lipsShift: number) {
  const md: Arr = C.map(c => (c.high + c.low) / 2)
  const shift = (a: Arr, s: number): Arr => { const o: Arr = new Array(a.length).fill(null); for (let i = s; i < a.length; i++) o[i] = a[i - s]; return o }
  return [
    { data: shift(smaCN(md, jawN), jawShift), color: '#2962ff' },
    { data: shift(smaCN(md, teethN), teethShift), color: '#e53935' },
    { data: shift(smaCN(md, lipsN), lipsShift), color: '#43a047' },
  ]
}

export function calcLinRegChannel(C: Candle[], len: number, mult: number): [Arr, Arr, Arr] {
  const sv = (c: Candle) => (c.high + c.low + c.close) / 3
  const n = C.length
  const up: Arr = new Array(n).fill(null)
  const mid: Arr = new Array(n).fill(null)
  const dn: Arr = new Array(n).fill(null)
  const L = Math.min(len, n)
  if (L < 2) return [up, mid, dn]
  const start = n - L
  let sx = 0, sy = 0, sxx = 0, sxy = 0
  for (let k = 0; k < L; k++) { const y = sv(C[start + k]); sx += k; sy += y; sxx += k * k; sxy += k * y }
  const den = (L * sxx - sx * sx) || 1
  const b = (L * sxy - sx * sy) / den
  const a = (sy - b * sx) / L
  let q = 0
  for (let k2 = 0; k2 < L; k2++) { const e = sv(C[start + k2]) - (a + b * k2); q += e * e }
  const sd = Math.sqrt(q / L) * mult
  for (let k3 = 0; k3 < L; k3++) { const i3 = start + k3, m = a + b * k3; mid[i3] = m; up[i3] = m + sd; dn[i3] = m - sd }
  return [up, mid, dn]
}

/** openclarr KDJ channel overlay: price HHV/LLV with KDJ retained for parity. */
export function calcKDJChannel(C: Candle[], n: number, m1: number, m2: number) {
  const kdj = calcKDJ(C, n, m1, m2)
  return {
    upper: C.map((_, i) => hhv(C, n, i)),
    lower: C.map((_, i) => llv(C, n, i)),
    ...kdj,
  }
}

/** openclarr Williams %R channel overlay: price HHV/LLV with WR retained for parity. */
export function calcWRChannel(C: Candle[], p: number) {
  return {
    upper: C.map((_, i) => hhv(C, p, i)),
    lower: C.map((_, i) => llv(C, p, i)),
    wr: calcWR(C, p),
  }
}

// ===== 副图指标 =====

export function calcKDJ(C: Candle[], n: number, m1: number, m2: number): { k: Arr; d: Arr; j: Arr } {
  const rsv: Arr = []
  for (let i = 0; i < C.length; i++) {
    const h = hhv(C, n, i), l = llv(C, n, i)
    rsv.push(h === l ? 50 : (C[i].close - l) / (h - l) * 100)
  }
  const k = smaCN(rsv, m1), d = smaCN(k, m2)
  const j: Arr = k.map((_, i) => (k[i] == null || d[i] == null) ? null : 3 * k[i]! - 2 * d[i]!)
  return { k, d, j }
}

export function calcRSI(C: Candle[], p: number): Arr {
  const up: Arr = [], dn: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i === 0) { up.push(null); dn.push(null); continue }
    const ch = C[i].close - C[i - 1].close
    up.push(Math.max(ch, 0)); dn.push(Math.abs(ch))
  }
  const su = smaCN(up, p), sd = smaCN(dn, p)
  return su.map((_, i) => su[i] == null ? null : (sd[i] === 0 ? 100 : su[i]! / sd[i]! * 100))
}

export function calcWR(C: Candle[], p: number): Arr {
  return C.map((c, i) => {
    const h = hhv(C, p, i), l = llv(C, p, i)
    return h === l ? 0 : (h - c.close) / (h - l) * 100
  })
}

export function calcCCI(C: Candle[], p: number): Arr {
  const tp = C.map(c => (c.high + c.low + c.close) / 3)
  const ma = maArr(tp, p)
  return tp.map((_, i) => {
    if (ma[i] == null) return null
    let md = 0
    for (let j = i - p + 1; j <= i; j++) md += Math.abs(tp[j] - ma[i]!)
    md /= p
    return md === 0 ? 0 : (tp[i] - ma[i]!) / (0.015 * md)
  })
}

export function calcBIAS(C: Candle[], p: number): Arr {
  const ma = calcSMA(C, p)
  return ma.map((v, i) => v == null ? null : (C[i].close - v) / v * 100)
}

export function calcOBV(C: Candle[]): Arr {
  const o: Arr = []
  let v = 0
  for (let i = 0; i < C.length; i++) {
    if (i > 0) {
      if (C[i].close > C[i - 1].close) v += (C[i].volume ?? 0)
      else if (C[i].close < C[i - 1].close) v -= (C[i].volume ?? 0)
    }
    o.push(v)
  }
  return o
}

export function calcVR(C: Candle[], n: number): Arr {
  return C.map((_, i) => {
    if (i < n - 1) return null
    let th = 0, tl = 0, tq = 0
    for (let j = i - n + 1; j <= i; j++) {
      const v = C[j].volume ?? 0
      const pc = j > 0 ? C[j - 1].close : C[j].close
      if (C[j].close > pc) th += v
      else if (C[j].close < pc) tl += v
      else tq += v
    }
    const den = tl * 2 + tq
    return den === 0 ? null : (th * 2 + tq) / den * 100
  })
}

export function calcATR(C: Candle[], n: number): Arr {
  const tr: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i === 0) { tr.push(C[i].high - C[i].low); continue }
    const pc = C[i - 1].close
    tr.push(Math.max(C[i].high - C[i].low, Math.abs(C[i].high - pc), Math.abs(C[i].low - pc)))
  }
  return smaCN(tr, n)
}

export function calcDMI(C: Candle[], n: number, m: number): { pdi: Arr; mdi: Arr; adx: Arr; adxr: Arr } {
  const tr: Arr = [], dmp: Arr = [], dmm: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i === 0) { tr.push(0); dmp.push(0); dmm.push(0); continue }
    const h = C[i].high, l = C[i].low, pc = C[i - 1].close, ph = C[i - 1].high, pl = C[i - 1].low
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)))
    const hd = h - ph, ld = pl - l
    dmp.push(hd > 0 && hd > ld ? hd : 0)
    dmm.push(ld > 0 && ld > hd ? ld : 0)
  }
  const rsumN = (a: Arr) => { const o: Arr = []; const q: number[] = []; let s = 0; for (let i = 0; i < a.length; i++) { q.push(a[i] ?? 0); s += a[i] ?? 0; if (q.length > n) s -= q.shift()!; o.push(q.length >= n ? s : null) } return o }
  const str = rsumN(tr), sp = rsumN(dmp), sm = rsumN(dmm)
  const pdi: Arr = [], mdi: Arr = [], dx: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (str[i] == null || str[i] === 0) { pdi.push(null); mdi.push(null); dx.push(null); continue }
    const pp = sp[i]! / str[i]! * 100, mm = sm[i]! / str[i]! * 100
    pdi.push(pp); mdi.push(mm)
    dx.push((pp + mm) === 0 ? 0 : Math.abs(mm - pp) / (pp + mm) * 100)
  }
  const adx = maArr(dx, m)
  const adxr: Arr = adx.map((_, i) => (adx[i] == null || i < m || adx[i - m] == null) ? null : (adx[i]! + adx[i - m]!) / 2)
  return { pdi, mdi, adx, adxr }
}

export function calcMTM(C: Candle[], n: number, m: number): { mtm: Arr; mamtm: Arr } {
  const mtm: Arr = C.map((_, i) => i >= n ? C[i].close - C[i - n].close : null)
  return { mtm, mamtm: maArr(mtm, m) }
}

export function calcROC(C: Candle[], n: number, m: number): { roc: Arr; maroc: Arr } {
  const roc: Arr = C.map((_, i) => {
    const ref = i >= n ? C[i - n].close : null
    return ref == null || ref === 0 ? null : (C[i].close - ref) / ref * 100
  })
  return { roc, maroc: maArr(roc, m) }
}

export function calcMFI(C: Candle[], n: number): Arr {
  const tp = C.map(c => (c.high + c.low + c.close) / 3)
  const mf = tp.map((v, i) => v * (C[i].volume ?? 0))
  return tp.map((_, i) => {
    if (i < n) return null
    let pos = 0, neg = 0
    for (let j = i - n + 1; j <= i; j++) {
      if (tp[j] > tp[j - 1]) pos += mf[j]
      else if (tp[j] < tp[j - 1]) neg += mf[j]
    }
    return neg === 0 ? 100 : 100 - 100 / (1 + pos / neg)
  })
}

export function calcCMF(C: Candle[], n: number): Arr {
  const mfv = C.map(c => { const rng = c.high - c.low, v = c.volume ?? 0; return rng === 0 ? 0 : ((c.close - c.low) - (c.high - c.close)) / rng * v })
  return mfv.map((_, i) => {
    if (i < n - 1) return null
    let sm = 0, sv = 0
    for (let j = i - n + 1; j <= i; j++) { sm += mfv[j]; sv += C[j].volume ?? 0 }
    return sv === 0 ? null : sm / sv
  })
}

export function calcCMO(C: Candle[], n: number): Arr {
  const up: Arr = [], dn: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < 1) { up.push(0); dn.push(0); continue }
    const d = C[i].close - C[i - 1].close
    up.push(Math.max(0, d)); dn.push(Math.max(0, -d))
  }
  const su = rsumArr(up, n), sd = rsumArr(dn, n)
  return su.map((_, i) => (su[i] == null || su[i]! + sd[i]! === 0) ? null : 100 * (su[i]! - sd[i]!) / (su[i]! + sd[i]!))
}

export function calcTRIX(C: Candle[], n: number, m: number): { trix: Arr; matrix: Arr } {
  const cl = closeArr(C)
  const e1 = emaArr(cl, n), e2 = emaArr(e1, n), e3 = emaArr(e2, n)
  const trix: Arr = e3.map((_, i) => (i === 0 || e3[i - 1] == null || e3[i - 1] === 0) ? null : (e3[i]! - e3[i - 1]!) / e3[i - 1]! * 100)
  return { trix, matrix: maArr(trix, m) }
}

export function calcTSI(C: Candle[], r: number, s: number, sig: number): { tsi: Arr; signal: Arr } {
  const mom: Arr = [], amom: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < 1) { mom.push(0); amom.push(0); continue }
    const d = C[i].close - C[i - 1].close
    mom.push(d); amom.push(Math.abs(d))
  }
  const e2 = emaArr(emaArr(mom, r), s), a2 = emaArr(emaArr(amom, r), s)
  const tsi: Arr = e2.map((_, i) => (a2[i] == null || a2[i] === 0) ? null : 100 * e2[i]! / a2[i]!)
  return { tsi, signal: emaArr(tsi, sig) }
}

export function calcStoch(C: Candle[], n: number, sk: number, sd: number): { k: Arr; d: Arr } {
  const raw: Arr = C.map((c, i) => {
    const h = hhv(C, n, i), l = llv(C, n, i)
    return h === l ? 50 : (c.close - l) / (h - l) * 100
  })
  const k = maArr(raw, sk)
  return { k, d: maArr(k, sd) }
}

export function calcStochRSI(C: Candle[], rn: number, sn: number, sk: number, sd: number): { k: Arr; d: Arr } {
  const rsi = calcRSI(C, rn)
  const st: Arr = rsi.map((v, i) => {
    if (v == null) return null
    let hi = -Infinity, lo = Infinity, ok = true
    for (let j = i - sn + 1; j <= i; j++) {
      if (j < 0 || rsi[j] == null) { ok = false; break }
      if (rsi[j]! > hi) hi = rsi[j]!
      if (rsi[j]! < lo) lo = rsi[j]!
    }
    if (!ok) return null
    return hi === lo ? 0 : (v - lo) / (hi - lo) * 100
  })
  const k = maArr(st, sk)
  return { k, d: maArr(k, sd) }
}

export function calcPPO(C: Candle[], f: number, s: number, sig: number): { ppo: Arr; signal: Arr; hist: Arr } {
  const ef = calcEMA(C, f), es = calcEMA(C, s)
  const ppo: Arr = ef.map((_, i) => (ef[i] == null || es[i] == null || es[i] === 0) ? null : (ef[i]! - es[i]!) / es[i]! * 100)
  const signal = emaArr(ppo, sig)
  const hist: Arr = ppo.map((_, i) => (ppo[i] == null || signal[i] == null) ? null : ppo[i]! - signal[i]!)
  return { ppo, signal, hist }
}

export function calcDMA(C: Candle[], n1: number, n2: number, m: number): { ddd: Arr; ama: Arr } {
  const a = calcSMA(C, n1), b = calcSMA(C, n2)
  const ddd: Arr = a.map((_, i) => (a[i] == null || b[i] == null) ? null : a[i]! - b[i]!)
  return { ddd, ama: maArr(ddd, m) }
}

export function calcUO(C: Candle[], s: number, m: number, l: number): Arr {
  const bp: Arr = [], tr: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i === 0) { bp.push(0); tr.push(C[i].high - C[i].low); continue }
    const pc = C[i - 1].close
    const mn = Math.min(C[i].low, pc)
    bp.push(C[i].close - mn)
    tr.push(Math.max(C[i].high, pc) - mn)
  }
  const rs = (a: Arr, n: number) => { const o: Arr = []; const q: number[] = []; let sum = 0; for (let i = 0; i < a.length; i++) { q.push(a[i] ?? 0); sum += a[i] ?? 0; if (q.length > n) sum -= q.shift()!; o.push(q.length >= n ? sum : null) } return o }
  const b1 = rs(bp, s), t1 = rs(tr, s), b2 = rs(bp, m), t2 = rs(tr, m), b3 = rs(bp, l), t3 = rs(tr, l)
  return b1.map((_, i) => (!t1[i] || !t2[i] || !t3[i]) ? null : 100 * (4 * (b1[i]! / t1[i]!) + 2 * (b2[i]! / t2[i]!) + b3[i]! / t3[i]!) / 7)
}

export function calcVortex(C: Candle[], n: number): { plus: Arr; minus: Arr } {
  const vp: Arr = [], vm: Arr = [], tr: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i === 0) { vp.push(0); vm.push(0); tr.push(C[i].high - C[i].low); continue }
    vp.push(Math.abs(C[i].high - C[i - 1].low))
    vm.push(Math.abs(C[i].low - C[i - 1].high))
    const pc = C[i - 1].close
    tr.push(Math.max(C[i].high - C[i].low, Math.abs(C[i].high - pc), Math.abs(C[i].low - pc)))
  }
  const rs = (a: Arr) => { const o: Arr = []; const q: number[] = []; let s = 0; for (let i = 0; i < a.length; i++) { q.push(a[i] ?? 0); s += a[i] ?? 0; if (q.length > n) s -= q.shift()!; o.push(q.length >= n ? s : null) } return o }
  const sp = rs(vp), sm = rs(vm), stt = rs(tr)
  const plus: Arr = [], minus: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (stt[i] == null || stt[i] === 0) { plus.push(null); minus.push(null) }
    else { plus.push(sp[i]! / stt[i]!); minus.push(sm[i]! / stt[i]!) }
  }
  return { plus, minus }
}

export function calcPSY(C: Candle[], n: number, m: number): { psy: Arr; psyma: Arr } {
  const psy: Arr = C.map((_, i) => {
    if (i < n) return null
    let c = 0
    for (let j = i - n + 1; j <= i; j++) if (C[j].close > C[j - 1].close) c++
    return c / n * 100
  })
  return { psy, psyma: maArr(psy, m) }
}

export function calcChop(C: Candle[], n: number): Arr {
  return C.map((_, i) => {
    if (i < n - 1) return null
    let sm = 0
    for (let j = i - n + 1; j <= i; j++) {
      const pc = j > 0 ? C[j - 1].close : C[j].close
      sm += Math.max(C[j].high - C[j].low, Math.abs(C[j].high - pc), Math.abs(C[j].low - pc))
    }
    const rng = hhv(C, n, i) - llv(C, n, i)
    return rng <= 0 ? null : 100 * Math.log(sm / rng) / Math.log(n)
  })
}

export function calcAO(C: Candle[], fast: number, slow: number): Arr {
  const md: Arr = C.map(c => (c.high + c.low) / 2)
  const f = maArr(md, fast), s = maArr(md, slow)
  return f.map((_, i) => (f[i] == null || s[i] == null) ? null : f[i]! - s[i]!)
}

export function calcAroon(C: Candle[], n: number): { up: Arr; dn: Arr } {
  const up: Arr = [], dn: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < n) { up.push(null); dn.push(null); continue }
    let hi = -Infinity, lo = Infinity, hh = 0, ll = 0
    for (let j = 0; j <= n; j++) {
      const idx = i - n + j
      if (C[idx].high >= hi) { hi = C[idx].high; hh = j }
      if (C[idx].low <= lo) { lo = C[idx].low; ll = j }
    }
    up.push(hh / n * 100); dn.push(ll / n * 100)
  }
  return { up, dn }
}

export function calcPVT(C: Candle[]): Arr {
  const o: Arr = []
  let v = 0
  for (let i = 0; i < C.length; i++) {
    if (i < 1) { o.push(0); continue }
    const pc = C[i - 1].close
    v += (pc ? (C[i].close - pc) / pc : 0) * (C[i].volume ?? 0)
    o.push(v)
  }
  return o
}

export function calcDPO(C: Candle[], n: number): Arr {
  const sma = calcSMA(C, n)
  const sh = Math.floor(n / 2) + 1
  return sma.map((_, i) => {
    const s = i - sh >= 0 ? sma[i - sh] : null
    return s == null ? null : C[i].close - s
  })
}

export function calcForceIndex(C: Candle[], n: number): Arr {
  const raw: Arr = C.map((_, i) => i === 0 ? 0 : (C[i].close - C[i - 1].close) * (C[i].volume ?? 0))
  return emaArr(raw, n)
}

export function calcEMV(C: Candle[], n: number, m: number): { emv: Arr; maemv: Arr } {
  const em: Arr = C.map((_, i) => {
    if (i < 1) return null
    const mm = (C[i].high + C[i].low) / 2 - (C[i - 1].high + C[i - 1].low) / 2
    const rng = C[i].high - C[i].low
    const v = C[i].volume ?? 0
    const br = v > 0 && rng > 0 ? v / 1e8 / rng : 0
    return br === 0 ? 0 : mm / br
  })
  const emv = maArr(em, n)
  return { emv, maemv: maArr(emv, m) }
}

export function calcADL(C: Candle[]): Arr {
  const o: Arr = []
  let a = 0
  for (let i = 0; i < C.length; i++) {
    const h = C[i].high, l = C[i].low
    const rng = h - l
    const mfm = rng === 0 ? 0 : ((C[i].close - l) - (h - C[i].close)) / rng
    a += mfm * (C[i].volume ?? 0)
    o.push(a)
  }
  return o
}

export function calcChaikinOsc(C: Candle[], fast: number, slow: number): Arr {
  const adl = calcADL(C)
  const ef = emaArr(adl, fast), es = emaArr(adl, slow)
  return ef.map((_, i) => (ef[i] == null || es[i] == null) ? null : ef[i]! - es[i]!)
}

export function calcElderRay(C: Candle[], n: number): { bull: Arr; bear: Arr } {
  const ema = calcEMA(C, n)
  const bull: Arr = [], bear: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (ema[i] == null) { bull.push(null); bear.push(null); continue }
    bull.push(C[i].high - ema[i]!)
    bear.push(C[i].low - ema[i]!)
  }
  return { bull, bear }
}

export function calcTTMSqueeze(C: Candle[], n: number, bbMult: number, kcMult: number): { sqz: Arr; src: Arr } {
  const basis = calcSMA(C, n)
  const dev: Arr = basis.map((v, i) => {
    if (v == null) return null
    let q = 0
    for (let j = i - n + 1; j <= i; j++) q += (C[j].close - v) ** 2
    return Math.sqrt(q / n)
  })
  const tr: Arr = C.map((c, i) => {
    if (i === 0) return c.high - c.low
    const pc = C[i - 1].close
    return Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc))
  })
  const rng = maArr(tr, n)
  const sqz: Arr = [], src: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (basis[i] == null || dev[i] == null || rng[i] == null) { sqz.push(null); src.push(null); continue }
    const ubb = basis[i]! + bbMult * dev[i]!, lbb = basis[i]! - bbMult * dev[i]!
    const ukc = basis[i]! + kcMult * rng[i]!, lkc = basis[i]! - kcMult * rng[i]!
    sqz.push(lbb > lkc && ubb < ukc ? 0 : null)
    const hh = hhv(C, n, i), ll = llv(C, n, i)
    src.push(C[i].close - ((hh + ll) / 2 + basis[i]!) / 2)
  }
  return { sqz, src }
}

export function calcSTC(C: Candle[], f: number, s: number, cyc: number): Arr {
  const ef = calcEMA(C, f), es = calcEMA(C, s)
  const macdLine: Arr = ef.map((_, i) => (ef[i] == null || es[i] == null) ? null : ef[i]! - es[i]!)
  const stoch = (src: Arr): Arr => src.map((v, i) => {
    if (v == null) return null
    let hi = -Infinity, lo = Infinity, ok = false
    for (let j = Math.max(0, i - cyc + 1); j <= i; j++) {
      if (src[j] == null) continue
      ok = true
      if (src[j]! > hi) hi = src[j]!
      if (src[j]! < lo) lo = src[j]!
    }
    return !ok ? null : hi === lo ? 0 : (v - lo) / (hi - lo) * 100
  })
  const smooth = (a: Arr): Arr => {
    let p: number | null = null
    return a.map(v => {
      if (v == null) return p
      p = p == null ? v : p + 0.5 * (v - p)
      return p
    })
  }
  return smooth(stoch(smooth(stoch(macdLine))))
}

export function calcCR(C: Candle[], n: number): Arr {
  const ph: Arr = [], pl: Arr = []
  for (let i = 0; i < C.length; i++) {
    if (i < 1) { ph.push(0); pl.push(0); continue }
    const m = (C[i - 1].high + C[i - 1].low) / 2
    ph.push(Math.max(0, C[i].high - m))
    pl.push(Math.max(0, m - C[i].low))
  }
  const sp = rsumArr(ph, n), sm = rsumArr(pl, n)
  return sp.map((_, i) => (sp[i] == null || !sm[i]) ? null : sp[i]! / sm[i]! * 100)
}

export function calcBRAR(C: Candle[], n: number): { ar: Arr; br: Arr } {
  const ho: Arr = [], ol: Arr = [], bh: Arr = [], bl: Arr = []
  for (let i = 0; i < C.length; i++) {
    ho.push(C[i].high - C[i].open)
    ol.push(C[i].open - C[i].low)
    if (i < 1) { bh.push(0); bl.push(0) }
    else { bh.push(Math.max(0, C[i].high - C[i - 1].close)); bl.push(Math.max(0, C[i - 1].close - C[i].low)) }
  }
  const sho = rsumArr(ho, n), sol = rsumArr(ol, n), sbh = rsumArr(bh, n), sbl = rsumArr(bl, n)
  const ar: Arr = sho.map((_, i) => (sho[i] == null || !sol[i]) ? null : sho[i]! / sol[i]! * 100)
  const br: Arr = sbh.map((_, i) => (sbh[i] == null || !sbl[i]) ? null : sbh[i]! / sbl[i]! * 100)
  return { ar, br }
}
