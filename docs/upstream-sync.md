# TickFlow 上游同步制度

状态：权威升级流程。目标是持续跟踪 `shy3130/tick-stock-panel`，同时保留 Quantall 的 QuantX、实验室和自有功能。

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
git switch -c sync/upstream-20260828
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
