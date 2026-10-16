/**
 * QuantX 离线便携报告运行时 — Vite 插件。
 *
 * 把 src/portable/quantxPortable.tsx 用 esbuild 打成单文件 IIFE, 以
 * virtual:quantx-portable-runtime 虚拟模块暴露给 exportStaticHtml.ts,
 * 使导出的交互报告脱离本仓库也能运行 (React/ECharts 全部内联)。
 *
 * 原内联于 vite.config.ts; 抽出为独立插件文件后, 上游 vite.config.ts
 * 只需注册一行, 未来同步零冲突。
 */
import path from 'node:path'
import { build as buildWithEsbuild } from 'esbuild'
import type { Plugin, ResolvedConfig } from 'vite'

const portableRuntimeId = 'virtual:quantx-portable-runtime'
const resolvedPortableRuntimeId = `\0${portableRuntimeId}`

function portableRuntimePlugin(): Plugin {
  let runtime = ''
  let command: ResolvedConfig['command'] = 'build'
  const sourceRoot = `${path.resolve(__dirname, './src')}${path.sep}`
  const compile = async () => {
    const result = await buildWithEsbuild({
      entryPoints: [path.resolve(__dirname, './src/portable/quantxPortable.tsx')],
      bundle: true,
      write: false,
      format: 'iife',
      platform: 'browser',
      target: 'es2022',
      minify: true,
      legalComments: 'none',
      jsx: 'automatic',
      alias: { '@': path.resolve(__dirname, './src') },
      external: [portableRuntimeId],
      define: {
        'process.env.NODE_ENV': JSON.stringify('production'),
        global: 'globalThis',
      },
    })
    runtime = result.outputFiles[0]?.text || ''
    if (!runtime) throw new Error('QuantX portable runtime build produced no output')
  }
  return {
    name: 'quantx-portable-runtime',
    configResolved(config) {
      command = config.command
    },
    async buildStart() {
      await compile()
    },
    resolveId(id: string) {
      return id === portableRuntimeId ? resolvedPortableRuntimeId : null
    },
    async load(id: string) {
      if (id !== resolvedPortableRuntimeId) return null
      // The dev server may stay alive while QuantX components are updated by
      // HMR. Compile on virtual-module load so an export never receives the
      // buildStart snapshot from an older frontend revision.
      if (command === 'serve' || !runtime) await compile()
      return `export default ${JSON.stringify(runtime)}`
    },
    async handleHotUpdate(context) {
      if (!`${path.resolve(context.file)}${path.sep}`.startsWith(sourceRoot)) return
      await compile()
      const module = context.server.moduleGraph.getModuleById(resolvedPortableRuntimeId)
      if (!module) return
      context.server.moduleGraph.invalidateModule(module)
      return [module]
    },
  }
}

export function quantxPortableRuntime(): Plugin {
  return portableRuntimePlugin()
}
