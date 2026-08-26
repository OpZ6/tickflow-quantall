/**
 * 多日驾驶舱 — 总面板。
 *
 * 跨日表格 · 14 列 · 点击日期行进入单日复盘 /quantx/:date。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Loader2, LayoutGrid } from 'lucide-react'
import { quantxApi } from '@/lib/api'
import { toast } from '@/components/Toast'
import { cn } from '@/lib/cn'

function scoreColor(score: number): string {
  if (score >= 70) return '#ef4444'
  if (score >= 60) return '#f97316'
  if (score >= 40) return '#3b82f6'
  if (score >= 30) return '#6b7280'
  return '#1e40af'
}

export function QuantXCatalog() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [sortKey, setSortKey] = useState<'date' | 'heat' | 'limit_up' | 'advance'>('date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data, isLoading } = useQuery({
    queryKey: ['quantx-catalog'],
    queryFn: () => quantxApi.getCatalog(),
    retry: false,
    staleTime: 0,
  })

  const buildMut = useMutation({
    mutationFn: () => quantxApi.buildCatalog(),
    onSuccess: () => { toast('驾驶舱构建完成', 'success'); qc.invalidateQueries({ queryKey: ['quantx-catalog'] }) },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const records = [...(data?.records || [])]
  records.sort((a, b) => {
    let av: number | string = 0, bv: number | string = 0
    if (sortKey === 'date') { av = a.trade_date; bv = b.trade_date }
    else if (sortKey === 'heat') { av = (a.metrics.market_heat_score as number) ?? 0; bv = (b.metrics.market_heat_score as number) ?? 0 }
    else if (sortKey === 'limit_up') { av = (a.metrics.limit_up_count as number) ?? 0; bv = (b.metrics.limit_up_count as number) ?? 0 }
    else if (sortKey === 'advance') { av = (a.metrics.advance_rate as number) ?? 0; bv = (b.metrics.advance_rate as number) ?? 0 }
    const cmp = typeof av === 'string' && typeof bv === 'string' ? av.localeCompare(bv) : (av as number) - (bv as number)
    return sortDir === 'desc' ? -cmp : cmp
  })

  function toggleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortKey(key); setSortDir('desc') }
  }

  if (isLoading) return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted" /></div>

  return (
    <div className="mx-auto max-w-7xl p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <LayoutGrid className="h-5 w-5 text-accent" />
          <h1 className="text-xl font-bold">多日驾驶舱</h1>
          {data && <span className="text-xs text-muted">{data.stats.total_dates} 日 · 完整 {data.stats.complete}</span>}
        </div>
        <button onClick={() => buildMut.mutate()} disabled={buildMut.isPending}
          className="inline-flex items-center gap-1.5 rounded-btn bg-accent/20 px-3 py-1.5 text-xs text-accent hover:bg-accent/30 disabled:opacity-50">
          {buildMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          构建
        </button>
      </div>

      {records.length === 0 ? (
        <div className="text-center py-16 text-muted text-sm">无数据，点击「构建」</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-elevated sticky top-0 z-10">
              <tr>
                <th className="px-3 py-2 text-left cursor-pointer hover:text-accent" onClick={() => toggleSort('date')}>日期 {sortKey === 'date' && (sortDir === 'desc' ? '↓' : '↑')}</th>
                <th className="px-3 py-2 text-left cursor-pointer hover:text-accent" onClick={() => toggleSort('heat')}>热度 {sortKey === 'heat' && (sortDir === 'desc' ? '↓' : '↑')}</th>
                <th className="px-3 py-2 text-left">短线</th>
                <th className="px-3 py-2 text-left">趋势</th>
                <th className="px-3 py-2 text-left cursor-pointer hover:text-accent" onClick={() => toggleSort('limit_up')}>涨停 {sortKey === 'limit_up' && (sortDir === 'desc' ? '↓' : '↑')}</th>
                <th className="px-3 py-2 text-left">封板率</th>
                <th className="px-3 py-2 text-left">板高</th>
                <th className="px-3 py-2 text-left cursor-pointer hover:text-accent" onClick={() => toggleSort('advance')}>晋级率 {sortKey === 'advance' && (sortDir === 'desc' ? '↓' : '↑')}</th>
                <th className="px-3 py-2 text-left">参与度</th>
                <th className="px-3 py-2 text-left">退潮</th>
                <th className="px-3 py-2 text-left">崩塌</th>
                <th className="px-3 py-2 text-left">变化</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => {
                const m = r.metrics || {}
                const heat = (m.market_heat_score as number) ?? 0
                return (
                  <tr key={r.trade_date}
                    className="border-t border-border hover:bg-accent/10 cursor-pointer transition-colors"
                    onClick={() => navigate(`/quantx/${r.trade_date}`)}>
                    <td className="px-3 py-1.5 font-mono font-semibold">{r.trade_date}</td>
                    <td className="px-3 py-1.5">
                      <span className="inline-block w-7 h-5 leading-5 text-center rounded text-white font-semibold text-[10px]" style={{ backgroundColor: scoreColor(heat) }}>{heat || '--'}</span>
                      <span className="ml-1 text-muted text-[10px]">{m.market_heat_zone}</span>
                    </td>
                    <td className="px-3 py-1.5">{m.short_term_sentiment_score ?? '--'}</td>
                    <td className="px-3 py-1.5">{m.trend_sentiment_score ?? '--'}</td>
                    <td className="px-3 py-1.5">{m.limit_up_count ?? '--'}</td>
                    <td className="px-3 py-1.5">{m.seal_rate != null ? `${m.seal_rate}%` : '--'}</td>
                    <td className="px-3 py-1.5">{m.max_board ?? '--'}</td>
                    <td className="px-3 py-1.5">{m.advance_rate != null ? `${m.advance_rate}%` : '--'}</td>
                    <td className="px-3 py-1.5">{m.participation_verdict ?? ''}</td>
                    <td className={cn('px-3 py-1.5', (m.ebb_signal_count as number) > 0 && 'text-orange-400')}>{m.ebb_risk_verdict ?? ''}</td>
                    <td className={cn('px-3 py-1.5', m.crash_triggered ? 'text-red-400 font-semibold' : 'text-muted')}>{m.crash_triggered ? '是' : '否'}</td>
                    <td className="px-3 py-1.5 text-muted text-[10px] max-w-[120px] truncate">{r.change_summary}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
