# 数据源与每日更新时序参考

> 状态：权威当前文档（2026-08-31 核验）。回答「什么数据来自哪里、什么时候更新、每天最早几点可以跑完」。
> 代码事实以 `backend/app/jobs/daily_pipeline.py`、`backend/app/services/preferences.py`、`backend/app/quantx_data/scheduler.py` 为唯一权威；本文件只做导航与时间线说明。历史方案（如 `docs/quantx-unified-data-foundation-plan.md`）不覆盖当前实现。

## 1. A 股市场时段（北京时间，`backend/app/market_time.py`）

| 时段 | 说明 |
| --- | --- |
| 09:15–09:25 | 集合竞价 |
| 09:25–09:30 | 竞价定盘（`kline_sync.fetch_intraday_monitor_batch` 以 9:25 为当日数据起点） |
| 09:30–11:30 / 13:00–15:00 | 连续竞价（实时行情主窗口） |
| 15:00 | 收盘，当日行情定格 |

盘中阶段口径（`quote_service._market_phase`）：`preopen`(9:15-9:30)、`morning`(9:30-11:30)、`morning_final`(11:30-12:55)、`pre_afternoon`(12:55-13:00)、`afternoon`(13:00-15:00)、`close_final`(≥15:00)。

## 2. 外部数据源与更新机制

### 2.1 TickFlow 官方 SDK（主行情源，`tickflow/`、`data_providers/tickflow_provider.py`）

| 数据集 | 档位门槛 | 更新机制 | 当日数据可用时间 |
| --- | --- | --- | --- |
| 日 K `kline.daily` | None/Free：free-api 服务器 | 盘后管道 batch 拉 | **盘后约 1–2 小时（约 16:00–17:00）**，README / 操作说明书 / docs/configuration.md 一致描述 |
| 日 K（今日覆写）`quote.batch/pool` | Starter+ | `quote_service` 盘中实时落盘 → 盘后管道「实时覆写今日」 | 收盘 15:00 即刻可用 |
| 实时快照 | Free 自选 / Starter+ 全市场 | `quote_service` 轮询（9:15 预热 → 11:30/15:00 定版后停止） | 盘中 9:30–15:00 |
| 五档盘口 `depth5` | Pro+（`DEPTH5_BATCH`） | `depth_service` 连续竞价时段轮询（默认 10s，按 rpm 自适应）→ 15:02 sealed 定版 | 盘中可用 |
| 分钟 K `kline.minute` | Pro+（`KLINE_MINUTE_BATCH`） | 盘后管道 Step 2.5（可选开关） | 收盘后 |
| 复权因子 `adj_factor` | Starter+ | 盘后增量；范围拉取对齐日 K | 交易所晚间公布新除权，当日新除权通常次日补全 |
| 财务 `financial` | Expert | 手动同步 `/api/financials/sync/*`（默认不自动） | — |
| 标的维表 `get_instruments` | 无门槛 | 盘前 09:10 全量覆盖（含当日涨跌停价） | 盘前 |

### 2.2 可选插件数据源（`backend/app/plugins/*`）

| 插件 | 数据 | 路由/门槛 | 备注 |
| --- | --- | --- | --- |
| `tushare` | daily / adj_factor / index / financial / moneyflow | 需 `TUSHARE_TOKEN` | 用于 quantall 能力迁移 |
| `stocksdk`（Node，抓腾讯+东财） | daily / minute / adj_factor / realtime | Node 18+，`INCLUDE_STOCKSDK=1` | 版权/反爬风险；实测日K/分钟常返回空，realtime 仅股票不全资产 |
| `local_financial` | AkShare 全市场业绩概览 + Tushare 单股三表 | 无 Expert 依赖 | 业绩概览按报告期；三表单股按需 |
| `fuyao`（同花顺官方 REST） | realtime | `FUYAO_API_KEY`，`hidden: true` | 未接入日K/分钟/财务 |
| YAML 自定义源 / 腾讯备用 | 自定义扩展；QuantX 必需指数 | ext_data | 详见 §3.2 |

