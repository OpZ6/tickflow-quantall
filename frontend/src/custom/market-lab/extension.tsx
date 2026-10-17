/**
 * 市场实验室 — ETF 动量 / 板块资金流 / 宏观择时 / 仓位 sizing / 蒙特卡洛模拟。
 *
 * 以源码内前端扩展形式注册: 核心 router.tsx 零改动。
 */
import { FlaskConical } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { MarketLab } from '@/pages/MarketLab'

const extension: FrontendExtension = {
  id: 'tickflow.market-lab',
  apiVersion: 1,
  routes: [
    { id: 'market-lab', path: '/market-lab', component: MarketLab },
  ],
  navigation: [
    { id: 'market-lab', routeId: 'market-lab', label: '市场实验室', icon: FlaskConical, order: 175, badge: 'beta' },
  ],
}

export default extension
