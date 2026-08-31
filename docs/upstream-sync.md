# TickFlow 上游同步制度

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

同步候选默认只取上游正式 Tag 或 `upstream/main` 的明确提交。功能分支必须单独建立评估分支，完成契约、数据迁移和 UI 回归后才能考虑引入。

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
5. 优先选择上游正式 Tag；没有 Tag 时才选择明确 commit。

未提交内容不会进入 Git 三方预演，因此脏工作区的“无冲突”结论无效。

## 3. 只读预检

```powershell
git fetch origin
git fetch upstream --tags
python scripts/upstream_status.py --target upstream/main
python scripts/upgrade_check.py upstream/main
```

`upstream_status.py` 检查远端、共同基线、双方提交数、脏工作区和高冲突热点；`upgrade_check.py` 继续负责双方重叠文件和 merge-tree 文本冲突预演。

## 4. 集成流程

```powershell
git switch main
git pull --ff-only origin main
$syncDate = Get-Date -Format yyyyMMdd
git switch -c "sync/upstream-$syncDate"
git merge --no-ff upstream/main
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

同步上游涉及这些路径时，必须保留单一 candles/单一 ECharts、版本化图层契约、策略深链接、派生事件幂等键和回放确认时间；不能用上游整文件覆盖本地证据链。

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
