import { build } from 'esbuild'
import { readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const output = join(tmpdir(), `tickflow-indicators-${process.pid}.mjs`)
try {
  await build({ entryPoints: ['scripts/verify-indicator-formulas.ts'], outfile: output, bundle: true, platform: 'node', format: 'esm', logLevel: 'silent' })
  await import(`${pathToFileURL(output).href}?v=${Date.now()}`)

  const source = await readFile('src/components/EChartsCandlestick.tsx', 'utf8')
  const overlays = source.match(/export const OVERLAY_INDICATORS[\s\S]*?\n\]/)?.[0].match(/\n  \{ key:/g)?.length ?? 0
  const coreKeys = ['vol', 'macd', 'rsi', 'kdj']
  if (!coreKeys.every(key => source.includes(`key: '${key}'`))) throw new Error('核心副图清单不完整')
  const extended = source.match(/makeLinesSub\('/g)?.length ?? 0
  const panes = coreKeys.length - 1 + extended
  if (overlays !== 20 || panes !== 38) throw new Error(`指标注册清单错误: overlay=${overlays}, pane=${panes}`)
  console.log(`INDICATOR_REGISTRY_OK=${overlays}+${panes}`)
} finally {
  await rm(output, { force: true })
}
