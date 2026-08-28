# QuantX 统一看板改造执行计划

状态：第一阶段已于 2026-08-28 落地。视觉和内容范围见 [`quantx-unified-dashboard-design.md`](quantx-unified-dashboard-design.md)，预览见 [`examples/quantx-unified-dashboard-mockup.html`](examples/quantx-unified-dashboard-mockup.html)。

当前实现已经统一 `/quantx` 与 `/quantx/:date`，落地日期、5/10/20 日窗口矩阵、固定全面展开、16 列桌面栅格、一级/二级行业宽度、去重后的完整富图表、七个深度域、完整数据与质量血缘。行业宽度使用整行和可滚动完整矩阵，题材生灭三视图同屏，退潮/崩塌信号前置；完整数据与质量血缘默认折叠并按需加载。基线提交为 `a40c0f5`，可回退标签为 `baseline-quantx-unified-20260828`。

2026-08-29 视觉收口：资金生态与行业宽度改为 9:7 比例，资金图获得更大绘图区；行业宽度明确显示 MA5/10/20/60“站上对应均线占比”的列语义。拥挤度当前值与近十日历史合为一个面板。题材生灭改为“当日结构 + 连续性热力图”同排、全部跨日事件全宽四列展开，不使用内部纵向滚动。通用业务表和质量血缘表统一采用自适应满宽表格、粘性中文表头和按内容触发的横向滚动，禁止窄表贴左并在卡片右侧留下无意义空白。

本轮没有假装完成仍需独立验证的后续项：组件与 view model 进一步拆分、`dimension/selected` 主从钻取、个股弹窗、完整表筛选/排序/虚拟化、历史事实缺口补齐及性能 Profiler 预算。这些继续按批次 4、5、6、7 收口，不影响当前统一入口使用。

本阶段验证证据：前端生产构建通过；36 组单日消费路径审计无缺失和冲突；Microsoft Edge headless 覆盖 20260825、20260826、20260827；固定全面展开页均渲染 12 个不重复 canvas；1024px 无横向溢出；empty、404、日期切换、一级/二级行业切换及关联页面通过。

## 1. 改造原则

1. 先建立零丢失基线，再移动组件；不能边重写图表边改变数据口径。
2. `/quantx` 与 `/quantx/:date` 渲染同一个页面，不建立驾驶舱和报告两套实现。
3. 第一阶段复用现有 API，不先引入聚合“超级接口”。
4. 当日事实来自 review V2 和标准表，多日事实来自 multiday；历史日期不得读取当前实时概念快照。
5. 页面固定全面展开；同一数据语义只保留一张图，禁止在概览区和深度区重复挂载。
6. 每个迁移批次都必须保持页面可运行、可回滚和可独立验证。

## 2. 目标调用链

```text
/quantx 或 /quantx/:date
  -> QuantXDashboard 页面容器
      -> catalog query：日期、发布阶段、基础指标
      -> review query：当日权威事实、七区确定性 View
      -> multiday query：5/10/20 日窗口、生命周期、连续性、机会雷达
      -> observability query：仅质量抽屉打开时加载
      -> tables query：仅完整数据页签打开时加载
  -> buildQuantXDashboardViewModel
  -> 16 列看板组件
      -> 首屏决策区
      -> 多日与情绪区
      -> 行业、资金与关注区
      -> 深度图表工作区
```

不在 React 组件中直接拼接 raw JSON，也不从概念分析页面读取当前快照。需要补充历史事实时走 Market Facts、Repository、Service、API、前端类型的标准链路。

## 3. 路由与状态设计

### 3.1 路由

- `/quantx`：读取 catalog，解析最新 `multiday_available` 且 review 可用的交易日；URL 可以保持 `/quantx`。
- `/quantx/:date`：直接展示指定交易日，保留全部现有历史链接。
- 两条路由使用同一个 `QuantXDashboard`，不做页面级复制。
- 非交易日、未发布日期和部分发布日期分别显示明确状态。

### 3.2 URL 状态

