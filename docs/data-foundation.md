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
14. `security_listing_history`（手动研究来源，不加入日常采集）
15. `security_name_history`（手动研究来源，不加入日常采集）
16. `security_popularity_daily`（同花顺、雪球、东财、百度个股热榜；可选来源）
17. `stock_logic_evidence_daily`（涨停梯队解读、同花顺热点理由、同花顺个股异动解读的逐股逻辑原文；可选来源）

`sector_breadth_daily` 同时保存 `sw_level1` 与 `sw_level2`。乐咕乐股宽度响应包含滚动历史时，日流水线必须将最近 30 个交易日展开为独立事实分区，而不是只落目标日；每个分区仍按 `(trade_date, dimension, sector_id)` 唯一。历史修复使用 `scripts/backfill_sector_breadth_history.py`：默认仅预检，`--apply` 前备份被替换分区到 `data/.fact_backups/`，再通过 `FactPublication` 原子发布。

`limit_event_daily.limit_reason` 保存事件来源给出的短理由；`limit_ladder_daily.theme_reason` 保存题材级催化，`interpretation` 保存个股级涨停解读。三者缺失时保持空字符串，不得由展示层补写推测性理由。历史低版本分区通过 union-by-name 兼容读取，新采集分区分别使用事件 schema v2 与梯队 schema v3。

`security_popularity_daily`按`(trade_date, symbol, source_name, list_type)`保存各来源的独立名次，不合并重排。网页实时接口只能采集上海时区当天；历史日期必须由`scripts/import_security_popularity_snapshot.py`显式导入当时已冻结的快照，禁止用当前榜单冒充历史观察。该事实设置`degrades_when_missing=false`，缺失时依赖它的页面能力显示`unavailable`，不阻断其余市场事实和股票池发布。

`stock_logic_evidence_daily`按`(trade_date, evidence_source, symbol, evidence_kind)`合并逐股逻辑原文，`evidence_source`为`limit_ladder`（涨停梯队解读）、`ths_hot`（同花顺热点理由）、`fuyao_anomaly`（同花顺个股异动解读）或`ths_hot_list`（同花顺热榜解读，降级）。`match_text`是允许确定性题材关键词规则匹配的来源专属文本：梯队用`theme_name`、热点用`reason`、异动用`keyword_list`拼接、热榜降级用整段理由。`text`保存展示原文，异动的长篇业务解读不参与匹配以免过度归类。`catalyst`保存梯队题材催化，`tag`保存异动标签。同花顺异动接口只返回当日快照，历史日期必须由`scripts/import_fuyao_anomaly_snapshot.py`导入冻结响应；两个导入脚本都会把来源快照写回`quantx/<date>/normalized/`，使后续`--recompute`复用而不是发布空分区。热榜解读与异动解读是同一上游分析：同股同文时只保留异动行；仅在异动来源缺失或未覆盖该股时保留热榜行，并标记`is_fallback=true`、`quality_level=fallback`。该事实设置`degrades_when_missing=false`，缺失时股票池只保留可用来源并标记降级。

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
- 缺失是否使整体运行降级（`degrades_when_missing`）；
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
- 缺失是否使整体运行降级（`degrades_when_missing`）。

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

研究日历回填 `scripts/backfill_trading_calendar.py` 当前明确请求 SSE，预检要求请求区间内每个自然日恰有一行、无区间外日期、无其他交易所或空开市状态。日期数量相同不代表范围完整；SSE 发布不能视为 SZSE/BSE 日历已覆盖。

指定 `--source-file data/research/calendar-20150101-20260907.json` 时，首次成功响应先保存再预检；后续同范围命令（包括 `--apply`）只复用该文件，不再请求 Tushare。请求范围或状态不符拒绝复用，失败请求不保存，已有文件不覆盖；无此选项仍沿用原调用行为。预检和发布使用相同来源观察时间，不能将离线重跑时间当成首次观察时间。

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

历史证券事实的来源准备（已实现采集、Dataset、builder 和显式快照读取；尚未生产发布或接入回测）：

```powershell
backend/.venv/Scripts/python.exe scripts/collect_security_history.py --endpoint stock_basic --output data/research/security-snapshots/20260907-stock-basic-v1 --fetch-one
backend/.venv/Scripts/python.exe scripts/collect_security_history.py --endpoint namechange --output data/research/security-snapshots/20260907-namechange-v1 --fetch-one
```

去掉 `--fetch-one` 仅查看已有页进度。每次最多采集一页，由独立 SourceManager 注册 `module:app.quantx_data.security_snapshots` 执行，未加入日常流水线。当前复用 Tushare 客户端的镜像优先/官方备用链，来源标记为 `tushare_client_chain`，不能当作已确认来自官方直连的独立证据。