### 2.3 QuantX 市场事实采集器（`quantx_data/legacy_scrapers/*`）

| SourceSpec | display_name | 角色 | 上游 | 当日数据可用时间 |
| --- | --- | --- | --- | --- |
| `tushare` | Tushare Pro | **必需** | `pro.daily` / `margin` / `trade_cal` / `suspend_d` | 行情盘后即可；**融资融券 margin 通常日终清算后晚间更新（约 17:00 后，需实测），缺时该日 margin_daily 为空，需单来源 retry** |
| `pywencai` | 同花顺问财 | **必需** | iwencai 问句（涨停/题材） | 收盘后即可 |
| `akshare` | AKShare | 可选 | 东财行业资金流 s:4 等 | 收盘后 |
| `ths_hot` | 同花顺热点 | 可选 | 热点榜单 | 收盘后 |
| `zhangtingke` / `zhangtingjun` | 涨停客 / 涨停君 | 可选 | 连板/情绪 API | 收盘后 |
| `legulegu` | 乐咕乐股 | 可选 | 申万 level1/2 行业宽度 | **通常当日晚间/次日早完整（需实测）；乐咕宽度响应含滚动历史时，日流水线将最近 30 个交易日展开为独立事实分区** |
| `duanxianxia` / `deepq` | 短线侠 / DeepQ | 可选 | — | 收盘后 |
| `quicktiny` / `dabanke` | QuickTiny / 打板客 | 可选（浏览器 / 登录态） | fpb 等 | 收盘后，依赖登录态 |
| `sector_fund_flow_s4` | S4 行业资金流 | 可选（浏览器） | 东财 s:4 | 收盘后，依赖登录态 |
| `tickflow_enriched_aggregate` | TickFlow enriched 聚合 | 本地 | `kline_daily_enriched` | 盘后管道完成后 |

## 3. 内置定时任务（默认时间、可调范围）

| 任务（job id） | 默认（北京时间） | 可调范围 | 说明 |
| --- | --- | --- | --- |
| `pre_market_instruments` | 09:10 | 上限 09:15 | 盘前维表，含当日涨跌停价 |
| `depth_finalize` | 15:02 | 15:01–18:00 | 五档盘口 sealed 定版（Pro+） |
| `daily_pipeline` | **16:30**（2026-08-31 从 15:30 调后） | 下限 15:00 | 日K + 除权 + enriched + 指数/ETF/分钟 + regime/mainline |
| `quantx_data_deadline_recovery` | 17:30 | 不可配 | QuantX 末班兜底（父管道成功后已依赖触发一次；17:30 复用已有快照，幂等） |
| `scheduled_review` | 16:45（**默认关闭**；2026-08-31 从 15:10 调后） | 下限 15:00 | AI 大盘复盘，需 AI Key |
| `reprobe_capabilities` | 每小时 | — | 能力重探，Key 过期/续费热更新 |
| financial metrics | 手动（`auto_schedule=False`） | — | 财务默认手动；开启后启动+60s 首跑、每 7 天 |
| 周度 mining | 关闭（默认） | 周五默认 | 选股挖掘，候选库显式发布 |
| ext_data 预设（同花顺概念/行业） | 启动立即 + 每 1440 分钟 | 至少 60s | `ext_gn_ths` / `ext_hy_ths` |

调度器统一 `day_of_week="mon-fri"`、`timezone="Asia/Shanghai"`。

## 4. 盘后执行链

