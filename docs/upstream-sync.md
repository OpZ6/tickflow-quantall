# TickFlow 上游同步制度

> **执行手册**：具体怎么判断、怎么解冲突、踩过哪些坑，见 [`upstream-sync-playbook.md`](upstream-sync-playbook.md)。
> 本文档只记**制度**与**历史台账**。

> **稳定 Tag 硬约束（2026-08-31 起）**：Quantall 每次上游合并只允许选择上游已发布的稳定 Tag；禁止直接合并 `upstream/main`、功能分支或未打 Tag 的单独提交。若最新稳定 Tag 不满足需求，停止合并并由维护者决定是否等待下一稳定版本。

## 最新同步记录（v0.4.1，分支 `sync/upstream-v0.4.1`，2026-11-23）

| 项目 | 值 |
| --- | --- |
| 同步目标 | `upstream/main` @ `v0.4.1`（稳定 Tag） |
| 真实同步基准 | `b8f1ebaa`（= v0.3.23，与默认 merge-base 一致，本次无需桥接） |
| 集成分支 | `sync/upstream-v0.4.1`（worktree `D:\tickflow-sync`） |
| 合并方式 | 三方合并，**未使用 `--union`**；先合上游（`d3fd3153`），再落回归修复（`e42fd3b6`），最后并入 `main`（`00fd1993`） |
| 规模 | 15 个 release / 113 commits / 1099 文件 / +166,818 −26,598 |
| 回退点 | `checkpoint/pre-upstream-v0.4.1-merge-20261123`（`402a7249`）+ `.git/backups/pre-upstream-v0.4.1-merge-20261123.bundle`（71M，`bundle verify` 完整历史） |
| 版本号 | `0.3.23` → `0.4.1`（`VERSION` + 前端 `package.json`） |

### 上游形态变更（本次最大变量）

1. **monorepo 抽取**：后端内核拆成 `packages/tivelo-{contracts,data,market-cn,backtest,extensions}`，
   `backend/app/backtest/engine.py`、`market_time.py`、`data_providers/base.py`、`enriched_generation.py`
   等退化为**兼容垫片**（只 re-export）。→ 本地实现在这些文件里的改动"零冲突但被静默丢弃"，
   安全区粒度从目录级降为子包级（见 playbook §3.1）。
2. **撮合器搬家**：实盘撮合逻辑迁入 `tivelo_backtest.legacy.simulator`，`engine.py` 只做委托。
3. **依赖升级**：`lightweight-charts` `^4.2.0` → `5.2.1`（大版本，K 线类型定义全量改写）；
   后端新增 `rfc8785` / `keyring` 等（`tivelo-contracts[signatures]`）。

### 本地移植 / 回归修复清单

| 位置 | 问题 | 处理 |
| --- | --- | --- |
| `tivelo_backtest/legacy/simulator.py` | 本地实盘风控在新位置不存在 | `MatcherConfig` 补 `stamp_tax_policy` / `entry_risk_profiles` / `profit_lock_steps` / `close_breakeven_activate_pct`；分段印花税、移动止盈、保本止损、拒单审计接入 A/B/C/D/E 五条路径 |
| `backend/app/tickflow/repository.py` | 单股热路径变成冷查询，每 tick 触发全市场 warmup | 恢复直读内存快照 |
| `backend/app/indicators/pipeline.py`、`backtest/matrix.py` | 涨跌停守卫依赖"与理论价容差比对" | 改为逻辑不变量 `limit_up > 前收` |
| `backend/app/api/settings.py` | `full_minute_data_provider` 不在 `field_to_dataset` → `KeyError` | chained/rest 字段分离；PUT 按上游契约原样回显 `provider_chains` |
| `backend/app/api/screener.py` | `enrich_and_persist_strategy_result` 引用了闭包外的 `context` | 移入 `compute()` 闭包 |
| `backend/app/backtest/matrix.py` | `dynamic` 在分支内赋值 → `UnboundLocalError` | 判定提到分支外 |
| `frontend/src/lib/chart-types.ts` | 上游抽取时丢失本地字段（`OHLC.amv_*` ×9、`ChartMarker.id/evidenceId/symbol`、`ChartRange.high/low/evidenceId`、`ChartPriceLine.endValue`） | 全部补回 |

