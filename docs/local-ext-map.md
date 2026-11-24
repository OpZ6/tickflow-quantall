# 本地增强分布图（LOCAL-EXT 清单）

> 基线：上游 `v0.4.1`。由 `backend/scripts/mark_local_ext.py` 生成，
> 用于下次同步时快速定位「这个文件里哪些区块是我们的」。
>
> Python 文件已插入 `# >>> LOCAL-EXT` / `# <<< LOCAL-EXT` 内联标记；
> TS/TSX **不插内联标记**（JSX 属性区里的 `//` 不是注释，会破坏结构），以本清单为准。

共 71 个双方都改过的源码文件。

| 文件 | 本地区块数 | 本地新增行 |
|---|---|---|
| `frontend/src/components/EChartsCandlestick.tsx` | 9 | 1367 |
| `packages/tivelo-backtest/src/tivelo_backtest/legacy/simulator.py` | 18 | 732 |
| `backend/app/tickflow/repository.py` | 14 | 528 |
| `backend/app/backtest/matrix.py` | 13 | 486 |
| `frontend/src/custom/stock-analysis/extension.tsx` | 1 | 380 |
| `backend/app/api/strategy.py` | 5 | 289 |
| `backend/app/strategy/engine.py` | 6 | 268 |
| `backend/app/indicators/pipeline.py` | 10 | 212 |
| `backend/app/services/index_sync.py` | 4 | 204 |
| `frontend/src/pages/backtest/StrategyBacktest.tsx` | 8 | 178 |
| `backend/app/jobs/daily_pipeline.py` | 9 | 171 |
| `backend/app/services/financial_sync.py` | 5 | 171 |
| `backend/app/api/financials.py` | 2 | 144 |
| `backend/app/backtest/strategy.py` | 12 | 140 |
| `frontend/src/lib/api.ts` | 9 | 140 |
| `backend/app/main.py` | 3 | 133 |
| `backend/app/services/quote_service.py` | 4 | 132 |
| `backend/app/api/screener.py` | 6 | 111 |
| `frontend/src/pages/settings/DataSources.tsx` | 7 | 104 |
| `backend/app/strategy/seeds/low_volatility_leader.py` | 1 | 91 |
| `backend/app/api/backtest.py` | 3 | 89 |
| `backend/app/services/depth_service.py` | 3 | 87 |
| `backend/app/services/preferences.py` | 5 | 87 |
| `backend/app/data_providers/capabilities.py` | 1 | 77 |
| `frontend/src/pages/Dashboard.tsx` | 3 | 75 |
| `backend/app/api/settings.py` | 4 | 69 |
| `frontend/src/components/screener/ScreenerTable.tsx` | 4 | 68 |
| `backend/app/services/screener.py` | 4 | 65 |
| `frontend/src/components/StockDailyKChart.tsx` | 4 | 64 |
| `frontend/src/components/DatePicker.tsx` | 3 | 62 |
| `backend/app/services/kline_sync.py` | 4 | 58 |
| `frontend/src/lib/chart-types.ts` | 1 | 53 |
| `frontend/src/components/screener/StrategyCard.tsx` | 1 | 44 |
| `frontend/src/pages/Screener.tsx` | 8 | 43 |
| `backend/app/strategy/seeds/oversold_reversal.py` | 1 | 41 |
| `backend/app/services/mining_process_lock.py` | 3 | 37 |
| `frontend/src/lib/queryKeys.ts` | 1 | 37 |
| `backend/app/strategy/monitor.py` | 4 | 33 |
| `frontend/src/pages/Watchlist.tsx` | 3 | 33 |
| `backend/app/api/pipeline.py` | 2 | 31 |
| `backend/app/services/abnormal_moves.py` | 1 | 30 |
| `backend/app/services/mining_manager.py` | 1 | 29 |
| `backend/app/services/data_integrity.py` | 3 | 24 |
| `frontend/src/lib/useFinancials.ts` | 2 | 22 |
| `backend/app/backtest/fundamentals.py` | 2 | 19 |
| `backend/app/services/ext_source_import.py` | 2 | 15 |
| `frontend/src/router.tsx` | 3 | 15 |
| `backend/app/plugins/fuyao/client.py` | 1 | 12 |
| `backend/app/services/ai_provider.py` | 1 | 11 |
| `backend/app/services/regime_builder.py` | 1 | 11 |
| `frontend/src/components/StockDailyKChart.test.tsx` | 1 | 11 |
| `backend/app/config.py` | 2 | 10 |
| `backend/app/services/fs_utils.py` | 1 | 10 |
| `frontend/src/lib/storage.ts` | 1 | 10 |
| `frontend/src/components/stock-table/primitives.tsx` | 1 | 9 |
| `frontend/src/lib/signals.ts` | 1 | 9 |
| `backend/app/strategy/ai_generator.py` | 1 | 8 |
| `packages/tivelo-data/src/tivelo_data/legacy/base.py` | 1 | 8 |
| `backend/app/services/instrument_sync.py` | 1 | 5 |
| `frontend/src/lib/board.ts` | 1 | 5 |
| `frontend/src/pages/Data.tsx` | 2 | 5 |
| `backend/app/api/kline.py` | 2 | 3 |
| `frontend/src/lib/useQuoteStream.ts` | 1 | 2 |
| `backend/app/backtest/stats_v2.py` | 1 | 1 |
| `frontend/src/components/screener/StrategyPoolDialog.tsx` | 1 | 1 |
| `frontend/src/lib/strategyOverrides.ts` | 1 | 1 |
| `frontend/src/pages/settings/DataSourceEditor.tsx` | 1 | 1 |
| `backend/app/api/alerts.py` | 0 | 0 |
| `backend/app/services/webhook_adapter.py` | 0 | 0 |
| `frontend/src/lib/aiReportStore.ts` | 0 | 0 |
| `frontend/src/lib/capability-labels.tsx` | 0 | 0 |
