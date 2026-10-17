# 上游同步剧本（AI 执行手册）

> 这份文档**不是脚本**，是给 AI（或未来接手的人）在上游出新版时照着判断的框架。
> 命令会随环境变化，判断原则不会。每一步都写了「验收标准」和「不符合怎么办」。
> 配套记录见 [`upstream-sync.md`](upstream-sync.md)（制度与历史同步台账）。

---

## 0. 一句话总纲

> **以上游为底，把自研功能放在上游永远不会创建同名文件的路径里；能外置就外置，不能外置就标记清楚。**

本项目的自研功能已经按这个原则落到四个"安全区"，这些文件上游永远不碰，**永久零冲突**：

| 安全区 | 内容 |
|---|---|
| `frontend/src/custom/` | 三面板扩展（quantx / market-lab / stock_pools 等）、`api.ts`（全部自定义 API 客户端） |
| `backend/app/custom/*.py` | 7 个后端插件（`EXTENSION_ID` + `setup(registrar)`） |
| `backend/app/strategy/research/` | 19 个自研策略 + 4 个 `_*.py` 依赖模块 |
| `frontend/src/features/stock-chart/` | K 线增强、缠论图层等独立模块 |

**同步时优先保护这四块，其余都是可协商的。**

---

## 1. 前置铁律（违反必出事，都是踩过的）

1. **绝不在用户正在用的工作目录切分支、checkout、改工作树。**
   同步必须在独立 worktree 里做（`git worktree add`）。
   历史上曾在主目录 `git checkout -b sync/... upstream/main`，直接把用户环境切到上游基线，
   面板消失、启动报错。
2. **worktree 的 `node_modules` / `.venv` 必须独立安装，不能做成指向用户目录的 junction 后再 `pnpm install`。**
   曾因此卸掉了用户目录的 `esbuild`，导致 `virtual:quantx-portable-runtime` 解析失败。
3. **删除任何东西之前先归档**，并告知用户归档位置。
4. **用户的 `main` 全程不动**，直到验证全部通过、用户点头，才做最后一步合并。
5. **不要用 `--union` 做冲突合并**。它永不输出冲突标记，看着"零冲突"，实际会重复插入导入、
   重复副作用语句、把参数插到同名函数的另一个定义里。

---

## 2. 第一步：确认"真实同步基准"（最容易错的一步）

上游会**强推重写历史**（本项目 2026-09-22 发生过）。一旦发生：

- `git merge-base upstream/main main` 会回退到很老的提交（本项目退到了 `a1566632`，v0.1.x 时代）
- 如果按这个基准做三方合并，会把"本地自研改动"误判成"上游更新尚未合入"，
  从而**大批量地把自研功能整份丢给上游版本覆盖**（本项目第一次只保住了 9 个文件，实际有 141 个）

### 正确做法

1. 查台账 `docs/upstream-sync.md` 的"最新同步记录"，拿上次同步的上游 commit（本项目是 `4fa83aea`）
2. 若无台账，用版本 Tag 反查：`git log --all --oneline --grep="sync upstream"`
3. **验证候选基准是否可信**：
   - `git merge-base --is-ancestor <候选base> upstream/main` 必须为真
   - `git diff <候选base> <上次记录的上游commit>` 应为空
4. 若默认 merge-base 明显早于候选基准 → **判定为上游重写历史**，显式指定基准

### 验收标准

```
git merge-file -p  --ours=main --base=<真实base> --theirs=upstream/main
```

冲突块数量应在**几十个量级**（本项目为 82 零冲突 / 39 有冲突）。
若冲突数上百、或几乎所有文件都整份冲突 → **基准错了，停下重来**，不要硬做。

---

## 3. 第二步：建隔离环境

```bash
git worktree add ../<repo>-merge -b sync/upstream-<ver> upstream/main
cd ../<repo>-merge/frontend && pnpm install     # 独立安装，不要 junction
```

后端若没有 `.venv`，可临时复用主仓的 Python 解释器（只读调用，不装包）：

```bash
/d/<主仓>/backend/.venv/Scripts/python.exe -m pytest ...
```

**验收**：`npx vite build` 能过一次（证明插件链、依赖、虚拟模块都正常）。

---

## 4. 第三步：三方合并 + 冲突分级

先做**全量冲突普查**（不带 `--union`），把文件分成三类：

| 类型 | 特征 | 处理 |
|---|---|---|
| **零冲突** | merge-file 无标记 | 直接采用，但**必须抽查**本地改动是否仍在内（自动合并也会漏） |
| **区块冲突** | 少量 `<<<<<<<` | 逐块按第 5 节决策树判定 |
| **整文件冲突** | 标记覆盖全文 | 先 `cmp base theirs` —— 若字节相同，说明上游只是**搬位置或改行尾**，直接用 ours |

