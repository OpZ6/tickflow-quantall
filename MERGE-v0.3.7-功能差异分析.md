# v0.3.7 合并功能差异分析（本地新增 vs 上游）

> 分支 `sync/v037-clean`（worktree `D:\tickflow-quantall-merge`），基线 `upstream/main` @ `99efc808`。
> 原则：**以上游为底**，逐功能判断能否零侵入承载；不能的才直接改核心。

---

## 零、三个核心问题的结论（先看这里）

| 问题 | 结论 |
|---|---|
| **① 三个自研面板（选股池 / 市场实验室 / QuantX 复盘）是否完全保留（含后台与数据功能）？** | **是**。三层齐备：前端路由+侧栏导航、后端 API、后端业务/数据模块。14 条扩展路由全部注册，0 加载错误；后端 7 个扩展 API 实测可达。 |
| **② 个股 K 线面板的完全增强是否保留？** | **是，且比本地还多**。`EChartsCandlestick` 导出 18→18 零丢失、Props 30→31（多上游 `addedDate`）；统一 K 线工作台已接入个股分析页；本地缠论图层与上游「加入自选日」竖线**双向保留**。 |
| **③ 我的策略是否还在？** | **是**。`strategy/research/` 24 文件，引擎实测加载 **20 个策略、0 失败**（19 个自研 + 上游 `factor_rank_research`），4 个 `_*.py` 形态内核作为依赖自动注入。 |

### 合入过程中发现并修复的 3 个"看不见的坑"

1. **QuantX 面板整体失效**：扩展注册表只接受静态路径，`/quantx/:date` 让整个
   `tickflow.quantx` 扩展加载失败 → `/quantx` 也没注册。改为 `?date=YYYYMMDD`。
2. **个股 K 线增强成了孤儿**：本地 K 线工作台接在 `pages/StockAnalysis.tsx`，
   而上游已把该页重构为 `custom/stock-analysis/extension.tsx`（用简易 `AnalysisKChart`）。
   不接回去等于"代码在、没人用"。已把 `UnifiedStockChart` 接进上游插件并透传
   `strategyContext`（承接策略图表预览入口）。
3. **121 个核心文件的本地改动被整份覆盖**：详见第一节。
   其中包含 `strategy/engine.py`(+204)、`api/strategy.py`(+197)、
   `tickflow/repository.py`(+269)、`api/kline.py`(+175)、`backtest/engine.py`(+185)
   等，直接影响 ②③ 的底层。

---

## 一、总览

| 项 | 数量 |
|---|---|
| 新增文件（上游没有 → 永久零冲突） | **240** |
| 修改的上游既有文件（唯一同步面） | **118**（+5755 / -594 行） |
| 删除 / 改名上游文件 | **0** |

> **为什么从 9 变成 118**：第一版只碰了 9 个上游文件，看似干净，但那是把
> "本地相对**真实同步点** `4fa83aea` 的自研改动"误判成"上游更新"而整份取上游了。
> 用 `git merge-file`（ours=`main`, base=`4fa83aea`, theirs=`upstream/main`）重做后，
> 82 个零冲突自动合并、39 个逐条判定，本地功能才真正回到合并版里。

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

**验证**：合并版启动日志 0 条 route conflicts；9 个扩展（含上游自带 `assistant.chat`、本地 `tickflow.amv`）
全部零错误挂载。同时从 `main.py` 删除了这 7 个 API 的重复 `import` + `include_router`
（各 7 处），让插件独占，避免重复注册。

### 2. 后端：24 个自研策略 → `app/strategy/research/`

上游「去内置化」后引擎不再扫 `builtin/`，但 `research/` 是核心扫描目录，
且引擎 `_load_file()` 会**自动把同目录 `_*.py` 注入为依赖模块**（含安全白名单）。

| 内容 | 做什么用 |
|---|---|
| VCP 家族 8 个（`vcp_breakout` / `vcp_leader_tradable_v1` / `vcp_middle_expansion` …） | 波动收缩形态突破与失效退出 |
| Quants 系列 6 个（`quants_vcp` / `quants_cup_handle_legacy_v1` …） | 老版形态策略的兼容实现 |
| 形态类 5 个（`cup_handle_breakout` / `high_tight_flag_breakout` / `launch_pullback_*`） | 杯柄 / 高紧旗 / 启动回踩 |
| 4 个 `_*.py` helper（`_quants_vcp` 1346 行等，共 2199 行） | 上述策略共用的形态计算内核 |

