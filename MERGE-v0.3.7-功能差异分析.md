# v0.3.7 合并功能差异分析（本地新增 vs 上游）

> 分支 `sync/v037-clean`（worktree `D:\tickflow-quantall-merge`），基线 `upstream/main` @ `99efc808`。
> 原则：**以上游为底**，逐功能判断能否零侵入承载；不能的才直接改核心。

---

## 一、总览

| 项 | 数量 |
|---|---|
| 新增文件（上游没有 → 永久零冲突） | **238** |
| 修改的上游既有文件（唯一同步面） | **9** |
| 删除 / 改名上游文件 | **0** |

对比：上一轮「文件级合并」的冲突文件数是 **303**。

---

## 二、零侵入即可承载的功能（用上游插件机制）

### 1. 后端：7 个 API 路由 → `app/custom/*.py` 插件

上游 v0.3.6 起有后端插件体系：`app/extensions/loader.py` 自动扫描 `app/custom/*.py`，
要求模块暴露 `EXTENSION_ID` / `EXTENSION_API_VERSION` / `setup(registrar)`，
`registrar.include_router()` 自动挂载并做**路由冲突校验**。`main.py` 无需任何改动。

| 功能 | 原文件 | 做什么用 | 现在 |
|---|---|---|---|
| 缠论工作台状态 | `api/chanlun.py` | 探测可选隔离的缠论引擎是否就绪 | `custom/chanlun.py` |
| 缠论分析 | `api/chanlun_analysis.py` | 本地流水线合成 K 线 + 官方 ZenChart 图层直连 | `custom/chanlun_analysis.py` |
| 数据源面板 | `api/data_sources.py` | market_facts + QuantX 采集源的只读发现与健康检查 | `custom/data_sources.py` |
| 市场实验室 | `api/market_lab.py` | ETF 动量 / 板块资金流 / 宏观择时 / 仓位 / 蒙特卡洛 | `custom/market_lab.py` |
| QuantX 复盘 | `api/quantx.py` | 情绪状态 + 复盘 V4 报告 + 多日驾驶舱 | `custom/quantx.py` |
| QuantX 数据管线 | `api/quantx_data.py` | 采集 / 质量 / 清单 / 迁移 | `custom/quantx_data.py` |
| 选股池 | `api/stock_pools.py` | 入池规则 / 阶段演化 / 复盘 / 发布 | `custom/stock_pools.py` |

**验证**：9 个扩展（含上游自带 `assistant.chat`、本地 `tickflow.amv`）全部零错误挂载。

### 2. 后端：24 个自研策略 → `app/strategy/research/`

上游「去内置化」后引擎不再扫 `builtin/`，但 `research/` 是核心扫描目录，
且引擎 `_load_file()` 会**自动把同目录 `_*.py` 注入为依赖模块**（含安全白名单）。

| 内容 | 做什么用 |
|---|---|
| VCP 家族 8 个（`vcp_breakout` / `vcp_leader_tradable_v1` / `vcp_middle_expansion` …） | 波动收缩形态突破与失效退出 |
| Quants 系列 6 个（`quants_vcp` / `quants_cup_handle_legacy_v1` …） | 老版形态策略的兼容实现 |
| 形态类（`cup_handle_breakout` / `high_tight_flag_breakout` / `launch_pullback_*`） | 杯柄 / 高紧旗 / 启动回踩 |
| 4 个 `_*.py` helper（`_quants_vcp` 1346 行等，共 2199 行） | 上述策略共用的形态计算内核 |

**做法**：24 个文件整体迁入 `research/`；4 个 helper 名加进
`ai_generator._ALLOWED_IMPORT_MODULES`（8 行，沿用上游 `app.strategy.research.factor_rank_research`
已有的白名单先例），使脱离引擎单独过安全校验时也能解析 `from _xxx import`。

> 备选方案被否：放 `strategy/seeds/`（启动播种到用户目录）——因为 `seed_missing_builtins()`
> 第 38 行**跳过 `_` 前缀文件**，helper 不会随种子落地，策略会 import 失败。

### 3. 前端：本地自研页面 → `custom/*/extension.tsx` 插件

上游 `extensions/bootstrap.ts` 用 `import.meta.glob('../custom/*/extension.tsx')`
自动发现扩展，支持 `routes` / `navigation` / `slots`。

| 页面 | 做什么用 | 现在 |
|---|---|---|
| QuantX 复盘 | 情绪 + 多日复盘 V4 驾驶舱 | `custom/quantx/extension.tsx`，注册 `/quantx`、`/quantx/:date` |
| 市场实验室 | ETF 动量 / 板块 / 宏观 / 模拟 | `custom/market-lab/extension.tsx`，注册 `/market-lab` |
| 选股池 | 入池规则 / 阶段演化 / 复盘 | `custom/stock_pools/extension.tsx`（原本就是插件） |

**验证**：构建产物中出现独立 chunk `extension-*.js`，含「QuantX 复盘」「市场实验室」导航项。

> 注：本地另有一批页面（Financials / Monitor / Lots / ConceptAnalysis / IndustryAnalysis /
> StockAnalysis / Signals / Review / LimitUpLadder / AbnormalMoves）**上游已各自做成 custom 模块**，
> 因此不再重复引入本地版本。

