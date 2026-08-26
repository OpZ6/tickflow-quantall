# QuantX 统一数据底座与数据源管理实施规划

## 1. Goal

### 1.1 当前 Goal

> 在 `tickflow-quantall` 中将 QuantX 数据采集、数据源管理、标准化事实存储、Repository 调用、质量治理与调度发布统一到 TickFlow 数据底座，同时保持现有 QuantX 单日富图表和多日面板兼容。

- 状态：`active`
- 建立日期：2026-08-26
- 当前阶段：规划已固化，尚未开始统一底座的代码迁移
- 核心工作目录：`D:\tickflow-quantall`
- 基线日期：`20260825`

文档落盘不代表 Goal 完成。只有第 12 节的完成定义全部满足，并经过数据对账、API 兼容验证和页面回归验证后，Goal 才能标记为完成。

### 1.2 Goal 边界

本 Goal 包含：

- QuantX 市场数据、涨跌停、题材、资金流、交易日历等确定性数据采集；
- 数据源注册、能力声明、优先级、降级、限流、健康状态和依赖检查；
- 原始来源快照、标准事实 Parquet、确定性派生数据和 API 快照；
- 单日情绪、题材、涨停生态、候选池和多日窗口等处理逻辑；
- TickFlow 主盘后流水线、QuantX 采集和派生任务之间的依赖调度；
- QuantX 单日富图表、多日面板以及市场实验室对统一数据的调用；
- 历史数据迁移、双写、双读、对账和旧格式兼容。

本 Goal 不包含：

- LLM 分析、Review Editor、Research Daily、反思知识库；
- AI 文案、HTML 报告、PNG/PDF 报告生成；
- 未经单独审批删除历史 QuantX JSON、报告或归档；
- 为统一而强制把所有数据写入一张表或一个持久化 DuckDB 文件。

## 2. 当前问题

TickFlow 原生行情链路已经使用统一的 provider、Polars 标准化、日期分区 Parquet、DuckDB 内存视图和 `KlineRepository`。市场实验室直接读取该 Repository，因此已经基本建立在主数据底座上。

QuantX 当前虽然位于同一个 `data/` 根目录，但仍然是独立逻辑数据仓库：

```text
QuantX legacy collectors
  -> data/quantx/YYYYMMDD/*.json
  -> source-specific normalization
  -> _computed.json + structured JSON tables
  -> multiday_snapshot.json + catalog.json
  -> QuantX API and React panels
```

主要割裂包括：

1. QuantX 采集器未使用 TickFlow 的 provider/dataset 契约；
2. 指数、市场宽度、成交额等数据存在重复采集和双重口径；
3. 主系统使用 Parquet/Repository，QuantX 使用按日期 JSON 扫描；
4. 必需性绑定到具体来源，而不是绑定到业务数据集；
5. 主系统和 QuantX 分别维护质量状态、缓存版本和发布事务；
6. QuantX 日期目录混有来源数据、派生表、兼容文件和历史报告资产；
7. 更换数据源时可能同时修改采集器、计算器、API 和前端。

## 3. 架构原则

1. **来源可以多套，标准事实只能一套。**
2. **必需的是数据集，不是某个供应商。** Tushare 或问财不可用时，只要其他来源满足同一数据契约，就可以降级发布。
3. **原始证据与业务事实分离。** 原始响应用于审计和离线重算，业务统一读取标准事实。
4. **JSON 是兼容快照，不是长期唯一事实源。** 历史、查询和复用以 Parquet + Repository 为主。
5. **统一访问契约，不追求单一物理表。** OHLCV、涨停事件、题材关系和资金流按领域分别存储。
6. **缺失不补零，代理必须标注。** `observed`、`fallback`、`proxy` 和 `missing` 必须可区分。
7. **发布失败不得覆盖上一版成功数据。** 所有读者只能看到完整发布代。
8. **消费者与来源解耦。** QuantX、市场实验室、市场总览、策略和回测只依赖 Repository。

## 4. 目标数据链路

```text
Source Registry / Dataset Registry
  -> Collection Planner
  -> Provider or Collector Adapter
  -> compressed raw snapshot + SHA-256
  -> dataset normalization
  -> schema and semantic validation
  -> multi-source reconciliation
  -> canonical fact Parquet
  -> MarketFactRepository
  -> deterministic daily derivation
  -> deterministic multiday derivation
  -> API-compatible JSON snapshot
  -> FastAPI
  -> QuantX and Market Lab React panels
```

