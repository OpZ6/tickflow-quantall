import { ChevronDown, ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { QuantXRiskRadar } from '@/lib/api'

export function RiskRadar({ radar }: { radar: QuantXRiskRadar | null }) {
  if (!radar) return <section data-testid="quantx-risk-signals" className="rounded-lg border border-border p-4 text-xs text-muted xl:[grid-column:span_16/span_16]">市场风险画像尚未生成，请刷新数据。</section>
  const toneClass = {
    red: 'border-red-500/50 bg-red-500/10 text-red-300',
    amber: 'border-orange-500/50 bg-orange-500/10 text-orange-300',
    green: 'border-green-500/40 bg-green-500/10 text-green-300',
  }
  return (
    <section data-testid="quantx-risk-signals" className="overflow-hidden rounded-lg border border-border bg-elevated/25 xl:[grid-column:span_16/span_16]">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border/70 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2"><ShieldAlert className="h-4 w-4 shrink-0 text-orange-400" /><h2 className="shrink-0 text-xs font-semibold">市场风险画像</h2><strong className="truncate text-xs font-semibold" title={radar.headline}>{radar.headline}</strong></div>
        <p className="min-w-0 flex-1 truncate text-right text-[10px] text-muted" title={radar.summary}>{radar.summary}</p>
      </header>
      {radar.missing.length > 0 && <p className="mx-3 mt-2 rounded border border-orange-500/40 bg-orange-500/10 px-2 py-1 text-[10px] text-orange-300">{radar.missing.join('、')}数据待同步，暂不生成完整风险结论。</p>}
      <div className="grid gap-2 p-2.5 sm:grid-cols-2 lg:grid-cols-5">
        {radar.dimensions.map((item, index) => <div key={item.key} className={cn('min-w-0 rounded-md border bg-base/35 px-2.5 py-2', item.tone ? toneClass[item.tone] : 'border-border/70')}>
          <div className="truncate text-[10px] text-muted">0{index + 1} {item.title}</div>
          <div className="mt-1 truncate text-xs font-semibold" title={item.status}>{item.status}</div>
        </div>)}
      </div>
      <div className="space-y-1 border-t border-border/70 p-2.5 pt-2">
        {radar.dimensions.map(item => <details key={item.key} className="group min-w-0 rounded-md border border-border/70 bg-base/25 open:border-border">
          <summary className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 marker:hidden">
            <span className="w-28 shrink-0 text-[11px] font-semibold">{item.title}</span>
            <span className={cn('w-28 shrink-0 text-[10px]', item.tone === 'red' ? 'text-red-300' : item.tone === 'amber' ? 'text-orange-300' : item.tone === 'green' ? 'text-green-300' : 'text-muted')}>{item.status}</span>
            <span className="order-last flex min-w-0 w-full flex-wrap gap-x-5 gap-y-1 sm:order-none sm:w-auto sm:flex-1">{item.metrics.map(metric => <span key={metric.label} className="whitespace-nowrap text-[10px]"><span className="text-muted">{metric.label} </span><b className="font-mono text-foreground">{metric.value}</b></span>)}</span>
            <ChevronDown className="h-3 w-3 shrink-0 text-muted transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-border/60 px-3 py-2 text-[10px] leading-5 text-muted">
            <p>{item.explanation}</p>
            {item.details.length > 0 && <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1">{item.details.map(detail => <span key={detail.label}>{detail.label} <b className="font-mono font-medium text-foreground">{detail.value}</b></span>)}</div>}
            <p className="mt-1">来源：{item.source}</p>
          </div>
        </details>)}
      </div>
    </section>
  )
}
