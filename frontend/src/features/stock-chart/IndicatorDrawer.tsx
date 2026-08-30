import { Search, Settings2, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { INDICATOR_REGISTRY } from './indicatorRegistry'

interface Props {
  open: boolean
  active: string[]
  onToggle: (key: string) => void
  onConfigure: (key: string) => void
  onClose: () => void
}

export function IndicatorDrawer({ open, active, onToggle, onConfigure, onClose }: Props) {
  const [search, setSearch] = useState('')
  const groups = useMemo(() => {
    const filtered = INDICATOR_REGISTRY.filter(item =>
      item.category !== 'structure'
      && `${item.label} ${item.key} ${item.group}`.toLowerCase().includes(search.trim().toLowerCase()),
    )
    return filtered.reduce((result, item) => {
      const group = item.category === 'overlay' ? `主图 · ${item.group}` : `副图 · ${item.group}`
      const current = result.get(group) ?? []
      result.set(group, [...current, item])
      return result
    }, new Map<string, typeof filtered>())
  }, [search])
  if (!open) return null

  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex w-[360px] max-w-[92vw] flex-col border-l border-border bg-surface/95 shadow-2xl backdrop-blur" aria-label="指标管理器">
      <div className="flex items-center gap-2 border-b border-border px-3 py-3">
        <Settings2 className="h-4 w-4 text-sky-400" />
        <strong className="text-sm text-foreground">指标管理</strong>
        <span className="text-[10px] text-muted">20 主图 · 38 副图 · VOL</span>
        <button type="button" onClick={onClose} className="ml-auto rounded p-1 text-muted hover:bg-elevated hover:text-foreground" aria-label="关闭指标管理器"><X className="h-4 w-4" /></button>
      </div>
      <label className="m-3 flex items-center gap-2 rounded-md border border-border bg-base px-2.5 py-2">
        <Search className="h-3.5 w-3.5 text-muted" />
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索指标或分类" className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none" />
      </label>
      <div className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
        {[...groups.entries()].map(([group, items]) => (
          <section key={group}>
            <h3 className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted">{group}</h3>
            <div className="grid grid-cols-2 gap-1.5">
              {items.map(item => {
                const selected = active.includes(item.key)
                return (
                  <div key={item.key} className={`flex items-center rounded-md border ${selected ? 'border-sky-400/40 bg-sky-400/10' : 'border-border/50 bg-base/30'}`}>
                    <button type="button" onClick={() => onToggle(item.key)} className={`min-w-0 flex-1 px-2 py-1.5 text-left text-xs ${selected ? 'text-sky-300' : 'text-secondary hover:text-foreground'}`}>
                      <span className="font-medium">{item.label}</span>
                      <span className="ml-1 text-[9px] text-muted">{item.key}</span>
                    </button>
                    {item.paramSchema.length > 0 && (
                      <button type="button" onClick={() => onConfigure(item.key)} className="mr-1 rounded p-1 text-muted hover:bg-elevated hover:text-foreground" title="参数"><Settings2 className="h-3 w-3" /></button>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        ))}
      </div>
    </aside>
  )
}