成功响应逐页原子保存，恢复复用成功页；缺页、重复记录、状态过滤失效或超过响应上限不推进断点。被拒绝页保留原响应，同一页后续调用返回 `requires_resolution=true` 且不再请求网络，必须先解决分页边界或来源合同，不能反复消耗配额。失败保存分类而非原异常；冷却以实际错误的分钟/小时/日窗口为准，默认名称页 65 秒、上市状态页 3,605 秒，每个目录单写入者。冷却是本任务目录级控制，不是账户全局限流；不要并发新建目录绕过它。进程被强制终止遗留的 `.writer.lock` 需确认对应进程已退出后人工处理，不按文件年龄自动删除。

`stock_basic` 按 L/D/P/G/UN 保存五组响应；`namechange` 保留 offset/limit 请求，短页仅标记 `collected_unverified`。分页排序稳定性、来源全量覆盖、公告时点和历史区间须继续验证，不能以采集结束代替历史主表验收。这些目录不供 Repository/API 消费，不修改 instruments、行情分区或运行中缓存。业务契约与接线验收见研究唯一主计划。

已实现离线名称区间预检：在上述 namechange 命令中用 `--inspect-names` 替代 `--fetch-one`。`security_name_history.normalize_name_pages` 输出类型化中间表；按照来源示例将包含结束日转换为 `valid_to_exclusive=end_date+1`，空结束日期仍为空。公告日期缺失时 `available_from` 为 null；只有日期时保守设为公告次日，使用时还必须同时满足生效区间与来源覆盖。`coverage_until` 为抓取时间对应的北京时间日期，不能据此证明之前每个时点的数据已被当时采集。

输出统一标记 `quality_level=reconstructed`。`is_st_name` 只表达名称前缀，不是官方 ST 状态或可交易判定；未提供名称的区间不能推断为非 ST。源端可能同时给出“拟变更公告日开始的新名称开放行”和交易所正式启用行；仅当同代码、同新名称、同公告日、恰有一个更晚开放行，且旧名称恰好结束于更晚行前一日时，前一行才标为 announcement shadow 并从事实区间折叠，原始页保持不变。任何不满足完整模式的重叠继续拒绝，不能通用裁剪。`--inspect-names` 即使发现非法来源代码，也会在内存排除这些代码后继续输出 `valid_code_rows_diagnostic`，但顶层保持 rejected 且非零退出。预检同时拒绝重复起点、非法日期和无时区的观察时间，保留并报告内部区间缺口。空输入报告 missing，非空通过只报告 normalized_unverified，不自动发布或接入回测。

上市事件中间表使用 stock_basic 命令的 `--inspect-listings` 离线预检，不能与 `--fetch-one` 同用。`security_listing_history` 校验代码/交易所、响应状态、重复证券、日期格式及退市早于上市；保留空日期，并报告缺失状态查询、退市日期缺失和当前上市日期在未来的矛盾。成功空状态页与未查询该状态分别记录。`source_status` 仅代表抓取时状态，不能直接广播成历史上市/停牌状态；空退市日期不证明永久上市。

`--inspect-facts` 离线构造 FactBatch，仅在内存中校验，不能与采集同用。`app.market_facts.security_history.build_security_history_batch` 将中间表映射到已注册 schema，保留 reconstructed 标记；空数据拒绝生成替换批次。两种事实以来源最新观察日 `as_of_date` 分区，禁止将分区日期回填为历史生效日。上市事实 schema v2 主键为 `(as_of_date, security_id)`；名称事实主键为 `(as_of_date, symbol, valid_from)`。构造成功只证明字段与结构可落库，不证明来源完整性。

上市事实分别保存供应商原始代码 `source_symbol`、来源命名空间内身份 `security_id=tushare:<source_symbol>` 和标准交易代码 `symbol`，不把共用交易代码的不同主体合并；这不是跨供应商的统一身份解析。仅对已核实的 `T600018.SH`（上港集箱，2000-07-19 至 2006-10-20，D 状态）显式映射至交易代码 `600018.SH`，其身份与上港集团独立。其他未知前缀仍拒绝；同代码生命周期重叠或无法确定先后时拒绝构造。`source_record_id` 保留来源代码。当前没有生产 v1 上市分区，本次仅更改未发布契约；旧研究批次需从原始页重建，不能直接补空身份后发布，不涉及运行中行情、instruments 或缓存迁移。

