import ReactDOM from 'react-dom/client'
import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ToastContainer } from '@/components/Toast'
import { QuantXDashboard } from '@/pages/QuantXDashboard'

type PortablePayload = {
  schemaVersion: 1
  tradeDate: string
  responses: {
    catalog: unknown
    review: unknown
    multiday: unknown
    advanced: unknown
    tables: unknown
    observability: unknown
    newHighMembers: Record<string, unknown>
  }
}

function readPayload(): PortablePayload {
  const element = document.getElementById('quantx-portable-data')
  if (!element?.textContent) throw new Error('便携报告数据缺失')
  const payload = JSON.parse(element.textContent) as PortablePayload
  if (payload.schemaVersion !== 1 || !/^\d{8}$/.test(payload.tradeDate)) {
    throw new Error('便携报告数据版本或交易日无效')
  }
  return payload
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  })
}

function installPortableFetch(payload: PortablePayload): void {
  const { tradeDate, responses } = payload
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase()
    const rawUrl = input instanceof Request ? input.url : String(input)
    const url = new URL(rawUrl, 'https://quantx.invalid')
    const path = url.pathname
    if (method !== 'GET') return jsonResponse({ detail: '离线交互报告不支持写入或刷新' }, 405)
    if (path === '/api/quantx-data/catalog') return jsonResponse(responses.catalog)
    if (path === `/api/quantx/review/${tradeDate}/data`) return jsonResponse(responses.review)
    if (path === `/api/quantx-data/multiday/${tradeDate}`) return jsonResponse(responses.multiday)
    if (path === `/api/quantx-data/advanced/${tradeDate}`) return jsonResponse(responses.advanced)
    if (path === `/api/quantx-data/${tradeDate}/tables`) return jsonResponse(responses.tables)
    if (path === `/api/quantx-data/observability/${tradeDate}`) return jsonResponse(responses.observability)
    if (path === `/api/quantx-data/new-high/${tradeDate}/members`) {
      const key = [
        url.searchParams.get('dimension') || '',
        url.searchParams.get('window') || '',
        url.searchParams.get('name') || '',
      ].join('|')
      const result = responses.newHighMembers[key]
      return result === undefined
        ? jsonResponse({ detail: `导出文件未包含聚类明细：${key}` }, 404)
        : jsonResponse(result)
    }
    return jsonResponse({ detail: `离线交互报告未包含请求：${path}` }, 404)
  }
}

function renderFailure(error: unknown): void {
  const root = document.getElementById('root')
  if (!root) return
  const main = document.createElement('main')
  main.style.cssText = 'min-height:100vh;display:grid;place-items:center;background:#080b10;color:#fca5a5;font:14px system-ui;padding:24px'
  const section = document.createElement('section')
  const title = document.createElement('h1')
  title.textContent = 'QuantX 交互报告无法启动'
  const detail = document.createElement('pre')
  detail.style.cssText = 'white-space:pre-wrap;color:#94a3b8'
  detail.textContent = String(error)
  section.append(title, detail)
  main.append(section)
  root.replaceChildren(main)
}

try {
  const payload = readPayload()
  window.__QUANTX_PORTABLE__ = true
  installPortableFetch(payload)
  const queryClient = new QueryClient({
    queryCache: new QueryCache(),
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/quantx/${payload.tradeDate}`]}>
        <Routes>
          <Route path="/quantx/:date" element={<QuantXDashboard />} />
        </Routes>
      </MemoryRouter>
      <ToastContainer />
    </QueryClientProvider>,
  )
} catch (error) {
  renderFailure(error)
}
