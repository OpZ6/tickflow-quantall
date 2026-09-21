import { Telescope } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { StockPoolsPage } from './StockPoolsPage'

const extension: FrontendExtension = {
  id: 'tickflow.stock-pools',
  apiVersion: 1,
  routes: [{ id: 'stock-pools', path: '/stock-pools', component: StockPoolsPage }],
  navigation: [{ id: 'stock-pools', routeId: 'stock-pools', label: '股票池', icon: Telescope, order: 185, badge: 'beta' }],
}

export default extension
