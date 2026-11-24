# 本地增强分布图（LOCAL-EXT 清单）

> 基线：上游 `v0.4.1`。由 `git diff v0.4.1 HEAD` 自动生成，
> 用于下次同步时快速定位「这个文件里哪些区块是我们的」。
>
> Python 文件已插入 `# >>> LOCAL-EXT` / `# <<< LOCAL-EXT` 内联标记；
> TS/TSX **不插内联标记**（JSX 属性区里的 `//` 不是注释，会破坏结构），以本清单为准。

共 71 个双方都改过的源码文件。

| 文件 | 本地区块数 | 本地新增行 |
|---|---|---|
| `frontend/src/components/EChartsCandlestick.tsx` | 25 | 1151 |
| `frontend/src/custom/stock-analysis/extension.tsx` | 1 | 380 |
| `packages/tivelo-backtest/src/tivelo_backtest/legacy/simulator.py` | 35 | 338 |
| `backend/app/tickflow/repository.py` | 22 | 322 |
| `backend/app/services/financial_sync.py` | 7 | 278 |
| `backend/app/backtest/matrix.py` | 23 | 258 |
| `backend/app/api/strategy.py` | 8 | 222 |
| `backend/app/strategy/engine.py` | 9 | 203 |
| `backend/app/api/kline.py` | 4 | 176 |
| `backend/app/jobs/daily_pipeline.py` | 9 | 172 |
| `frontend/src/lib/signals.ts` | 1 | 166 |
| `backend/app/services/index_sync.py` | 8 | 134 |
| `backend/app/services/quote_service.py` | 4 | 132 |
| `backend/app/indicators/pipeline.py` | 15 | 129 |
| `backend/app/api/financials.py` | 3 | 111 |
| `backend/app/backtest/strategy.py` | 14 | 94 |
| `frontend/src/pages/backtest/StrategyBacktest.tsx` | 11 | 92 |
| `backend/app/api/backtest.py` | 3 | 89 |
| `backend/app/services/depth_service.py` | 3 | 87 |
| `backend/app/services/preferences.py` | 5 | 87 |
| `frontend/src/lib/api.ts` | 12 | 76 |
| `backend/app/api/screener.py` | 8 | 66 |
| `backend/app/api/settings.py` | 5 | 58 |
| `backend/app/services/kline_sync.py` | 4 | 58 |
| `frontend/src/components/StockDailyKChart.tsx` | 5 | 43 |
| `frontend/src/pages/Screener.tsx` | 8 | 43 |
| `backend/app/data_providers/capabilities.py` | 3 | 42 |
| `frontend/src/lib/chart-types.ts` | 2 | 41 |
| `backend/app/services/mining_process_lock.py` | 3 | 37 |
| `frontend/src/lib/queryKeys.ts` | 1 | 37 |
| `frontend/src/pages/Dashboard.tsx` | 5 | 34 |
| `backend/app/strategy/monitor.py` | 4 | 33 |
| `frontend/src/components/DatePicker.tsx` | 4 | 33 |
| `backend/app/services/screener.py` | 5 | 32 |
| `backend/app/strategy/seeds/low_volatility_leader.py` | 4 | 28 |
| `frontend/src/components/screener/ScreenerTable.tsx` | 6 | 28 |
| `backend/app/strategy/seeds/oversold_reversal.py` | 2 | 27 |
| `backend/app/main.py` | 6 | 25 |
| `frontend/src/pages/settings/DataSources.tsx` | 10 | 25 |
| `backend/app/services/data_integrity.py` | 3 | 24 |
| `frontend/src/lib/useFinancials.ts` | 2 | 22 |
| `frontend/src/components/screener/StrategyCard.tsx` | 2 | 20 |
| `backend/app/backtest/fundamentals.py` | 2 | 19 |
| `backend/app/api/pipeline.py` | 3 | 16 |
| `backend/app/services/mining_manager.py` | 2 | 16 |
| `backend/app/services/ext_source_import.py` | 2 | 15 |
| `frontend/src/router.tsx` | 3 | 15 |
| `backend/app/services/abnormal_moves.py` | 2 | 14 |
| `backend/app/plugins/fuyao/client.py` | 1 | 12 |
| `backend/app/services/ai_provider.py` | 1 | 11 |
| `backend/app/services/regime_builder.py` | 1 | 11 |
| `frontend/src/components/StockDailyKChart.test.tsx` | 1 | 11 |
| `backend/app/config.py` | 2 | 10 |
| `backend/app/services/fs_utils.py` | 1 | 10 |
| `frontend/src/lib/storage.ts` | 1 | 10 |
| `frontend/src/components/stock-table/primitives.tsx` | 1 | 9 |
| `frontend/src/pages/Watchlist.tsx` | 4 | 9 |
| `backend/app/strategy/ai_generator.py` | 1 | 8 |
| `packages/tivelo-data/src/tivelo_data/legacy/base.py` | 1 | 8 |
| `backend/app/services/instrument_sync.py` | 1 | 5 |
| `frontend/src/lib/board.ts` | 1 | 5 |
| `frontend/src/pages/Data.tsx` | 2 | 5 |
| `frontend/src/lib/useQuoteStream.ts` | 1 | 2 |
| `backend/app/backtest/stats_v2.py` | 1 | 1 |
| `frontend/src/components/screener/StrategyPoolDialog.tsx` | 1 | 1 |
| `frontend/src/lib/strategyOverrides.ts` | 1 | 1 |
| `frontend/src/pages/settings/DataSourceEditor.tsx` | 1 | 1 |
| `backend/app/api/alerts.py` | 0 | 0 |
| `backend/app/services/webhook_adapter.py` | 0 | 0 |
| `frontend/src/lib/aiReportStore.ts` | 0 | 0 |
| `frontend/src/lib/capability-labels.tsx` | 0 | 0 |
