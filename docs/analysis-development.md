# 新数据分析与前端功能开发

状态：权威开发流程。本文从已有标准数据出发，说明如何增加确定性指标、分析、API 和展示。

## 1. 开始前分类

先回答：

1. 输入是否已存在于 KlineRepository、MarketFactRepository 或 ext_data？
2. 输出是可复用事实、确定性派生指标，还是仅展示状态？
3. 时间窗口按交易日还是自然日？
4. 数值单位、复权口径、时区、空值和质量等级是什么？
5. 是否会被策略、回测、监控或多个页面复用？

若分析结果需要叠加到个股 K 线，不得在 React 页面或 ECharts option 中直接复制业务算法。纯观察、不可执行的结构标记可实现 `ChartLayerProvider`，消费 `/api/kline/chart` 的最终同口径 candles，返回版本化 `ChartAnnotationLayer`；必须提供稳定 ID、算法版本、输入指纹、确认时间、证据和数据不足状态。凡是会被解释为候选、入场、离场或交易触发的条件，必须先注册为正式策略，不得用独立 `pattern.*` 图层绕过策略注册。

正式策略在 K 线中有两条清晰分开的路径：策略面板、回测或实时监控产生的跨日证据写入 `strategy_signal_events`，供“已记录事件”图层读取；已声明 `META["chart_preview"]={"enabled": True, "mode": "single_asset"}` 的 `matrix_native` 策略可由 `POST /api/strategies/preview` 对当前单一标的、所选日线区间和必要预热 K 线做因果信号回放，返回临时 `ChartAnnotationLayer`。预览不得执行全市场扫描、不得写入事件仓库、不得模拟成交，也不得计算单标的横向评分；不支持该契约或周期的策略必须明确不可用。`signal_kind` 用于区分策略信号、回测成交和实时触发。

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

QuantX 页面分享统一调用 `frontend/src/lib/exportStaticHtml.ts`：它从现有 QuantX API 收集一个交易日的已发布响应，内嵌页面样式和由 `frontend/src/portable/quantxPortable.tsx` 启动的 React/ECharts 便携运行时，在浏览器内生成一个不依赖后端的交互式 HTML。便携运行时只把内嵌响应映射回既有 `quantxApi` 契约，不复制指标计算或另建报告数据流水线；批量百日新高成员使用 `GET /api/quantx-data/new-high/{trade_date}/member-bundle`，避免导出时逐聚类请求。页面按钮与 `scripts/export_quantx_static.py` 必须复用这一实现；命令行脚本需使用 Edge 在断网浏览器上下文重新加载文件，验证图表重绘、悬浮提示、筛选、下钻、折叠区、本机地址和网络请求、控制台错误及页面级横向溢出。操作说明见 `docs/quantx-static-export.md`。

单日 QuantX V2 必须额外区分字段来源：可复用数值来自 Repository，页面专用摘要进入版本化 ViewBuilder，标题和布局进入前端常量。V2 从 `QuantXReviewResponseV2.empty(trade_date)` 构建，禁止深拷贝展示缓存；新增前端消费字段必须通过 `scripts/audit_quantx_review_consumers.py`，并在 schema endpoint `GET /api/quantx/review/schema/v2` 中声明来源、单位、空值和排序。默认响应的 fallback 和 implicit cache 必须始终为空。

QuantX 高级图谱由 `app.quantx_data.advanced.build_advanced_snapshot()` 在服务层一次性构建，前端只通过 `GET /api/quantx-data/advanced/{date}` 发起一个共享查询。当前契约固定包含 15 张数据卡片；每张卡必须返回 `status`、`rows`、`data`，缺数据时显式返回 `unavailable`，不得生成模拟值。固定连线但没有统计因果依据的“风险传导链”不属于当前契约。行业相关性和 RPS 轮动使用当前行业成分回看历史，主线强度历史使用当前概念成分回看历史；响应和页面必须持续展示“不是历史时点成分、越接近当前日期越可靠”的口径提示。市场状态转移矩阵来自 TickFlow Regime 四维模型，顶部市场热度、短线情绪和趋势情绪来自 QuantX `market_state_daily`，两套分值与状态不得直接互换。跨日队列存活 Sankey 和龙头交接时间轴不属于当前契约。