### 假冲突识别

- **CRLF/LF 差异**会让整文件显示冲突：`cmp` 一下 base 和 theirs，相同就是假冲突
- 本项目 `seeds/low_volatility_leader.py` 就属此类：上游把 `builtin/` 搬到 `seeds/`，
  内容与同步基准**字节完全相同**，本地增强直接覆盖即可

---

## 5. 决策树：冲突时取谁

按顺序判断，命中即停：

1. **上游是"重构/迁移"，本地是"增强"** → 取上游结构，把本地增强**移植到新位置**
   （例：上游把 `builtin/` 迁到 `seeds/`，本地策略应迁到 `research/`，而不是硬顶在 `builtin/`）
2. **本地是"防御式兼容"**（`getattr(..., None)` 兜底、fail-closed 抛错、保留旧数据） → **优先保留本地**
   这类改动上游不会主动加，丢了就是功能回退。
   本项目 `kline_sync` 的 `日K同步失败: X/Y 只标的未获取, 已保留旧数据` 就是被上游版本覆盖后丢失的。
3. **本地是独立新功能、上游同文件只是无关改动** → 取本地，或手工并
4. **双方改同一逻辑** → 手工并：**保留上游语义 + 注入本地参数/分支**
   （例：上游新增"期末强制平仓"，本地有 `profit_lock_steps` → 两者都留）
5. **拿不准** → **看测试**。本地测试就是行为规格；
   若测试与上游新语义冲突，先判断"这是上游有意变更还是我们漏了"（见第 7 节）

---

## 6. 第四步：识别"迁移型变更"

上游搬文件时（本项目：25 个内置策略 `builtin/` → `seeds/`），文件"消失"不等于"被删"。

**必须全仓扫旧路径引用，三种形式都要查：**

```bash
# ① 模块导入（带尾点）
grep -rn "app\.strategy\.builtin\." .
# ② 无尾点的 from-import
grep -rn "from app\.strategy\.builtin import" .
# ③ Path 分段拼接
grep -rn '"strategy" / "builtin"' .
```

本项目第一次只查了 ①，漏了 ②③，导致 36 个脚本/测试在合并后 import 失败。

**本地新增代码该放哪？** 选上游**永远不会创建同名文件**的目录。
本项目选 `strategy/research/`：上游把 `research/` 当"研究模板区"（`research_only`），
不会往里放策略，且引擎的 `_load_file()` 会自动把同目录 `_*.py` 当依赖注入。

---

## 7. 第五步：覆盖度复查（本项目最大教训）

**只查"代码目录"一定会漏。** 本项目第一轮只查了 `backend/app`、`frontend/src`、`backend/tests`，
漏掉了 **981 个文件**：603 篇 `docs/research`、153 个 `scripts/`、136 个测试、
`docs/` 根目录 13 篇（含契约校验器强制要求的 5 篇）、`prompt/`、`screenshots/`、`frontend/e2e/`。

### 正确做法

```bash
# 用 -z 避免中文路径被转义成八进制
git diff --name-only -z --diff-filter=A <真实base> main
```

逐个检查是否存在于合并版；对**修改类**文件抽查关键函数/常量是否保留。

**排除项要写清楚**：本项目的 23 个 `builtin/*.py` 是**有意迁移**到 `research/`，不算缺失。

### 契约校验器是个好哨兵

本项目 `tests/test_project_contract_scripts.py` 会强制校验
`docs/README.md`、`architecture.md`、`data-foundation.md`、`analysis-development.md`、`upstream-sync.md`
必须存在。文档漏搬时它会直接报 `PROJECT_CONTRACTS_INVALID`——**先补文件，不要改测试**。

---

## 8. 第六步：验证关卡（四道 + 一道对照实验）

| # | 关卡 | 命令 |
|---|---|---|
| 1 | 后端全量 | `backend/.venv/Scripts/python.exe -m pytest -q` |
| 2 | 前端类型 | `npx tsc --noEmit -p tsconfig.json` |
| 3 | 前端单测 | `npx vitest run` |
| 4 | 前端构建 | `npx vite build` |

### 第 5 道：对照实验（关键）

任何失败项，**立刻拿到用户的 `main` 上跑同一批**：

- 两边都挂 → **既有失败**，与本次合并无关（记入基线）
- 只有合并版挂 → **迁移引入的回归**，必须修，不能"记录下来以后再说"

本项目靠这一招，一次性确认 26 个失败全是回归（本地 main 38 passed / 0 failed）。

> 注意：对照命令里的路径要写对（`tests/backtest/xxx` 不是 `tests/xxx`）。
> 路径写错时 pytest 可能跳过该文件，"对照通过"是假的。

### 环境类失败要认出来

