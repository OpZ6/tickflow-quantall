# TickFlow 独立 QuantX 数据流水线

> 文档角色：运维运行手册。数据契约和新增来源规则以 [`data-foundation.md`](data-foundation.md) 为准。

本原型只负责 QuantX Review 背后的市场数据表格：采集、原始留存、标准化、确定性指标计算、跨日趋势、质量校验、结构化 API 和 React 展示。

它不读取 `apps/quantx/output`，不生成或消费 LLM 判断、Review Editor、HTML 文案、反思知识、PNG/PDF。

TickFlow 的 `/quantx/:date` 单日页面默认通过 `/api/quantx/review/:date/data` 读取 `quantx-review.v2`，从类型化空结构、Market Facts、KlineRepository 和确定性 ViewBuilder 原生组装七区并渲染 ECharts；运行时不读取 `review_data.json`、`review.html` 或来源 JSON。`review_data.json` 仅保留为历史迁移证据，短期排障必须显式使用 `?view_version=v1`。`/quantx` 多日驾驶舱继续使用 `/api/quantx-data/catalog` 和 `/api/quantx-data/multiday/:date`。

V2 契约可通过 `GET /api/quantx/review/schema/v2` 查看；提交前运行 `python scripts/audit_quantx_review_consumers.py`，确保所有前端读取字段都具有唯一来源分类。

## 运行

在独立仓库的 `backend` 下（脚本默认写入仓库根目录的 `data`；如需覆盖可传 `--data-dir`）：

```powershell
uv run python ../scripts/run_quantx_data.py --date 20260825
uv run python ../scripts/run_quantx_data.py --date 20260825 --recompute
uv run python ../scripts/run_quantx_data.py --date 20260825 --source pywencai --force
```

每个日期的结构化产物位于 `data/quantx/YYYYMMDD/`。`raw/` 保留采集器原始对象，`normalized/` 保存统一交易日/代码字段后的对象；`_pipeline_status.json` 是运行状态，`_data_manifest.json` 保存来源状态、请求次数、原始/规范化 SHA-256、产物哈希和降级警告。只有 `complete` 或 `degraded` 才会发布新快照。

流水线始终按完整来源契约验收。单源重试只强制刷新目标来源，其余来源复用同日期快照；`--recompute` 和对应 API 只读本地来源，不触网。必需来源缺失/过期会 `failed`，可选来源缺失会 `degraded`，失败时保留上一次已发布的表格文件。

### 运行时依赖与凭据

QuantX 的 Tushare、AKShare、PyWencai 和 Playwright 适配器是后端默认运行时依赖，`uv sync --frozen` 会在本仓库 `backend/.venv` 内安装。Windows 的 Playwright 适配器使用已安装的 Microsoft Edge channel，不依赖仓库外的 QuantX 服务或单独报告目录。

Tushare 凭据只从 `TUSHARE_TOKEN` 环境变量读取，不得写入仓库配置。QuickTiny 是需要用户登录态的可选证据源；未配置 `QUICKTINY_LOGIN_STATE` 时必须显式报告 `needs_login_state`/`degraded`，不得伪装成成功。

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

### QuantX 候选漏斗

`GET /api/quantx/review/{date}/data?view_version=v2` 的 `sections.s5` 是报告末尾关注名单的唯一读模型。候选漏斗不改写 `screening_candidate_daily` 事实，而是按所选交易日做 point-in-time 派生：合并近 45 个自然日内的规则候选与百日新高事实，再使用截至所选日的 TickFlow 日 K、涨停事件和连板梯队识别强势前排、分歧承接、健康回调、低位启动四类形态。

漏斗先根据市场热度、短线情绪、趋势情绪、上涨家数占比、退潮信号和崩溃信号确定强势进攻、强势分歧、震荡轮动或弱势防守状态，再动态调整逻辑、强度、形态和可执行性权重。最终关注池必须满足：最多 10 只、同一题材最多 2 只、相同输入稳定排序；一字板不进入可执行池，20cm/30cm 封板只进入 `market_anchors` 并标记等待分歧。`candidate_funnel.audit_rows` 保留每只股票经过的层级和淘汰原因，供页面逐层审查；这些结果是次日观察条件，不是自动买卖信号。

`POST /api/pipeline/run` 会先完成 TickFlow 主行情、enriched 和指数更新，然后在同一任务结果中运行并返回 `quantx` 发布结果。主数据更新成功但 QuantX 发布失败时，手动数据任务不得伪报为完整成功。

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
- 合并后的题材、行业、个股多日机会与连续性卡片：5 日视图强调近期
  加权机会强度，20 日视图强调活跃持续性与行业累计净流入；两者都来自
  申万行业资金流、规则候选池和题材事实，不代表机构席位或机构身份。

历史来源缺失会降低 `data_coverage` 和 `coverage_confidence`，不会用零值补造。
每日流水线成功发布后自动刷新当日多日快照和紧凑 catalog；历史全量重建只由
显式 POST 或界面“重建多日数据”触发。

新日期不存在有效必需来源时会 `failed`；可选来源缺失会 `degraded` 并保留警告。重复运行只重用同日期来源快照，`--force` 或单源 retry 才重新采集；`--recompute` 只计算、不访问网络。