| 参数 | 示例 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `window` | `5/10/20` | `20` | 多日统计和连续性窗口 |
| `tab` | `market/themes/emotion/flow/watch/data/quality` | `market` | 深度工作区页签 |
| `dimension` | `theme/industry1/industry2` | `theme` | 主从分析维度 |
| `selected` | 稳定名称或代码 | 空 | 当前题材、行业或个股选择 |

日期进入路径而不是只放本地状态；页面刷新、复制链接和浏览器前进后退必须恢复相同上下文。

### 3.3 查询与缓存

- `QK.quantxCatalog` 保持现状。
- `QK.quantxReview(date)` 和 `QK.quantxMultiday(date)` 继续按日期隔离。
- 新增 `QK.quantxTables(date)`；完整数据页签未打开时禁用。
- 质量页签复用 `QK.quantxObservability(date)`，只有打开时加载。
- 日期切换使用 TanStack Query 的 placeholder/previous data 机制保留旧快照，并在顶栏明确显示“正在切换到 YYYYMMDD”。
- 刷新成功后同时失效 catalog、review、multiday、tables 和 observability 的精确日期键。

## 4. 组件与文件结构

```text
frontend/src/pages/QuantXDashboard.tsx
frontend/src/hooks/useQuantXDashboard.ts
frontend/src/components/quantx/dashboard/
  QuantXHeader.tsx
  QuantXCalendarPopover.tsx
  MetricRibbon.tsx
  DashboardPanel.tsx
  MarketPulsePanel.tsx
  ThemeWorkbench.tsx
  DecisionRail.tsx
  WindowSignalPanel.tsx
  EmotionCyclePanel.tsx
  OpportunityRadarPanel.tsx
  SectorBreadthPanel.tsx
  CapitalEcosystemPanel.tsx
  WatchlistPanel.tsx
  DeepDiveWorkspace.tsx
  DataQualityPanel.tsx
  viewModel.ts
frontend/src/components/quantx/charts/
  IndexChart.tsx
  KlineChart.tsx
  UpCountChart.tsx
  SectorBreadthHeatmap.tsx
  CongestionGauge.tsx
  MarginChart.tsx
  HeightChart.tsx
  AdvanceRateChart.tsx
  EmotionTrendChart.tsx
  SectorFlowChart.tsx
  SectorTreemapChart.tsx
  SectorScatterChart.tsx
```

`QuantXDashboard.tsx` 只负责路由状态、查询状态和区域编排。数据组合进入 `viewModel.ts`，ECharts option 留在图表组件中，题材/行业选择逻辑进入 `ThemeWorkbench`，避免生成新的大型单文件页面。

## 5. 分批执行

### 批次 0：冻结基线和消费者清单

目标：在任何页面重排前证明现有能力边界。

改动：

- 扩展 `scripts/audit_quantx_review_consumers.py`，覆盖 review V2 的嵌套字段；
- 新增 multiday 消费者审计，覆盖 `window_signals`、`institution_continuity`、`core_stocks` 等字段；
- 更新 `scripts/verify_quantx_review_ui.py`，保存当前 3 个交易日的全页截图和canvas清单；
- 记录每张图的标题、series、tooltip字段、markLine和表格列。

门槛：

- 当前34组review顶层消费路径继续通过；
- 所有嵌套字段被分类为首屏、页签、抽屉、质量页或明确废弃；
- 不允许未分类字段进入后续批次。

### 批次 1：无视觉变化地拆分图表

目标：先把 `QuantXReview.tsx` 中12个图表和共享ECharts生命周期拆出，页面视觉保持一致。

改动：

- 新建 `components/quantx/charts/`；
- 提取 `useEChart` 或统一使用项目已有ECharts封装；
- 保留全部 series、tooltip、颜色、markLine、坐标轴和空数据判断；
- 图表props从 `any[]` 收紧为 review V2 对应类型；
- `QuantXReview.tsx` 暂时继续按原布局组合新组件。

门槛：

- 旧页面仍至少渲染原有图表数量；
- 三个基准日期的字段、标题和图表语义不变；
- 前端build通过，Playwright截图无明显内容缺失。

### 批次 2：统一页面容器和兼容路由

目标：让两个路由先使用同一个容器，但暂不完成最终视觉。