### 验证结果

| 关卡 | 结果 |
| --- | --- |
| 前端 `tsc --noEmit` | 0 错误 |
| 前端 `vitest run` | 131 文件 / **979 用例全过**；`local-panels.test` 实测 16 条自研路由全部注册 |
| 前端 `npm run build` | 成功（`virtual:quantx-portable-runtime` 虚拟模块正常产出 1.63MB chunk） |
| 后端对照实验 | 上游纯净 worktree（`D:\tickflow-upcheck` @ v0.4.1）vs 同步侧：失败清单 11 vs 12，交集 9；**差异项逐条归因为同一环境根因**——`sqlite3.OperationalError: attempt to write a readonly database`（Python 3.14.4 + Windows + sqlite WAL 并发写），在**上游纯净 worktree 同样复现**，非合并引入 |
| 后端定向回归 | 风控/成本模型/市场矩阵 32 ✓；涨跌停守卫+缓存复用 42 ✓；设置链/契约/筛选器/quantx 数据源 79 ✓ |

### 遗留与操作提示

- **主目录 venv 必须补依赖**（历史 venv 建于 v0.3.23，不含新包）：
  `cd backend && uv sync --frozen --inexact`。用 `--inexact` 保留手工装的额外包，
  **不要**裸跑 `uv sync`（会 prune 掉用户手工安装的包）。
- 前端 `pnpm install` 后 `node_modules` 已含 `lightweight-charts 5.2.1`。
- 未做：用户真机 `dev.bat` 端到端冒烟；推送 `origin/main` 需用户确认。
- 主目录合并前的 WIP 已存档为 `402a7249`（quantx 洛伦兹网格 / tushare 镜像熔断 / duanxianxia 旧版域名 / `dev.bat` 复用模式 / `/quantx/:date` 兼容重定向）。

## 上一次同步记录（v0.3.7，分支 `sync/v037-clean`）

| 项目 | 值 |
| --- | --- |
| 同步目标 | `upstream/main` @ `99efc808`（v0.3.7） |
| 真实同步基准 | `4fa83aea`（= 上次同步的 `v0.3.0` Tag commit；**默认 merge-base 会错退回 v0.1.x**） |
| 集成分支 | `sync/v037-clean`（worktree `D:\tickflow-quantall-merge`） |
| 合并方式 | 三方合并 `ours=main / base=4fa83aea / theirs=upstream/main`，82 零冲突 + 39 逐条判定 |
| 最终差异 | 新增 1221 / 修改 121（+5799 / -612）/ 删除改名 0 |
| 覆盖度 | 本地相对 `4fa83aea` 的新增 1166 项 **100% 覆盖**（23 个 `builtin/` 策略为有意迁移至 `research/`） |
| 验证结果 | 后端 3740 passed / 3 failed（2 个缺 `tdxaidata` + 1 个并发 flaky）；前端 tsc 0 / vitest 158 / build ✓ |
| 上游行为变更 | ① 去内置化（`builtin/`→`seeds/`）② 期末强制平仓（`censored`→`sold`，计卖出佣金）③ 信号定义迁数据库（`SIGNAL_OPTIONS` 废弃）④ 策略 `source` 口径 `builtin`→`custom` |
| 已知未做 | 用户真机端到端冒烟；推送 `origin/main` 需用户确认 |

## 更早同步记录（v0.3.0，2026-09-22）

| 项目 | 值 |
| --- | --- |
| 同步目标 | `v0.3.0` |
| Tag commit | `4fa83aea79e3fb9957e3963f6cd1ce45c0199fb4` |
| 集成分支 | `sync/upstream-v0.3.0` |
| 历史桥接 | 上游重写后的 `v0.2.3` commit `7eba93e75f3a6f25ed8df230c3104480094575eb` |
| 回退点 | `checkpoint/pre-upstream-v0.3.0-20260922`、`backup/pre-upstream-v0.3.0-20260922`、`.git/backups/pre-upstream-v0.3.0-20260922.bundle` |
| 明确排除 | `v0.3.0` 之后的 `upstream/main` 提交 |