TickFlow 现有行情 provider 继续负责 OHLCV、复权、分钟、实时和财务数据。题材、涨跌停、市场宽度等非 OHLCV 数据新增通用 `DatasetProvider` 契约，避免无限扩张现有 `MarketDataProvider` 接口。

## 5. Dataset Registry

### 5.1 数据集定义

每个数据集必须注册以下属性：

```text
dataset_id
schema_version
description
primary_key
partition_keys
required_columns
field_units
freshness_policy
quality_rules
retention_policy
```

### 5.2 保留的核心数据集

现有目录保持不动，避免破坏上游兼容：

- `instruments`
- `kline_daily`
- `kline_daily_enriched`
- `kline_index_daily`
- `kline_index_enriched`
- `kline_etf_daily`
- `kline_etf_enriched`
- `kline_minute`
- `kline_etf_minute`
- `adj_factor`
- `adj_factor_etf`
- `financials`
- `ext_data`

### 5.3 新增标准事实数据集

| Dataset ID | 粒度 | 建议主键 | 主要消费者 |
| --- | --- | --- | --- |
| `trading_calendar` | 交易所/交易日 | `exchange, trade_date` | 调度、窗口计算 |
| `market_breadth_daily` | 市场/交易日 | `market, trade_date` | QuantX、市场总览 |
| `market_liquidity_daily` | 市场/交易日 | `market, trade_date` | QuantX、实验室 |
| `margin_daily` | 范围/交易日 | `scope, trade_date` | QuantX 单日图表 |
| `limit_event_daily` | 股票/交易日/事件 | `symbol, trade_date, event_type` | 连板、情绪、策略 |
| `limit_ladder_daily` | 交易日/板数/股票 | `trade_date, board_height, symbol` | QuantX、连板面板 |
| `theme_observation_daily` | 来源/题材/交易日 | `source, theme_id, trade_date` | 题材归因、生命周期 |
| `theme_stock_daily` | 题材/股票/交易日 | `theme_id, symbol, trade_date` | 龙头、机会雷达 |
| `sector_flow_daily` | 行业/来源/交易日 | `sector_id, source, trade_date` | 实验室、机构连续性 |
| `hot_rank_daily` | 来源/股票/交易日 | `source, symbol, trade_date` | 热度、候选池 |

### 5.4 公共字段与单位

标准事实至少包含：

```text
trade_date
source
source_record_id
observed_at
ingested_at
run_id
schema_version
quality_level
is_fallback
```

身份字段统一为：

- `symbol`：六位证券代码；
- `exchange`：`SSE`、`SZSE`、`BSE`；
- `asset_type`：`stock`、`index`、`etf`；
- `source_code`：保留供应商原始代码。

数值单位统一为：

- `*_pct`：百分数，`3.66` 表示 `3.66%`；
- `*_ratio`：小数比例，`0.0366` 表示 `3.66%`；
- 金额字段显式使用 `_yuan`、`_wan` 或 `_yi` 后缀；
- 禁止新增无法由字段名判断单位的 `amount`、`change_pct`。

## 6. Source Registry 与路由

### 6.1 来源声明

每个来源声明：

```text
source_id
display_name
supported_datasets
collector_type: provider | python | http | browser | file
credentials_ref
dependency_check
health_check
rate_limit
timeout
retry_policy
priority
```

配置只保存环境变量名或 secret 引用，不保存真实 Token。

### 6.2 数据集路由示例

```text
market_breadth_daily
  1. tickflow_enriched_aggregate
  2. tushare
  3. pywencai

limit_event_daily
  1. pywencai
  2. zhangtingke
  3. zhangtingjun
  4. duanxianxia

sector_flow_daily
  1. sector_fund_flow_s4
  2. akshare
  3. enriched_ohlcv_proxy
```

`enriched_ohlcv_proxy` 必须输出 `quality_level=proxy`，不能伪装成真实主力净流入。

### 6.3 来源管理能力

统一管理层需要支持：

- 能力发现与依赖检查；
- 当前健康状态和最近成功日期；
- 数据集级主来源、备用来源和禁用来源；
- 每来源限流、超时、重试和熔断；
- 同一来源内串行、不同来源间受控并行；
- 单来源重试、单数据集回补和整日重算；
- 原始响应哈希去重；
- 错误分类：认证、依赖、限流、网络、解析、schema、空数据、过期。

