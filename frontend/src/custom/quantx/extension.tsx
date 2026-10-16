/**
 * QuantX 市场驾驶舱 — 情绪状态 / 多日复盘 V4 / 新高聚类 / 数据可观测。
 *
 * 以源码内前端扩展形式注册: extensions/bootstrap.ts 的 import.meta.glob
 * 自动发现本文件, 路由与侧栏导航随之生效, 核心 router.tsx 零改动。
 */
import { Zap } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { QuantXDashboard } from '@/pages/QuantXDashboard'

const extension: FrontendExtension = {
  id: 'tickflow.quantx',
  apiVersion: 1,
  routes: [
    { id: 'quantx', path: '/quantx', component: QuantXDashboard },
    { id: 'quantx-date', path: '/quantx/:date', component: QuantXDashboard },
  ],
  navigation: [
    { id: 'quantx', routeId: 'quantx', label: 'QuantX 复盘', icon: Zap, order: 180, badge: 'beta' },
  ],
}

export default extension