本次同步保留 Quantall 的 QuantX、股票池、市场实验室、Market Facts、本地全市场历史财务、统一 K 线和策略证据链、Quants/VCP 策略及数据源优先级，并接入稳定版的 AI 助手、板块轮动、原子写入、增强历史窗口、流式日线同步、任务心跳和并发队列等更新。由于上游重写了 `v0.2.3` 之前的历史，集成分支先用 `ours` merge 桥接同版本的新历史，再正常合并固定的 `v0.3.0` commit；不依赖可变 Tag 指针作为回退依据。上一版逐文件冲突决策见历史归档 [`upstream-v0.2.3-integration.md`](archive/20260907/upstream-v0.2.3-integration.md)。

状态：权威升级流程。目标是持续跟踪 `shy3130/tick-stock-panel`，同时保留 Quantall 的 QuantX、实验室和自有功能。

## 0. 当前跟踪快照（2026-08-28）

本节是一次可复核的审计快照，不替代合并前的实时预检。真正开始同步时，必须重新执行第 3 节命令。

| 项目 | 当前值 |
| --- | --- |
| 本地 `main` | `bbb4608f7b5d349ed401a124a6a9b7a3e9f8605a` |
| `origin/main` | `bbb4608f7b5d349ed401a124a6a9b7a3e9f8605a` |
| `upstream/main` | `afbf432eae21e964f9f871ff23b0bfbfaa98f204` |
| 共同基线 | `55b8e739c3b087b30497185c12e2b83f44815998` |
| 双方分叉 | 本地独有 20 个提交，上游独有 2 个提交 |
| 上游最新正式 Tag | `v0.2.1`，尚无更新的稳定 Tag |
| 文件重叠 | 仅 `README.md`，高冲突热点 0 个，`merge-tree` 文本冲突 0 个 |
| 审计开始时的合并就绪状态 | 否；当时工作区有 2 项未提交内容，预演不能覆盖它们 |

### 0.1 `upstream/main` 待同步内容

| 提交 | 内容 | 本地状态与判断 |
| --- | --- | --- |
| `afbf432` | 修复回测子进程已经送达结果、但退出收尾超过 10 秒时误丢结果的问题；增加强制退出标志和回归测试 | 本地尚无此修复。属于低耦合可靠性修复，建议同步 |
| `e346e25` | README 徽章文字从“非第三方官方项目”调整为“非 TickFlow 官方项目” | 仅文案变化；合并时需保留 Quantall fork 的准确说明 |

结论：建议同步 `upstream/main`，但尚未执行合并。应先提交并验证当前连板梯队修复、清理或隔离未跟踪生成物，再从干净的 `main` 创建同步分支。

### 0.2 尚未进入稳定主线的上游功能

以下分支仅用于观察，不能因为“代码更新较多”就直接整体合并：

| 上游分支 | 相对 `upstream/main` | 主要能力 | 当前判断 |
| --- | --- | --- | --- |
| `feat/minute-strategy` | 23 个提交、76 个文件，约 `+5363/-1229` | 分钟策略与回测、日线/分钟策略池、盘中增量持久化、实时预览轮询、数据源能力路由与设置页改造 | 变更面大且未进入主线/Tag；继续跟踪，待稳定后单独评估 |
| `feat/volume-delta-alert` | 1 个提交、9 个文件，约 `+763/-18` | 量差监控与告警 | 会修改 `LimitUpLadder.tsx`，与当前本地连板梯队修复直接重叠；暂不合并 |

同步候选只取上游正式稳定 Tag。`upstream/main`、功能分支和单独提交仅可做只读评估，不能进入同步分支。

## 1. 分支与远端

- `origin`：`OpZ6/tickflow-quantall`，分叉后的稳定仓库。
- `upstream`：`shy3130/tick-stock-panel`，原项目只读来源。
- `main`：已验证的 Quantall 稳定分支，不在脏工作区直接合并上游。
- `sync/upstream-YYYYMMDD`：每次上游同步的临时集成分支。

采用 merge 保留双方历史，不对已经推送的 Quantall 提交 rebase，不 force-push。

## 2. 同步前条件

