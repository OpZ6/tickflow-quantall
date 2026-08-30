import { RotateCcw, X } from 'lucide-react'
import { useState } from 'react'

import { getParams, resetParam, setParam } from '@/lib/indicator-params'
import { INDICATOR_REGISTRY } from './indicatorRegistry'

interface Props {
  indicatorKey: string | null
  onChanged: () => void
  onClose: () => void
}

export function IndicatorParamEditor({ indicatorKey, onChanged, onClose }: Props) {
  const definition = INDICATOR_REGISTRY.find(item => item.key === indicatorKey)
  const [revision, setRevision] = useState(0)
  if (!definition || !indicatorKey) return null
  const values = getParams(indicatorKey)
  const update = (name: string, value: number, min: number, max: number) => {
    if (!Number.isFinite(value)) return
    setParam(indicatorKey, name, Math.min(max, Math.max(min, value)))
    setRevision(value => value + 1)
    onChanged()
  }
  return (
    <div className="absolute inset-0 z-40 grid place-items-center bg-black/45 p-4" onClick={onClose} data-revision={revision}>
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-4 shadow-2xl" onClick={event => event.stopPropagation()}>
        <div className="mb-3 flex items-center">
          <strong className="text-sm text-foreground">{definition.label} 参数</strong>
          <button type="button" onClick={() => { resetParam(indicatorKey); setRevision(value => value + 1); onChanged() }} className="ml-auto inline-flex items-center gap-1 text-[10px] text-muted hover:text-foreground"><RotateCcw className="h-3 w-3" />恢复默认</button>
          <button type="button" onClick={onClose} className="ml-2 rounded p-1 text-muted hover:bg-elevated"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-2">
          {definition.paramSchema.map(param => (
            <label key={param.key} className="grid grid-cols-[1fr_120px] items-center gap-3 text-xs text-secondary">
              <span>{param.label} <span className="font-mono text-[9px] text-muted">{param.key}</span></span>
              <input type="number" min={param.min} max={param.max} step={param.step} value={values[param.key] ?? param.defaultValue} onChange={event => update(param.key, Number(event.target.value), param.min, param.max)} className="rounded-md border border-border bg-base px-2 py-1.5 font-mono text-foreground outline-none focus:border-sky-400" />
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}