### 4. Vite：QuantX 便携运行时 → 独立插件文件

| 功能 | 做什么用 | 做法 |
|---|---|---|
| `virtual:quantx-portable-runtime` | 把 `portable/quantxPortable.tsx` 用 esbuild 打成单文件 IIFE，使导出的交互报告脱离仓库也能跑 | 抽为 `vite-plugin-quantx-portable.ts`，`vite.config.ts` 只加 1 行 import + 1 行注册 |

---

## 三、无法插件化、直接改核心的部分（9 个文件）

| 文件 | 改动 | 为什么必须直接改 |
|---|---|---|
| `frontend/components/EChartsCandlestick.tsx` | +934/-38 | 缠论图层需要在**组件内部**构建 ECharts series，插件机制无此钩子。用**真三方合并**（base = 真实同步点 `4fa83aea`，`git merge-file --union`）双向保留：本地缠论图层 + 上游「加入自选日」蓝色竖线 |
| `backend/services/kline_sync.py` | +44 | 新增 `fetch_daily_selected()`：按 preferences 选源、第三方源 fail-closed（空结果不静默回落 TickFlow），供缠论 K 线补齐用 |
| `frontend/lib/api.ts` | +15/-2 | ①`request` / `COMPUTE_REQUEST_TIMEOUT_MS` 改 `export`；②`api` 对象末尾 `...customApi` 展开，使 104 处 `api.xxx` 本地调用零改动 |
| `frontend/lib/queryKeys.ts` | +37 | 追加 31 个自定义 QK 键（带分区注释） |
| `frontend/lib/storage.ts` | +10 | 追加 `indicatorParams` / `stockChartLayout` / `stockChartDrawings` 三个持久化键 |
| `frontend/vite.config.ts` | +8/-1 | 注册插件 + `dedupe`/`optimizeDeps` 防 React 双实例 |
| `backend/strategy/ai_generator.py` | +8 | 策略安全白名单加 4 个 `_*.py` 依赖模块 |
| `frontend/package.json` | +7/-1 | 补 `class-variance-authority`、`echarts-for-react`、`esbuild`；补 3 个校验脚本 |
| `frontend/pnpm-lock.yaml` | +307/-13 | 依赖锁 |

**为什么 `lib/api.ts` 只改 15 行**：本地原本在此文件里有 +1605 行自定义客户端，
已全部抽到 `frontend/src/custom/api.ts`（上游不存在该文件 → 未来同步零冲突）。
`api` 对象末尾加一行 `...customApi` 让调用方无感。

---

## 四、纯新增的功能模块（无需任何决策，直接叠加）

| 模块 | 规模 | 做什么用 |
|---|---|---|
| `backend/app/quantx_data` | 43 文件 / 10871 行 | QuantX 数据采集管线：14 个 legacy scraper、质量校验、清单、迁移、风险雷达、新高聚类、多日驾驶舱 |
| `backend/app/plugins` | 29 文件 / 4909 行 | 数据源插件：tdx / tushare / stocksdk / local_financial（含 bridge） |
| `backend/app/market_facts` | 11 文件 / 3901 行 | 数据地基：数据集注册表、快照留存、审计、备份、证券历史 |
| `backend/app/stock_pools` | 11 文件 / 2113 行 | 选股池内核：规则 / 演化 / 复盘 / 发布 / 主题聚类 |
| `backend/app/chanlun` | 10 文件 / 1195 行 | 缠论内核：分型 / 笔 / 线段 / 中枢 / 买卖点 / MACD |
| `backend/app/research_materials` | 4 文件 / 639 行 | 研究材料仓库 + SMNC |
| `backend/app/chart_layers` | 5 文件 / 586 行 | 图表图层注册表与 provider |
| `frontend/features/stock-chart` | 9 文件 / 1746 行 | 统一 K 线工作台：图层管理、持久化、回放、指标注册 |
| `frontend/custom/stock_pools` | 5 文件 / 1399 行 | 选股池工作台 UI |
| `frontend/features/stock-chart/chanlun.ts` | 94 行 | 本次新增：缠论类型与映射工具（从 `EChartsCandlestick` 抽出，降低后续同步耦合） |

---

## 五、验证结论

| 关卡 | 结果 |
|---|---|
| 后端 pytest | **2756 passed / 2 failed** —— 2 个为环境缺 `tdxaidata` 模块，与上游基线**逐项一致** |
| 前端 `tsc --noEmit` | **0 错误** |
| 前端 vitest | 3 failed / 149 passed —— 与上游基线一致，**零新增失败** |
| 前端 `vite build` | ✓ 通过 |
| 后端真实启动 | `/health` 200；7 个扩展 API 路由全部可达 |
| 前端插件 | 产物含独立 chunk `extension-*.js`（QuantX / 市场实验室） |

---

## 六、遗留

1. `frontend/src/lib/signals.ts` 目前为本地版直取，待做真三方合并。
2. 合入 `main` 需用户确认；`main` 全程保持 `bc2b892d` 未动。