1. 当前功能改动已经按任务提交，`git status --short` 为空。
2. 本地 HEAD 已推送到 origin。
3. 数据、Token、缓存和报告未进入 Git。
4. 已记录当前可运行基线和验证结果。
5. 必须选择上游正式稳定 Tag；没有新稳定 Tag 时停止本次同步。

未提交内容不会进入 Git 三方预演，因此脏工作区的“无冲突”结论无效。

## 3. 只读预检

```powershell
git fetch origin
git fetch upstream --tags
python scripts/upstream_status.py --target vX.Y.Z
python scripts/upgrade_check.py vX.Y.Z
```

`upstream_status.py` 检查远端、共同基线、双方提交数、脏工作区和高冲突热点；`upgrade_check.py` 继续负责双方重叠文件和 merge-tree 文本冲突预演。

## 4. 集成流程

```powershell
git switch main
git pull --ff-only origin main
$stableTag = "vX.Y.Z"
git switch -c "sync/upstream-$stableTag"
git merge --no-ff $stableTag
```

冲突处理原则：

1. 先理解上游行为变化和本地定制目的，不按“ours/theirs”整文件覆盖。
2. 上游 bugfix 优先保留；Quantall 功能通过现有扩展边界重新接线。
3. 公共契约变化同时更新后端模型、前端类型和测试。
4. 不借同步顺手重构无关代码。
5. 每个冲突文件记录选择依据和验证覆盖。

## 5. 高冲突热点

重点复核：

```text
backend/app/main.py
backend/app/jobs/daily_pipeline.py
backend/app/api/pipeline.py
backend/app/data_providers/custom/loader.py
backend/app/strategy/engine.py
frontend/src/router.tsx
frontend/src/components/Layout.tsx
frontend/src/lib/api.ts
frontend/src/lib/queryKeys.ts
frontend/package.json
```

统一 K 线证据层增加后，下列文件也属于高冲突热点：

```text
backend/app/api/kline.py
backend/app/api/screener.py
backend/app/api/strategy.py
backend/app/services/chart_data.py
backend/app/services/strategy_evidence.py
backend/app/services/strategy_signal_events.py
backend/app/chart_layers/
frontend/src/components/EChartsCandlestick.tsx
frontend/src/features/stock-chart/
frontend/src/pages/Screener.tsx
frontend/src/pages/StockAnalysis.tsx
```

同步上游涉及这些路径时，必须保留单一 candles/单一 ECharts、唯一指标中心、layout v4、系统/自定义指标模板、`analysis_rows` 隐藏预热、逐指标 readiness、单股按范围补齐、版本化图层契约、策略深链接、派生事件幂等键和回放确认时间；不能用上游整文件覆盖本地工作区与证据链。`indicatorRegistry.ts`、`chartPersistence.ts`、`ChartLayerManager.tsx` 和 K 线 API 查询键均按高冲突热点逐项合并，禁止恢复旧双抽屉或独立缠论/价位控制行。

QuantX 的隔离目录通常冲突较少，但凡修改共享 pipeline、data source API、依赖文件或前端路由，必须执行跨模块回归。

## 6. 验证门禁

至少完成：

```powershell
cd backend
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check <本次上游合并涉及的 Python 文件和对应测试>

cd ../frontend
pnpm install --frozen-lockfile
pnpm build

cd ..
python scripts/validate_project_contracts.py
git diff --check
```

再用 standalone Playwright 覆盖：看板、自选、策略、连板梯队、市场环境、QuantX 单日和 QuantX 多日。不能以“Git 无冲突”代替语义回归。

## 7. 发布

验证通过后：

1. 审查 `git diff upstream/main...HEAD` 和 staged diff。
2. 提交同步冲突解决和必要兼容改动。
3. 推送 `sync/upstream-*`，通过 PR 合并到 origin/main。
4. 在 PR 中记录 upstream commit/tag、共同基线、重叠热点和验证命令。
5. 合并后确认 origin/main 与本地 HEAD 一致。

## 8. 自动巡检

`.github/workflows/upstream-compat.yml` 每周及手动运行，只 fetch 和预检，不自动 merge、不创建提交。发现文本冲突、契约错误或文档缺失时失败，由维护者创建同步分支处理。