连板晋级阶梯必须同时提供目标交易日、最近 5 个交易日和最近 20 个交易日三个视图，并把当前高级快照覆盖范围内的全部可评估交易日作为全样本基线。5/20 日与全样本均按“窗口成功数 ÷ 窗口样本数”计算样本加权晋级率，不得把每日百分比直接做算术平均；前端切换视图时必须始终保留全样本基线。`0→1` 表示当日首板封板率，`1→2` 以上表示前一交易日对应板高股票在下一交易日的晋级率。

多日快照中的 `factor_attribution` 当前保存同花顺热点榜题材及其覆盖股票数，并非涨停个股原因标签归因。前端必须使用“同花顺热点题材覆盖”等准确名称；只有在输入事实明确包含逐只涨停股的原因标签并完成标准化后，才能恢复“涨停因子归因”名称。

主线强度贡献瀑布必须发布目标交易日全部已排名主线及各自的涨停广度、连板高度、梯队完整度和二板以上贡献。首名主线兼容字段只用于默认选中，前端必须提供主线选择器，不能把首名主线呈现为当日唯一主线。

行业收益相关性矩阵必须包含当前映射中具备足够收益样本的全部一级、二级行业，不得用固定数量截断二级行业。行业较多时由前端双轴缩放控制可视窗口。每个层级同时返回去除对角线和重复组合后的最高、最低 Pearson 相关行业组合排行，并显示样本交易日数；前端默认从完整矩阵展示全部行业组合的相关度前 10、后 10，选中任意行业后切换为该行业与其他全部行业的前 10、后 10，并允许恢复总排名。相关性不得表述为因果或收益预测。

QuantX 多日快照 `tickflow-quantx-multiday-v3` 只保留 `sector_flow_continuity` 作为行业资金与规则候选连续性的权威字段，其中候选集合统一为 `rule_candidates`；不再发布内容相同的 `institution_continuity`、`institution`、`institution_days` 或 `core_stocks` 兼容别名。5/10/20 日题材结构必须分别使用所选交易日窗口聚合：主线要求在窗口有效题材日中出现率不低于 60%，升温和降温要求前后半窗归一化强度差至少为正/负 8 分，不能复用最后一个交易日的生命周期标签。

顶部“题材主线”摘要必须按页面展示的多源归一化强度 `rank_strength` 降序排列，来源数只用于同分排序，保证名次与可见分数一致；完整“题材生灭与多源连续性”表仍按多源共识优先，用于表达不同的分析口径。

百日新高卡片的权威个股集合来自 `screening_candidate_daily(candidate_type=new_high_100d)`，由 `app.quantx_data.new_high_clusters` 聚合后进入 `sections.s2.new_high`。页面主视图展示题材概念、申万一级和申万二级的 1/5/10/20 交易日聚类；点击聚类后，通过 `GET /api/quantx-data/new-high/{trade_date}/members` 按需读取完整成员证据，区分今日新高与窗口出现，并提供活跃天数、首次及最近出现日，禁止把所有成员重复塞入单日 Review 响应。交互式单文件导出可调用 `GET /api/quantx-data/new-high/{trade_date}/member-bundle` 一次读取该日所有已展示聚类的成员集合；该接口只用于传输优化，必须复用与单项接口相同的领域计算。概念标签须过滤“百日新高、趋势股、昨日、高换手”等市场属性标签；当日题材占比按一股多标签 `1/N` 加权。当前 `ext_data` 仅提供最新成分快照，因此历史窗口的行业与概念归属属于 `latest_ext_snapshot_proxy`，API 和页面必须显式提示，不能表述为历史时点成分。若未来接入带日期的成分表，应在领域 Service 内切换 point-in-time 映射，前端契约保持不变。

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
