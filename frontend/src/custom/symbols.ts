/**
 * 股票代码归一化工具（自定义安全区, 上游不存在此文件 → 同步零冲突）
 *
 * 后端 K 线接口按"完整代码"匹配分区数据, 传裸 6 位代码(如 600400)会返回空 rows,
 * 页面随即显示"暂无日 K 数据"且不渲染图表。URL 参数 / 手工输入 / 外部跳转
 * 经常只有裸代码, 因此在客户端统一补全交易所后缀。
 *
 * 放在独立文件而非 custom/api.ts, 是为了让 lib/api.ts 也能引用而不产生循环依赖。
 */

export function normalizeStockSymbol(raw: string): string {
  const s = (raw || '').trim().toUpperCase()
  if (!s || s.includes('.')) return s
  if (!/^\d{6}$/.test(s)) return s
  const head = s[0]
  // 沪市: 6xxxxx 股票 / 5xxxxx ETF 基金 / 9xxxxx B 股
  if (head === '6' || head === '5' || head === '9') return `${s}.SH`
  // 深市: 0xxxxx / 3xxxxx 股票 / 1xxxxx ETF 基金 / 2xxxxx B 股
  if (head === '0' || head === '1' || head === '2' || head === '3') return `${s}.SZ`
  // 北交所: 4xxxxx / 8xxxxx
  if (head === '4' || head === '8') return `${s}.BJ`
  return s
}
