# TickFlow 数据底座契约

状态：权威当前文档。适用于新数据源、DatasetSpec、字段口径、分区、质量和发布修改。

## 1. 数据分类

| 数据类型 | 权威入口 | 典型存储 |
| --- | --- | --- |
| 日 K、复权、分钟、实时、财务 | MarketDataProvider | kline/instruments/financial Parquet |
| 用户扩展表 | ext_data | `data/ext_data` |
| 可复用市场事实 | SourceManager + Market Facts | `{dataset_id}/date=YYYY-MM-DD/part.parquet` |
| QuantX 原始证据 | SourceSnapshotStore | `source_snapshots` |
| QuantX 展示兼容 | QuantX publish cache | `quantx/YYYYMMDD/*.json` |

数据类型必须先分类再写代码。不得为了绕过 Dataset Contract 把长期事实塞入展示 JSON，也不得把普通 OHLCV 来源重复实现成 QuantX scraper。

## 2. 当前标准事实

当前 Dataset Registry 包含：

1. `trading_calendar`
2. `market_breadth_daily`
3. `market_liquidity_daily`
4. `margin_daily`
5. `limit_event_daily`
6. `limit_ladder_daily`
7. `theme_observation_daily`
8. `theme_member_daily`
9. `sector_flow_daily`
10. `sector_breadth_daily`
11. `market_state_daily`
12. `market_signal_daily`
13. `screening_candidate_daily`

以 `backend/app/market_facts/registry.py` 为唯一机器可读权威。文档列表仅用于导航。

## 3. DatasetSpec 必备内容

每个事实必须声明：

- 稳定 `dataset_id`；
- 描述和 `schema_version`；
- `primary_key`；
- `partition_keys`；
- `required_columns`；
- 完整 Polars `storage_schema`；
- 所有非显然数值的 `field_units`；
- 新鲜度语义；
- `SourceRoute` 中的主来源和备用来源顺序。

公共溯源字段由统一 schema 提供：`source`、`source_record_id`、`observed_at`、`ingested_at`、`run_id`、`schema_version`、`quality_level`、`is_fallback`。

运行 `validate_registry_contracts()` 可检查 schema、主键、分区、必填字段、单位和路由结构的一致性。

## 4. 字段与单位

- `*_pct`：百分数，`3.66` 表示 `3.66%`。
- `*_ratio`：小数比例，`0.0366` 表示 `3.66%`。
- 金额使用 `_yuan`、`_wan`、`_yi` 等显式后缀。
- 日期使用 `date` 类型，时间戳必须说明时区。
- 股票代码进入事实层前统一为标准 symbol 和 exchange。
- 缺失保持 null；不得用零推断“没有发生”。
- 代理指标必须标记 `quality_level=proxy` 和 `is_fallback=true`。

禁止用数值大小猜单位，例如“值小于 1 就乘 100”。转换必须由来源契约显式决定。

## 5. Source Manager

QuantX 专项来源在 `collectors.py` 声明 `SourceSpec`，由 `SourceManager` 注册。SourceSpec 至少包含：

- `name`、`display_name`；
- `required`、`role`；
- collector 引用和 `collector_type`；
- `credentials_ref`，只保存环境变量名；
- dependency modules；
- timeout、rate limit 和 retry metadata；
- freshness 和最小记录数。

Source Manager 是唯一执行入口。它复用已发布快照，执行依赖检查，隔离来源异常，并输出稳定的 `error_kind`：

- `authentication`
- `dependency`
- `rate_limit`
- `timeout`
- `network`
- `parse`
- `missing`
- `stale`
- `unknown`

scraper 内部仍需设置 HTTP/浏览器超时；此外 SourceManager 会把生产 collector 放入独立子进程，按 SourceSpec 执行可取消的 wall-clock timeout。两层超时分别约束单次网络调用和整个来源任务，不能互相替代。

来源运行状态必须分别报告 `manifest_health`、`credential_readiness`、`dependency_readiness` 和 `live_probe`，不能把“有历史快照”误写为“凭据和实时接口健康”。统一刷新血缘通过 `GET /api/quantx-data/observability/{date}` 查看，数据页提供 run、resume、recompute 和单来源 retry 操作。

## 6. 标准采集与发布链

```text
plan
→ SourceManager.collect
→ raw snapshot + hash
→ normalize
→ build FactBatch
→ schema/quality validation
→ FactPublication.stage
→ manifest
→ atomic commit
→ Repository / API refresh
```

规则：

1. 同一交易日只有一个 QuantX 发布任务。
2. required 来源或必需事实不满足时 `failed`，保留旧发布。
3. 备用来源满足契约时可 `degraded`，必须标记来源和质量。
4. `--recompute` 只读本仓库快照，不访问网络。
5. 原始响应保存 hash 和来源引用，标准事实不保存凭据。
6. API 和页面读取已发布 Repository，不读取 `.runs` 或原始响应。

## 7. 新事实数据脚手架

先生成到新的空目录，脚本不会修改 registry，也不会覆盖非空目录：

```powershell
python scripts/scaffold_market_fact.py northbound_flow_daily `
  --source tushare `
  --description "Daily northbound capital flow" `
  --output .tmp/northbound_flow_daily
```

输出包括：

- `registry_snippet.py`：DatasetSpec 和 SourceRoute 草案；
- `builder.py`：来源到 FactBatch 的转换骨架；
- `test_<dataset>.py`：契约测试骨架；
- `README.md`：接线清单。

脚手架故意要求人工或 AI 明确替换单位、主键和字段，不会自动把占位契约注册进生产。完成时必须：

1. 确认现有事实不能表达需求；
2. 固化来源 JSON fixture；
3. 添加 DatasetId、DatasetSpec 和 SourceRoute；
4. 在统一 Source Manager 声明来源；
5. 实现 builder 并接入 `build_initial_fact_batches`；
6. 增加 Repository 方法；
7. 执行历史回填与多源对账；
8. 最后接 API 和前端。

## 8. Schema 变更

- 向后兼容新增 nullable 字段：提升 schema version，保留旧分区读取。
- 字段改名、单位变化、主键变化：视为破坏性迁移，必须提供备份、预检、幂等迁移和回滚说明。
- 不得直接覆盖历史分区；使用现有迁移和 FactPublication 工具。
- 迁移前后对任务外事实计算集合指纹，证明没有旁路改写。

## 9. 验收清单

- [ ] 来源和 Dataset 路由存在且一致。
- [ ] schema、必填、主键、分区和单位校验通过。
- [ ] 重复记录和错误日期 fail-closed。
- [ ] required/optional/fallback 状态符合契约。
- [ ] 空值没有被零或未来数据填充。
- [ ] 发布失败保留上一版本。
- [ ] Repository、API 和前端使用同一事实。
- [ ] 历史对账、备份和隔离恢复有证据。