## 7. 存储布局

### 7.1 原始来源快照

```text
data/source_snapshots/
  {source_id}/
    {dataset_id}/
      trade_date=YYYY-MM-DD/
        {run_id}.json.gz
        {run_id}.meta.json
```

原始快照规则：

- 不可变；
- gzip 或 zstd 压缩；
- 保存内容 SHA-256；
- 相同哈希不重复保存正文；
- 支持离线 replay；
- 大型原始正文保留周期可配置，manifest 长期保留；
- 任何历史清理必须使用独立脚本、预检、备份和用户确认。

### 7.2 标准事实 Parquet

```text
data/market_breadth_daily/date=YYYY-MM-DD/part.parquet
data/market_liquidity_daily/date=YYYY-MM-DD/part.parquet
data/limit_event_daily/date=YYYY-MM-DD/part.parquet
data/limit_ladder_daily/date=YYYY-MM-DD/part.parquet
data/theme_observation_daily/date=YYYY-MM-DD/part.parquet
data/theme_stock_daily/date=YYYY-MM-DD/part.parquet
data/sector_flow_daily/date=YYYY-MM-DD/part.parquet
```

采用当前项目已有规则：

- 日期分区；
- 显式 schema；
- 主键去重；
- 临时文件写入后原子替换；
- `union_by_name` 兼容加列升级；
- 发布后重建 DuckDB 视图并刷新 Repository 缓存。

### 7.3 确定性派生数据

建议将可复用结果从 QuantX 私有目录提升为领域数据：

```text
data/market_state/date=YYYY-MM-DD/part.parquet
data/theme_state/date=YYYY-MM-DD/part.parquet
data/screening_candidates/date=YYYY-MM-DD/part.parquet
data/opportunity_radar/date=YYYY-MM-DD/part.parquet
```

其中：

- `market_state` 保存市场热度、短线情绪、趋势情绪和风险状态；
- `theme_state` 保存题材生命周期、连续性和共识强度；
- `screening_candidates` 保存确定性规则候选及命中依据；
- `opportunity_radar` 保存多日确定性派生结果。

每个派生分区必须记录算法版本和输入 generation。

### 7.4 QuantX API 兼容快照

```text
data/quantx_views/YYYYMMDD/
  review_data.json
  multiday_snapshot.json
  quality.json
```

这些 JSON 由统一 Repository 生成，只作为：

- API 响应缓存；
- 前端兼容；
- 快速诊断和导出。

来源级 JSON 不再作为 QuantX API 的直接输入。

## 8. 统一采集与发布 DAG

```text
1. plan
   -> 确认交易日、数据集、主来源和备用来源

2. collect
   -> 按来源限流采集

3. raw_checkpoint
   -> 压缩、哈希、原始证据留存

4. normalize
   -> 转换为 Dataset Contract

5. validate
   -> schema、主键、日期、单位、覆盖率、异常值

6. reconcile
   -> 多源比较、冲突记录、主来源/备用来源选择

7. publish_facts
   -> 原子写标准事实 Parquet

8. derive_daily
   -> 情绪、涨停生态、题材、资金流和候选集

9. derive_multiday
   -> 5/10/20 日窗口、生命周期、连续性、机会雷达

10. publish_generation
    -> 最后发布 manifest/generation，形成可读屏障

11. refresh
    -> DuckDB 视图、Polars 缓存、SSE 和前端查询失效
```

发布规则：

- 同一交易日只允许一个活跃发布任务；
- 必需数据集缺失时为 `failed`，不覆盖旧版本；
- 备用来源满足契约时为 `degraded`，允许发布；
- 缺失值使用 null，不允许用零伪造；
- manifest 最后写入，只有 manifest 成功才视为新 generation 可用；
- API、worker 和页面都通过 Repository 读取已发布 generation。

## 9. Repository 与 API

### 9.1 MarketFactRepository

新增统一查询接口：

```python
get_trading_calendar(start, end)
get_market_breadth(trade_date)
get_market_liquidity(trade_date)
get_margin_history(start, end)
get_limit_events(trade_date)
get_limit_ladder(trade_date)
get_theme_observations(start, end)
get_theme_memberships(start, end)
get_sector_flows(start, end)
get_market_states(start, end)
```