改动：

- 新建 `QuantXDashboard.tsx` 和 `useQuantXDashboard.ts`；
- `/quantx` 与 `/quantx/:date` 都指向统一组件；
- `/quantx` 自动选择最新可用日期；
- 同时查询 catalog、review、multiday，并分别处理loading、404、degraded；
- 建立 `buildQuantXDashboardViewModel`，禁止组件直接跨响应对象拼字段；
- URL同步window、view、tab、dimension和selected。

门槛：

- 旧 `/quantx/:date` 书签仍可打开；
- 日期选择、前后交易日、最新和浏览器前进后退正确；
- 日期切换时没有上一交易日数据冒充当前日期；
- review或multiday单独缺失时其余区域仍可使用。

### 批次 3：落地首屏16列看板

目标：实现设计稿的固定顶栏、指标带和A/B/C三行主体。

改动：

- 实现 `QuantXHeader`、日历弹层、指标带；
- 实现市场脉搏、题材主线和今日决断；
- 实现多日矩阵、情绪时间轴和机会雷达；
- 实现行业宽度、资金生态和关注池；
- 引入统一 `DashboardPanel` 标题、动作、loading、empty、error和degraded样式；
- 桌面使用16列不对称跨度，窄屏按信息优先级重新排列。

门槛：

- 1440×900首屏可见指标带、市场脉搏、题材主线和今日决断；
- 1600×1100可见A/B/C主要区域；
- 1024宽度无横向滚动；
- 颜色之外有文字、图标或形状表达状态。

### 批次 4：迁移多日、主从钻取和隐藏能力

目标：合并 `MultidayPanels.tsx` 全部能力，并把API已有但未展示的字段接入。

改动：

- 迁移交易日历、窗口统计、题材生命周期、因子归因、机会雷达、行业连续性；
- 窗口矩阵补齐mainline、warming、cooling、institution和sector_flow；
- 情绪卡补齐 `ladder_grid` 和 `ladder_detail`；
- 资金卡补齐 `institution_continuity`、`core_stocks` 和规则候选；
- 题材/行业采用左排行、右详情或详情抽屉；
- 个股点击复用 `StockPreviewDialog`。

门槛：

- multiday契约中所有字段都有消费者；
- 题材/行业切换不会改变所选日期；
- 一级/二级行业切换和5/10/20窗口互不污染；
- 历史日期没有调用当前实时概念快照。

### 批次 5：完整富图表工作区

目标：让所有不重复的原图表和表格在同页固定展开。

改动：

- 实现市场、题材行业、情绪连板、资金、关注、完整数据、质量七个页签；
- 按领域逐段挂载全部图表，不再设置紧凑/全部展开双模式；
- 市场脉搏与全A K线只保留一处，情绪趋势只保留在“情绪周期与交易日历”；
- 图表使用完整语义所需高度；
- 完整数据页签按需调用 `getTables(date)`，支持数据集选择、列筛选、排序和虚拟滚动；
- 质量页签按需调用observability，展示来源、事实、版本、覆盖和错误。

门槛：

- 原12类图表全部存在且数据series未减少；
- 所有领域默认可见，重复图表数量为零；
- 初始页面不同时初始化全部重型图表；
- 完整表切换不会触发重复全量请求。

### 批次 6：补历史事实缺口

目标：只补经过审计确认的历史钻取缺口，不为UI临时抓数据。

执行顺序：

1. 列出题材成员、行业成员、龙头、核心个股和机构连续性的缺失日期与字段；
2. 判断现有 `QuantXTableRepository` 或 Market Facts 是否已有事实；
3. 已有事实只增加Repository读取和API类型；
4. 没有事实时先定义DatasetSpec、SourceRoute、单位、质量和历史回填方案；
5. 再增加Service/API和前端消费者；
6. 缺失期间显示coverage/degraded，不读取未来数据补空。

门槛：

- 后端固定样本测试覆盖目标日和前后交易日；
- 没有自然日冒充交易日窗口；
- 无未来数据、无当前成分回填历史；
- 数据源失败不导致整个看板500。

### 批次 7：切换主入口和清理旧编排

