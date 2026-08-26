# TickFlow 独立 QuantX 数据流水线

本原型只负责 QuantX Review 背后的市场数据表格：采集、原始留存、标准化、确定性指标计算、跨日趋势、质量校验、结构化 API 和 React 展示。

它不读取 `apps/quantx/output`，不生成或消费 LLM 判断、Review Editor、HTML 文案、反思知识、PNG/PDF。

## 运行

在 `prototypes/tickflow/backend` 下（脚本默认写入 `prototypes/tickflow/data`；如需覆盖可传 `--data-dir`）：

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
GET  /api/quantx-data/{date}/tables
GET  /api/quantx-data/{date}/overview
GET  /api/quantx-data/{date}/limit-ladder
GET  /api/quantx-data/{date}/themes
GET  /api/quantx-data/{date}/sentiment
GET  /api/quantx-data/{date}/fund-flow
GET  /api/quantx-data/{date}/candidates
GET  /api/quantx-data/{date}/quality
```

新日期不存在有效必需来源时会 `failed`；可选来源缺失会 `degraded` 并保留警告。重复运行只重用同日期来源快照，`--force` 或单源 retry 才重新采集；`--recompute` 只计算、不访问网络。