消费者关系：

```text
MarketLab ---------+
QuantX Daily ------+
QuantX Multiday ---+--> MarketFactRepository
Market Overview ---+
Strategy/Backtest -+
```

### 9.2 API 兼容

保留当前前端契约：

- `GET /api/quantx/review/{date}/data`
- `GET /api/quantx-data/catalog`
- `GET /api/quantx-data/multiday/{date}`
- `GET /api/quantx-data/{date}/tables`

后端实现切换为 Repository，不要求重新开发现有单日富图表和多日页面。

新增统一管理 API：

```text
GET  /api/data-sources/datasets
GET  /api/data-sources/sources
GET  /api/data-sources/routes
GET  /api/data-sources/health
GET  /api/data-runs/{run_id}
POST /api/data-runs
POST /api/data-runs/{run_id}/retry
POST /api/data-runs/backfill
```

管理 API 只负责编排和状态映射，重计算和磁盘扫描放在 service/job 层。

## 10. 调度方案

将 QuantX 固定 16:00 任务改成依赖式调度：

```text
15:30 TickFlow 主盘后流水线
  -> 核心 Parquet 发布
  -> market_data_ready
  -> 领域数据采集
  -> 标准事实发布
  -> QuantX 单日派生
  -> QuantX 多日派生
  -> API 快照和页面缓存刷新
```

要求：

- 主行情未完成时 QuantX 不提前计算；
- 数据源未就绪时指数退避重试；
- 设置盘后最终截止时间；
- 截止时失败则保留上一版并暴露明确错误；
- 节假日以 `trading_calendar` 为准，不只判断星期；
- 支持指定日期 backfill；
- 支持 dataset/source 粒度的重试；
- `recompute` 只读本地快照，禁止访问网络。

## 11. 实施阶段

### Phase 0：冻结基线

- 以 `20260825` 固化单日七区、图表数量和多日数据；
- 保存当前 API 响应和关键字段；
- 记录全部来源、字段、单位和缺失行为；
- 增加黄金数据回归测试；
- 不删除或移动现有 `data/quantx`。

### Phase 1：Dataset Registry 与 Repository 骨架

首批实现：

1. `market_breadth_daily`
2. `limit_event_daily`
3. `theme_observation_daily`
4. `sector_flow_daily`

建立 schema、质量规则、Parquet 写入、DuckDB 视图和 `MarketFactRepository`。

### Phase 2：统一 Source Manager

- 将现有 QuantX collectors 包装为 Dataset Provider；
- 先不改爬虫内部解析逻辑；
- 增加统一依赖检查、超时、重试、限流、健康状态和错误分类；
- 写入共享 `source_snapshots`；
- 安装依赖改为明确的可验证环境或可选依赖组。

### Phase 3：双写与逐日对账

采集后同时写：

- 旧 `data/quantx/YYYYMMDD/*.json`；
- 新标准事实 Parquet。

对账内容：

- 记录数和股票集合；
- 指数、成交额、上涨下跌家数；
- 涨停、跌停、炸板和连板高度；
- 题材名称、排名和成员；
- 行业资金流方向和单位；
- 情绪三件套及风险布尔信号。

### Phase 4：QuantX 双读

- 计算器优先读取 `MarketFactRepository`；
- 新事实缺失时临时回退旧 JSON；
- 所有回退记录到 manifest；
- 黄金日期和连续历史窗口对账完成后关闭回退。

### Phase 5：API 切换

- 单日富图表改读统一 Repository 组装结果；
- 多日窗口直接查询标准事实和派生 Parquet；
- 保持前端类型、路由和视觉结果不变；
- Market Lab 优先读取真实 `sector_flow_daily`，没有真实值时才使用代理。

### Phase 6：历史迁移与旧链路冻结

- 将现有 QuantX 日期目录批量转换为标准事实；
- 每个日期生成迁移 manifest 和对账结果；
- 旧 JSON 改为只读归档；
- 停止重复采集主底座已提供的数据；
- 旧数据清理另开任务，不包含在迁移脚本默认行为中。

## 12. Definition of Done

只有全部满足，Goal 才能完成：