本项目 2 个 `test_tdxquant_probe.py` 失败是缺 `tdxaidata` 包，纯净上游同样失败 —— 属基线。

---

## 9. 第七步：推送策略（别丢历史）

先判断 `main` 是不是合并分支的祖先：

```bash
git merge-base --is-ancestor main sync/upstream-<ver>   # 真=可快进
```

本项目为**否**（合并分支基于 upstream，`main` 有 1450 个提交不在其中）。

| 方式 | 后果 | 何时用 |
|---|---|---|
| `git merge -s ours main` 再推 | 内容取合并版，**`main` 的提交全部成为祖先**，推送是快进，历史完整 | ✅ 默认 |
| `git push --force origin sync/...:main` | 内容对，但**丢 1450 个提交的历史**，不可逆 | 仅当用户明确同意"不要历史" |

> `-s ours` 会忽略 `main` 的树内容，所以**必须先确认第 7 节覆盖度 100%**，否则等于丢掉没搬过来的东西。

---

## 10. 陷阱清单（全部踩过）

1. `git merge-file --union` 永不输出冲突标记 → 不能用"无标记"判"无冲突"
2. union 会产生：重复 import 块、重复 `useEffect` 依赖数组、重复 `const xxx = useRef`、
   可选参数被插到必填参数之前（TS 报错）、参数被插进同名函数的另一个定义
3. **前端扩展注册表只接受静态路径**：`/quantx/:date` 会让**整个扩展**加载失败（面板直接不出现），
   动态参数走查询串 `?date=`
4. **文件在 ≠ 功能可用**：必须查引用方。本项目 K 线工作台接在已废弃的 `pages/StockAnalysis.tsx` 上，
   上游把该页重构成 `custom/stock-analysis/extension.tsx` 后，不接回去就是"代码在、没人用"
5. **React hooks 顺序**：`useState`/`useEffect` 不能放在 early return 之后
6. **"策略只有 7 个"是假象**：`list_strategies()` 默认 `include_research=False`，
   会过滤 `research_only` 的策略。要看全量得传参，或直接读引擎 `_strategies`
7. **CRLF/编码差异制造假冲突**：先 `cmp`
8. **中文路径被 git 转义**：用 `--name-only -z`
9. **上游语义变更 ≠ 我们的 bug**：先判断是"上游有意改"还是"我们漏了"。
   本项目 3 处：期末强制平仓（`censored`→`sold`，多计卖出佣金）、
   信号定义迁数据库（`SIGNAL_OPTIONS` 常量废弃）、策略 `source` 口径（`builtin`→`custom`）
10. **BOM**：某些本地文件带 U+FEFF，合并后要检查

---

## 11. 完成定义（Definition of Done）

全部满足才允许推送：

- [ ] 四道关卡全绿；失败项都做过**对照实验**并归因
- [ ] 覆盖度复查 100%（新增文件 + 修改文件抽查）
- [ ] 三大自研面板路由实测注册（`/quantx`、`/market-lab`、`/stock-pools` 等）
- [ ] 自研策略引擎实测加载数正确、`load_errors()` 为空
- [ ] 后端插件全部零错误挂载
- [ ] 上游行为变更逐条记录进差异分析文档
- [ ] 差异分析文档更新（新增/修改/删除数字）
- [ ] 用户真机跑一次 `dev.sh` 确认
- [ ] 用户明确同意后才推送

---

## 12. 下次的预期

冲突面已经收敛到**固定的 121 个修改文件**（`backend/app` 46、`backend/tests` 34、`frontend/src` 29 等），
新增的 1221 个文件永久零冲突。

| 同步节奏 | 预计冲突文件 |
|---|---|
| 每 1–2 个上游版本一次 | **10–25 个**，多为区块级 |
| 跨 5 个版本以上 | 50+，且容易出现整文件冲突 |

**结论：同步频率比同步技巧更重要。** 上游小版本一发布就跟，不要攒。

---

## 13. 可选加固（未做，按需）

1. **区块标记**：在 121 个修改文件的核心块加 `# >>> LOCAL-EXT` / `# <<< LOCAL-EXT`，
   冲突时一眼认出"这是我的块"，不用通读全文件
2. **继续外置**：仍可搬进 `custom/` 的改动——`frontend/src/lib/signals.ts`（+166）、
   `backend/app/api/kline.py`（+175）、`backend/app/services/financial_sync.py`（+273）
3. **数据备份**：现有 `D:\tickflow-quantall-backups` 是 2026-08-27 的整份快照（923M），
   已被当前 `data/` 全面覆盖。若要"新备份点"，用 `backend/scripts/backup_quantx_data_foundation.py`
   生成新快照后删旧快照，比留着一个 7 周前的快照更有意义
