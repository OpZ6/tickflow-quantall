import { ChevronDown, ShieldAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { QuantXRiskRadar } from '@/lib/api'

type Tone = 'red' | 'amber' | 'green' | null

const textTone: Record<Exclude<Tone, null>, string> = {
  red: 'text-red-700 dark:text-red-300',
  amber: 'text-amber-700 dark:text-amber-300',
  green: 'text-green-700 dark:text-green-300',
}
const ruleTone: Record<Exclude<Tone, null>, string> = {
  red: 'bg-red-500', amber: 'bg-amber-400', green: 'bg-green-500',
}

function Metric({ item }: { item: { label: string; value: string; tone: Tone } }) {
  return <div className="min-w-0" data-tone={item.tone || 'context'}>
    <span className="block truncate text-[10px] text-muted" title={item.label}>{item.label}</span>
    <strong className={cn('mt-0.5 block truncate font-mono text-sm font-semibold tabular-nums', item.tone ? textTone[item.tone] : 'text-foreground')} title={item.value}>{item.value}</strong>
  </div>
}

export function RiskRadar({ radar }: { radar: QuantXRiskRadar | null }) {
  if (!radar) return <section data-testid="quantx-risk-signals" className="rounded-lg border border-border p-4 text-xs text-muted xl:[grid-column:span_16/span_16]">市场风险画像尚未生成，请刷新数据。</section>
  return (
    <section data-testid="quantx-risk-signals" className="overflow-hidden rounded-xl border border-border bg-elevated/25 xl:[grid-column:span_16/span_16]">
      <header className="grid grid-cols-12 gap-5 border-b border-border bg-gradient-to-br from-orange-500/10 via-elevated/30 to-base/20 px-4 py-5 md:px-6">
        <div className="col-span-12 min-w-0 lg:col-span-10">
          <div className="flex items-center gap-2 text-[10px] font-bold tracking-[0.14em] text-orange-700 dark:text-orange-300"><ShieldAlert className="h-3.5 w-3.5" />QUANTX / 收盘风险画像</div>
          <h2 className="mt-2 text-xl font-bold leading-tight text-foreground md:text-2xl">{radar.headline}</h2>
          <p className="mt-3 max-w-[1080px] text-xs leading-6 text-foreground/85 md:text-[13px]">{radar.summary}</p>
          {radar.counter_evidence && <p className="mt-2 text-[11px] leading-5 text-muted">相反证据：{radar.counter_evidence}</p>}
          {radar.missing.length > 0 && <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">{radar.missing.join('、')}数据待同步，当前结论按已具备的证据生成。</p>}
        </div>
        <div className="col-span-12 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/70 pt-3 lg:col-span-2 lg:flex-col lg:items-start lg:justify-center lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          <span className="text-[10px] text-muted">证据覆盖</span>
          <strong className="font-mono text-2xl font-bold tabular-nums text-foreground">{radar.coverage.complete} / {radar.coverage.total}</strong>
          <span className="text-[10px] leading-4 text-muted">五维已发布事实与指数日线</span>
        </div>
      </header>

      <div className="px-3 pb-3 pt-4 md:px-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">五维证据</h3><span className="text-[10px] text-muted">每维展示全部已核对数值 · 点击可查看口径与指数明细</span></div>
        <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {radar.dimensions.map((item, index) => <div key={item.key} className="min-w-0 rounded-lg border border-border bg-base/35 px-3 py-2.5">
            <div className="truncate text-[10px] text-muted">0{index + 1} {item.title}</div>
            <div className={cn('mt-1.5 truncate text-xs font-semibold', item.tone ? textTone[item.tone] : 'text-foreground')} title={item.status}>{item.status}</div>
            <div className={cn('mt-3 h-0.5 rounded-full', item.tone ? ruleTone[item.tone] : 'bg-border')} />
          </div>)}
        </div>
        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted" aria-label="状态颜色说明"><span><b className={textTone.red}>红色</b> 显著风险</span><span><b className={textTone.amber}>橙色</b> 需要关注</span><span><b className={textTone.green}>绿色</b> 正常</span><span>单项数值按自身条件着色</span></div>

        <div className="space-y-2">
          {radar.dimensions.map((item, index) => <details key={item.key} className="group rounded-lg border border-border bg-base/25 open:border-border/90">
            <summary className="relative grid cursor-pointer list-none grid-cols-12 items-center gap-3 px-3 py-3 pr-8 transition-colors hover:bg-elevated/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
              <span className="col-span-2 flex h-8 w-8 items-center justify-center rounded-md bg-elevated font-mono text-[11px] font-bold text-muted sm:col-span-1">0{index + 1}</span>
              <span className="col-span-10 min-w-0 sm:col-span-3 lg:col-span-2"><span className="block text-xs font-semibold">{item.title}</span><span className={cn('mt-0.5 block truncate text-[10px]', item.tone ? textTone[item.tone] : 'text-muted')}>{item.status}</span></span>
              <div className="col-span-12 grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 sm:col-span-8 sm:grid-cols-3 lg:col-span-9 lg:grid-cols-4 xl:grid-cols-6">{item.metrics.map(metric => <Metric key={metric.label} item={metric} />)}</div>
              <ChevronDown className="absolute right-3 top-4 h-3.5 w-3.5 text-muted transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <div className="border-t border-border/70 px-4 pb-4 pt-3 text-[11px] leading-5 md:pl-[62px]">
              <p className="text-foreground/85">{item.explanation}</p>
              {item.details.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{item.details.map(detail => <div key={detail.label} className="flex min-w-0 justify-between gap-3 rounded-md bg-elevated/65 px-2.5 py-1.5"><span className="truncate text-muted" title={detail.label}>{detail.label}</span><b className={cn('shrink-0 font-mono font-semibold tabular-nums', detail.tone ? textTone[detail.tone] : 'text-foreground')}>{detail.value}</b></div>)}</div>}
              {(['ordinary', 'sentiment'] as const).map(kind => {
                const lines = item.series.filter(line => line.kind === kind)
                if (!lines.length) return null
                return <div key={kind} className="mt-4"><h4 className="mb-2 text-[11px] font-semibold">{kind === 'ordinary' ? '普通指数 · MA10 偏离' : '通达信四情绪 · MA10 偏离'}</h4><div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{lines.map(line => <div key={line.code} className="rounded-md border border-border bg-elevated/60 px-3 py-2.5"><div className="flex justify-between gap-2 text-[10px]"><b className="truncate">{line.name}</b><span className="font-mono text-muted">{line.code}</span></div><div className={cn('mt-1 font-mono text-lg font-semibold tabular-nums', textTone[line.tone])}>{line.deviation_pct >= 0 ? '+' : ''}{line.deviation_pct.toFixed(2)}%</div><div className="text-[10px] text-muted">{line.zone}{line.close != null && line.ma10 != null ? ` · 收盘 ${line.close.toFixed(2)} / MA10 ${line.ma10.toFixed(2)}` : ''}</div>{line.change_pct != null && <div className="text-[10px] text-muted">当日 {line.change_pct >= 0 ? '+' : ''}{line.change_pct.toFixed(2)}%</div>}</div>)}</div></div>
              })}
              <p className="mt-3 text-[10px] text-muted">数据来源：{item.source}</p>
            </div>
          </details>)}
        </div>
      </div>
    </section>
  )
}