- [ ] QuantX API 不再直接读取来源级 JSON；
- [ ] 主系统与 QuantX 对同一指数、成交额和市场宽度只有一个事实值；
- [ ] 更换来源不需要修改 QuantX 计算器和前端；
- [ ] 必需性落在 dataset，而不是 Tushare、问财等具体来源；
- [ ] 单源失败可以按确定性规则走备用来源并显示降级；
- [ ] 同一来源和日期重复运行不产生重复事实记录；
- [ ] 离线 recompute 不发起网络请求；
- [ ] 失败运行不覆盖上一版成功数据；
- [ ] 每个结果可追溯到来源、原始哈希、run ID、schema 和算法版本；
- [ ] 历史 QuantX 日期完成迁移和逐日对账；
- [ ] `20260825` 单日七区、富图表和多日面板结果保持兼容；
- [ ] Market Lab 与 QuantX 共用 `MarketFactRepository`；
- [ ] 数据源设置页可以查看路由、健康、依赖、覆盖率和最近运行；
- [ ] 原始快照具备压缩、去重和可配置保留策略；
- [ ] 后端单元、集成、幂等、回滚、降级、历史回放测试通过；
- [ ] 前端 TypeScript 构建及 standalone Playwright 页面回归通过；
- [ ] 当前数据目录完成备份和迁移演练，没有不可恢复删除。

## 13. 测试与验证矩阵

### 13.1 数据源适配器

- 固定 fixture 的字段映射测试；
- 认证缺失、依赖缺失、超时、限流和响应变化测试；
- 空数据、错误交易日和过期数据隔离测试；
- 不同来源单位转换测试。

### 13.2 存储与发布

- 主键幂等和重复运行测试；
- schema 加列兼容测试；
- 原子写入中断和旧版本保留测试；
- manifest、哈希和 generation 一致性测试；
- 同日期并发写锁测试。

### 13.3 计算与对账

- 当前 JSON 与新 Repository 同日对账；
- 5/10/20 个实际交易日窗口测试；
- 缺失数据不补零测试；
- fallback/proxy 质量标签传播测试；
- 多源冲突和来源优先级测试。

### 13.4 页面兼容

- QuantX 单日七个区块完整；
- 富图表 canvas 数量和关键标题不回退；
- 多日矩阵、交易日历、生命周期、机会雷达和机构连续性存在；
- API 无 500、浏览器控制台无错误；
- 使用 standalone Python Playwright + Microsoft Edge headless 验证。

## 14. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 多源字段和单位漂移 | Dataset schema、fixture、范围校验、来源版本 |
| 浏览器采集器不稳定 | 依赖检查、隔离进程、限并发、超时、备用来源 |
| 双写期间口径不一致 | 日级对账报告，不一致不切读 |
| 新旧发布同时写同一日期 | 日期锁、staging、manifest 发布屏障 |
| 历史 JSON 混有报告资产 | 只读识别和分类，不在迁移中删除 |
| Parquet 小文件膨胀 | 单日单文件、定期可审计 compaction |
| API 快照与 Repository 不一致 | 快照记录输入 generation，发布后统一失效 |
| 迁移破坏单日富图表 | 固化 `20260825` standalone Playwright 回归 |

## 15. 推荐首个实施闭环

第一批只完成 `market_breadth_daily + limit_event_daily`：

1. 定义两个 Dataset Contract；
2. 建立 Source Registry 和数据集路由；
3. 包装 TickFlow 聚合、Tushare、问财和涨停客来源；
4. 保存压缩 raw snapshot；
5. 写标准事实 Parquet；
6. 建立 `MarketFactRepository`；
7. 与旧 QuantX JSON 双写、双读；
8. 对账 `20260825`；
9. 保持单日富图表无变化；
10. 验证失败回滚、离线 recompute 和备用来源降级。

该闭环通过后，再迁移题材和行业资金流。这样可以先验证统一架构的完整生命周期，而不一次性改动所有 QuantX 来源。

## 16. 相关文档

- [`quantx-data-pipeline.md`](quantx-data-pipeline.md)：当前独立 QuantX 数据流水线；
- [`architecture-and-extension.md`](architecture-and-extension.md)：TickFlow 当前架构与扩展边界；
- [`tickflow-unification-master-plan.md`](tickflow-unification-master-plan.md)：更大范围的 Quantall/TickFlow 能力迁移规划；
- [`custom-data-source.md`](custom-data-source.md)：现有自定义 HTTP 数据源契约；
- [`plugin-development.md`](plugin-development.md)：数据源插件开发约定。
