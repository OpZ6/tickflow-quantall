import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { klineDailyQueryOptions } from '@/lib/kline'
import type { KlineRow } from '@/lib/api'

const MA = [
  { key: 'ma5', label: 'MA5', color: '#a1a1aa' },
  { key: 'ma10', label: 'MA10', color: '#60a5fa' },
  { key: 'ma20', label: 'MA20', color: '#fb923c' },
] as const

function validRow(row: KlineRow, end: string): boolean {
  return String(row.date).slice(0, 10) <= end
    && [row.open, row.high, row.low, row.close].every(value => typeof value === 'number' && Number.isFinite(value))
}

export function StockPoolMiniKline({ symbol, date }: { symbol: string; date: string }) {
  const start = useMemo(() => {
    const day = new Date(`${date}T00:00:00Z`)
    day.setUTCDate(day.getUTCDate() - 240)
    return day.toISOString().slice(0, 10)
  }, [date])
  const kline = useQuery({ ...klineDailyQueryOptions(symbol, { start, end: date }), enabled: Boolean(symbol && date) })
  const rows = useMemo(() => (kline.data?.rows ?? []).filter(row => validRow(row, date)).slice(-120), [kline.data?.rows, date])
  const option = useMemo(() => {
    const dates = rows.map(row => String(row.date).slice(0, 10))
    return {
      animation: false, backgroundColor: 'transparent',
      grid: [
        { left: 45, right: 44, top: 12, height: 177 },
        { left: 45, right: 44, top: 207, height: 53 },
      ],
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'cross' },
        backgroundColor: '#18181b', borderColor: '#52525b', textStyle: { color: '#e4e4e7', fontSize: 10 },
        formatter: (params: Array<{ dataIndex: number }> | { dataIndex: number }) => {
          const index = Array.isArray(params) ? params[0]?.dataIndex : params.dataIndex
          const row = rows[index]
          if (!row) return ''
          const ma = MA.map(item => `${item.label} ${typeof row[item.key] === 'number' ? Number(row[item.key]).toFixed(2) : '—'}`).join(' · ')
          return `${dates[index]}<br/>开 ${row.open.toFixed(2)} · 高 ${row.high.toFixed(2)}<br/>低 ${row.low.toFixed(2)} · 收 ${row.close.toFixed(2)}<br/>${ma}<br/>量 ${Number(row.volume ?? 0).toLocaleString('zh-CN')}`
        },
      },
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#3f3f46' } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
        { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#3f3f46' } }, axisLabel: { color: '#a1a1aa', fontSize: 9, interval: 14, formatter: (value: string) => value.slice(5) }, axisTick: { show: false }, splitLine: { show: false } },
      ],
      yAxis: [
        { scale: true, axisLabel: { color: '#a1a1aa', fontSize: 9 }, axisLine: { show: false }, splitLine: { lineStyle: { color: '#27272a' } } },
        { gridIndex: 1, scale: true, axisLabel: { show: false }, axisLine: { show: false }, splitLine: { show: false } },
      ],
      series: [
        { name: '日K', type: 'candlestick', data: rows.map(row => [row.open, row.close, row.low, row.high]), itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' } },
        ...MA.map(item => ({ name: item.label, type: 'line', symbol: 'none', connectNulls: false, smooth: false, lineStyle: { color: item.color, width: 1.3 }, itemStyle: { color: item.color }, data: rows.map(row => typeof row[item.key] === 'number' && Number.isFinite(row[item.key]) ? row[item.key] : null) })),
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 8, data: rows.map(row => ({ value: row.volume ?? 0, itemStyle: { color: row.close >= row.open ? '#ef444477' : '#22c55e77' } })) },
      ],
    }
  }, [rows])

  return <section className="rounded-lg border border-[#353539] bg-[#111113] p-3" aria-label="简洁日K">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-xs font-semibold">日K走势</h3><span className="text-[10px] text-muted">前复权 · {rows.length ? `${rows.length}根 · ${rows[0].date.slice(0, 10)}—${rows.at(-1)?.date.slice(0, 10)}` : `截至 ${date}`}</span></div>
    <div className="mt-1 flex flex-wrap gap-3 text-[9px] text-muted"><span>红涨绿跌</span>{MA.map(item => <span key={item.key} className="inline-flex items-center gap-1"><i className="h-0.5 w-3" style={{ backgroundColor: item.color }} />{item.label}</span>)}<span>下方为成交量</span></div>
    {kline.isLoading || kline.isPlaceholderData ? <div className="grid h-[280px] place-items-center text-xs text-muted">正在加载日K…</div>
      : kline.isError ? <div className="grid h-[280px] place-items-center text-xs text-danger">日K加载失败，可打开完整K线查看</div>
        : rows.length ? <div data-testid="stock-pool-mini-kline"><ReactECharts option={option} notMerge style={{ height: 280 }} /></div>
          : <div className="grid h-[280px] place-items-center text-xs text-muted">该快照日期前暂无可用日K</div>}
  </section>
}
