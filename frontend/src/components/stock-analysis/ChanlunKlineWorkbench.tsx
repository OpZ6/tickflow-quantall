import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, RefreshCw } from 'lucide-react'

import { api, type ChanlunAnalysis, type ChanlunCandleRow } from '@/lib/api'
import {
  EChartsCandlestick,
  DEFAULT_CHANLUN_CONFIG,
  buildTimeIndex,
  mapChanlunData,
  toChanlunCandles,
  type ChanlunLayerConfig,
  type OHLC,
} from '@/components/EChartsCandlestick'

interface Props {
  symbol: string
  /** 图表像素高度(默认 640;看板传入视口自适应值) */
  height?: number
}

/** 本地窗口日历天数 (不足时后端按根数实拉补齐, ≈3 年以上) */
const CHANLUN_DAYS = 800
/** ZenChart 官方窗口根数 (≈4 年日K) */
const ZEN_LIMIT = 1000

/** 对齐 openclarr 原型的三档模式 */
type ChanMode = 'both' | 'local' | 'official'

function tsToDateStr(ts: number): string {
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function rowsToOHLC(rows: ChanlunCandleRow[]): OHLC[] {
  return rows.map(r => ({
    date: r.date,
    open: Number(r.open),
    high: Number(r.high),
    low: Number(r.low),
    close: Number(r.close),
    volume: Number(r.volume ?? 0),
  }))
}

function zenToOHLC(candles: { time: number; open: number; high: number; low: number; close: number; volume?: number }[]): OHLC[] {
  return candles.map(c => ({
    date: tsToDateStr(c.time),
    open: c.open, high: c.high, low: c.low, close: c.close,
    volume: c.volume ?? 0,
  }))
}

/** 缠论图层开关按钮组 */
function LayerToggles({ config, onChange }: { config: ChanlunLayerConfig; onChange: (next: ChanlunLayerConfig) => void }) {
  const items: { key: keyof ChanlunLayerConfig; label: string; color: string }[] = [
    { key: 'showBi', label: '笔', color: '#19d3ff' },
    { key: 'showSegments', label: '线段', color: '#ff9f43' },
    { key: 'showZhongshu', label: '中枢', color: '#a55eea' },
    { key: 'showBsp', label: '买卖点', color: '#2bc983' },
  ]
  return (
    <>
      {items.map(it => (
        <label key={it.key} className="inline-flex cursor-pointer select-none items-center gap-1">
          <input
            type="checkbox"
            checked={config[it.key] !== false}
            onChange={e => onChange({ ...config, [it.key]: e.target.checked })}
            className="h-3 w-3"
          />
          <span style={{ color: it.color }}>{it.label}</span>
        </label>
      ))}
    </>
  )
}

/**
 * 原生缠论工作台 — 复刻 openclarr 原型:
 * 三档模式(叠加对比/仅本地/仅官方)。官方与叠加模式使用 ZenChart 自带 K 线窗口
 * 作为图表底座, 本地流水线在同一份 K 线上重算 —— 同 K 线同窗口层层严格对齐。
 */
export function ChanlunKlineWorkbench({ symbol, height = 640 }: Props) {
  const [mode, setMode] = useState<ChanMode>('both')
  const [config, setConfig] = useState<ChanlunLayerConfig>({ ...DEFAULT_CHANLUN_CONFIG })
  // ZenChart 只认裸代码 (600460), 剥离 600460.SH 的交易所后缀
  const zenSymbol = symbol.includes('.') ? symbol.split('.')[0] : symbol

  // ---- 仅本地模式数据源: tickflow 窗口补全 K 线 ----
  const tfKline = useQuery({
    queryKey: ['chanlun', 'candles', symbol, CHANLUN_DAYS],
    queryFn: () => api.chanlunCandles(symbol, CHANLUN_DAYS),
    enabled: !!symbol && mode === 'local',
    placeholderData: prev => prev,
    staleTime: 60_000,
  })
  const tfRows = useMemo(() => rowsToOHLC(tfKline.data?.rows ?? []), [tfKline.data?.rows])
  const tfAnalyze = useQuery({
    queryKey: ['chanlun', 'analyze-tf', symbol, tfRows.length, tfRows[tfRows.length - 1]?.date ?? ''],
    queryFn: () => api.chanlunAnalyze(toChanlunCandles(tfRows)),
    enabled: mode === 'local' && tfRows.length >= 10,
    staleTime: 60_000,
  })

  // ---- 官方 / 叠加模式数据源: ZenChart 自带 K 线 ----
  const zen = useQuery({
    queryKey: ['chanlun', 'official', zenSymbol, ZEN_LIMIT],
    queryFn: () => api.chanlunOfficial(zenSymbol, 'D1', ZEN_LIMIT),
    enabled: !!symbol && mode !== 'local',
    staleTime: 5 * 60_000,
    retry: false,
  })
  const zenCandles = useMemo(() => zen.data?.candles ?? [], [zen.data?.candles])
  const zenRows = useMemo(() => zenToOHLC(zenCandles), [zenCandles])
  const zenAnalyze = useQuery({
    queryKey: ['chanlun', 'analyze-zen', zenSymbol, zenCandles.length],
    queryFn: () => api.chanlunAnalyze(zenCandles),
    enabled: mode !== 'local' && zenCandles.length >= 10,
    staleTime: 5 * 60_000,
  })

  // ---- 当前图表底座与图层映射 ----
  const rows = mode === 'local' ? tfRows : zenRows
  const timeToIndex = useMemo(() => {
    if (mode !== 'local') {
      // Zen 模式直接用 candle.time 作 key, 免去日期往返
      const m = new Map<number, number>()
      zenCandles.forEach((c, i) => m.set(c.time, i))
      return m
    }
    return buildTimeIndex(tfRows)
  }, [mode, zenCandles, tfRows])

  // 仅官方模式: 不渲染本地图层 (chanlunLayer 置空), 只画 ZenChart 官方结构
  const localResult: ChanlunAnalysis | null | undefined =
    mode === 'local' ? tfAnalyze.data : mode === 'both' ? zenAnalyze.data : null
  const chanlunLayer = useMemo(
    () => mapChanlunData(localResult, timeToIndex),
    [localResult, timeToIndex],
  )
  const officialLayer = useMemo(
    () => (mode !== 'local' ? mapChanlunData(
      zen.data?.available
        ? ({ ...(zen.data.official ?? {}), merged_klines: [], fenxing: [], macd: [] }) as any
        : null,
      timeToIndex,
    ) : null),
    [mode, zen.data, timeToIndex],
  )

  const effConfig: ChanlunLayerConfig = {
    ...config,
    visible: true,
    showOfficial: mode !== 'local',
  }

  if (!symbol) return null

  const loading =
    (mode === 'local' && (tfKline.isLoading || (tfRows.length >= 10 && !tfAnalyze.data && tfAnalyze.isLoading))) ||
    (mode !== 'local' && (zen.isLoading || (zenCandles.length >= 10 && !zenAnalyze.data && zenAnalyze.isLoading)))
  if (loading) {
    return (
      <div className="grid min-h-[480px] place-items-center rounded-lg border border-dashed border-border bg-base/20">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Activity className="h-4 w-4 animate-pulse" />
          正在计算缠论结构…
        </div>
      </div>
    )
  }

  if (mode !== 'local' && zen.isError) {
    return (
      <div className="grid min-h-[480px] place-items-center rounded-lg border border-dashed border-border bg-base/20 px-6 text-center">
        <div>
          <p className="text-sm text-danger">ZenChart 官方服务不可用</p>
          <button
            type="button"
            onClick={() => zen.refetch()}
            disabled={zen.isFetching}
            className="mt-3 inline-flex items-center gap-1.5 rounded-btn border border-border px-3 py-1.5 text-xs text-secondary hover:bg-elevated hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${zen.isFetching ? 'animate-spin' : ''}`} />
            重试
          </button>
          <p className="mt-2 text-[10px] text-muted">可切换到「仅本地」使用内置引擎</p>
        </div>
      </div>
    )
  }
  // 官方服务可达但 K 线窗口为空 (旧响应缓存/接口变更) — 明确兜底而非静默空白
  if (mode !== 'local' && zen.isSuccess && zenCandles.length === 0) {
    return (
      <div className="grid min-h-[480px] place-items-center rounded-lg border border-dashed border-border bg-base/20 px-6 text-center">
        <div>
          <p className="text-sm text-warning">官方响应缺少 K 线数据</p>
          <button
            type="button"
            onClick={() => zen.refetch()}
            disabled={zen.isFetching}
            className="mt-3 inline-flex items-center gap-1.5 rounded-btn border border-border px-3 py-1.5 text-xs text-secondary hover:bg-elevated hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${zen.isFetching ? 'animate-spin' : ''}`} />
            重新拉取
          </button>
        </div>
      </div>
    )
  }
  if (mode === 'local' && (tfKline.isError || tfRows.length === 0)) {
    return (
      <div className="grid min-h-[480px] place-items-center rounded-lg border border-dashed border-border bg-base/20 px-6 text-center">
        <p className="text-sm text-danger">日 K 数据加载失败</p>
      </div>
    )
  }

  const localStats = localResult
    ? `本地 笔${localResult.bi.length} 段${localResult.segments.length} 中枢${localResult.zhongshu.length} 点${localResult.bsp.length}`
    : null
  const offCounts = zen.data?.available ? zen.data.counts : null

  const modes: { key: ChanMode; label: string }[] = [
    { key: 'both', label: '叠加对比' },
    { key: 'local', label: '仅本地' },
    { key: 'official', label: '仅官方' },
  ]

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted">
        <span className="inline-flex items-center gap-1 text-emerald-400">
          <Activity className="h-3 w-3" />
          缠论引擎
        </span>
        <div className="flex overflow-hidden rounded border border-border">
          {modes.map(m => (
            <button
              key={m.key}
              onClick={() => setMode(m.key)}
              className={`px-2 py-0.5 font-mono transition-colors ${
                mode === m.key ? 'bg-accent/25 text-accent' : 'bg-elevated text-muted hover:text-secondary'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <LayerToggles config={config} onChange={setConfig} />
        {localStats && (
          <>
            <span>·</span>
            <span>{localStats}</span>
          </>
        )}
        {offCounts && mode !== 'local' && (
          <>
            <span>·</span>
            <span className="text-[#f23645]">
              官方({zen.data?.source === 'pro' ? 'Pro' : '免费'}) 笔{offCounts.bi} 段{offCounts.segments} 中枢{offCounts.zhongshu}
              {zen.data?.source !== 'pro' ? ' · 免费端点无买卖点' : ''}
            </span>
          </>
        )}
      </div>
      <div className="overflow-hidden rounded-lg border border-border/60">
        {rows.length > 0 && (
          <EChartsCandlestick
            data={rows}
            height={height}
            showMA
            showInfoBar
            visibleBars={240}
            activeIndicators={['vol', 'macd']}
            chanlunData={chanlunLayer ?? undefined}
            chanlunConfig={effConfig}
            chanlunOfficial={officialLayer}
          />
        )}
      </div>
      <p className="text-[10px] leading-4 text-muted">
        叠加对比/仅官方使用 ZenChart 原生 K 线窗口，本地流水线在同一份 K 线上重算，层层严格对齐；
        官方买卖点需在后端配置 TICKFLOW_ZENCHART_TOKEN（Pro）。
      </p>
    </div>
  )
}
