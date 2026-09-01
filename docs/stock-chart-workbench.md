# 统一个股 K 线工作台

个股分析页只创建一个 ECharts 实例。主图、副图、关键价位、缠论结构、形态、正式策略信号和用户画线共用同一组 candles、时间轴、缩放和十字光标。主路径只有一层工具栏、一个“指标中心”和最多一行已启用摘要；旧指标抽屉和独立参数编辑器已退出主路径并删除。

## 数据契约

`GET /api/kline/chart` 参数：

- `symbol`，可选显式 `asset_type=stock|etf|index`；显式类型与本地维表冲突时返回 422。
- `interval=1m|5m|15m|30m|60m|1d|1w|1mo`。
- `adjustment=none|qfq|hfq`；指数强制 `none`。
- `range=1m|3m|6m|1y|3y|5y|all|custom`；自定义范围使用 `start_date/end_date`。
- `layers=pattern,strategy,event,plan`；不传时保持旧响应兼容，传入后返回 `annotation_layers`。
- `strategy_ids`、`source_run_id`、`params_fingerprint` 用于恢复策略页来源及精确运行批次。
- `warmup_bars` 是本次查询的最大预热需求；`indicator_warmups=id:bars,...` 携带逐指标需求并进入查询键。

`POST /api/strategies/preview` 是独立的只读单股策略接口：请求包含 `symbol`、`asset_type`、`timeframe`、`start_date`、`end_date`、至多三个正式 `strategy_ids` 和可选参数覆盖；响应返回临时策略 `annotation_layers`、策略版本和输入指纹。当前首批只开放声明日线 `chart_preview` 的四个价格结构策略，计算口径固定为前复权 enriched 日线；切换图表复权只改变 K 线显示，不重新定义策略的正式信号日期。

处理顺序固定为：原始 Repository 数据 → 复权 → 周期聚合 → 隐藏区间预热 → 指标与 11 组关键价位 → 裁剪 → API。`rows` 只含可见区间，`analysis_rows` 含隐藏预热和可见区间。响应 `meta` 提供请求/实际周期与复权、来源、覆盖起止、`complete`、`required_fetch_start`、总预热和逐指标 `indicator_readiness`。关键价位位于同一响应的 `levels`，不得再用另一份日线生成。

日线历史不足时调用 `POST /api/kline/sync_daily_single`，只补当前标的从 `required_fetch_start` 到请求结束日的原始日线和复权因子，经能力路由选择当前可用 provider；不得启动全市场历史任务。写入后失效 Repository generation/cache，再按同一查询验证可见覆盖和隐藏预热。分区读取统一使用兼容 schema，允许历史分区的整数/浮点成交量和新增 `quote_ts` 共存。

分钟线只使用本地分钟仓库已有历史。覆盖不足时页面显示真实起止，并可调用 `POST /api/kline/sync_minute_single` 补齐单股历史；provider 拒绝长区间时错误原样可见。当前本地指数分钟线不受支持，不会冒充股票分钟线。

## 指标与结构层

- `frontend/src/features/stock-chart/indicatorRegistry.ts` 是 20 个主图、38 个副图、成交量、缠论、关键价位、形态、正式策略和事件的统一类型化目录。定义包含稳定 ID、版本、语义类型、主副图位置、计算位置、字段、周期、参数 schema、样式 schema 和预热长度。
- `frontend/src/lib/indicator-formulas.ts` 保存纯公式；参数通过集中存储管理。公式异常会在工作台显示并写入控制台，不得静默消失。
- 缠论默认调用本地 `POST /api/chanlun/analyze`，显示算法版本、数据指纹和末笔确认状态。包含处理、分型、笔、段、中枢和买卖点均为同一 ECharts 的可选图层。
- ZenChart 仅是可选对照。任何官方端点无法映射到本地 candles 时整层拒绝叠加，不替换本地 K 线。
- “形态”图层只保留头肩顶、头肩底、双顶、双底、三角形五类本地启发式标记。VCP 突破、杯柄突破、高而紧旗形突破、启动后缩量回踩已注册为正式 `matrix_native` 策略，不再提供独立 `pattern.*` 图层，也不依赖 `D:\quantall\apps\quants`。

`ChartAnnotationLayer` 是版本化、与 ECharts 无关的领域契约。每层都有稳定 ID、类别、状态、复权口径、算法版本、输入指纹、marker/line/zone/segment、证据和警告。Provider 注册表拒绝重复 ID，并把单层异常隔离成 `status=error`，不会把整张 K 线变成 500。

唯一指标中心固定提供“技术指标、结构指标、形态、策略、事件、模板、画线”七类。技术指标支持搜索、仅看已启用、schema 参数、颜色、副图高度与折叠；缠论和十一组关键价位全部位于结构指标详情，不再生成顶部控制行。关键价位仍兼容 `plan.key_levels` 和旧 `levels` 字段。后端只输出语义角色，前端统一映射图形和颜色。点击带证据 ID 的标记会打开证据抽屉。

