# TickFlow 独立 QuantX 数据流水线

本原型只负责 QuantX Review 背后的市场数据表格：采集、原始留存、标准化、确定性指标计算、跨日趋势、质量校验、结构化 API 和 React 展示。

它不读取 `apps/quantx/output`，不生成或消费 LLM 判断、Review Editor、HTML 文案、反思知识、PNG/PDF。

TickFlow 的 `/quantx/:date` 单日页面通过 `/api/quantx/review/:date/data` 将同一日期目录中的确定性 JSON 组装为七区数据，并原生渲染 ECharts；该适配器不读取 `review.html`，也不消费其中的 LLM 占位或编辑内容。`/quantx` 多日驾驶舱继续使用 `/api/quantx-data/catalog` 和 `/api/quantx-data/multiday/:date`。

## 运行

在独立仓库的 `backend` 下（脚本默认写入仓库根目录的 `data`；如需覆盖可传 `--data-dir`）：

```powershell
uv run python ../scripts/run_quantx_data.py --date 20260825
uv run python ../scripts/run_quantx_data.py --date 20260825 --recompute
uv run python ../scripts/run_quantx_data.py --date 20260825 --source pywencai --force
```

每个日期的结构化产物位于 `data/quantx/YYYYMMDD/`。`raw/` 保留采集器原始对象，`normalized/` 保存统一交易日/代码字段后的对象；`_pipeline_status.json` 是运行状态，`_data_manifest.json` 保存来源状态、请求次数、原始/规范化 SHA-256、产物哈希和降级警告。只有 `complete` 或 `degraded` 才会发布新快照。

流水线始终按完整来源契约验收。单源重试只强制刷新目标来源，其余来源复用同日期快照；`--recompute` 和对应 API 只读本地来源，不触网。必需来源缺失/过期会 `failed`，可选来源缺失会 `degraded`，失败时保留上一次已发布的表格文件。

## API

核心端点：

```text
POST /api/quantx-data/runs
GET  /api/quantx-data/runs/{date}
POST /api/quantx-data/runs/{date}/resume
POST /api/quantx-data/runs/{date}/recompute
POST /api/quantx-data/runs/{date}/sources/{source}/retry
GET  /api/quantx-data/catalog
POST /api/quantx-data/catalog/rebuild
GET  /api/quantx-data/multiday/{date}
GET  /api/quantx-data/{date}/tables
GET  /api/quantx-data/{date}/overview
GET  /api/quantx-data/{date}/limit-ladder
GET  /api/quantx-data/{date}/themes
GET  /api/quantx-data/{date}/sentiment
GET  /api/quantx-data/{date}/fund-flow
GET  /api/quantx-data/{date}/candidates
GET  /api/quantx-data/{date}/quality
```

`GET /catalog` 只扫描并返回紧凑日期目录，不写文件；`POST /catalog/rebuild?trade_date=YYYYMMDD`
显式重建并原子写入选定日期的 `multiday_snapshot.json`。维护场景可传
`all_dates=true` 全量重建。多日快照完全从本仓库
`data/quantx` 内的结构化表和来源快照派生，固定标记 `llm: false`，不读取原
QuantX 报告目录。

## 多日驾驶舱

React `/quantx` 面板通过 `GET /catalog` 加载日期列表，再按选定日期请求一个
`GET /multiday/{date}` 聚合快照。快照包含：

- 5/10/20 个交易日的热度、广度、接力和风险信号矩阵；
- 交易日历与窗口均值、极值和风险日统计；
- 多源题材生命周期、连续性热力图和涨停原因标签归因；
- 题材、行业、个股的确定性多日机会雷达；
- 基于申万行业资金流和可用趋势池的机构趋势连续性。

历史来源缺失会降低 `data_coverage` 和 `coverage_confidence`，不会用零值补造。
每日流水线成功发布后自动刷新当日多日快照和紧凑 catalog；历史全量重建只由
显式 POST 或界面“重建多日数据”触发。

新日期不存在有效必需来源时会 `failed`；可选来源缺失会 `degraded` 并保留警告。重复运行只重用同日期来源快照，`--force` 或单源 retry 才重新采集；`--recompute` 只计算、不访问网络。
