# 统一个股 K 线工作台

个股分析页只创建一个 ECharts 实例。主图、副图、关键价位、缠论结构、形态和用户画线共用同一组 candles、时间轴、缩放和十字光标；旧图表组件暂时保留作为兼容入口。

## 数据契约

`GET /api/kline/chart` 参数：

- `symbol`，可选显式 `asset_type=stock|etf|index`；显式类型与本地维表冲突时返回 422。
- `interval=1m|5m|15m|30m|60m|1d|1w|1mo`。
- `adjustment=none|qfq|hfq`；指数强制 `none`。
- `range=1m|3m|6m|1y|3y|5y|all|custom`；自定义范围使用 `start_date/end_date`。
- `layers=pattern,strategy,event,plan`；不传时保持旧响应兼容，传入后返回 `annotation_layers`。
- `strategy_ids`、`source_run_id`、`params_fingerprint` 用于恢复策略页来源及精确运行批次。

处理顺序固定为：原始 Repository 数据 → 复权 → 周期聚合 → 隐藏区间预热 → 指标与 11 组关键价位 → 裁剪 → API。响应 `meta` 提供请求/实际周期与复权、来源、覆盖起止、`complete`、`warmup_bars`、`warmup_complete` 和告警。关键价位位于同一响应的 `levels`，不得再用另一份日线生成。

分钟线只使用本地分钟仓库已有历史。覆盖不足时页面显示真实起止，并可调用 `POST /api/kline/sync_minute_single` 补齐单股历史；provider 拒绝长区间时错误原样可见。当前本地指数分钟线不受支持，不会冒充股票分钟线。

## 指标与结构层

- `frontend/src/features/stock-chart/indicatorRegistry.ts` 是 20 个主图、38 个副图及成交量的类型化目录。新增技术指标必须同时提供公式、参数定义、预热长度、分组和固定样本测试。
- `frontend/src/lib/indicator-formulas.ts` 保存纯公式；参数通过集中存储管理。公式异常会在工作台显示并写入控制台，不得静默消失。
- 缠论默认调用本地 `POST /api/chanlun/analyze`，显示算法版本、数据指纹和末笔确认状态。包含处理、分型、笔、段、中枢和买卖点均为同一 ECharts 的可选图层。
- ZenChart 仅是可选对照。任何官方端点无法映射到本地 candles 时整层拒绝叠加，不替换本地 K 线。
- 五类经典形态以及 VCP、杯柄、高而紧旗形、启动后缩量回踩均由后端消费最终图表 candles 计算；VCP 的形态确认、突破、守轴、失败和再触发各自使用实际发生日作为确认时间，回放不会提前看到后续阶段。它们是本地启发式研究标记，不代表官方缠论结论，也不依赖 `D:\quantall\apps\quants`。

`ChartAnnotationLayer` 是版本化、与 ECharts 无关的领域契约。每层都有稳定 ID、类别、状态、复权口径、算法版本、输入指纹、marker/line/zone/segment、证据和警告。Provider 注册表拒绝重复 ID，并把单层异常隔离成 `status=error`，不会把整张 K 线变成 500。

图层管理器固定提供“技术指标、缠论、形态、策略、事件、画线”六类。关键价位同时进入 `plan.key_levels` 统一图层，旧 `levels` 字段仍保留兼容。后端只输出语义角色，前端统一映射图形和颜色。点击带证据 ID 的标记会打开证据抽屉，显示命中条件、实际值、阈值、版本、参数指纹、运行批次、来源和关联形态。

标注密度支持“随缩放、聚合、详细”三种模式；默认随当前可见 K 线根数切换。远景隐藏普通标签并优先保留聚合/高优先级节点，近景再展开详细节点，底层事件不会因此删除。

## 策略闭环与派生事件

策略表格的“查看信号”携带 `strategyId/asOf/sourceRunId/paramsFingerprint/symbol/asset/returnTo`。个股页从 URL 恢复上下文、自动开启来源策略层并把信号日作为图表截止日；刷新或复制链接后仍可恢复，返回策略页保留日期、策略和筛选。

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

布局、指标参数、自定义预设、图层开关和画线写入版本化 localStorage；行情数据不写入。画线按股票、周期和复权隔离，支持单删、撤销、重做和全部清除。回放通过 `rowsAtReplay` 截断单一 candles 序列，并按 `confirmedAt/eventDate/fillDate/triggeredAt` 过滤图层，不重新请求另一份行情。

## 验证

```powershell
cd D:\tickflow-quantall\backend
uv run --frozen pytest tests/test_chart_data.py tests/test_chart_layers.py tests/test_strategy_signal_events.py tests/test_chanlun_pipeline.py tests/test_chanlun_bridge.py tests/test_minute_range_api.py -q
uv run --frozen ruff check app/chart_layers app/services/strategy_evidence.py app/services/strategy_signal_events.py tests/test_chart_layers.py tests/test_strategy_signal_events.py

cd D:\tickflow-quantall\frontend
pnpm test:indicators
pnpm test:chart-layers
pnpm build

cd D:\tickflow-quantall
python scripts/verify_stock_chart.py
```

Playwright 脚本必须使用 headless Microsoft Edge，验证唯一 canvas、六类图层管理、切换指标不重新请求行情、周期切换会请求行情、回放不请求行情、真实策略页深链、批次参数与刷新恢复、无控制台/网络错误和无横向溢出。

## 当前数据边界

接口支持长范围不等于本地已拥有长历史。以 2026-08-31 的开发数据为例，`600000.SH` 原始日线从 2025-08-25 开始，一年窗口起点之前不足 160 根预热数据；响应会明确 `warmup_complete=false`，开头部分长周期指标为空。分钟线可达到的历史长度继续取决于所选 provider 权限和上游限制。