Repository 的 `get_security_listing_snapshot(snapshot_date)` / `get_security_name_snapshot(snapshot_date)` 只读取明确指定的已发布分区，分区缺失返回空表，不自动读取未来快照。研究来源通过独立 `snapshot_manager()` 注册，项目契约校验同时检查日常和手动注册表；不加入日常 SOURCE_MANAGER。当前无生产发布命令、API 或回测消费者，生产写入仍需独立来源完整性验收；已用临时目录验证 FactPublication 写入、读取及失败恢复。

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

上市年龄算术使用 `security_history.listing_trade_days(calendar, exchange=..., listed_on=..., day=...)`，输入是调用方已解析版本和时点的日历。上市日计 1，排除前 N 个交易日应使用 age > N；要求区间内每个自然日都有明确开市状态，缺日/空值/未知上市日返回 null，重复日历日期拒绝。它不验证身份或公告可得性、不从 K 线根数推算、不单独判断可交易性，目前尚未接入两引擎。

每日研究股票池三态计算使用 `security_history.resolve_daily_security_eligibility(...)`，只接受调用方显式选择的完整上市快照、已按查询日解析的名称状态和对应交易所日历。输出 `eligible/ineligible/unknown`、证券身份、精确上市交易日年龄或可验证下界、名称 ST 标记及逐项原因；老股缺少上市日起完整日历时，只有已覆盖区间的开市日下界超过门槛才允许年龄条件通过，下界不足保持 unknown。已知不合格条件足以判定 `ineligible`。退市日期按来源生命周期末日包含处理，后来退市不删除其过去资格；复用代码按当日唯一有效 `security_id` 解析，重叠生命周期直接拒绝。Repository 的 `get_daily_security_eligibility(...)` 要求显式传入上市、名称、日历三个版本日期和带时区截止时刻，缺分区时保持 unknown，不搜索最新或未来分区。该资格不推断停牌或成交可行性，尚未接入两回测引擎。

名称时点查询已实现 `get_security_names_at(symbols, snapshot_date=..., cutoff=带时区时间, allow_reconstructed=False)`：默认要求 observed_at 和 ingested_at 均不晚于截止时刻；显式历史重建放宽采集时间限制，但仍要求公告可得日期、生效区间和观察覆盖满足查询日。缺公告、区间缺口、超覆盖返回 unknown，name/is_st_name 保持 null。输出 knowledge_basis 区分 recorded/reconstructed/unknown；名称前缀仍不等于官方交易状态。此接口尚未接入回测，不自动读取未来快照。

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

## 10. 财务数据双层事实

- `financials/overview/part.parquet` 是全市场报告期快照，用于覆盖率、筛选和横截面对比。
- `financials/{metrics,income,balance_sheet,cash_flow,shares}/part.parquet` 是按股票更新并累计的标准财报历史。
- `financials/shares` 同时承载交易日股本事实：`daily_basic.trade_date` 映射为 `effective_date/period_end`，来源单位万股必须无条件乘 10,000 后存为股；这类日期不是财报报告期或公告日，必须以 `quality_level=reconstructed` 和具体来源谱系区分。
- 两层都必须携带来源与观察时点；详细历史分析必须满足 `announce_date <= as_of`，概览快照不得用于其 `observed_at` 之前的回测。
- 普通权限采用“市场概览 + 单股按需详情”，只有明确检测到批量权限时才能全市场同步详细财报。
- 空响应和失败不得覆盖上一版数据，Parquet 发布使用临时文件原子替换。
- `local_financial` 的全市场历史回填从 2012 年开始，按季度调用 AkShare/东财的业绩、利润、资产负债和现金流核心表；已完成的旧报告期跳过，最近四期始终刷新以接收迟报和修订。
- 沪深利润表、现金流量表的批量接口不等于数百字段的完整个股财报；北交所当前由业绩摘要和资产负债批量表覆盖，完整三表仍由单股明细层补齐。页面和 API 必须展示实际标的/报告期覆盖，不能宣称不存在的字段完整度。
- 同一 `symbol + period_end` 已有 Tushare 明细时，AkShare 核心行不得覆盖它；批量事实只替换同来源的旧 AkShare 行或补充缺失键。

历史交易日股本使用 `scripts/import_quants_share_history.py` 从只读 Quants `dwd_daily_basic` 迁移。脚本默认仅预检，`--apply` 前备份旧表并原子发布；不允许用数值猜单位。回测矩阵对总/流通股本执行 `effective_date <= 交易日` 的向后时点关联；一旦历史表存在，缺失历史值保持 NaN 并使市值门槛拒绝，禁止回退到 instruments 当前股本。股本文件大小和修改时间参与矩阵缓存指纹，发布变化不能复用旧缓存。
