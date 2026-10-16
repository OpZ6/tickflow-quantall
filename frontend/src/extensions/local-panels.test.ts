import { describe, expect, it } from 'vitest'
import { initializeFrontendExtensions } from './bootstrap'
import { getFrontendExtensionRoutes, finalizeFrontendExtensions, getFrontendExtensionLoadErrors } from './registry'

describe('面板扩展注册实测', () => {
  // 扩展加载含全部 custom/*/extension.tsx 的动态 import, 并发跑时较慢
  it('三个自研面板的路由与导航均已注册', { timeout: 20_000 }, async () => {
    await initializeFrontendExtensions()
    finalizeFrontendExtensions(new Set(['/', '/watchlist']))
    const errs = getFrontendExtensionLoadErrors()
    expect(errs, JSON.stringify(errs)).toEqual([])
    const paths = getFrontendExtensionRoutes().flatMap(r => (r as { path?: string; children?: { path: string }[] }).children?.map(c => c.path) ?? [(r as { path: string }).path])
    console.log('全部注册路由:', paths.sort().join(' , '))
    expect(paths).toContain('/stock-pools')
    expect(paths).toContain('/market-lab')
    expect(paths).toContain('/quantx')
  })
})
