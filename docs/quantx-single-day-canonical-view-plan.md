# QuantX 单日富图表权威读取收口执行计划

> 状态：**complete**
>
> 建立日期：2026-08-28
>
> 当前阶段：Batch 1-9 已完成、验证并发布
>
> 关联审计：[`quantx-independent-update-audit-20260828.md`](quantx-independent-update-audit-20260828.md)
>
> 当前权威契约：[`architecture.md`](architecture.md)、[`data-foundation.md`](data-foundation.md)、[`analysis-development.md`](analysis-development.md)

## 1. Goal

在不丢失 QuantX 单日七区和现有富图表能力的前提下，将 `/quantx/:date` 从“深拷贝 `review_data.json` 后用权威事实覆盖”迁移为“从类型化空结构开始，完全由 Market Facts、KlineRepository、确定性 ViewBuilder 和前端展示常量组装”。

最终必须达到：

- 单日页面运行时不读取 `review_data.json`；
- 可复用业务数值只来自 Market Facts 或 KlineRepository；
- 页面摘要由版本化、可测试的确定性规则生成；
- 标题、颜色、布局等纯展示信息不进入事实存储；
- 缺失数据返回明确空值、质量和原因，不读取旧缓存兜底；
- API 不包含未声明字段；
- 删除或移走任意日期的 `review_data.json` 后，该日期页面仍可按现有事实完整渲染；
- 单日迁移不得破坏 QuantX 多日、市场实验室、连板梯队、市场环境和主数据更新链路。

## 2. 不在本计划内

- LLM 判断、Review Editor、Research Daily、反思知识、HTML/PDF/PNG 报告；
- 删除历史 QuantX JSON、来源快照、备份或审计资产；
- 为了消除 JSON 而把标题、颜色或文案强行建成 Market Facts；
- 没有真实来源时伪造期指或机构身份数据；
- 同时重写全部采集器、调度器和前端设计。

真实新日期联网采集、刷新可观测面板和来源治理列在本计划后半段，必须在单日读取收口稳定后分批执行。

## 3. 当前基线

以下是本计划启动时的基线（不是当前完成状态）：

- `QuantXReviewRepository.load()` 先读取并 `deepcopy(review_data.json)`，随后由 15 组 `_apply_*` 方法覆盖权威字段；
- 20260827 响应声明 `read_mode=canonical_facts_with_presentation_cache`；
- 已声明约 31 组 canonical 字段；
- 兼容骨架仍读取 `review_data.json`，当前 `source_json_read=true`；不得在 V2 切换前误报为 false；
- 仅 3 个受控遗留字段继续读取 presentation cache：futures、institution、dx_strength；
- `emotion_zones`、`height_trend`、`daily_summary`、diagnosis 和 risks 已转为版本化确定性派生；
- 多日面板已经直接从 Market Facts 构建，不依赖该单日 JSON 骨架；
- Market Facts 历史覆盖为 958/962，99.58%，有 4 个显式缺口；
- QuantX/SourceManager/Market Facts 定向测试基线为 39 passed；
- 最新 20260827 发布可正常读取，但 12 个网络来源均复用了本地快照，不能代替全新联网采集验收。

## 4. 执行原则

1. **先登记、再迁移、后删除。** 未登记字段不能静默保留，未完成消费方扫描的字段不能直接删除。
2. **事实与 View 分离。** 多页面可复用的数据进入 Market Facts；只服务单日页面的确定性摘要进入 ViewBuilder；纯展示信息进入前端。
3. **不以旧值一致为唯一目标。** 旧 JSON 与 canonical 冲突时，以有来源、版本和质量记录的权威事实为准，并记录差异原因。
4. **每批可独立回滚。** 每个 Batch 单独提交；未通过完整验收不得开始下一批。
5. **禁止隐式兜底。** canonical 缺失时返回空值与 coverage，不允许用 JSON 中同名旧值补齐。
6. **图表能力优先保护。** 每批都必须核对七区、图表数量、历史日期和交互，不以 API 200 代替页面验收。
7. **历史资产只读保留。** 在最终切换稳定前不删除 `review_data.json`，切换后也先降级为迁移证据，再单独决定归档策略。

## 5. 字段分类目标

每一个 API 叶子字段必须归入且只归入一类：

| 分类 | 定义 | 允许来源 | 缺失行为 |
| --- | --- | --- | --- |
| `canonical_fact` | 可跨页面、分析和日期复用的市场事实 | MarketFactRepository | 返回空值和事实缺口 |
| `canonical_kline` | 行情、指数及其确定性指标 | KlineRepository/IndexRepository | 返回空值和行情覆盖缺口 |
| `derived_view` | 只为当前 View 服务、可由权威事实重算 | 版本化 ViewBuilder | 返回空值和输入缺口 |
| `presentation_constant` | 标题、标签、颜色、布局提示 | 前端常量或版本化 UI 配置 | 使用前端默认值 |
| `deprecated` | 已确认无可靠语义或无消费者 | 仅兼容期保留 | 发出弃用信息，截止版本后删除 |

