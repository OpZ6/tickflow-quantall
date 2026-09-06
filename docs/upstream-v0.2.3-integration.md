# 上游 v0.2.3 集成记录

## 基线

| 项目 | 值 |
| --- | --- |
| Quantall 第一父提交 | `3a96f74364d4e8d6e056c2cd6d27440ebff5fff3` |
| 上游稳定 Tag | `v0.2.3` |
| 上游 Tag commit | `e0cd625ef455bd1ca1fcf36a8748813e53bdea09` |
| 集成分支 | `sync/upstream-v0.2.3` |

本次只合并稳定 Tag，不包含其后的 `upstream/main` 提交。

## 冲突决策

| 冲突文件 | 选择依据与结果 | 验证覆盖 |
| --- | --- | --- |
| `CONTRIBUTING.md` | 合并 `full_minute`、`depth5` 和指数补充的数据契约。 | 项目契约检查、后端全量测试 |
| `README.md` | 保留 Quantall 文档入口，并按合并后的公开策略清单更新说明。 | 项目契约检查 |
| `backend/app/api/kline.py` | 同时保留统一图表 API 和上游 gzip 响应辅助。 | 后端全量测试、前端构建 |
| `backend/app/backtest/strategy.py` | 保留请求区间追踪，并接入因子快照。 | 后端全量测试、回测页检查 |
| `backend/app/jobs/daily_pipeline.py` | 保留当日偏差字段修复，并接入流式增强重建。 | 后端全量测试 |
| `backend/app/main.py` | 同时初始化 Market Facts、市场实验室、手数与因子存储。 | 后端全量测试、页面检查 |
| `backend/app/providers/stocksdk_provider.py` | 采用上游等价的单位归一化实现，保留现有 Provider 契约。 | Provider 定向测试、后端全量测试 |
| `backend/app/services/quote_service.py` | 保留 Quantall 数据源优先级、路由与来源证据，并接入指数补充和最终边界缓存。 | 行情定向测试、后端全量测试 |
| `backend/app/services/rps_rotation_service.py` | 接入上游 tuple 缓存修复。 | 后端全量测试 |
| `backend/app/tickflow/repository.py` | 采用批量增强历史计算，之后继续修复当日偏差字段。 | 后端全量测试 |
| `backend/tests/test_builtin_matrix_invariants.py` | 用非空和契约不变量替代易失效的精确策略数量。 | 后端全量测试 |
| `backend/tests/test_capability_matrix.py` | 接受 v0.2.3 可路由的全量分钟能力，同时保留本地数据源优先级断言。 | 定向测试、后端全量测试 |
| `backend/tests/test_data_integrity_api.py` | 合并双方格式调整，行为保持一致。 | 后端全量测试 |
| `backend/tests/test_screener_etf.py` | 用公开策略清单不变量替代精确数量。 | 后端全量测试 |
| `backend/tests/test_stocksdk_provider.py` | 合并为一套一致的 fixture 和单位断言。 | 定向测试、后端全量测试 |
| `backend/uv.lock` | 按合并后的 `pyproject.toml` 重新生成锁文件。 | `uv sync --frozen`、后端全量测试 |
| `docs/custom-data-source.md` | 记录 v0.2.3 全量分钟可路由能力。 | 项目契约检查 |
| `docs/plugin-development.md` | 合并深度、全量分钟和实时指数 Provider 契约。 | 项目契约检查 |
| `frontend/src/components/EChartsCandlestick.tsx` | 保留历史前插后的缩放锚点，并接入上游 hover/crosshair 状态。 | 前端构建、页面检查 |
| `frontend/src/components/screener/ScreenerTable.tsx` | 同时保留外部图表动作和上游列表导航。 | 前端构建、策略页检查 |
| `frontend/src/lib/queryKeys.ts` | 合并双方查询键并保留最新 K 线键。 | 前端构建 |
| `frontend/src/pages/Screener.tsx` | 同时接入候选预览导航与图表深链接。 | 前端构建、策略页检查 |

冲突解除后的兼容修正包括：补齐前端导入、删除重复静态装饰器、更新指数来源证据断言、修正异步上传测试标记，并删除与 v0.2.3 明确能力契约相反的旧全量分钟测试。

## 验证结果

- 后端全量回归：`2040 passed, 104 warnings`，耗时 168.38 秒。
- 冲突相关定向回归：`46 passed`。
- Ruff：冲突兼容测试按项目完整规则通过；后端 `E9/F63/F7/F82` 关键错误检查通过。上游合并文件仍带有既存的中文标点和复杂度规则存量，未在同步分支扩大范围重排。
- 前端生产构建：通过，构建 2788 个模块。
- 项目契约：`PROJECT_CONTRACTS_OK authoritative_docs=6`。
- `git diff --check`：通过。
- standalone Python Playwright + Edge（headless）：看板、自选、策略、连板梯队、市场环境、QuantX 单日/多日、因子、回测页面均完成真实路由渲染；隔离数据目录下的缺数据 400/404 由页面按预期显示为空态，未出现 JavaScript 控制台异常。
