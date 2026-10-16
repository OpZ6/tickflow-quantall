import { describe, expect, it } from 'vitest'
import { initializeFrontendExtensions } from './extensions/bootstrap'
import { getFrontendExtensionRoutes, finalizeFrontendExtensions, getFrontendExtensionLoadErrors } from './extensions/registry'

describe('面板扩展注册实测', () => {
  it('三个自研面板的路由与导航均已注册', async () => {
    await initializeFrontendExtensions()
    finalizeFrontendExtensions(new Set(['/', '/watchlist']))
    const errs = getFrontendExtensionLoadErrors()
    expect(errs, JSON.stringify(errs)).toEqual([])
    const paths = getFrontendExtensionRoutes().flatMap(r => (r as any).children?.map((c: any) => c.path) ?? [(r as any).path])
    console.log('全部注册路由:', paths.sort().join(' , '))
    expect(paths).toContain('/stock-pools')
    expect(paths).toContain('/market-lab')
    expect(paths).toContain('/quantx')
  })
})