禁止存在第六类“因为旧 JSON 里有，所以继续返回”。

## 6. Batch 1：消费字段清单与 V2 契约

状态：`complete`

### 工作项

- [x] 自动提取 `frontend/src/pages/QuantXReview.tsx` 及其子组件实际读取的响应路径。
- [x] 扫描仓库内其他 `/api/quantx/review/{date}/data` 消费者。
- [x] 建立版本化 `QuantXReviewResponseV2` schema；明确日期格式、数值单位、空值和列表排序。
- [x] 建立字段来源 registry，覆盖每一个响应叶子字段。
- [x] 在 `data_foundation` 增加：`schema_version`、`derived_fields`、`presentation_fields`、`deprecated_fields`、`fallback_fields`、`implicit_cache_fields`。
- [x] 增加审计函数：响应叶子字段与 registry 做双向差集。
- [x] 未登记字段、重复分类、前端读取不存在字段时测试失败。
- [x] 保持 V1 对外响应兼容，本批不删除 JSON、不改变图表。

### 验收门槛

- [x] `implicit_cache_fields` 能准确列出全部当前隐式字段。
- [x] 所有实际前端消费字段都有唯一分类。
- [x] 20260825、20260826、20260827 单日 API 字段清单可重复生成。
- [x] 现有 QuantX 定向测试通过，并新增 schema/registry 和缺输入用例。
- [x] 前端生产构建通过。
- [x] standalone Python Playwright + Microsoft Edge headless 基线通过，保存七区、12 个 canvas 和关键文本证据。

### 本批禁止

- 删除或重命名现有字段；
- 修改采集器和 Market Fact schema；
- 将所有展示字段不加区分地提升为事实。

## 7. Batch 2：迁移确定性派生和展示字段

状态：`complete`。

### 字段处置

| 字段 | 目标分类 | 实现 |
| --- | --- | --- |
| section 标题 | `presentation_constant` | 移到前端区块配置 |
| `sections.s3.emotion_zones` | `derived_view` | 从 canonical 情绪分数和版本化阈值计算 |
| `emotion.height_trend` | `derived_view` | 从 canonical `sections.s3.height_history` 计算 |
| `emotion.daily_summary` | `derived_view` 或删除 | 使用确定性模板；若无实际价值则走 deprecated 流程 |
| `sections.s0.diagnosis` | `derived_view` | 从 market state/signals 生成 |
| `sections.s0.risks` | `derived_view` | 从 risk signals 生成，保留证据代码 |

### 工作项

- [x] 将规则放入版本化 ViewBuilder，不在 React 中复制业务阈值。
- [x] 每个派生结果记录输入字段和算法版本。
- [x] 输入事实缺失时返回空派生值及 `missing_inputs` coverage reason。
- [x] 禁止从缓存读取同名字段作为回退。
- [x] 对 74 个已发布日期生成旧缓存/当前权威视图差异报告。

### 验收门槛

- [x] 上表字段全部不再依赖 `review_data.json`；section 标题已移至前端常量。
- [x] 相同输入产生完全相同的序列化响应。
- [x] 历史差异已归类为确定性规则重算或标准事实输入缺口。
- [x] 单日页面图表、情绪卡片、梯队摘要和风险展示不回退。

## 8. Batch 3：弃用无效或来源不可靠字段

状态：`complete`。

### 字段决策

- [x] `sections.s1.futures`：V2 删除；没有可靠期指事实，不建立空事实表。
- [x] `sections.s4.institution`：V2 删除；不把行业/题材资金解释为机构身份。
- [x] `sections.s4.dx_strength`：V2 和前端删除；没有可靠标准来源。
- [x] `llm_block`：消费者为零，V2 删除。

### 验收门槛

- [x] 仓库内消费者扫描为零，或已有明确迁移版本。
- [x] deprecated 字段在 V1 `deprecation_schedule` 声明 V2 删除版本。
- [x] 不新增空事实表，不用其他数据伪装缺失语义。

## 9. Batch 4：从空结构构建 V2 View

状态：`complete`。

### 目标结构

```text
QuantXReviewViewBuilder
├─ build_header
├─ build_market_overview
├─ build_indexes_and_history
├─ build_breadth_and_congestion
├─ build_themes
├─ build_sentiment_and_ladder
├─ build_sector_flow
├─ build_candidates
└─ build_position_and_scenarios
```

### 工作项

