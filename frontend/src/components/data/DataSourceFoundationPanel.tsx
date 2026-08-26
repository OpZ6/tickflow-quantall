import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, DatabaseZap, Route, ServerCog } from 'lucide-react'

import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

const DATASET_LABELS: Record<string, string> = {
  market_breadth_daily: '市场宽度',
  limit_event_daily: '涨跌停事件',
  theme_observation_daily: '题材观察',
  sector_flow_daily: '行业资金流',
}

function StatusBadge({ status }: { status: string }) {
  const healthy = status === 'ok' || status === 'complete'
  const warning = status === 'degraded' || status === 'empty' || status === 'partial'
  const className = healthy
    ? 'border-bull/30 bg-bull/10 text-bull'
    : warning
      ? 'border-warning/30 bg-warning/10 text-warning'
      : 'border-danger/30 bg-danger/10 text-danger'
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] ${className}`}>{status}</span>
}

export function DataSourceFoundationPanel() {
  const query = useQuery({
    queryKey: QK.dataFoundation,
    queryFn: api.marketDataFoundation,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (query.isLoading) {
    return <div className="h-40 animate-pulse rounded-card border border-border bg-elevated/30" />
  }
  if (query.isError || !query.data) {
    return (
      <div className="rounded-card border border-danger/30 bg-danger/5 p-4 text-sm text-danger">
        统一数据源状态加载失败：{String(query.error ?? 'unknown error')}
      </div>
    )
  }

  const { datasets, sources, routes, health } = query.data
  const healthBySource = new Map(health.sources.map(item => [item.source_id, item]))
  const dependencyProblems = sources.filter(
    source => !source.dependency_available || !source.credentials_configured,
  ).length

  return (
    <section data-testid="data-source-foundation" className="rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div className="flex items-start gap-2">
          <DatabaseZap className="mt-0.5 h-4 w-4 text-accent" />
          <div>
            <h3 className="text-sm font-medium text-foreground">统一市场数据底座</h3>
            <p className="mt-0.5 text-[11px] text-muted">Dataset 路由、依赖、最近采集和标准事实覆盖</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted">
          <StatusBadge status={health.status} />
          <span>最近交易日 {health.latest_trade_date ?? '尚未运行'}</span>
          <span>·</span>
          <span>{datasets.length} 个标准数据集</span>
          {dependencyProblems > 0 && <span className="text-warning">· {dependencyProblems} 项依赖待配置</span>}
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_1fr]">
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-secondary">
            <Route className="h-3.5 w-3.5" />数据集路由
          </div>
          <div className="space-y-2">
            {routes.map(route => (
              <div key={route.dataset_id} className="rounded border border-border/70 bg-elevated/30 px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="mr-1 text-xs font-medium text-foreground">
                    {DATASET_LABELS[route.dataset_id] ?? route.dataset_id}
                  </span>
                  {route.sources.map((source, index) => {
                    const state = healthBySource.get(source)
                    return (
                      <span key={source} className="contents">
                        {index > 0 && <span className="text-[10px] text-muted">→</span>}
                        <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] text-secondary">
                          {source}{state?.used_fallback ? ' · fallback' : ''}
                        </span>
                      </span>
                    )
                  })}
                </div>
                <div className="mt-1 text-[10px] text-muted">
                  schema v{datasets.find(item => item.dataset_id === route.dataset_id)?.schema_version ?? '—'} · 按交易日分区
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-secondary">
            <ServerCog className="h-3.5 w-3.5" />来源健康与覆盖
          </div>
          <div className="max-h-64 space-y-1.5 overflow-auto pr-1">
            {sources.map(source => {
              const state = healthBySource.get(source.source_id)
              const ready = source.dependency_available && source.credentials_configured
              return (
                <div key={source.source_id} className="flex items-center gap-2 rounded border border-border/60 px-2.5 py-1.5 text-[10px]">
                  {ready
                    ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-bull" />
                    : <CircleAlert className="h-3.5 w-3.5 shrink-0 text-warning" />}
                  <span className="min-w-28 font-mono text-secondary">{source.source_id}</span>
                  <span className="min-w-16 text-muted">{source.collector_type}</span>
                  <span className="ml-auto text-muted">{state?.record_count?.toLocaleString() ?? '—'} 条</span>
                  <StatusBadge status={state?.status ?? (ready ? 'unknown' : 'dependency')} />
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}
