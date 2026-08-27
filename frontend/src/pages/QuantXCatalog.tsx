import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, ExternalLink, LayoutGrid, Loader2, RefreshCw } from 'lucide-react'
import { quantxApi } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { toast } from '@/components/Toast'
import {
  FactorAttribution,
  SectorFlowContinuity,
  OpportunityRadar,
  ThemeLifecyclePanel,
  TradingCalendar,
  WindowSignalMatrix,
  WindowStatistics,
  type WindowSize,
} from '@/components/quantx/MultidayPanels'

export function QuantXCatalog() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedDate, setSelectedDate] = useState('')
  const [windowSize, setWindowSize] = useState<WindowSize>(20)

  const catalogQuery = useQuery({ queryKey: QK.quantxCatalog, queryFn: quantxApi.getCatalog, staleTime: 30_000, retry: false })
  const records = useMemo(() => catalogQuery.data?.records || [], [catalogQuery.data])
  const dates = useMemo(() => records.map(record => record.trade_date), [records])
  const latestPublishedDate = useMemo(
    () => records.filter(record => record.multiday_available).at(-1)?.trade_date || '',
    [records],
  )
  useEffect(() => {
    if (!selectedDate && latestPublishedDate) setSelectedDate(latestPublishedDate)
  }, [latestPublishedDate, selectedDate])

  const snapshotQuery = useQuery({
    queryKey: QK.quantxMultiday(selectedDate),
    queryFn: () => quantxApi.getMultiday(selectedDate),
    enabled: Boolean(selectedDate),
    staleTime: 30_000,
    retry: false,
  })

  const rebuild = useMutation({
    mutationFn: () => quantxApi.buildCatalog(selectedDate),
    onSuccess: result => {
      toast(`多日派生数据已重建：${result.rebuilt} 日`, 'success')
      queryClient.invalidateQueries({ queryKey: QK.quantxCatalog })
      queryClient.invalidateQueries({ queryKey: ['quantx-multiday'] })
    },
    onError: (error: Error) => toast(error.message, 'error'),
  })

  if (catalogQuery.isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>
  const snapshot = snapshotQuery.data

  return <div className="mx-auto max-w-[1500px] space-y-4 p-4 pb-20">
    <header className="flex flex-wrap items-center gap-3">
      <LayoutGrid className="h-5 w-5 text-accent" />
      <div><h1 className="text-xl font-bold">QuantX 多日驾驶舱</h1><p className="text-[11px] text-muted">独立确定性数据管线 · 不含 LLM 分析</p></div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <select aria-label="多日驾驶舱交易日" value={selectedDate} onChange={event => setSelectedDate(event.target.value)} className="rounded-btn border border-border bg-elevated px-3 py-1.5 text-sm font-semibold">
          {[...dates].reverse().map(date => <option key={date} value={date}>{date}</option>)}
        </select>
        <button onClick={() => selectedDate && navigate(`/quantx/${selectedDate}`)} disabled={!selectedDate} className="inline-flex items-center gap-1.5 rounded-btn border border-border px-3 py-1.5 text-xs text-muted hover:text-foreground"><ExternalLink className="h-3 w-3" />单日数据</button>
        <button onClick={() => rebuild.mutate()} disabled={rebuild.isPending} className="inline-flex items-center gap-1.5 rounded-btn bg-accent/20 px-3 py-1.5 text-xs text-accent hover:bg-accent/30 disabled:opacity-50">
          {rebuild.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}重建多日数据
        </button>
      </div>
    </header>

    <div className="flex flex-wrap gap-2 text-[11px] text-muted">
      <span className="rounded bg-elevated px-2 py-1">{records.length} 个交易日</span>
      <span className="rounded bg-elevated px-2 py-1">完整 {catalogQuery.data?.stats.complete || 0}</span>
      <span className="rounded bg-elevated px-2 py-1">仅数据 {catalogQuery.data?.stats.data_only || 0}</span>
      <span className="rounded bg-elevated px-2 py-1">降级 {catalogQuery.data?.stats.degraded || 0}</span>
    </div>

    {snapshotQuery.isLoading && <div className="flex justify-center rounded-xl border border-border py-20"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>}
    {snapshotQuery.error && <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-center text-sm text-red-300">多日数据加载失败：{(snapshotQuery.error as Error).message}</div>}
    {snapshot && <>
      <div className="grid gap-2 sm:grid-cols-3" data-testid="quantx-data-coverage">
        <div className="rounded-lg border border-border bg-elevated/30 p-2"><div className="text-[10px] text-muted">窗口覆盖</div><div className="font-mono text-lg">{snapshot.data_coverage.window_days}/20 日</div></div>
        <div className="rounded-lg border border-border bg-elevated/30 p-2"><div className="text-[10px] text-muted">题材覆盖</div><div className="font-mono text-lg">{snapshot.data_coverage.theme_days}/20 日</div></div>
        <div className="rounded-lg border border-border bg-elevated/30 p-2"><div className="text-[10px] text-muted">行业资金覆盖</div><div className="font-mono text-lg">{snapshot.data_coverage.sector_flow_days}/20 日</div></div>
      </div>
      <WindowSignalMatrix data={snapshot} active={windowSize} onChange={setWindowSize} />
      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]"><TradingCalendar rows={snapshot.calendar} selectedDate={selectedDate} onSelect={setSelectedDate} /><WindowStatistics data={snapshot} active={windowSize} /></div>
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]"><ThemeLifecyclePanel data={snapshot} /><FactorAttribution rows={snapshot.factor_attribution} /></div>
      <OpportunityRadar data={snapshot.opportunity_radar} />
      <SectorFlowContinuity data={snapshot.sector_flow_continuity} />
    </>}

    {!snapshot && !snapshotQuery.isLoading && records.length === 0 && <div className="rounded-xl border border-border py-20 text-center text-sm text-muted"><Database className="mx-auto mb-2 h-8 w-8" />暂无 QuantX 数据</div>}
  </div>
}