```text
16:30  daily_pipeline  start
  └─ Step 0/1   同步维表 + 日K（付费＝实时覆写今日；免费＝batch，免费当日数据需 16:00-17:00 已就绪）
     Step 1.5   除权因子增量（范围拉取对齐；增量兜底最近 15/30 天）
     Step 2     enriched（增量/扇动个股重算/全量重建）
     Step 2.3   指数 / ETF（依赖 KLINE_DAILY_BATCH）
     Step 2.5   分钟K（可选）
     Step 2.6   市场环境 regime + Step 2.7 主线（可选开关）
     Step 3     刷新视图 + 缓存
  └─ 成功后 → QuantX 依赖触发（run_scheduled：交易日历判定 → run_pipeline）
17:30  quantx deadline recovery（仅补偿主触发遗漏，复用快照）
16:45  scheduled_review（可选，流式生成 → 归档 → 飞书/企微）
```

## 5. 每天最早应该在什么时间

结论分三档（`settings` 页可分别配置）：

| 目标 | 最早可行 | 说明 |
| --- | --- | --- |
| 盘前维表同步 | 09:10（现状合理） | 需早于 09:25 竞价定盘；上限 09:15 |
| 五档定版 | 15:02（现状合理） | 收盘后最早稳定时点 |
| **盘后管道（行情线）** | **付费档 15:15–16:00；免费档 16:30–17:00** | 免费当日日K盘后 1-2 小时可用；付费盘中已落盘 |
| AI 复盘 | 不早于盘后管道完成 | 默认 16:45 已自动对齐 |
| QuantX 全量事实 | **≈17:30 之后** | 受融资融券（margin）与乐咕行业宽度晚间更新的最晚节点约束 |

默认值取舍：`daily_pipeline=16:30` 同时覆盖免费档（当日日K就绪）与付费档（盘中实时已落盘，仅多等片刻）；付费用户可在设置里调早到 15:15–16:00。**不建议把管道调回 15:30 之前**——免费档当天 K 线会静默缺失，需靠模板「数据修正」补拉。

## 6. 风险与操作提示

1. **免费当日日K**：16:00–17:00 内仍在更新窗口，偶发延迟时当日分区会缺；数据页对缺失日执行「数据修正」（`override_start_date`）可补，勿用 `fast_sync` 冒充成功。
2. **融资融券 margin**：Tushare 日终清算后更新，时点不固定；若 QuantX 首跑时未就绪，保存的该日 margin 为空，需在数据页对该日做**单来源 retry**（`retry_sources=tushare`）。17:30 恢复任务复用快照，不会自动重拉。
3. **乐咕乐股行业宽度**：当日晚间/次日早才完整；日流水线展开最近 30 个交易日落分区时以最新一次采集为准，历史修复走 `scripts/backfill_sector_breadth_history.py`。
4. **节假日判定**：交易日历优先来自 `MarketFactRepository.is_trading_day` + 本地 TickFlow 分区（`quantx_data/scheduler.py`），工作日的 cron 仅作兜底；节假日调度自动跳过。
5. **付费档调早到 15:15** 时，除权因子仍可能缺当日新事件、QuantX margin 仍缺，行情线完成后请到日终（≥17:30）为 QuantX 做单来源 retry 以获得完整事实。

## 7. 参考来源

- `backend/app/jobs/daily_pipeline.py`：调度注册、run_now 各 stage、深度定版/复盘/能力重探 job。
- `backend/app/services/preferences.py`：`get_pipeline_schedule`(16:30)、`get_instruments_schedule`(09:10)、`get_depth_finalize_time`(15:02)、`get_review_schedule`(16:45)。
- `backend/app/quantx_data/scheduler.py`、`docs/quantx-independent-update-audit-20260828.md` §3.7：QuantX 依赖触发 + 17:30 恢复。
- `backend/app/quantx_data/collectors.py`、`legacy_scrapers/*`：QuantX 来源清单与采集方式。
- `tiers.yaml`、`backend/app/tickflow/policy.py`：档位能力与免费用量上限。
- README「快速开始」、`docs/configuration.md`：免费档当日日 K 盘后 1-2 小时可用。

> 修改时间：2026-08-31。盘后管道默认时间由 15:30 调至 16:30；定时复盘默认时间由 15:10 调至 16:45。