- [x] 用 `QuantXReviewResponseV2.empty(trade_date)` 取代 `deepcopy(cached)`。
- [x] 每个 builder 只通过 Repository 接口读取数据，不读来源 JSON。
- [x] V1/V2 独立构建并通过 74 日对账；默认切换后仍保留显式 V1 运维路径。
- [x] 差异记录包含字段路径、V1/V2 值、来源分类和原因。
- [x] V1 运维路径可独立构建；V2 错误不会破坏历史兼容资产。

### 验收门槛

- [x] V2 七个 section 完整。
- [x] `source_json_read=false`。
- [x] `fallback_fields=[]`。
- [x] `implicit_cache_fields=[]`。
- [x] 关键数值、列表排序和图表序列通过 74 日历史对账。

## 10. Batch 5：切换 V2 并停止运行时读取 JSON

状态：`complete`。20260828 完整交易日发布观察完成，公开 V1 回退入口已关闭。

### 工作项

- [x] API 默认返回 V2；观察期结束后 `view_version=v1` 返回 422，不再暴露运行时 JSON 读取入口。
- [x] 前端 TypeScript 类型切换到 V2。
- [x] 将 `review_data.json` 从运行时输入降级为历史迁移证据。
- [x] 添加测试：移走目标日期 `review_data.json` 后 API 仍可工作；页面通过 V2 元数据与空态联调验证。
- [x] 观察 20260828 完整交易日发布周期后，移除公开 V1 回退开关。
- [x] 决定暂时继续生成兼容 JSON 作为迁移证据；停止生成另开迁移任务，不删除历史文件。

### 最终响应目标

```json
{
  "data_foundation": {
    "schema_version": "quantx-review.v2",
    "read_mode": "canonical_view_v2",
    "source_json_read": false,
    "canonical_fields": [],
    "derived_fields": [],
    "presentation_fields": [],
    "deprecated_fields": [],
    "fallback_fields": [],
    "implicit_cache_fields": []
  }
}
```

### 切换门槛

- [x] 三个连续已发布交易日 V1/V2 对账无未解释差异。
- [x] 75 日历史对账不存在隐式回退。
- [x] 删除测试副本中的 `review_data.json` 后 API 通过；页面只消费 V2 契约。
- [x] 单日、QuantX 多日、市场实验室、连板梯队、市场环境回归通过。
- [x] 0825/26/27/28 单日页面均保持七区和 12 个 canvas，未低于切换前基线。

## 11. Batch 6：完整回归和发布保护

状态：`complete`。

### 必须执行

```powershell
# 仓库根目录
backend\.venv\Scripts\python.exe -m pytest `
  backend\tests\test_quantx_data.py `
  backend\tests\test_quantx_source_manager.py `
  backend\tests\test_quantx_browser_runtime.py `
  backend\tests\test_market_facts.py -q

backend\.venv\Scripts\python.exe -m pytest backend\tests -q
pnpm --dir frontend build
backend\.venv\Scripts\python.exe scripts\validate_project_contracts.py
git diff --check
```

### UI 验证

- [x] 使用 standalone Python Playwright；未使用内置浏览器工具。
- [x] 使用 `p.chromium.launch(channel="msedge", headless=True)`。
- [x] 验证 20260825、20260826、20260827、20260828。
- [x] 验证单日七区、12 个 canvas、日期切换、空态和错误提示。
- [x] 验证 QuantX 多日、市场实验室、连板梯队、市场环境。
- [x] 保存截图并断言 console error、failed request 均为空；证据目录为 `docs/evidence/quantx-canonical-v2-20260828/`（本地产物，不作为源码提交）。

## 12. Batch 7：全新交易日独立联网更新验收

状态：`complete`。首次发布失败验证了原子保留；随后 20260828 全新联网发布成功。

- [x] 从继承用户级 `TUSHARE_TOKEN` 的新 PowerShell 启动后端，全程未输出 Token。
- [x] 选择已收盘且执行前不存在同日来源目录的 20260828。
- [x] 在旧 QuantX 目录和旧服务均不存在的条件下运行完整主 pipeline。
- [x] required 的 Tushare 与 pywencai 均为 `fresh`，12 个外部来源均非复用快照。
- [x] 原始快照、13 类事实、单日 V2、多日和 catalog 同批发布。
- [x] 成功 run id 为 `20260828-f3cc36bd88fb`；Tushare 输入为 `20260828/tushare.json`、5547 条、hash `ebe605…47a`；13/13 事实均已发布。
- [x] 首次 job `dd706a864c` 因收盘数据尚不可用而质量失败，确认未发布不完整事实；17:00 后 job `d5e4c8c7d0` 成功。

完成本 Batch 后，才允许将“当前环境完全独立更新”标记为实证通过。

## 13. Batch 8：QuantX 刷新、质量和血缘面板

状态：`complete`。