**实测**：`StrategyEngine(strategy_dirs=[app/strategy/research])` → `_strategies` **20 个**，
`load_errors()` **0**。含 13 个 `research_only` 模板（`list_strategies()` 默认会过滤掉，
需 `include_research=True` 才可见——上一版就是漏了这个参数才误判成"只有 7 个"）。

**做法**：24 个文件整体迁入 `research/`；4 个 helper 名加进
`ai_generator._ALLOWED_IMPORT_MODULES`（8 行，沿用上游
`app.strategy.research.factor_rank_research` 已有的白名单先例），使脱离引擎单独过安全校验时
也能解析 `from _xxx import`。

> 备选方案被否：放 `strategy/seeds/`（启动播种到用户目录）——因为 `seed_missing_builtins()`
> 第 38 行**跳过 `_` 前缀文件**，helper 不会随种子落地，策略会 import 失败。

### 3. 前端：本地自研页面 → `custom/*/extension.tsx` 插件

上游 `extensions/bootstrap.ts` 用 `import.meta.glob('../custom/*/extension.tsx')`
自动发现扩展，支持 `routes` / `navigation` / `slots`。

| 页面 | 做什么用 | 现在 |
|---|---|---|
| QuantX 复盘 | 情绪 + 多日复盘 V4 驾驶舱 | `custom/quantx/extension.tsx`，注册 `/quantx`（交易日走 `?date=`） |
| 市场实验室 | ETF 动量 / 板块 / 宏观 / 模拟 | `custom/market-lab/extension.tsx`，注册 `/market-lab` |
| 选股池 | 入池规则 / 阶段演化 / 复盘 | `custom/stock_pools/extension.tsx`（原本就是插件） |

**验证**：新增 `src/extensions/local-panels.test.ts` 运行时断言——
14 条扩展路由全部注册、0 加载错误，其中含 `/stock-pools`、`/market-lab`、`/quantx`。
构建产物中出现独立 chunk `extension-*.js`。

> 同时删除了 `Layout.tsx` 里本地硬编码的 `customNav`（含 `/market-lab`、`/quantx`），
> 因为上游 `extensionNav` 已自动生成同名导航项，保留会**重复两次**。

> 注：本地另有一批页面（Financials / Monitor / Lots / ConceptAnalysis / IndustryAnalysis /
> StockAnalysis / Signals / Review / LimitUpLadder / AbnormalMoves）**上游已各自做成 custom 模块**，
> 因此不再重复引入本地版本。

### 4. Vite：QuantX 便携运行时 → 独立插件文件

| 功能 | 做什么用 | 做法 |
|---|---|---|
| `virtual:quantx-portable-runtime` | 把 `portable/quantxPortable.tsx` 用 esbuild 打成单文件 IIFE，使导出的交互报告脱离仓库也能跑 | 抽为 `vite-plugin-quantx-portable.ts`，`vite.config.ts` 只加 1 行 import + 1 行注册 |

---

## 三、无法插件化、直接改核心的部分（118 个文件，改动量 +5755/-594）

其中**最关键的 10 个**（其余多为随本轮三方合并一起回到位的小改）：

| 文件 | 改动 | 为什么必须直接改 |
|---|---|---|
| `frontend/components/EChartsCandlestick.tsx` | +934/-38 | 缠论图层需在**组件内部**构建 ECharts series，插件机制无此钩子。用**真三方合并**（base = 真实同步点 `4fa83aea`）双向保留：本地缠论图层 + 上游「加入自选日」蓝色竖线 |
| `backend/strategy/engine.py` | +204/-33 | 策略引擎：本地 `preview_signal_history`/`StrategySignalHistory` + 上游矩阵目标帧修复 |
| `backend/api/strategy.py` | +197/-1 | 本地 `/events`、`/events/backfill`、`preview` 端点 + 上游 override 优先口径；并合本地三个风控字段 |
| `backend/tickflow/repository.py` | +269/-20 | 数据仓库：`get_index_daily_batch` / `get_adjustment_factors` / `get_raw_daily_asset` / `_overlay_live_enriched` 等 |
| `backend/api/kline.py` | +175/-3 | 本地 `/chart` 端点 + `_canonical_chart_symbol`（裸代码补全市场）＋ `sync_daily_single`；并合上游 `_json_safe` |
| `backend/backtest/engine.py` | +185/-32 | 本地盈亏锁定/收盘保本 + 上游期末强制平仓（`force=True`，避免递延持仓被静默丢弃） |
| `backend/services/financial_sync.py` | +273/-14 | 数据源路由/故障转移链 |
| `backend/services/preferences.py` | +75/-13 | `provider_chains` 优先级链（`get/set/promote_data_provider_chain`） |
| `backend/api/pipeline.py` | 见下 | 本地在主管道后追加 QuantX/选股池两个后置发布阶段 |
| `frontend/lib/api.ts` | +15/-2 | ①`request`/`COMPUTE_REQUEST_TIMEOUT_MS` 改 `export`；②`api` 对象末尾 `...customApi`，使本地 104 处 `api.xxx` 调用零改动 |

