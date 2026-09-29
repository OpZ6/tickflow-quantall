import { ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { QuantXRiskRadar } from '@/lib/api'

type Tone = 'red' | 'amber' | 'green' | null

const riskText = {
  red: 'text-red-600 dark:text-red-400',
  amber: 'text-amber-600 dark:text-amber-400',
}
const statusText = { ...riskText, green: 'text-green-600 dark:text-green-400' }
const riskDot = { red: 'bg-red-500', amber: 'bg-amber-400' }
const riskSurface = { red: 'bg-red-500/10', amber: 'bg-amber-500/10' }
const edgeTone = {
  red: 'from-red-500/20', amber: 'from-amber-500/20',
  green: 'from-green-500/20', unknown: 'from-slate-500/10',
}

function Metric({ item }: { item: { label: string; value: string; tone: Tone } }) {
  const risk = item.tone === 'red' || item.tone === 'amber' ? item.tone : null
  return <span className={cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded px-1 py-0.5 text-[11px]', risk && riskSurface[risk])} data-tone={risk || 'normal'}>
    {risk && <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', riskDot[risk])} aria-label={risk === 'red' ? '显著风险' : '需要关注'} />}
    <span className="text-muted">{item.label}</span>
    <strong className="font-mono font-semibold tabular-nums text-foreground">{item.value}</strong>
  </span>
}

export function RiskRadar({ radar }: { radar: QuantXRiskRadar | null }) {
  if (!radar) return <section data-testid="quantx-risk-signals" className="rounded-lg border border-border p-4 text-xs text-muted xl:[grid-column:span_16/span_16]">风险画像尚未生成，请刷新数据。</section>
  const normalCount = radar.dimensions.filter(item => item.tone === 'green').length
  const overallTone = radar.dimensions.some(item => item.tone === 'red') ? 'red' : radar.dimensions.some(item => item.tone !== 'green') ? 'amber' : 'green'
  return (
    <section data-testid="quantx-risk-signals" className="overflow-hidden rounded-xl border border-border bg-elevated/25 xl:[grid-column:span_16/span_16]">
      <header className="relative grid grid-cols-12 gap-4 border-b border-border px-4 py-4 md:px-6">
        <span aria-hidden="true" className={cn('pointer-events-none absolute inset-y-0 left-0 w-40 bg-gradient-to-r to-transparent', edgeTone[overallTone])} />
        <div className="relative col-span-12 min-w-0 lg:col-span-10">
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground"><ShieldAlert className="h-4 w-4" />风险画像</h2>
          <p className="mt-2 text-sm font-semibold text-foreground">{radar.headline}</p>
          <p className="mt-1 max-w-[1080px] text-xs leading-5 text-foreground/85">{radar.summary}</p>
          {radar.counter_evidence && <p className="mt-1.5 text-[11px] leading-5 text-muted">相反证据：{radar.counter_evidence}</p>}
          {radar.missing.length > 0 && <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">{radar.missing.join('、')}数据待同步，当前结论按已具备的证据生成。</p>}
        </div>
        <div className="relative col-span-12 flex items-center gap-2 border-t border-border/70 pt-2 text-xs lg:col-span-2 lg:flex-col lg:items-start lg:justify-center lg:gap-0 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          <span className="text-muted">正常维度</span>
          <strong className="font-mono text-lg font-semibold tabular-nums text-foreground">{normalCount} / {radar.dimensions.length}</strong>
        </div>
      </header>

      <div className="px-3 py-3 md:px-4">
        <div className="space-y-2">
          {radar.dimensions.map((item, index) => <div key={item.key} className="relative flex flex-wrap items-center gap-x-4 gap-y-2 overflow-hidden rounded-lg border border-border bg-base/25 px-3 py-2.5">
            <span aria-hidden="true" className={cn('pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r to-transparent', edgeTone[item.tone ?? 'unknown'])} />
            <div className="relative flex w-full shrink-0 items-center gap-2 sm:w-48">
              <span className="font-mono text-[10px] text-muted">0{index + 1}</span>
              <span className="whitespace-nowrap text-xs font-semibold">{item.title}</span>
              <span className={cn('whitespace-nowrap text-[10px]', item.tone ? statusText[item.tone] : 'text-muted')}>{item.status}</span>
            </div>
            <div className="relative flex min-w-0 flex-1 flex-wrap items-center gap-x-1 gap-y-2">{item.metrics.map(metric => <Metric key={metric.label} item={metric} />)}</div>
          </div>)}
        </div>
      </div>
    </section>
  )
}