- [x] 展示主 pipeline job id、QuantX run id、交易日和发布时间。
- [x] 展示来源 required/optional、fresh/reused、记录数、凭据就绪和错误。
- [x] 展示 13 类事实分区、行数、质量等级、覆盖率和缺口。
- [x] 展示 canonical/derived/cache/fallback/reconciliation 状态。
- [x] 接入 run、resume、recompute、单来源 retry。
- [x] 展示 multiday/catalog 和前端 cache 刷新结果。
- [x] 数据源管理页与 QuantX 发布状态页互相链接，但保持职责分离。

## 14. Batch 9：来源契约和历史缺口治理

状态：`complete`。

- [x] SourceManager 通过独立子进程统一实现可取消的 wall-clock timeout。
- [x] Dabanke 补齐 `DABANKE_LOGIN_STATE` metadata 和受控登录态路径。
- [x] 区分 manifest health、credential readiness 和 live probe。
- [x] 为来源字段漂移、陈旧快照、空结果和限流建立指标。
- [x] 20260427 sector breadth 从同日 sidecar 正式迁移；剩余 3 个历史缺口逐项登记为 accepted gap，未使用相邻日伪填。
- [x] CI 契约检查禁止旧目录、旧端口和业务层直接 import scraper。

## 15. 执行顺序与提交边界

推荐严格按以下提交边界推进：

1. `test:` 前端消费清单、字段 registry 和失败测试；
2. `feat:` Response V2 schema 和审计元数据；
3. `refactor:` 情绪区间、连板摘要和确定性文案迁移；
4. `chore:` 无消费者字段 deprecated；
5. `feat:` V2 ViewBuilder 和 shadow 对账；
6. `feat:` API/前端切换 V2；
7. `test:` 独立 JSON 删除测试与完整 Playwright 回归；
8. `feat:` QuantX 发布可观测面板；
9. `fix:` 来源契约和历史缺口治理。

每次提交只包含当前 Batch 的文件；不得夹带当前工作区已有的任务外修改。每批完成且验证通过后单独提交和推送，失败时停止在当前 Batch，不提前勾选后续项。

## 16. 执行记录

每完成一批，在下表追加证据，不用“已完成”代替实际命令和产物：

| 日期 | Batch | 状态 | Commit | 验证证据 | 未解决风险 |
| --- | --- | --- | --- | --- | --- |
| 2026-08-28 | Plan | complete | — | 审计报告与本执行计划建立 | Batch 1 尚未开始 |
| 2026-08-28 | 1-5 | complete | `c9e8006` | 61 项 QuantX/SourceManager/Market Facts 定向测试；75/75 日期 V2 审计无 JSON、fallback、implicit cache、schema mismatch 或未解释差异；34 个前端消费字段无缺失和冲突 | 兼容 JSON 继续生成，仅作为迁移证据；公开 V1 API 已关闭 |
| 2026-08-28 | 7 | complete | `c9e8006` | job `d5e4c8c7d0`、run `20260828-f3cc36bd88fb`；12 外部来源 fresh；13/13 facts；V2/multiday/catalog 已发布 | S4 东财源空响应，明确降级使用同日 AKShare；QuickTiny 缺登录态为空 |
| 2026-08-28 | 8-9 | complete | `c9e8006` | observability API/页面；972/975 历史分区存在，3 个缺口全部 accepted、0 个未接受缺口；项目边界检查通过 | live probe 当前为按需状态，不主动探测第三方 |
| 2026-08-28 | 6 | complete | `c9e8006` | 后端全量测试、前端生产构建、项目契约、`git diff --check`；Edge headless 验证 0825-0828 和五个关联页面，单日均 12 canvas、无 console/failed request | Ruff 全仓存在大量历史基线问题，不属于本计划门禁；本次改动不做全仓格式化 |
| 2026-08-28 | Release | complete | `c9e8006` | 敏感信息扫描 0 命中；生成物未入库；`git push origin HEAD` 成功，远端 `main` 从 `2de5deb` 前进到 `c9e8006` | 无阻塞项 |

## 17. 整体完成定义

只有同时满足以下条件，才将本文状态改为 `complete`：

- [x] 单日 API 不读取 `review_data.json` 或任何来源级 JSON；
- [x] 所有响应字段具有唯一、可审计的来源分类；
- [x] Market Facts/Kline 缺失不会被旧缓存静默覆盖；
- [x] V2 历史对账、全量后端测试、前端构建和独立 Playwright 通过；
- [x] 单日富图表、多日、实验室、连板和市场环境无能力回退；
- [x] 完成一个无同日快照的新交易日联网更新验收；
- [x] 数据页可查看该次更新的来源、事实、质量和刷新血缘，并与数据源管理页互链；
- [x] 兼容 JSON 决定暂时保留并继续生成，定位仅为迁移证据；停止生成和历史归档另立迁移任务；
- [x] 文档、测试、提交和推送记录完整。
