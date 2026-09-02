import { defineConfig, type Plugin, type ResolvedConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { build as buildWithEsbuild } from 'esbuild'

const backendHost = process.env.BACKEND_HOST || '127.0.0.1'
const proxyHost = ['0.0.0.0', '::'].includes(backendHost) ? '127.0.0.1' : backendHost
const backendPort = process.env.BACKEND_PORT || '3018'
const backendTarget = `http://${proxyHost}:${backendPort}`
const portableRuntimeId = 'virtual:quantx-portable-runtime'
const resolvedPortableRuntimeId = `\0${portableRuntimeId}`

function quantxPortableRuntime(): Plugin {
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

export default defineConfig({
  plugins: [react(), quantxPortableRuntime()],
  resolve: {
    // dnd-kit/framer-motion both consume React hooks.  Pin every dependency to
    // the application's React instance so a stale optimize-deps graph cannot
    // load a second dispatcher ("Cannot read properties of null (useMemo)").
    dedupe: ['react', 'react-dom'],
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      '@dnd-kit/core',
      '@dnd-kit/sortable',
      '@dnd-kit/utilities',
    ],
  },
  server: {
    host: '0.0.0.0',   // dev.sh / dev.ps1 会用 CLI --host 覆盖
    port: 3011,
    proxy: {
      // dev 时 /api 转发到与启动脚本相同的 FastAPI 地址
      '/api': {
        target: backendTarget,
        // SSE 端点需要禁用缓冲
        configure: (proxy) => {
          proxy.on('proxyReq', (_proxyReq, req) => {
            if (req.url?.includes('/stream')) {
              _proxyReq.setHeader('Accept', 'text/event-stream')
              _proxyReq.setHeader('Cache-Control', 'no-cache')
              _proxyReq.setHeader('Connection', 'keep-alive')
            }
          })
        },
      },
      '/health': backendTarget,
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // 把重型图表库拆到独立 chunk, 避免打进主包 + 让页面按需加载。
        // 用函数形式按 node_modules 路径匹配, 比对象形式更可靠。
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts')) return 'echarts'
            if (id.includes('lightweight-charts')) return 'lightweight-charts'
          }
        },
      },
    },
  },
})
