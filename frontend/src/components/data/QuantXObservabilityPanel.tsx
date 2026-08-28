import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ExternalLink, RefreshCw, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { api, quantxApi } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

function Badge({ value }: { value: string }) {
  const ok = ['ok', 'complete', 'present', 'fresh'].includes(value)
  const cls = ok ? 'border-bull/30 bg-bull/10 text-bull' : 'border-warning/30 bg-warning/10 text-warning'
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] ${cls}`}>{value}</span>
}

export function QuantXObservabilityPanel({ pipelineJobId }: { pipelineJobId?: string | null }) {
  const qc = useQueryClient()
  const foundation = useQuery({ queryKey: QK.dataFoundation, queryFn: api.marketDataFoundation })
  const date = foundation.data?.health.latest_trade_date ?? ''
  const query = useQuery({
    queryKey: QK.quantxObservability(date),
    queryFn: () => quantxApi.getObservability(date, pipelineJobId),
    enabled: Boolean(date),
    refetchInterval: 60_000,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: QK.quantxObservability(date) })
    qc.invalidateQueries({ queryKey: QK.dataFoundation })
    qc.invalidateQueries({ queryKey: QK.quantxCatalog })
  }
  const run = useMutation({ mutationFn: () => quantxApi.runData(date, { force: true }), onSuccess: refresh })
  const resume = useMutation({ mutationFn: () => quantxApi.resumeData(date), onSuccess: refresh })
  const recompute = useMutation({ mutationFn: () => quantxApi.recomputeData(date), onSuccess: refresh })
  const retry = useMutation({ mutationFn: (source: string) => quantxApi.retrySource(date, source), onSuccess: refresh })

  if (!date) return null
  if (query.isLoading) return <div className="h-48 animate-pulse rounded-card border border-border bg-elevated/30" />
  if (!query.data) return <div className="rounded-card border border-warning/30 bg-warning/5 p-4 text-xs text-warning">QuantX 发布状态暂不可用：{String(query.error ?? 'unknown error')}</div>
  const data = query.data
  const pending = run.isPending || resume.isPending || recompute.isPending || retry.isPending

  return (
    <section data-testid="quantx-observability" className="rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div className="flex items-start gap-2">
          <Activity className="mt-0.5 h-4 w-4 text-accent" />
          <div><h3 className="text-sm font-medium">QuantX 发布、质量与血缘</h3><p className="mt-0.5 text-[11px] text-muted">{data.trade_date} · 主任务 {data.pipeline_job_id ?? '独立运行'} · QuantX {data.quantx_run_id ?? '—'}</p></div>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <button disabled={pending} onClick={() => run.mutate()} className="rounded border border-border px-2 py-1 hover:bg-elevated disabled:opacity-50"><RefreshCw className="mr-1 inline h-3 w-3" />重新采集</button>
          <button disabled={pending} onClick={() => resume.mutate()} className="rounded border border-border px-2 py-1 hover:bg-elevated disabled:opacity-50">继续运行</button>
          <button disabled={pending} onClick={() => recompute.mutate()} className="rounded border border-border px-2 py-1 hover:bg-elevated disabled:opacity-50"><RotateCcw className="mr-1 inline h-3 w-3" />离线重算</button>
          <Link to="/settings?tab=data-sources" className="rounded border border-border px-2 py-1 hover:bg-elevated">数据源管理 <ExternalLink className="inline h-3 w-3" /></Link>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-[11px]">
        <div className="rounded border border-border p-2">发布状态 <Badge value={data.status} /><div className="mt-1 text-muted">{data.published_at ?? '—'}</div></div>
        <div className="rounded border border-border p-2">事实分区 <b className="ml-1 font-mono">{data.fact_summary.present_partition_count}/{data.fact_summary.expected_partition_count}</b><div className="mt-1 text-muted">缺口 {data.fact_summary.gap_partition_count}</div></div>
        <div className="rounded border border-border p-2">V2 视图 <b className="ml-1 font-mono">{data.view.canonical_count} canonical</b><div className="mt-1 text-muted">derived {data.view.derived_count} · cache/fallback {data.view.cache_count}/{data.view.fallback_count}</div></div>
        <div className="rounded border border-border p-2">联动发布 <div className="mt-1"><Badge value={data.multiday.published ? 'multiday ok' : 'multiday missing'} /> <Badge value={data.catalog.published ? 'catalog ok' : 'catalog missing'} /></div></div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div><h4 className="mb-2 text-xs font-medium text-secondary">来源采集</h4><div className="max-h-72 space-y-1 overflow-auto">
          {data.sources.map(source => <div key={source.source_id} className="flex flex-wrap items-center gap-2 rounded border border-border/60 px-2 py-1.5 text-[10px]">
            <span className="min-w-24 font-mono">{source.source_id}</span><span className="text-muted">{source.required ? 'required' : 'optional'}</span><Badge value={source.status} /><Badge value={source.freshness} /><span className="ml-auto font-mono text-muted">{source.record_count.toLocaleString()} 条</span>
            {(source.status !== 'ok' || source.error) && <button disabled={pending} onClick={() => retry.mutate(source.source_id)} className="text-accent hover:underline">retry</button>}
            {source.error && <div className="w-full truncate text-danger" title={source.error}>{source.error_kind}: {source.error}</div>}
          </div>)}
        </div></div>
        <div><h4 className="mb-2 text-xs font-medium text-secondary">13 类标准事实</h4><div className="max-h-72 space-y-1 overflow-auto">
          {data.facts.map(fact => <div key={fact.dataset_id} className="rounded border border-border/60 px-2 py-1.5 text-[10px]" title={`${fact.path}\n${fact.sha256 ?? ''}`}><div className="flex items-center gap-2"><span className="min-w-40 font-mono">{fact.dataset_id}</span><Badge value={fact.status} /><span className="ml-auto font-mono text-muted">{fact.row_count ?? 0} 行 · {(fact.coverage * 100).toFixed(0)}%</span></div><div className="mt-0.5 truncate text-muted">{fact.quality_level}</div></div>)}
        </div></div>
      </div>
      <div className="mt-3 text-[10px] text-muted">治理指标：字段漂移 {data.metrics.field_drift} · 陈旧快照 {data.metrics.stale_snapshot} · 空结果 {data.metrics.empty_result} · 限流 {data.metrics.rate_limit} · reconciliation {data.reconciliation.status}</div>
    </section>
  )
}
