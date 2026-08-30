type QuantXStaticExportOptions = {
  root: HTMLElement
  tradeDate: string
  fileName?: string
  exportedAt?: Date
}

export type QuantXStaticExportResult = {
  fileName: string
  canvasCount: number
  bytes: number
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

async function inlineExistingImages(source: HTMLElement, clone: HTMLElement): Promise<void> {
  const sourceImages = Array.from(source.querySelectorAll<HTMLImageElement>('img'))
  const clonedImages = Array.from(clone.querySelectorAll<HTMLImageElement>('img'))
  await Promise.all(sourceImages.map(async (image, index) => {
    const clonedImage = clonedImages[index]
    if (!clonedImage) return
    const sourceUrl = image.currentSrc || image.src
    if (!sourceUrl) return
    const dataUrl = await fetchAsDataUrl(sourceUrl)
    if (dataUrl) {
      clonedImage.src = dataUrl
      clonedImage.removeAttribute('srcset')
      return
    }
    clonedImage.removeAttribute('src')
    clonedImage.removeAttribute('srcset')
  }))
}

function replaceCanvases(source: HTMLElement, clone: HTMLElement): number {
  const sourceCanvases = Array.from(source.querySelectorAll<HTMLCanvasElement>('canvas'))
  const clonedCanvases = Array.from(clone.querySelectorAll<HTMLCanvasElement>('canvas'))

  sourceCanvases.forEach((canvas, index) => {
    const clonedCanvas = clonedCanvases[index]
    if (!clonedCanvas) return
    const image = document.createElement('img')
    const bounds = canvas.getBoundingClientRect()
    image.src = canvas.toDataURL('image/png')
    image.alt = canvas.getAttribute('aria-label') || 'QuantX 图表静态快照'
    image.className = clonedCanvas.className
    image.setAttribute('data-exported-canvas', String(index + 1))
    image.setAttribute('draggable', 'false')
    image.setAttribute('style', clonedCanvas.getAttribute('style') || '')
    if (bounds.width > 0) image.style.width = `${bounds.width}px`
    if (bounds.height > 0) image.style.height = `${bounds.height}px`
    image.style.maxWidth = '100%'
    clonedCanvas.replaceWith(image)
  })

  return sourceCanvases.length
}

function preserveFormState(source: HTMLElement, clone: HTMLElement): void {
  const sourceFields = Array.from(source.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea'))
  const clonedFields = Array.from(clone.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea'))
  sourceFields.forEach((field, index) => {
    const clonedField = clonedFields[index]
    if (!clonedField) return
    if (field instanceof HTMLInputElement) {
      clonedField.setAttribute('value', field.value)
      if (field.checked) clonedField.setAttribute('checked', '')
    } else if (field instanceof HTMLSelectElement && clonedField instanceof HTMLSelectElement) {
      Array.from(clonedField.options).forEach((option, optionIndex) => {
        option.toggleAttribute('selected', optionIndex === field.selectedIndex)
      })
    } else if (field instanceof HTMLTextAreaElement) {
      clonedField.textContent = field.value
    }
  })
}

function makeCloneStatic(clone: HTMLElement): void {
  clone.setAttribute('data-static-export', 'true')
  clone.querySelectorAll('[data-static-export-remove], script, iframe').forEach(node => node.remove())
  clone.querySelectorAll<HTMLElement>('*').forEach(element => {
    Array.from(element.attributes).forEach(attribute => {
      if (attribute.name.toLowerCase().startsWith('on')) element.removeAttribute(attribute.name)
    })
    if (element.matches('button, [role="button"], [role="tab"]')) {
      element.setAttribute('aria-disabled', 'true')
      element.setAttribute('tabindex', '-1')
    }
  })
  clone.querySelectorAll<HTMLAnchorElement>('a[href]').forEach(anchor => {
    const href = anchor.getAttribute('href') || ''
    try {
      const target = new URL(href, window.location.href)
      if (target.origin === window.location.origin || ['localhost', '127.0.0.1', '::1'].includes(target.hostname)) {
        anchor.removeAttribute('href')
        anchor.setAttribute('aria-disabled', 'true')
      }
    } catch {
      anchor.removeAttribute('href')
    }
  })
}

function escapeHtml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
}

function buildStaticDocument(options: {
  clone: HTMLElement
  css: string
  tradeDate: string
  exportedAt: Date
}): string {
  const { clone, css, tradeDate, exportedAt } = options
  const title = `QuantX 市场驾驶舱 — ${tradeDate}（静态导出）`
  const htmlClasses = escapeHtml(document.documentElement.className)
  const bodyClasses = escapeHtml(document.body.className)
  const safeCss = css.replaceAll('</style', '<\\/style')
  const exportCss = `
    html, body { min-height: 100%; height: auto !important; overflow: visible !important; }
    body { margin: 0; background: var(--color-base, #080b10); color: var(--color-foreground, #e8edf5); }
    .quantx-static-report { min-height: 100vh; }
    [data-testid="quantx-unified-dashboard"] { margin-inline: auto; overflow: visible !important; }
    [data-testid="quantx-dashboard-header"] { position: relative !important; top: auto !important; }
    [data-static-export] button, [data-static-export] [role="button"], [data-static-export] [role="tab"] { cursor: default !important; pointer-events: none !important; }
    img[data-exported-canvas] { display: block; object-fit: contain; }
    .quantx-static-footer { margin: 28px auto 0; max-width: 1720px; border-top: 1px solid rgba(148, 163, 184, .18); padding: 14px 16px 24px; color: #8490a3; font: 11px/1.6 ui-monospace, SFMono-Regular, Consolas, monospace; }
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
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:">
  <meta name="generator" content="TickFlow QuantX static export">
  <meta name="quantx-trade-date" content="${escapeHtml(tradeDate)}">
  <meta name="quantx-exported-at" content="${escapeHtml(exportedAt.toISOString())}">
  <title>${escapeHtml(title)}</title>
  <style>${safeCss}\n${exportCss}</style>
</head>
<body class="${bodyClasses}">
  <main class="quantx-static-report">${clone.outerHTML}</main>
  <footer class="quantx-static-footer">QuantX 静态快照 · 数据日期 ${escapeHtml(tradeDate)} · 导出时间 ${escapeHtml(exportedAt.toLocaleString('zh-CN', { hour12: false }))} · 图表与样式已内嵌，无需 TickFlow 服务即可查看。</footer>
</body>
</html>`
}

export async function downloadQuantXStaticHtml(options: QuantXStaticExportOptions): Promise<QuantXStaticExportResult> {
  const clone = options.root.cloneNode(true) as HTMLElement
  preserveFormState(options.root, clone)
  await inlineExistingImages(options.root, clone)
  const canvasCount = replaceCanvases(options.root, clone)
  makeCloneStatic(clone)
  const css = await collectInlineCss()
  const exportedAt = options.exportedAt || new Date()
  const html = buildStaticDocument({ clone, css, tradeDate: options.tradeDate, exportedAt })
  const safeDate = options.tradeDate.replace(/[^0-9]/g, '') || 'snapshot'
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
  return { fileName, canvasCount, bytes: blob.size }
}