**为什么 `lib/api.ts` 只改 15 行**：本地原本在此文件里有 +1605 行自定义客户端，
已全部抽到 `frontend/src/custom/api.ts`（上游不存在该文件 → 未来同步零冲突）。

### 本轮修复的合并副作用

| 问题 | 修复 |
|---|---|
| `api/pipeline.py` 的 `_run_pipeline_and_quantx(repo, capset, progress)` 引用上游 `_submit_job` 作用域中不存在的 `capset`（NameError） | 改签名收 `make_run` 闭包：`_run_pipeline_and_quantx(run, progress)` |
| `main.py` 中 7 个本地 API 与 `app/custom/*.py` 插件**重复注册**（启动日志 route conflicts） | 从 `main.py` 删 7 处 `import` + 7 处 `include_router`，插件独占 |
| `StockDailyKChart.tsx` union 合并把缠论 state 与上游 `addedDate` state 叠在一起导致语法错 | 保留两者，`B` 并合 |
| `StrategyBacktest.tsx` union 合并产生两份 lucide/`api` 导入 | 合并为一份（图标与类型取并集） |
| `Layout.tsx` 本地 `customNav` 与上游 `extensionNav` 重复渲染 | 删本地硬编码 |
| `MenuSettings.tsx` 本地硬编码 `CUSTOM_PAGES`（market-lab/quantx）已过时 | 取上游（扩展页自动进菜单） |
| 契约快照 / 矩阵缓存版本 / 本地测试签名 4 处不一致 | 逐一对齐（详见下表） |

---

## 四、纯新增的功能模块（无需任何决策，直接叠加）

| 模块 | 规模 | 做什么用 |
|---|---|---|
| `backend/app/quantx_data` | 43 文件 / 10871 行 | QuantX 数据采集管线：14 个 legacy scraper、质量校验、清单、迁移、风险雷达、新高聚类、多日驾驶舱 |
| `backend/app/plugins` | 29 文件 / 4909 行 | 数据源插件：tdx / tushare / stocksdk / local_financial（含 bridge） |
| `backend/app/market_facts` | 11 文件 / 3901 行 | 数据地基：数据集注册表、快照留存、审计、备份、证券历史 |
| `backend/app/strategy/research` | 24 文件 / 4304 行 | 19 个自研策略 + 4 个形态内核 + 上游 `factor_rank_research` |
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
| 后端 pytest | **2797 passed / 2 failed** —— 2 个为环境缺 `tdxaidata` 模块，与上游基线**逐项一致** |
| 前端 `tsc --noEmit` | **0 错误** |
| 前端 vitest | **26 文件 / 158 用例全部通过**（上游基线为 149 passed + 3 failed） |
| 前端 `vite build` | ✓ 通过 |
| 后端插件 | 9 个扩展零错误挂载，无 route conflicts |
| 前端插件 | 14 条扩展路由全部注册（含三个自研面板），0 加载错误 |
| 策略引擎 | `research/` 20 个策略加载成功、0 失败 |
| 文件差异 | 新增 240 / 修改 118 / 删除改名 **0** |

---

## 六、遗留

1. `main` 全程保持 `bc2b892d` 未动；合并结果（`sync/v037-clean`）**待用户确认后再并入**。
2. 2 个环境失败：`test_tdxquant_probe.py` 需安装 `tdxaidata` 包。
3. `frontend/src/lib/signals.ts` 为本地版与上游的合并结果，如需可再逐段校。