目标：正式以统一看板替代两个旧页面实现。

改动：

- 删除 `QuantXCatalog` 和 `QuantXReview` 的页面编排职责；
- 仍被使用的组件迁入dashboard/charts，确认无引用后再删除旧壳文件；
- 更新导航文案、开发文档和Playwright脚本；
- 保留后端review V2、multiday和tables接口，不因前端合并而破坏外部消费者。

门槛：

- `/quantx` 与 `/quantx/:date` 都通过最终回归；
- 仓库无重复QuantX页面业务逻辑；
- consumer audit、前端构建、后端测试和Playwright全部通过后才移除旧壳。

## 6. 测试与验证矩阵

### 6.1 后端

```powershell
cd backend
uv run --frozen pytest tests/test_quantx_review_view.py tests/test_quantx_data.py -q
uv run --frozen pytest tests/test_quantx_source_manager.py tests/test_quantx_browser_runtime.py -q
uv run --frozen ruff check app/quantx_data app/api/quantx.py app/api/quantx_data.py tests/test_quantx_review_view.py tests/test_quantx_data.py
```

仅改前端且API契约不变时，至少运行前两组QuantX定向测试。补充历史事实时增加对应Market Facts测试。

### 6.2 前端

```powershell
cd frontend
pnpm build
pnpm lint
```

必须检查：日期、窗口矩阵、行业层级、题材选择、个股弹窗、全部深度域、刷新、空数据、部分发布、来源降级和错误状态。

### 6.3 Standalone Playwright

更新 `scripts/verify_quantx_review_ui.py` 为统一看板验收脚本，继续使用Microsoft Edge headless。至少覆盖：

- 20260825、20260826、20260827三个已发布样本；
- `/quantx`解析最新日期；
- `/quantx/:date`兼容；
- 日历切换和浏览器前进后退；
- 5/10/20日窗口切换；
- 一级/二级行业切换；
- 题材/行业/个股机会雷达；
- 情绪时间轴、梯队和风险信号页签；
- 七个固定展开的深度域；
- 重复 K 线、重复情绪趋势及视图模式开关均不存在；
- empty、404、degraded和刷新中；
- console error、page error和失败网络请求为0；
- 每个关键区域截图和最终全页截图。

## 7. 性能预算

- 初始数据请求：catalog、review、multiday三类；同一query key不得重复请求。
- observability和tables默认不请求。
- 固定全面展开页只创建语义唯一的图表实例，当前目标不超过12个。
- 题材、个股和完整表长列表使用分页、行数限制或虚拟化。
- 日期切换不清空整页；旧快照保留并明确标记refreshing。
- ResizeObserver、ECharts实例和事件监听在卸载时全部释放。

性能结论必须通过React Profiler、请求计数和ECharts实例计数验证，不能凭主观感受声明优化完成。

## 8. 提交拆分建议

每个批次一个聚焦提交或PR，避免把零丢失基线、布局重写和历史数据schema混在一起：

1. `test: freeze quantx dashboard consumer baseline`
2. `refactor: extract quantx chart components`
3. `feat: unify quantx routes and dashboard state`
4. `feat: build dense quantx dashboard layout`
5. `feat: integrate quantx multiday drilldowns`
6. `feat: preserve full quantx chart workspace`
7. `feat: close quantx historical fact gaps`（仅确有缺口时）
8. `chore: retire legacy quantx page shells`

任何批次验证失败都停在当前批次修复，不带着红灯进入下一批。

## 9. 最终完成定义

- 用户只感知一个QuantX看板；
- 日期是全页唯一主上下文；
- 驾驶舱、多日能力和单日富图表全部在同页；
- 原12类图表、34组review消费路径及multiday全部字段没有丢失；
- API中原未展示的梯队、机构连续性、核心个股和窗口题材变化已接入；
- 页面只有固定全面展开态，概览与深度区不存在重复图表；
- 历史数据没有未来污染；
- 数据缺失可解释、可降级，不出现模糊500；
- 后端定向测试、前端build/lint、消费者审计、项目契约和Playwright全部通过；
- 文档、截图证据、提交和推送状态完整记录。
