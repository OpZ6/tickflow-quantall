# TickFlow 当前架构

状态：权威当前文档。本文只描述当前仓库中真实存在的调用链；未来设想必须写入独立计划或 ADR。

## 1. 分层与依赖方向

```text
外部来源
  ├─ 行情 Provider: TickFlow / YAML HTTP / Python-Node plugin
  └─ 事实 Source Adapter: Tushare / PyWencai / 网页与浏览器适配器
          ↓
采集、标准化、原始证据
          ↓
  ├─ DataStore / KlineRepository
  └─ MarketFactRepository / source_snapshots
          ↓
indicators / services / strategy / quantx_data repositories
          ↓
FastAPI API / SSE
          ↓
frontend api.ts / queryKeys / TanStack Query
          ↓
pages / components / ECharts
```

依赖只能向下。API 和页面不得直接读取供应商响应、scraper 文件或任意 Parquet；它们通过 Repository 或 Service 获取稳定结构。

## 2. 数据入口不是一个万能接口

项目有两种互补的采集契约：

### 2.1 行情 Provider

位置：`backend/app/data_providers/` 和 `backend/app/plugins/`。

适用于：

- `daily`
- `adj_factor`
- `realtime`
- `minute`
- `financial`
- instruments（部分 Provider）

Provider 负责供应商字段、代码、日期和单位映射。业务层通过 preferences、`get_provider()` 和 `provider_has_dataset()` 选择来源。

### 2.2 市场事实 Source Manager

位置：`backend/app/quantx_data/source_manager.py`、`collectors.py` 和 `backend/app/market_facts/`。

适用于涨停事件、连板梯队、题材观察、行业资金流、行业宽度、市场状态等不能表达为通用 OHLCV 的数据。

所有 QuantX 来源必须先注册 `SourceSpec` 和 collector adapter，再由 `SourceManager.collect()` 执行。Source Manager 统一负责：

- 来源发现和唯一 ID；
- 依赖检查；
- 重试与失败隔离；
- 认证、依赖、限流、超时、网络、解析等错误分类；
- 已发布快照复用和交易日新鲜度检查；
- 来源元数据 API。

`legacy_scrapers` 只是供应商适配器目录，不是业务接口。新代码不得在 Source Manager 以外直接调用它们。

## 3. 存储层

### 3.1 K 线与维表

`backend/app/tickflow/` 提供 DataStore、KlineRepository 和 DuckDB/Parquet 访问。日 K 原始表、复权因子、enriched、分钟 K、指数 K 线和 instruments 按各自契约存储。

### 3.2 标准市场事实

`backend/app/market_facts/` 管理可复用的非 K 线事实：

- `registry.py`：DatasetSpec、字段类型、单位、主键、分区和来源路由；
- `builders.py`：来源 payload 到标准事实的确定性转换；
- `storage.py`：暂存、原子发布、回滚和 manifest；
- `repository.py`：稳定读取接口；
- `snapshots.py`：原始响应证据和哈希；
- `quality.py`/`audit.py`：契约、完整性和历史对账；
- `backup.py`：备份与隔离恢复。

物理上 K 线与市场事实可以分表，逻辑上通过 Repository 和 Dataset Contract 构成同一数据底座。统一不等于把所有内容塞进一个文件。

### 3.3 QuantX 发布缓存

`data/quantx/YYYYMMDD/review_data.json` 仅作为历史迁移证据，不再是运行时输入。`QuantXReviewRepository` 的默认 V2 从类型化空结构开始，只用 Market Facts、KlineRepository 和版本化确定性 ViewBuilder 组装七区；`source_json_read=false`、`fallback_fields=[]`、`implicit_cache_fields=[]` 是 V2 响应硬门禁。完整交易日观察完成后，公开 API 已关闭 V1 回退，`view_version=v1` 会被契约校验拒绝。兼容 JSON 暂时继续生成，停止生成和归档必须走独立迁移决策。

## 4. 逻辑处理层

- `indicators/`：向量化技术指标和 enriched 流水线。
- `services/`：同步、市场状态、情绪、轮动、监控等业务编排。
- `strategy/`：策略注册、筛选、评分和监控。
- `backtest/`：信号与成交模拟；禁止未来函数。
- `quantx_data/`：来源编排、单日/多日确定性计算和兼容发布。

来源解析不得进入分析层；展示格式不得反向污染事实表；API handler 不承载全量扫描和重计算。

## 5. API 和前端

FastAPI route 负责参数校验、调用 service/repository 和响应映射。前端统一通过 `frontend/src/lib/api.ts`，查询键统一在 `queryKeys.ts`。

页面职责：

- 选择日期、筛选条件和展示状态；
- 组合可复用组件；
- 渲染 API 已定义的数据；
- 对 loading、empty、error、disabled 和 stale 状态给出明确反馈。

页面不得：

- 直接拼接多个供应商 URL；
- 自行解释供应商字段单位；
- 用零填补缺失事实；
- 在浏览器里复制后端核心分析算法；
- 创建与 TanStack Query 平行的缓存。

## 6. 扩展选择矩阵

| 需求 | 正确入口 |
| --- | --- |
| 自有 HTTP 日 K/实时/分钟/财务 | YAML Custom Source |
| SDK、签名或复杂分页行情源 | Provider plugin |
| 用户自己的辅助字段或外部表 | ext_data |
| 可跨页面复用的市场事实 | DatasetSpec + Source Manager + Market Facts |
| 新指标 | indicators，必要时读取 Repository |
| 新分析 | service/repository + API |
| 新图表 | api.ts 类型 + queryKey + page/component |
| 单页面局部定制 | secondary-development 中已有插槽 |

## 7. 缓存与发布边界

每次写路径变更都要检查：持久化文件、Repository 内存对象、generation/version、SSE 和前端 query invalidation。

多步数据更新必须先构建完整新快照，再原子发布。失败不能覆盖上一次有效版本。历史缺失用 null 和质量状态表达，不用零、未来值或其他日期数据伪造。

## 8. 验证最低要求

- 新来源：依赖缺失、认证失败、空数据、过期、重试和来源隔离。
- 新事实：schema、单位、主键、分区、来源、空值、重复、原子发布和历史对账。
- 新分析：正常、边界、缺失输入和时间窗口。
- 新 API：参数、状态码、响应契约和错误映射。
- 新页面：loading/empty/error、交互、控制台、网络和最终渲染。
- 上游合并：重叠热点、完整后端测试、前端构建和 Playwright。

具体步骤分别见 `data-foundation.md`、`analysis-development.md` 和 `upstream-sync.md`。
