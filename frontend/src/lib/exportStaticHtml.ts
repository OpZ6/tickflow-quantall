import {
  quantxApi,
  type CatalogData,
  type QuantXAdvancedSnapshot,
  type QuantXDataTables,
  type QuantXMultidaySnapshot,
  type QuantXNewHighClusterMembers,
  type QuantXObservability,
  type QuantXReviewData,
} from '@/lib/api'

type QuantXInteractiveExportOptions = {
  root: HTMLElement
  tradeDate: string
  fileName?: string
  exportedAt?: Date
}

export type QuantXInteractiveExportResult = {
  fileName: string
  canvasCount: number
  memberDatasets: number
  bytes: number
}

type PortablePayload = {
  schemaVersion: 1
  tradeDate: string
  exportedAt: string
  responses: {
    catalog: CatalogData
    review: QuantXReviewData
    multiday: QuantXMultidaySnapshot
    advanced: QuantXAdvancedSnapshot
    tables: QuantXDataTables
    observability: QuantXObservability
    newHighMembers: Record<string, QuantXNewHighClusterMembers>
  }
}

const CSS_URL_PATTERN = /url\(\s*(['"]?)(.*?)\1\s*\)/gi

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error || new Error('资源编码失败'))
    reader.onload = () => resolve(String(reader.result))
    reader.readAsDataURL(blob)
  })
}

async function fetchAsDataUrl(url: string): Promise<string | null> {
  if (url.startsWith('data:')) return url
  try {
    const response = await fetch(url, { credentials: 'same-origin' })
    if (!response.ok) return null
    return await blobToDataUrl(await response.blob())
  } catch {
    return null
  }
}

async function inlineCssUrls(css: string, baseUrl: string): Promise<string> {
  const matches = [...css.matchAll(CSS_URL_PATTERN)]
  const replacements = new Map<string, string>()
  const resourceUrls = [...new Set(matches
    .map(match => match[2]?.trim() || '')
    .filter(url => url && !url.startsWith('data:') && !url.startsWith('#')))]

  await Promise.all(resourceUrls.map(async rawUrl => {
    try {
      const absoluteUrl = new URL(rawUrl, baseUrl).href
      replacements.set(rawUrl, await fetchAsDataUrl(absoluteUrl) || 'data:,')
    } catch {
      replacements.set(rawUrl, 'data:,')
    }
  }))

  return css.replace(CSS_URL_PATTERN, (full, _quote: string, rawUrl: string) => {
    const replacement = replacements.get(rawUrl.trim())
    return replacement ? `url("${replacement}")` : full
  })
}

async function collectInlineCss(): Promise<string> {
  const chunks: string[] = []
  for (const sheet of Array.from(document.styleSheets)) {
    let css = ''
    try {
      css = Array.from(sheet.cssRules).map(rule => rule.cssText).join('\n')
    } catch {
      if (sheet.href) {
        try {
          const response = await fetch(sheet.href, { credentials: 'same-origin' })
          if (response.ok) css = await response.text()
        } catch {
          css = ''
        }
      }
    }
    if (css) chunks.push(await inlineCssUrls(css, sheet.href || document.baseURI))
  }
  return chunks.join('\n')
}

async function collectPayload(tradeDate: string, exportedAt: Date): Promise<PortablePayload> {
  const [catalog, review, multiday, advanced, tables, observability, memberBundle] = await Promise.all([
    quantxApi.getCatalog(),
    quantxApi.getReviewData(tradeDate),
    quantxApi.getMultiday(tradeDate),
    quantxApi.getAdvanced(tradeDate),
    quantxApi.getTables(tradeDate),
    quantxApi.getObservability(tradeDate),
    quantxApi.getNewHighMemberBundle(tradeDate),
  ])
  return {
    schemaVersion: 1,
    tradeDate,
    exportedAt: exportedAt.toISOString(),
    responses: {
      catalog,
      review,
      multiday,
      advanced,
      tables,
      observability,
      newHighMembers: memberBundle.datasets,
    },
  }
}

function escapeHtml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
}

function escapeScript(value: string): string {
  return value
    .replace(/<\/script/gi, '<\\/script')
    .replaceAll('\u2028', '\\u2028')
    .replaceAll('\u2029', '\\u2029')
}

function buildInteractiveDocument(options: {
  css: string
  runtime: string
  payload: PortablePayload
}): string {
  const { css, runtime, payload } = options
  const title = `QuantX 市场驾驶舱 — ${payload.tradeDate}（交互导出）`
  const htmlClasses = escapeHtml(document.documentElement.className)
  const bodyClasses = escapeHtml(document.body.className)
  const safeCss = css.replace(/<\/style/gi, '<\\/style')
  const payloadJson = JSON.stringify(payload).replaceAll('<', '\\u003c')
  const exportCss = `
    html, body, #root { min-height: 100%; height: auto !important; }
    html, body { overflow: visible !important; }
    body { margin: 0; background: var(--color-base, #080b10); color: var(--color-foreground, #e8edf5); }
    [data-testid="quantx-unified-dashboard"] { margin-inline: auto; }
    [data-testid="quantx-dashboard-header"] { position: relative !important; top: auto !important; }
    .quantx-portable-loading { min-height: 100vh; display: grid; place-items: center; color: #94a3b8; font: 13px/1.6 system-ui, sans-serif; }
    @media print {
      body { background: #080b10 !important; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      [data-testid="quantx-dashboard-header"] { position: relative !important; }
      section { break-inside: avoid; }
    }
  `

  return `<!doctype html>
<html lang="zh-CN" class="${htmlClasses}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
  <meta name="generator" content="TickFlow QuantX interactive export">
  <meta name="quantx-export-mode" content="interactive">
  <meta name="quantx-trade-date" content="${escapeHtml(payload.tradeDate)}">
  <meta name="quantx-exported-at" content="${escapeHtml(payload.exportedAt)}">
  <title>${escapeHtml(title)}</title>
  <style>${safeCss}\n${exportCss}</style>
</head>
<body class="${bodyClasses}">
  <div id="root"><div class="quantx-portable-loading">正在启动 QuantX 离线交互报告…</div></div>
  <script id="quantx-portable-data" type="application/json">${payloadJson}</script>
  <script>${escapeScript(runtime)}</script>
</body>
</html>`
}

export async function downloadQuantXInteractiveHtml(options: QuantXInteractiveExportOptions): Promise<QuantXInteractiveExportResult> {
  const exportedAt = options.exportedAt || new Date()
  const canvasCount = options.root.querySelectorAll('canvas').length
  const [css, runtimeModule, payload] = await Promise.all([
    collectInlineCss(),
    import('virtual:quantx-portable-runtime'),
    collectPayload(options.tradeDate, exportedAt),
  ])
  if (!runtimeModule.default) throw new Error('QuantX 便携运行时为空')
  const html = buildInteractiveDocument({ css, runtime: runtimeModule.default, payload })
  const safeDate = options.tradeDate.replace(/[^0-9]/g, '') || 'report'
  const fileName = options.fileName || `quantx-${safeDate}.html`
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  return {
    fileName,
    canvasCount,
    memberDatasets: Object.keys(payload.responses.newHighMembers).length,
    bytes: blob.size,
  }
}
