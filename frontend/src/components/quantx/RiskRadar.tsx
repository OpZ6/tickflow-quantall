import { ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { QuantXRiskRadar } from '@/lib/api'

type Tone = 'red' | 'amber' | 'green' | null

const riskText = {
  red: 'text-red-600 dark:text-red-400',
  amber: 'text-amber-600 dark:text-amber-400',
}
const riskDot = { red: 'bg-red-500', amber: 'bg-amber-400' }

function Metric({ item }: { item: { label: string; value: string; tone: Tone } }) {
  const risk = item.tone === 'red' || item.tone === 'amber' ? item.tone : null
  const directional = item.label === '上涨' || item.label === '下跌' || /^[+-]\d/.test(item.value)
  const falling = item.label === '下跌' || item.value.startsWith('-')
  return <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[11px]" data-tone={risk || 'normal'}>
    {risk && <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', riskDot[risk])} aria-label={risk === 'red' ? '显著风险' : '需要关注'} />}
    <span className="text-muted">{item.label}</span>
    <strong className={cn('font-mono font-semibold tabular-nums', directional ? falling ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400' : risk ? riskText[risk] : 'text-foreground')}>{item.value}</strong>
  </span>
}

export function RiskRadar({ radar }: { radar: QuantXRiskRadar | null }) {
  if (!radar) return <section data-testid="quantx-risk-signals" className="rounded-lg border border-border p-4 text-xs text-muted xl:[grid-column:span_16/span_16]">风险画像尚未生成，请刷新数据。</section>
  return (
    <section data-testid="quantx-risk-signals" className="overflow-hidden rounded-xl border border-border bg-elevated/25 xl:[grid-column:span_16/span_16]">
      <header className="grid grid-cols-12 gap-4 border-b border-border bg-gradient-to-br from-orange-500/10 via-elevated/30 to-base/20 px-4 py-4 md:px-6">
        <div className="col-span-12 min-w-0 lg:col-span-10">
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground"><ShieldAlert className="h-4 w-4 text-orange-600 dark:text-orange-400" />风险画像</h2>
          <p className="mt-2 text-sm font-semibold text-foreground">{radar.headline}</p>
          <p className="mt-1 max-w-[1080px] text-xs leading-5 text-foreground/85">{radar.summary}</p>
          {radar.counter_evidence && <p className="mt-1.5 text-[11px] leading-5 text-muted">相反证据：{radar.counter_evidence}</p>}
          {radar.missing.length > 0 && <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">{radar.missing.join('、')}数据待同步，当前结论按已具备的证据生成。</p>}
        </div>
        <div className="col-span-12 flex items-center gap-2 border-t border-border/70 pt-2 text-xs lg:col-span-2 lg:flex-col lg:items-start lg:justify-center lg:gap-0 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          <span className="text-muted">证据覆盖</span>
          <strong className="font-mono text-lg font-semibold tabular-nums text-foreground">{radar.coverage.complete} / {radar.coverage.total}</strong>
        </div>
      </header>

      <div className="px-3 py-3 md:px-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">五维证据</h3><span className="text-[10px] text-muted">红点：显著风险　橙点：需要关注；涨跌数值按红涨绿跌</span></div>
        <div className="space-y-2">
          {radar.dimensions.map((item, index) => <div key={item.key} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-base/25 px-3 py-2.5">
            <div className="flex w-full shrink-0 items-center gap-2 sm:w-48">
              <span className="font-mono text-[10px] text-muted">0{index + 1}</span>
              <span className="whitespace-nowrap text-xs font-semibold">{item.title}</span>
              <span className={cn('whitespace-nowrap text-[10px]', item.tone === 'red' || item.tone === 'amber' ? riskText[item.tone] : 'text-foreground')}>{item.status}</span>
            </div>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2">{item.metrics.map(metric => <Metric key={metric.label} item={metric} />)}
              {item.key === 'trend' && item.series.filter(line => line.kind === 'ordinary').map(line => <Metric key={line.code} item={{ label: line.name, value: `${line.deviation_pct >= 0 ? '+' : ''}${line.deviation_pct.toFixed(2)}%`, tone: line.tone }} />)}
            </div>
          </div>)}
        </div>
      </div>
    </section>
  )
}