标注密度支持“随缩放、聚合、详细”三种模式；默认随当前可见 K 线根数切换。远景隐藏普通标签并优先保留聚合/高优先级节点，近景再展开详细节点，底层事件不会因此删除。

## 策略闭环与派生事件

策略表格的“查看信号”携带 `strategyId/asOf/sourceRunId/paramsFingerprint/symbol/asset/returnTo`。个股页从 URL 恢复上下文、自动开启来源策略层并把信号日作为图表截止日；刷新或复制链接后仍可恢复，返回策略页保留日期、策略和筛选。

可执行的价格结构条件必须先注册到策略引擎。K 线“策略”页签将“即时策略标记”和“已记录的策略事件”分开：前者只允许策略登记 `chart_preview.enabled=true` 且声明 `mode=single_asset`，由 `POST /api/strategies/preview` 读取当前股票的前复权 enriched 日线和必要预热区间，因果回放入场/离场信号；它不执行全市场扫描、不写入 `strategy_signal_events`、不模拟成交，也不计算单股横向评分。后者读取策略面板执行、回测或实时监控已经写入 `strategy_signal_events` 的跨日证据。未声明预览能力的正式策略在当前周期必须显示不可用，不能以启发式形态或单股近似结果绕过注册契约。

跨日历史不再以 `strategy_cache.json` 为权威，而写入独立派生仓库：

```text
data/strategy_signal_events/date=YYYY-MM-DD/part.parquet
```

schema v2 的幂等键包含策略 ID/版本、参数指纹、股票、事件日、事件类型、运行批次和事件序号。写入使用同目录临时文件加原子替换；支持按股票、策略、日期、事件类型、批次和参数查询，兼容缺列的 v1 分区，并用 generation 标识变更。它不是 Market Facts，也不进入 Git。

`signal_kind` 明确区分：

- `strategy_signal`：策略条件成立；
- `backtest_fill`：回测撮合器的模拟成交；
- `realtime_trigger`：盘中监控边缘触发。

三者使用不同标记、标题和证据文案，均不会被描述成真实账户成交。策略运行、回测完成和监控边缘触发分别进入同一派生事件契约；前端在手动策略运行完成后精确失效 K 线查询，实时监控写入后沿现有 `strategy_results_updated` SSE 同时失效策略缓存与 `kline-chart` 查询。

## 状态和回放

layout v4 是唯一工作区状态：指标实例、参数、样式、位置、顺序、高度、折叠、标注密度、摘要显隐和模板写入版本化 localStorage；行情、计算缓存、策略事件和具体股票画线不进入模板。旧 activeIndicators、缠论、价位、图层和 customPresets 只读迁移，未知/重复/损坏项 fail-closed 并显示迁移警告。

系统模板固定为“基础、趋势、震荡、缠论分析、关键价位”，运行时以源码定义覆盖任何本地伪造同名系统模板。自定义模板支持保存、应用/恢复、复制、重命名、当前工作区覆盖和删除；应用原子替换完整指标集合、参数、样式与布局，并显示当前工作区是否偏离模板。画线按股票、周期和复权隔离。回放通过 `rowsAtReplay` 截断单一 candles 序列，并按确认/事件/成交/触发时间过滤图层。

## 验证

```powershell
cd D:\tickflow-quantall\backend
uv run --frozen pytest tests/test_chart_data.py tests/test_chart_layers.py tests/test_strategy_signal_events.py tests/test_chanlun_pipeline.py tests/test_chanlun_bridge.py tests/test_minute_range_api.py -q
uv run --frozen pytest tests/test_strategy_preview.py -q
uv run --frozen ruff check app/chart_layers app/services/strategy_preview.py app/services/strategy_evidence.py app/services/strategy_signal_events.py tests/test_chart_layers.py tests/test_strategy_preview.py tests/test_strategy_signal_events.py

cd D:\tickflow-quantall\frontend
pnpm test:indicators
pnpm test:chart-layers
pnpm test:chart-workspace
pnpm build

cd D:\tickflow-quantall
python scripts/verify_stock_chart.py
```

Playwright 脚本必须使用 headless Microsoft Edge，验证唯一 canvas/指标中心、单行工具栏、七类统一管理、缠论/价位不新增控制行、模板完整保存与刷新恢复、3 年请求、参数化预热、策略深链、无控制台/网络错误和移动端无页面横向溢出。

## 当前数据边界

接口支持长范围不等于每个标的本地都已拥有长历史。页面按实际覆盖和逐指标预热状态显示“完整/部分”，并提供单股补齐。2026-09-01 验收时，`600000.SH` 通过本仓库 Fuyao provider 路由写入 2022-07-28—2026-08-31 共 993 根原始日线；3 年请求实际返回 2023-08-31—2026-08-31 共 726 根可见 K 线及 267 根隐藏预热，`complete=true`、`warmup_complete=true`。这是验收样本，不代表其他标的已自动补齐。分钟历史仍取决于所选 provider 权限和上游限制。
