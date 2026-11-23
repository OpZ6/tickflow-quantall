import type { IndicatorEvaluation, VolumeCompareSettings } from './custom-chart-indicators'

export interface OHLC {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  ma5?: number | null
  ma10?: number | null
  ma20?: number | null
  ma60?: number | null
  macd_dif?: number | null
  macd_dea?: number | null
  macd_hist?: number | null
  rsi_6?: number | null
  rsi_14?: number | null
  rsi_24?: number | null
  kdj_k?: number | null
  kdj_d?: number | null
  kdj_j?: number | null
  boll_upper?: number | null
  boll_lower?: number | null
  // ===== 本地扩展: 集合竞价 (AMV) 与资金族的派生列 =====
  amv_yi?: number | null
  amv_ma10?: number | null
  amv_bbi?: number | null
  amv_active_pct?: number | null
  amvchg_pct?: number | null
  amvchg_yi?: number | null
  amvchg_active_pct?: number | null
  amvpct_value?: number | null
  amvpct_active_pct?: number | null
}

export interface ChartMarker {
  date: string
  kind: 'buy' | 'sell' | 'neutral'
  label?: string
  /** 若为 true，标记放在蜡烛上方（如涨停连板标签）。 */
  above?: boolean
  /** 自定义标签颜色，覆盖默认的 kind 对应色。 */
  color?: string
  /** 明确的异动来源，避免把策略买卖点按颜色猜成涨停或炸板。 */
  event?: 'limit_up' | 'broken_limit_up' | 'limit_down' | 'limit_down_recovery'
  // ===== 本地扩展: 策略证据链标记 =====
  /** 点击标记时定位回测逐笔证据。 */
  evidenceId?: string
  /** 多标的叠加时标记所属标的。 */
  symbol?: string
}

export type DailyMarkerStyle = 'label' | 'candle'

export interface ChartRange {
  start: string
  end: string
  label?: string
  color?: string
  // ===== 本地扩展: 区间上下沿与证据回跳 =====
  high?: number
  low?: number
  evidenceId?: string
}

export interface ChartPriceLine {
  value: number
  label?: string
  color?: string
  start?: string
  end?: string
  /** 斜线价位线的终点值。 */
  endValue?: number
}

export interface StockInfo {
  name?: string
  total_shares?: number
  float_shares?: number
  /** 扩展数据（key: configId__fieldName），来自 klineDaily 的 ext_columns */
  ext?: Record<string, unknown>
}

export interface VolumeCompareConfig {
  enabled: boolean
  days: number
}

export interface DailyChartProps {
  alignedLayout?: boolean
  mainTimeAxis?: boolean
  indicatorRows?: readonly object[]
  /** Successful quote refreshes also invalidate offscreen indicator warmup. */
  indicatorRevision?: string | number
  customIndicatorValues?: IndicatorEvaluation
  customVolumeCompare?: Record<string, VolumeCompareSettings>
  data: OHLC[]
  assetType?: 'stock' | 'etf' | 'index'
  markers?: ChartMarker[]
  ranges?: ChartRange[]
  priceLines?: ChartPriceLine[]
  height?: number
  showMA?: boolean
  showInfoBar?: boolean
  showMarkers?: boolean
  markerStyle?: DailyMarkerStyle
  onToggleMarkers?: () => void
  stockInfo?: StockInfo
  symbol?: string
  linkedPrice?: number | null
  onDateClick?: (date: string) => void
  onPriceDoubleClick?: (price: number, currentPrice: number) => void
  /** 初始可见根数；'all' 适配已加载的完整日期区间。 */
  visibleBars?: number | 'all'
  /** 已激活的子图 key 列表 (含 vol, 按点击顺序) */
  activeIndicators?: string[]
  /** 成交量柱相对前 N 个交易日均量的显示设置 */
  volumeCompare?: VolumeCompareConfig
  /** 加入自选日 (北京时间 YYYY-MM-DD); 有值且落在当前区间内时, 主图画一条「自选」竖虚线 */
  addedDate?: string | null
}

export type ChartRenderer = 'echarts' | 'lightweight'
