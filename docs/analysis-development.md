# 新数据分析与前端功能开发

状态：权威开发流程。本文从已有标准数据出发，说明如何增加确定性指标、分析、API 和展示。

## 1. 开始前分类

先回答：

1. 输入是否已存在于 KlineRepository、MarketFactRepository 或 ext_data？
2. 输出是可复用事实、确定性派生指标，还是仅展示状态？
3. 时间窗口按交易日还是自然日？
4. 数值单位、复权口径、时区、空值和质量等级是什么？
5. 是否会被策略、回测、监控或多个页面复用？

输入不存在时先走 `data-foundation.md`，不要从页面或 service 临时抓取供应商接口。

## 2. 标准开发链

```text
Repository 输入
→ 纯计算函数/领域 Service
→ API 响应模型
→ frontend api.ts 类型
→ queryKeys
→ page/component
→ 单元、API、构建和 Playwright 验证
```

### 2.1 Repository

Repository 只负责范围读取、来源优先级和稳定结构。读取时限制日期和列，避免全表扫描。不要把图表颜色、文案或排序标签放进 Repository。

### 2.2 计算逻辑

优先写纯函数：显式输入、显式窗口、确定输出。Polars 计算优先表达式和批处理。

必须测试：

- 最小窗口；
- 正常窗口；
- 非交易日和缺日；
- null、空表和备用来源；
- 排序稳定性；
- 禁止未来数据。

### 2.3 Service

Service 组合 Repository 和纯计算函数，负责业务选择、缓存与错误状态。不要让 Service import scraper、React 展示类型或任意本地报告文件。

### 2.4 API

API handler 保持薄层：校验参数、调用 Service、映射响应。新增响应字段同步更新 `frontend/src/lib/api.ts`；错误应使用可操作状态，不返回模糊 500。

### 2.5 前端

- 请求统一定义在 `api.ts`。
- query key 统一定义在 `queryKeys.ts`，影响结果的日期、周期和维度必须进入 key。
- 页面组合状态和区域，重复图表逻辑下沉组件。
- 保留上一份有效数据直至刷新完成。
- 明确 loading、empty、error、disabled、stale 和 degraded。
- A 股颜色和单位必须与现有页面一致。

单日 QuantX V2 必须额外区分字段来源：可复用数值来自 Repository，页面专用摘要进入版本化 ViewBuilder，标题和布局进入前端常量。V2 从 `QuantXReviewResponseV2.empty(trade_date)` 构建，禁止深拷贝展示缓存；新增前端消费字段必须通过 `scripts/audit_quantx_review_consumers.py`，并在 schema endpoint `GET /api/quantx/review/schema/v2` 中声明来源、单位、空值和排序。默认响应的 fallback 和 implicit cache 必须始终为空。

## 3. 新分析示例路径

假设需要“行业 20 日连续性”：

1. 从 `sector_flow_daily` 和交易日历读取最近 20 个交易日。
2. 纯函数计算出现天数、净流入方向一致性和覆盖率。
3. 缺日降低 coverage，不补零。
4. Service 返回 `{window, rows, coverage, quality}`。
5. API 增加带 `as_of` 和 `window` 的 endpoint。
6. api.ts 添加精确类型，query key 包含日期和窗口。
7. 页面提供 5/10/20 切换，并显示 coverage。
8. fixture 测试和 Playwright 验证切换、空数据和图表。

## 4. 禁止路径

- 在 React 中直接请求第三方 URL。
- 在 API handler 中读取 `raw/*.json` 并临时拼表。
- 为一个页面复制一套已有指标算法。
- 用缓存 JSON 作为回测或策略事实来源。
- 用自然日切片冒充交易日窗口。
- 把缺失来源显示为零值。
- 只检查页面能打开，不检查网络、控制台和数据语义。

## 5. AI 任务模板

```text
请在当前 TickFlow 仓库实现：[需求]。

开始前完整阅读 AGENTS.md、CONTRIBUTING.md、docs/README.md，按数据类型继续阅读：
- 新来源/schema：docs/data-foundation.md；
- 自有 HTTP 行情：docs/custom-data-source.md；
- Provider 插件：docs/plugin-development.md；
- 分析/API/页面：docs/analysis-development.md。

先用源码和测试证明输入数据、Repository、单位、交易日窗口和现有扩展点。
不得从页面/API 绕过 Repository 直接读取供应商或 raw JSON。
若输入事实不存在，先定义 DatasetSpec、SourceRoute、builder、质量规则和迁移方案。

完成时列出：
1. 数据来源和字段单位；
2. Repository → Service → API → 前端调用链；
3. 缓存和发布失效路径；
4. 实际测试、构建和 Playwright 证据；
5. 仍存在的来源或历史覆盖风险。
```

## 6. 验证命令

```powershell
cd backend
uv run --frozen pytest tests/<target>.py -q
uv run --frozen ruff check app/<target>.py tests/<target>.py

cd ../frontend
pnpm build

cd ..
python scripts/validate_project_contracts.py
git diff --check
```

涉及页面时按仓库规则使用 standalone Python Playwright 和 Microsoft Edge headless，检查最终渲染、console error 和失败网络响应。
