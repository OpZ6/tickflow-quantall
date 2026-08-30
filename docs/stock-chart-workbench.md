# 统一个股 K 线工作台

个股分析页只创建一个 ECharts 实例。主图、副图、关键价位、缠论结构、形态和用户画线共用同一组 candles、时间轴、缩放和十字光标；旧图表组件暂时保留作为兼容入口。

## 数据契约

`GET /api/kline/chart` 参数：

- `symbol`，可选显式 `asset_type=stock|etf|index`；显式类型与本地维表冲突时返回 422。
- `interval=1m|5m|15m|30m|60m|1d|1w|1mo`。
- `adjustment=none|qfq|hfq`；指数强制 `none`。
- `range=1m|3m|6m|1y|3y|5y|all|custom`；自定义范围使用 `start_date/end_date`。

处理顺序固定为：原始 Repository 数据 → 复权 → 周期聚合 → 隐藏区间预热 → 指标与 11 组关键价位 → 裁剪 → API。响应 `meta` 提供请求/实际周期与复权、来源、覆盖起止、`complete`、`warmup_bars`、`warmup_complete` 和告警。关键价位位于同一响应的 `levels`，不得再用另一份日线生成。

分钟线只使用本地分钟仓库已有历史。覆盖不足时页面显示真实起止，并可调用 `POST /api/kline/sync_minute_single` 补齐单股历史；provider 拒绝长区间时错误原样可见。当前本地指数分钟线不受支持，不会冒充股票分钟线。

## 指标与结构层

- `frontend/src/features/stock-chart/indicatorRegistry.ts` 是 20 个主图、38 个副图及成交量的类型化目录。新增技术指标必须同时提供公式、参数定义、预热长度、分组和固定样本测试。
- `frontend/src/lib/indicator-formulas.ts` 保存纯公式；参数通过集中存储管理。公式异常会在工作台显示并写入控制台，不得静默消失。
- 缠论默认调用本地 `POST /api/chanlun/analyze`，显示算法版本、数据指纹和末笔确认状态。包含处理、分型、笔、段、中枢和买卖点均为同一 ECharts 的可选图层。
- ZenChart 仅是可选对照。任何官方端点无法映射到本地 candles 时整层拒绝叠加，不替换本地 K 线。
- 五类形态是本地启发式研究标记，不代表官方缠论结论。

## 状态和回放

布局、指标参数、自定义预设和画线写入版本化 localStorage；行情数据不写入。画线按股票、周期和复权隔离，支持单删、撤销、重做和全部清除。回放通过 `rowsAtReplay` 只把当前时点之前的 candles 传给指标、价位、形态和缠论计算。

## 验证

```powershell
cd D:\tickflow-quantall\backend
uv run --frozen pytest tests/test_chart_data.py tests/test_chanlun_pipeline.py tests/test_chanlun_bridge.py tests/test_minute_range_api.py -q

cd D:\tickflow-quantall\frontend
pnpm test:indicators
pnpm build

cd D:\tickflow-quantall
python scripts/verify_stock_chart.py
```

Playwright 脚本必须使用 headless Microsoft Edge，验证唯一 canvas、切换指标不重新请求行情、周期切换会请求行情、回放不请求行情、布局刷新恢复、无控制台/网络错误和无横向溢出。

## 当前数据边界

接口支持长范围不等于本地已拥有长历史。以 2026-08-31 的开发数据为例，`600000.SH` 原始日线从 2025-08-25 开始，一年窗口起点之前不足 160 根预热数据；响应会明确 `warmup_complete=false`，开头部分长周期指标为空。分钟线可达到的历史长度继续取决于所选 provider 权限和上游限制。
