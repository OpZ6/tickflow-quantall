# TickFlow 架构与扩展开发指南

> 历史状态：这是 2026-08-26 的详细架构快照，不再作为当前开发入口。当前分层和扩展选择以 [`architecture.md`](architecture.md) 与 [`README.md`](README.md) 为准。

> 面向二次开发者:在你打算基于 TickFlow 底座做大量后续开发之前,先读这份文档。
>
> 它把项目从「数据底座 → 业务能力 → API → 前端」逐层拆开,标出每层的存储形式、调用链、扩展点和已知风险,并给出「新增数据源 / 新增策略 / 新增指标 / 新增 API / 新增面板」的可复用路径。
>
> 阅读本文前建议先浏览根目录 `README.md`、`CONTRIBUTING.md`、`PROJECT_ANALYSIS.md` 与 `操作说明书.md`,它们分别给出项目总览、贡献与审查规范、独立审计结论和终端用户操作流程。本文不重复这些内容,只在必要处引用。

## 目录

- [1. 项目定位与顶层架构](#1-项目定位与顶层架构)
- [2. 数据底座解构](#2-数据底座解构)
- [3. 数据源插件化与接入路径](#3-数据源插件化与接入路径)
- [4. 数据流:盘后管道与实时热路径](#4-数据流盘后管道与实时热路径)
- [5. 业务能力层](#5-业务能力层)
- [6. API 层](#6-api-层)
- [7. 前端架构](#7-前端架构)
- [8. 如何在底座之上做分析](#8-如何在底座之上做分析)
- [9. 如何新增功能](#9-如何新增功能)
- [10. 如何新增面板](#10-如何新增面板)
- [11. 扩展方向建议](#11-扩展方向建议)
- [12. 关键源码索引](#12-关键源码索引)
- [13. 验证与开发流程](#13-验证与开发流程)
- [14. 已知风险与开发约束](#14-已知风险与开发约束)

---

## 1. 项目定位与顶层架构

### 1.1 一句话定位

TickFlow Stock Panel 是一个**本地优先、数据源可插拔**的 A 股研究工作台,把「数据接入 → 复权 → 指标 → 选股 → 回测 → 监控 → 复盘 → AI 文本分析」放进同一套数据契约与同一份本地 Parquet 数据底座。

它**不是**交易终端:没有下单链路,没有真实撮合,没有逐笔 Tick。所有"成交"都是基于日 K / 分钟 K 的规则模拟。

### 1.2 顶层架构

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                        外部数据源 / 本地文件                              │
│  TickFlow SDK  ·  stock-sdk 插件  ·  自定义 HTTP (YAML)  ·  CSV/Excel/JSON │
└                                       ┬──────────────────────────────────┘
                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  data_providers/ (Provider 契约 + 标准化)                                 │
│  base.py · schemas.py · registry.py · tickflow_provider.py · custom/      │
│  将不同供应商的字段/单位/代码/日期归一成内部统一 schema                    │
└                                       ┬──────────────────────────────────┘
                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  tickflow/ (Repository / DataStore)                                       │
│  repository.py · capabilities.py · client.py · scheduler.py · pools.py    │
│  Parquet 分区写盘 + DuckDB union_by_name 视图 + Polars 内存缓存           │
└                                       ┬──────────────────────────────────┘
                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  indicators/ · strategy/ · backtest/ · services/                          │
│  pipeline.py (指标+信号) · engine.py (策略) · matrix.py (回测)            │
│  quote_service · monitor · regime_builder · market_overview · levels     │
│  stock_analyzer · financial_analyzer · market_recap · rps_rotation       │
│  ext_data · ext_pull · concept_rotation · sector_monitor                 │
└                                       ┬──────────────────────────────────┘
                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  api/ (FastAPI 路由 + SSE)                                               │
│  28 个 router · 187 个 path · 208 个 operation                          │
│  REST 拿快照,SSE 推行情/进度/AI 流                                       │
└                                       ┬──────────────────────────────────┘
                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  frontend/ (React 18 + Vite + TS + TanStack Query)                       │
│  24 个页面 lazy 加载 · lib/api.ts 统一客户端 · useQuoteStream 单 SSE      │
│  ECharts + lightweight-charts + dnd-kit                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.3 技术栈速览

| 层 | 选型 | 关键约束 |
| --- | --- | --- |
| 后端 | Python ≥ 3.11、FastAPI、Pydantic v2、APScheduler、sse-starlette | 业务计算优先 Polars,回测边界允许 pandas |
| 数据 | Polars(计算)· DuckDB(查询)· Parquet(存储)· PyArrow | DuckDB 不做主存储,只读 Parquet 视图 |
| 回测 | NumPy + Numba 自研矩阵引擎;vectorbt 为可选兼容边界 | 主路径已切到自研 matrix,不是 vectorbt |
| 数据源 | TickFlow 官方 SDK · stock-sdk 插件 · 自定义 HTTP | 一切供应商字段先归一再入库 |
| AI(可选) | OpenAI 兼容 / Codex CLI | 留空即关闭,不进热路径 |
| 前端 | React 18、Vite、TypeScript、Tailwind、TanStack Query | 单 SSE、统一 api.ts、查询键集中 |
| 部署 | Docker 两阶段构建,前端 dist 拷进后端镜像,单容器 | dev 模式 Vite 代理 /api 到 3018 |

### 1.4 模块边界(来自 CONTRIBUTING.md §2.3)

| 目录 | 职责 | 放置要求 |
| --- | --- | --- |
| `backend/app/api/` | HTTP、SSE、参数校验、响应映射 | 薄层,不放重计算/全量扫描/数据源专属业务 |
| `backend/app/services/` | 同步、实时、通知等业务编排 | 组合领域能力,不复制仓库或 provider 实现 |
| `backend/app/tickflow/` | 存储、仓库、能力检测、TickFlow 接入 | 通过抽象暴露能力,上层不依赖存储细节 |
| `backend/app/data_providers/` | Provider 接口、标准化、自定义数据源 | 新数据能力先定义数据集契约,再由 provider 实现 |
| `backend/app/plugins/` | 插件发现、加载、插件协议 | 插件失败不得破坏未启用插件的主流程 |
| `backend/app/indicators/` | 指标计算和 enriched 流水线 | 向量化,区分原始价/复权价/输出单位 |
| `backend/app/strategy/` | 策略注册、执行、监控、AI 策略 | 内置与自定义策略共享执行契约 |
| `backend/app/backtest/` | 回测、优化、步进、worker | 严格隔离信号生成与成交模拟,防未来函数 |
| `frontend/src/lib/` | API 客户端、查询键、共享查询 | 后端契约变化必须同步类型与调用方 |
| `frontend/src/pages/` | 页面级编排 | 复杂领域逻辑下沉到 hook / 组件 / 后端服务 |
| `frontend/src/components/` | 可复用交互组件 | 保持 props 契约稳定 |
| `data/` | 用户运行时数据 | 不提交 Git,不写绝对路径 |

铁律:**API 与页面不应直接读取某个供应商**。所有数据必须先走 provider → 标准化 → 仓库,再进入业务层。这是后续所有扩展都必须遵守的边界。

---

## 2. 数据底座解构

这是 TickFlow 最有价值的部分。后续大量开发绝大多数是「在已落地的底座上叠加新数据集、新指标、新分析、新面板」,而不是替换底座本身。理解本节是后续一切工作的前提。

### 2.1 三层存储

```text
┌────────────────────────────────────────────────────────────────────────┐
│  Parquet (持久层)                                                       │
│  按日期分区 / symbol+date 主键 merge-upsert                             │
│  临时文件 + replace 原子写,降低半文件概率                                │
│  窄表存储 enriched (15 列),完整指标在读取时重算                          │
└                                  ┬─────────────────────────────────────┘
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  DuckDB (查询层)                                                        │
│  内存模式,不建 .db 文件                                                 │
│  CREATE OR REPLACE VIEW ... read_parquet(...) union_by_name=true        │
│  适合统计/元数据/自定义 SQL;不做主存储                                   │
│  单 connection,所有读路径走 KlineRepository.execute_all/_one (锁保护)   │
└                                  ┬─────────────────────────────────────┘
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Polars 内存缓存 (热路径)                                              │
│  enriched 最新日 ~5500 行 + 完整历史 ~100 万行(含指标)                   │
│  instruments / live_agg(盘中递推状态)/ ETF enriched / index enriched   │
│  启动时 instruments 同步加载;enriched 推 daemon 线程异步重算            │
│  写盘后 refresh_cache() 同步刷新,clear_cache() 无条件清空                │
└────────────────────────────────────────────────────────────────────────┘
```

三层各司其职:

- **Parquet** 是真相之源,进程重启后唯一可恢复的状态。
- **DuckDB 视图** 是 Parquet 的索引层,提供 SQL 访问;`union_by_name=true` 让历史 Parquet 缺新字段时仍可读取(向后兼容关键设计)。
- **Polars 缓存** 是性能层;实时热路径只读内存,不扫盘。

代码入口:`backend/app/tickflow/repository.py` 的 `DataStore` 与 `KlineRepository`。

### 2.2 数据目录全景(`data/`)

`data/` 被 Git 忽略,所有内容都是程序运行时生成或拉取的用户数据。`DataStore.__init__` 在启动时确保下列子目录存在(repository.py:62-90):

| 子目录 | 内容 | 分区方式 |
| --- | --- | --- |
| `kline_daily/` | A 股日 K | `date=YYYY-MM-DD/part.parquet` |
| `kline_daily_enriched/` | A 股 enriched 窄表(15 列) | `date=YYYY-MM-DD/part.parquet` |
| `kline_index_daily/` | 指数日 K | 同上 |
| `kline_index_enriched/` | 指数 enriched | 同上 |
| `kline_etf_daily/` | ETF 日 K | 同上 |
| `kline_etf_enriched/` | ETF enriched | 同上 |
| `kline_etf_minute/` | ETF 分钟 K | `symbol=XXX/date=YYYY-MM-DD/part.parquet` |
| `kline_minute/` | A 股分钟 K | 同上 |
| `adj_factor/` | 除权因子 | `symbol=XXX/part.parquet` |
| `adj_factor_etf/` | ETF 除权因子 | 同上 |
| `instruments/` | 股票维表(代码/名称/市场/股本/涨跌停) | 单文件 `instruments.parquet` |
| `instruments_index/` | 指数维表 | 单文件 |
| `instruments_etf/` | ETF 维表 | 单文件 |
| `instruments_ext/` | 扩展维表 | 单文件 |
| `kline_ext/` | 扩展时序 K 线 | 按需 |
| `financials/metrics/` | 财务指标 | 单文件 |
| `financials/income/` | 利润表 | 单文件 |
| `financials/balance_sheet/` | 资产负债表 | 单文件 |
| `financials/cash_flow/` | 现金流量表 | 单文件 |
| `financials/shares/` | 历史股本 | 单文件 |
| `depth5/` | 五档盘口 sealed 状态(旁路,不进 enriched) | 按日 |
| `ext_data/{id}/` | 扩展数据集 | `part.parquet`(snapshot)或 `timeseries/date=.../part.parquet` |
| `pools/` | 标的池缓存(CN_Equity_A 等) | — |
| `backtest_results/` | 回测结果 JSON | — |
| `screener_results/` | 选股结果缓存 | — |
| `.backtest_matrix_cache/` | 回测矩阵 memmap 缓存 | 默认上限 512 MB |
| `.matrix_generation_stock.json` | 矩阵 generation ID | 单文件 |
| `ai_cache/` | AI 报告归档 | — |
| `job_store/` | 同步任务记录 | — |
| `capabilities.json` | TickFlow 能力检测结果 | 单文件 |
| `data_sources/` | 自定义数据源 YAML | 一个文件一个源 |
| `regime_history/` | 市场状态历史 | — |
| `user_data/` | 用户配置 | 见下 |

`data/user_data/` 下:

| 路径 | 内容 |
| --- | --- |
| `preferences.json` | 全局偏好(自动运行、监控开关、Webhook 等) |
| `custom_signals/*.json` | 用户自定义信号(编译为 `csg_*` Polars Expr) |
| `monitor_rules/` | 监控规则 |
| `strategy_overrides/` | 策略参数覆盖 |
| `auth.json` | 访问密码与会话 |
| `alerts.jsonl` | 监控触发记录(保留 7 天、最多 5000 条) |

策略文件另有独立目录,不在 `user_data/` 下:

| 路径 | 内容 |
| --- | --- |
| `data/strategies/custom/*.py` | 用户手写策略 |
| `data/strategies/ai/*.py` | AI 生成策略(`ai_` 前缀) |
| `data/strategies/composite/*.py` | 组合策略 |

### 2.3 数据集 schema

Provider 标准化 schema 由 `backend/app/data_providers/schemas.py` 定义:

```python
DAILY_COLUMNS = [
    "symbol", "asset_type", "source", "date",
    "open", "high", "low", "close",
    "volume", "amount", "pre_close", "change_pct",
]
ADJ_FACTOR_COLUMNS = ["symbol", "asset_type", "source", "trade_date", "ex_factor"]
INSTRUMENT_COLUMNS = [
    "symbol", "name", "exchange", "asset_type", "source", "list_date", "status",
]
MINUTE_COLUMNS = [
    "symbol", "asset_type", "source", "datetime",
    "open", "high", "low", "close", "volume", "amount", "freq",
]
```

**关键单位约定**(CONTRIBUTING.md §3,出错不会报异常但会产生看似合理的错误结果):

| 字段 / 场景 | 口径 | 示例 |
| --- | --- | --- |
| 自定义实时入口 `change_pct` | 小数 | `0.0366` 表示 3.66% |
| enriched 与监控内部 `change_pct` | 通常小数 | 阈值前必须确认调用链 |
| 指数实时展示缓存涨跌幅 | 百分数 | 使用前必须显式转换 |
| 自定义实时入口 `turnover_rate` | 小数 | `0.05` 表示 5% |
| enriched 的 `turnover_rate` | 百分数值 | `5` 表示 5% |
| enriched `open/high/low/close` | 前复权价 | 用于技术指标 |
| `raw_close/raw_high/raw_low` | 不复权价 | 用于涨跌停判断 |
| enriched 没有 `raw_open` | 缺失 | 历史已如此,改动需评估兼容 |

### 2.4 数据量级(来自 PROJECT_ANALYSIS.md §5.3)

| 数据 | 量级 |
| --- | --- |
| 最新 enriched 股票缓存 | ~5,500 行(全 A 股) |
| 完整 enriched 历史 | ~100 万行(随年限增长) |
| 股票/指数/ETF instruments | 各 ~5,500 行 |
| 矩阵缓存默认上限 | 512 MB |
| OpenAPI | 187 path / 208 operation |

启动后内存占用主要来自:`_enriched_history_cache`(全量指标)+ `_live_agg_cache`(盘中递推状态)+ instruments + ETF/index enriched 懒加载。

### 2.5 Enriched 表:核心分析底座

Enriched 是 TickFlow 的"中间层":落盘只存 15 列窄表,运行时由 `compute_indicators` 即时计算完整 50+ 列(指标 + 信号 + JOIN)。这套设计让存储紧凑、回测与策略共用同一份指标定义、历史 schema 缺字段也能向后兼容。

落盘列(`ENRICHED_STORAGE_COLS`,`indicators/pipeline.py:87-96`):

```python
symbol, date,
open, high, low, close,          # 前复权
volume, amount,
raw_close, raw_high, raw_low,    # 不复权
turnover_rate,                    # 依赖当时 float_shares,不可回推
consecutive_limit_ups,            # 递推状态,需从历史 cum_sum
consecutive_limit_downs,
quote_ts,                         # 行情时间戳(ms)
```

运行时计算列(`ENRICHED_COLUMNS`,共 50+ 项,分类见 `pipeline.py:104-200`):

- 基础:`prev_close / change_pct / change_amount / amplitude`
- 均线:`ma5/10/20/30/60`、`ema5/10/20/30/60`
- MACD:`macd_dif/dea/hist`
- 布林:`boll_upper/lower`
- KDJ:`kdj_k/d/j`
- ATR:`atr_14`
- 量价:`vol_ma5/10`、`vol_ratio_5d`
- 极值:`high_60d / low_60d`
- 动量:`momentum_5/10/20/30/60d`
- 波动率:`annual_vol_20d`
- RSI:`rsi_6/14/24`
- 信号(布尔):MA 金叉/死叉、MACD 金叉/死叉、MA20/MA5/MA10 突破/跌破、N 日新高/新低、布林突破/跌破、放量、涨停、跌停、跌停翘板、炸板
- JOIN 列:`name / total_shares / float_shares`(由 repository 从 instruments 补)

**历史与实时口径差异(必须知道)**:

- 历史批量 `high_60d/low_60d` 用 **close** 的极值。
- 实时递推用 **high/low** 的极值。
- 盘中"新高/新低"与盘后重算可能不一致。这是后续做实时分析时最容易踩的坑。

**自定义信号**(`data/user_data/custom_signals/*.json`):由 `strategy/custom_signals.py` 编译为 `csg_<id>` Polars Expr。两套表达式:

- 全量路径 `allow_shift=True`:支持日期偏移(回看 60 日)。
- 盘中增量 `allow_shift=False`:跳过带偏移的信号(单日快照上 `.shift` 跨 symbol 不正确)。
- 盘中快照不支持 shift,带回看天数的信号会被跳过。

### 2.6 写入并发与原子性

`KlineRepository` 用两把锁:

- `_lock`:串行化所有 DuckDB 读(`execute_all/_one`),因为 DuckDB 单 connection 非线程安全。
- `_write_lock`:串行化 parquet 分区的读-改-写。实时轮询线程、手动 refresh、盘后管道可能并发 merge/flush 同一分区,无锁会互相覆盖。

写策略:**临时文件 + replace**,symbol/date 主键 merge-upsert,降低中断造成半文件的概率。`DataStore` 不做事务,但 `failed` 任务此前成功阶段可能已经写盘,因此 `failed ≠ 零副作用`。

### 2.7 启动时缓存预热(main.py:54-60)

```text
lifespan
  └─ repo.refresh_cache(background=True)
       ├─ _refresh_instruments()       # 同步,毫秒级
       ├─ _refresh_index_instruments() # 同步,毫秒级
       ├─ _refresh_etf_instruments()   # 同步,毫秒级
       └─ _start_enriched_warmup()     # daemon 线程,107 万行 compute_indicators
            └─ 完成后调 _on_warmup_done → app.state.indicators_ready = True
            └─ 完成后调 _on_refresh_done → 触发 matrix cache 预热
```

预热期间 `get_enriched_latest / get_live_agg` 返回空表,上层走优雅降级。这意味着**应用一启动就能服务请求,但指标数据可能要等 50 秒级才就绪**。涉及 enriched 的页面/API 需要处理这种空态。

---

## 3. 数据源插件化与接入路径

### 3.1 Provider 契约

`backend/app/data_providers/base.py` 定义 `MarketDataProvider` Protocol 与 `ProviderCapabilities` dataclass:

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    instruments: bool = False
    daily: bool = False
    adj_factor: bool = False
    minute: bool = False
    realtime: bool = False
    financial: bool = False

class MarketDataProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities
    def get_instruments(self, asset_type: AssetType) -> pl.DataFrame: ...
    def get_daily(self, symbols, start_time, end_time, asset_type) -> pl.DataFrame: ...
    def get_adj_factors(self, symbols, start_time, end_time, asset_type) -> pl.DataFrame: ...
    def get_minute(self, symbols, start_time, end_time, asset_type, freq, on_chunk_done) -> pl.DataFrame: ...
    def get_realtime(self, universes=None, symbols=None) -> pl.DataFrame: ...
```

上层服务通过 `get_provider()` 与 `provider_has_dataset(name, dataset)` 路由,**禁止**把 TickFlow SDK 调用硬编码到策略/监控/回测/API/前端。

### 3.2 TickFlow 客户端

| 文件 | 职责 |
| --- | --- |
| `backend/app/tickflow/client.py` | SDK 包装、端点路由(none→free-api,有 Key→api.tickflow.org) |
| `backend/app/tickflow/capabilities.py` | 按端点探测生成 `CapabilitySet`,缓存到 `.capabilities.json`;档位有 none/Free/Starter/Pro/Expert |
| `backend/app/tickflow/policy.py` | 探测顺序、UI 友好标签 |
| `backend/app/tickflow/rate_limits.py` | 令牌桶限流,按 `tiers.yaml` 配置 |
| `backend/app/tickflow/pools.py` | 标的池(CN_Equity_A 等)解析与缓存 |
| `backend/app/tickflow/scheduler.py` | 调度器装配 |
| `backend/app/tickflow/repository.py` | DataStore + KlineRepository |

能力检测**不是只读配置**,而是按端点探测后生成能力集合。档位名称只是 UI 标签,真正可用性以探测结果为准。

### 3.3 自定义 HTTP 数据源(YAML)

适合「外部 HTTP 服务负责取数和整理,本项目只把返回结果映射成内部标准字段」的场景。配置位置:`data/data_sources/*.yaml`。

支持的数据集与必填字段(`docs/custom-data-source.md`):

| 数据集 | 必填字段 |
| --- | --- |
| `daily` | symbol, date, open/high/low/close, volume, amount |
| `adj_factor` | symbol, trade_date, ex_factor |
| `realtime` | symbol, last_price, prev_close, open/high/low, volume(建议再加 amount/change_pct/turnover_rate) |
| `minute` | symbol, datetime, open/high/low/close, volume, amount |
| `financial` | symbol(其余由具体 table 约定) |

YAML 能力:

- GET/POST,`batch / rpm / timeout`(timeout 限 0-300 秒)
- `response_path` 点路径取数组
- `field_map` 映射上游字段
- `params / body` 与 `symbols/start/end/freq` 参数名
- 鉴权:`none / bearer / header / query`,token 只引用 `token_env` 环境变量
- 变换只接受受控表达式(乘除常数、`parse_date`、`parse_datetime`),**无 eval**

修改 YAML 后调用 `POST /api/settings/data-sources/reload` 热加载。

### 3.4 数据源插件(Python / Node)

适合复杂鉴权、分页、签名、多端点组合或特殊数据规范。插件作为独立模块放在 `backend/app/plugins/<name>/`,清单 `plugin.yaml`:

```yaml
name: my_source
display_name: "我的数据源"
runtime: python              # python | node | none
entry: app.plugins.my_source.provider:MyProvider
check: app.plugins.my_source.bridge:availability
datasets: [daily, adj_factor, minute, realtime]
install_hint: "pip install xxx"
```

Provider 实现要求(详见 `docs/plugin-development.md`):

- 普通类(无需继承基类),方法签名对齐 `GenericHTTPProvider`,使 services 层路由零改动。
- 必须有 `config.datasets` 字典,key 是数据集名;`provider_has_dataset` 据此判断。
- `check` 函数返回 `(bool, str)`,后端启动时调用;不可用时设置页灰显。
- `close()` 在 `load_all` 重建注册表时调用,用于清理资源。

现有参考:`backend/app/plugins/stocksdk/`(Node 型,subprocess 桥接 stock-sdk)。**Docker 默认不打包 stock-sdk**(`INCLUDE_STOCKSDK=0`),合规考虑。

### 3.5 扩展数据(`ext_data`)

扩展数据与行情 provider 是**两条不同链**:行情 provider 提供核心 OHLCV/因子/实时/财务;`ext_data` 提供可附着到标的的任意维度、标签和时间序列。

| 接入方式 | 入口 | 存储 |
| --- | --- | --- |
| CSV/XLSX 上传 | `services/ext_data.py` | 自动处理 UTF-8/GBK 与代码归一 |
| JSON ingest | API 直接写 rows | — |
| HTTP pull | `services/ext_pull.py` | URL/method/headers/params/response_path/field_map |
| 定时 pull | `PullScheduler` | 最短 60 秒,默认 1440 分钟 |

存储模式:

| 模式 | 路径 | 语义 |
| --- | --- | --- |
| snapshot | `data/ext_data/{id}/part.parquet` | 当前快照覆盖写 |
| timeseries | `data/ext_data/{id}/timeseries/date=YYYY-MM-DD/part.parquet` | 按日期分区 |

系统内置两个扩展预设(`services/ext_presets.py`):

| ID | 数据 | URL |
| --- | --- | --- |
| `ext_gn_ths` | 同花顺概念映射 | `https://shy313.com/api/plugins/market_flow/exports/ths-concepts` |
| `ext_hy_ths` | 同花顺行业映射 | `https://shy313.com/api/plugins/market_flow/exports/ths-industries` |

启动只创建配置,但配置默认 `enabled=true`,`PullScheduler` 启动后立即执行一次,然后按 1440 分钟循环。

### 3.6 数据源路由规则

来自 `PROJECT_ANALYSIS.md §4.1`:

| 数据集 | 路由规则 |
| --- | --- |
| 日 K | 用户选了 custom daily → 走自定义;否则走 TickFlow |
| 复权因子 | 可选 `same_as_daily` / 单独 custom / TickFlow |
| 实时 | TickFlow 档位模式 或 自定义全市场源 |
| 分钟 | 优先 custom;失败可回退 TickFlow |
| 财务 | custom provider 可绕过 TickFlow Expert 门槛;否则走 TickFlow |
| 指数/ETF 部分批量同步 | 仍依赖 TickFlow capability,未完全供应商无关 |

缺少能力时:**明确提示、跳过该功能或 fail-closed**;禁止静默换用错误数据或错误口径。

---

## 4. 数据流:盘后管道与实时热路径

### 4.1 盘后管道(`backend/app/jobs/daily_pipeline.py`)

默认调度(北京时间):

| 时间 | 任务 |
| --- | --- |
| 09:10 | 标的维表同步 |
| 15:02 | 盘口定版(depth_finalize) |
| 15:30 | 盘后管道(日 K + 除权 + enriched + 视图刷新) |
| 每小时 | 能力重探 |

`run_now` 阶段(`daily_pipeline.py:108-`):

```text
Step 0  sync_instruments        (2% → 8%)   同步维表
        resolve_universe        (9% → 10%)  解析标的池(有 batch 能力用 CN_Equity_A)
Step 1  sync_daily              (12% → 45%) 日 K:
          - override_start_date 强制 batch 拉取(数据修正)
          - 付费档 + 今天有数据 → 实时行情覆写
          - 有历史 → batch 补缺口
          - 无数据 → batch 拉首次 1 年
Step 1.5 sync_adj_factor                     增量除权因子
Step 2  halt-day filter + 前复权 OHLC
Step 3  compute_indicators + signals + limits + turnover
Step 4  narrow enriched Parquet 落盘
Step 5  optional index / ETF / minute / regime
Step 6  refresh DuckDB views + Polars caches
```

关键行为:

- 有 batch 能力时 universe 使用 `CN_Equity_A`(沪深京 A 股 ~5522 只);否则退化为 demo + watchlist + instruments,排除指数。
- 停牌过滤:`open=0 且 high=0`(有的数据源把停牌 close 填成前收)。
- 复权因子缺失时有短窗口兜底;前复权后的 OHLC 用于技术指标,`raw_*` 用于涨跌停。
- 首次或向历史左侧扩展时全量算 enriched;正常新增日期只重算增量和受影响标的。
- 任何阶段异常 → job 标 failed,但此前成功阶段可能已经写盘,因此 **failed ≠ 零副作用**。
- regime 默认关闭;财务默认只手动同步。

### 4.2 实时行情热路径(`backend/app/services/quote_service.py`)

```text
provider realtime snapshot
  → normalize decimal fields
  → QuoteService in-memory cache
  → merge raw daily candle
  → compute_enriched_today recursive update
  → refresh latest caches
  → evaluate monitor rules
  → SSE quotes_updated / strategy_alert
  → TanStack Query invalidation
```

轮询模式:

| 模式 | 范围 |
| --- | --- |
| none | 无 Key,不启动实时 |
| Free | 主要覆盖自选,数量受限(自选前 5 个标的) |
| paid / custom full_market | 全市场模式 |

交易时段按北京时间,告警只在连续竞价阶段触发,避免集合竞价噪声。详见 `app/market_time.py`。

### 4.3 缓存生命周期

写数据后必须同步检查(CONTRIBUTING.md §6.1):

1. 持久化文件(Parquet)
2. 内存缓存(Polars)
3. generation/version(矩阵)
4. SSE 事件
5. 前端 query invalidation

不能只保证"文件已写入"却继续返回旧内存对象。多步刷新优先**构建新快照后原子替换**,避免 UI 在刷新期间短暂变成空列表或零结果。

`KlineRepository` 暴露的刷新 API:

| 方法 | 何时用 |
| --- | --- |
| `refresh_cache(background=False)` | 盘后管道/手动刷新:全部同步,保证即时一致 |
| `refresh_cache(background=True)` | 启动时:instruments 同步,enriched 推 daemon |
| `clear_cache()` | 清数据/重置场景:无条件清空所有内存缓存 |

注意:`refresh_cache` 在磁盘无数据时会提前 return,导致内存里的旧缓存残留(这是"清数据后看板仍显示旧数据"的根因)。清数据场景必须调 `clear_cache()`。

---

## 5. 业务能力层

### 5.1 指标与信号(`backend/app/indicators/`)

| 文件 | 职责 |
| --- | --- |
| `pipeline.py` | `compute_indicators` / `compute_signals` / `compute_limit_signals` / `compute_enriched_today` / `run_pipeline` |
| `levels.py` | 11 类关键价位(筹码 POC、枢轴、极值、Boll、Keltner 短/中/长、ATR、缺口、Fibonacci、整数关) |

指标公式见 `PROJECT_ANALYSIS.md §7`。所有指标 100% Polars 表达式,`.over("symbol")` 每只标的独立计算。原子信号包括 MA/MACD 金叉死叉、N 日新高新低、布林突破、量比放量、涨停/跌停/炸板/跌停翘板、连续涨跌停。

历史与实时**不是同一实现**:

- 历史批量:直接 `rolling / EWM`。
- 实时路径:保留 EMA/MACD/KDJ/ATR/RSI/部分和/历史 close 等状态,递推更新。
- 历史 `high_60d/low_60d` 用 close 极值;实时用 high/low 极值。**语义差异可能让盘中"新高/新低"与盘后重算不一致**。

### 5.2 策略引擎(`backend/app/strategy/`)

| 文件 | 职责 |
| --- | --- |
| `engine.py` | `StrategyEngine`:加载策略文件、`StrategyDef`、`StrategyResult`、两阶段过滤(基础+策略)、评分排序 |
| `scoring.py` | 评分依赖分析与评分表达式 |
| `composite.py` | 组合策略(union / intersect,最多 8 个子策略) |
| `custom_signals.py` | 自定义信号加载与表达式编译 |
| `monitor.py` | `StrategyMonitorService` + `MonitorRuleEngine` |
| `monitor_rules.py` | 监控规则存储与迁移 |
| `intraday_signals.py` | 盘中分钟信号(VWAP 穿越、0 轴穿越) |
| `ai_generator.py` | AI 策略生成(AST 白名单校验) |
| `prompt_builder.py` / `prompts/` | 提示词模板 |
| `config.py` | 策略参数覆盖加载 |

策略执行顺序(`engine.py`,所有内置策略声明 `EXECUTION_BACKEND = matrix_native`):

1. 基础过滤(价格/市值/成交额/ST/上市天数/板块)
2. 策略布尔掩码(`filter_fn` 返回 `pl.Expr` 或 `filter_history_fn` 返回 `pl.DataFrame`)
3. 候选集横截面评分(min-max 归一化,`score = 100 × Σ(norm_feature × norm_weight)`)
4. 排序 + limit

策略目录由 `main.py:150-159` 装配:

```python
strategy_dirs = [
    Path("backend/app/strategy/builtin"),
    store.data_dir / "strategies" / "custom",
    store.data_dir / "strategies" / "ai",
    store.data_dir / "strategies" / "composite",
]
```

18 个内置策略见 `backend/app/strategy/builtin/`,每策略一个独立 `.py` 文件。完整策略开发规范见 `backend/app/strategy/prompts/strategy-guide.md`。

### 5.3 回测系统(`backend/app/backtest/`)

| 文件 | 职责 |
| --- | --- |
| `matrix.py` | 时间×标的 NumPy 矩阵,内存/磁盘 memmap 缓存 |
| `engine.py` | `BacktestEngine` |
| `strategy.py` | 策略回测撮合、`prewarm_matrix_cache` |
| `factor.py` | 因子回测(Rank IC / IR / 分层 / 多空) |
| `optimizer.py` | 参数优化(笛卡尔积,最多 2000 组合) |
| `walkforward.py` | Walk-Forward(固定日历天切窗) |
| `minute_trigger.py` | 分钟级触发(下一分钟开盘成交) |
| `numba_runtime.py` | Numba 加速 |
| `worker.py` | 独立 worker 进程 |

成交时序(默认严格 `open_t+1`):

- t 日信号只用 t 日已完成数据;最早 t+1 开盘成交。
- 可选 `close_t`、`signal_next_minute`(当前分钟确认,下一分钟开盘模拟成交)。
- A 股 T+1:当日买入仓位不能当日卖出。
- 同日退出后不立即重新入场。
- 一字涨停阻止买入,一字跌停阻止卖出。
- 停牌或非法价格阻止成交。
- 未成交退出进入 pending,后续交易日继续尝试。

默认成本:佣金各 0.02%、印花税卖出侧(默认 0)、滑点 5bps 两侧、初始资金 100 万、最大持仓 10、最大敞口 100%、100 股整数手、权重 equal 或 score。

两种统计模式:

- `position`:真实组合资金曲线,受现金/仓位数/权重/T+1 限制。
- `full`:每个候选视作独立 100 股交易统计,**不是**可直接执行的组合净值。

输出指标:总收益/年化/最大回撤/Sharpe/Sortino/Calmar/胜率/profit factor/持仓天数/单笔收益/交易明细/bootstrap Monte Carlo(种子 42,最多 1000 次,200 万单元保护)。

**已知实现缺口**(`PROJECT_ANALYSIS.md §11.8`):`FactorBacktestConfig` 的 `weight/fees_pct/slippage_bps` 会进入响应 config,但计算函数没有引用它们。当前因子组收益与多空收益没有真正扣除费用,也没有实现 `factor_weight`。

### 5.4 监控与通知(`backend/app/strategy/monitor*.py` + `backend/app/services/sector_monitor.py`)

监控类型:

| 类型 | 场景 |
| --- | --- |
| strategy | 策略结果或买卖信号变化 |
| signal | 原子或自定义信号 |
| price | 价格、涨跌幅等字段条件 |
| market | 涨跌停、连板等市场异动 |
| ladder | 连板梯队和封单 |
| sector | 概念/行业聚合(专用,通用 sector scope 当前 fail-closed) |

规则最多 8 条条件,支持 AND/OR;字段和信号走白名单;scope 可为指定 symbols 或 all。状态机:

- 第一次策略评估只建立 baseline,不报警。
- 后续产生 `buy/sell`、`pool_entry/pool_exit`。
- 同一批超过 5 条时合并。
- cooldown key 包括 `rule/symbol/event`,默认 3600 秒。
- 告警追加到 `data/user_data/alerts.jsonl`,保留 7 天且最多 5000 条。

盘中分钟信号:VWAP = 累计 amount / (累计 volume × 100),检测价格上穿/下穿;零轴使用昨收;只在出现新的完整分钟 bar 时判定。

通知出口:`notify_adapter.py` + `webhook_adapter.py` + `wecom_bot_service.py`:本机系统通知、飞书 Webhook(可签名)、企业微信 Webhook、企业微信智能机器人长连接。文案使用用户可理解的中文名称,不泄漏内部枚举名。

### 5.5 市场状态、轮动与关键价位

| 服务 | 文件 | 算法 |
| --- | --- | --- |
| Regime 市场状态 | `services/regime_builder.py` | profit(0.35) + speculation(0.25) + resilience(0.20) + trend(0.20),阈值 70/55/45/30 → strong/lean_strong/range/lean_weak/weak;回测按 T-1 mask 控制当日入场 |
| 市场总览 | `services/market_overview_builder.py` | 指数表现/上涨下跌家数/成交额/涨停跌停炸板连板/趋势活跃度/概念行业平均涨跌与领涨落后 |
| 情绪雷达 | 同上 | 六维等权:index/profit/money/speculation/resilience/mainline |
| RPS 轮动 | `services/rps_rotation.py` | 每日板块平均涨幅横截面排名,3-30 天矩阵;标签 persistent/rising/fading/institutional/hot-money(只是排名稳定性启发式,**不是**席位/资金流证据) |
| 概念轮动 | `services/concept_rotation_analyzer.py` | 概念涨幅轮动矩阵 + 龙头候选评分 |
| 关键价位 | `indicators/levels.py` | 11 类:筹码 POC、枢轴 P/R1-3/S1-3、extremes、Boll、Keltner 短/中/长、ATR、gaps、Fibonacci、round(见 PROJECT_ANALYSIS §12.4) |

筹码分布是**近似模型**:成交量假设在当日高低价间均匀分布,不是交易所逐笔真实筹码。

### 5.6 AI 分析

| 服务 | 文件 | 边界 |
| --- | --- | --- |
| AI provider | `services/ai_provider.py` | OpenAI 兼容 / Codex CLI;不支持 temperature 的端点命中 400 后去掉 temperature 重试 |
| 个股技术分析 | `services/stock_analyzer.py` | 加载 K 线尾部 + 轻量财务 + 关键价位 → LLM 输出 Markdown;**禁止**买卖/仓位/操作建议 |
| 财务分析 | `services/financial_analyzer.py` | 读取 metrics/income/balance_sheet/cash_flow/shares → LLM 财务质量报告;无 DCF/可比估值/盈利预测 |
| 市场复盘 | `services/market_recap.py` | 数据与 `/api/overview/market` 同源;用户 focus 走敏感交易措辞 blocklist,命中整段丢弃 |
| 轮动分析 | `services/concept_rotation_analyzer.py` | 先确定性排名标签,再交 LLM;只做客观描述,不给交易指令 |
| AI 报告归档 | `services/ai_reports.py` / `json_report_store.py` / `stock_reports.py` | `data/ai_cache/` |
| 截图 OCR 导入自选 | `services/watchlist_ocr/` | Pillow 预处理 → 本机 Tesseract OCR → 正则提六位代码 → instruments 校验 → 候选;**不调用云端 OCR** |

---

## 6. API 层

### 6.1 路由装配(`backend/app/main.py:336-361`)

```python
app.include_router(core_router)            # routes.py: /health, /api/capabilities
app.include_router(auth_api.router)        # auth.py
app.include_router(kline.router)
app.include_router(watchlist.router)
app.include_router(screener.router)
app.include_router(backtest.router)
app.include_router(intraday.router)        # SSE 行情与监控事件
app.include_router(indices.router)
app.include_router(overview.router)
app.include_router(regime.router)
app.include_router(analysis.router)
app.include_router(pipeline.router)
app.include_router(data.router)
app.include_router(ext_data.router)
app.include_router(financials.router)
app.include_router(stock_analysis.router)
app.include_router(chanlun.router)
app.include_router(chanlun_analysis.router)
app.include_router(market_lab.router)
app.include_router(market_recap.router)
app.include_router(settings_api.router)
app.include_router(strategy.router)
app.include_router(signals.router)
app.include_router(monitor_rules.router)
app.include_router(alerts.router)
app.include_router(rps.router)
```

OpenAPI 规模:187 path / 208 operation。Tag 分布大致:`settings 54 / strategies 18 / ext-data 17 / kline 15 / backtest 11 / financials 11 / screener 9 / watchlist 9 / monitor-rules 7` 等。

### 6.2 REST 与 SSE 分工

- **REST** 承担快照与任务启动。
- **SSE / 流式响应** 承担:
  - `/api/intraday/stream` 行情与监控事件
  - 参数优化和 walk-forward 进度
  - 个股/财务/市场复盘/轮动 AI 文本流
  - AI 策略生成流

### 6.3 能力门控与认证

- **能力门控**:业务代码用 `capset.require(Cap.X)` 断言能力,缺失抛 `CapabilityDenied`;`main.py:372-377` 注册 handler 返回 403(而非 500)。
- **访问认证中间件**(`main.py:302-332`):
  - 未设密码 + 本机/内网 → 放行
  - 未设密码 + 公网 → 403(防裸奔也防抢占)
  - 已设密码 → 检查 session,无效 401
  - 白名单:`/api/auth/*`、`/health`、`/openapi.json`、`/docs`、`/redoc`
- **CORS**:`allow_origins=["*"]` + `allow_credentials=False`(认证走 header 不依赖 cookie,故换取通配来源)。
- **SPA fallback**:生产期前端 dist 由 FastAPI 同源托管,`index.html` 禁止缓存(`Cache-Control: no-store`),assets 带 hash 长缓存。

### 6.4 自定义 URL 外连风险

自定义 HTTP 数据源、扩展数据测试、`detect-url`、手动拉取都会由后端访问用户提供的 URL,并允许跟随重定向。这是有意提供的服务器侧外连能力。**公网或多人部署必须先启用访问认证并限制谁能操作数据源设置**,否则会形成内网 URL 探测面。

---

## 7. 前端架构

### 7.1 路由(`frontend/src/router.tsx`)

所有页面 `lazy` 加载,避免首屏打包所有页面(ECharts/lightweight-charts/framer-motion 等重库)。`Layout` / `Onboarding` / `Auth` 为应用外壳,保持同步加载。

```text
/onboarding                     首次引导
/login                          登录
/                               Dashboard(OnboardingGuard 守卫)
├─ overview                     → 重定向到 /
├─ analysis                     → 重定向到 /settings?tab=ext-pages
├─ analysis/:menuId             AnalysisDetail(动态扩展页面)
├─ concept-analysis            ConceptAnalysis
├─ industry-analysis           IndustryAnalysis
├─ stock-analysis              StockAnalysis(chanlun view 兼容)
├─ review                       Review(AI 复盘)
├─ watchlist                   Watchlist
├─ screener                     Screener
├─ backtest                     Backtest
├─ financials                  Financials
├─ data                         Data
├─ monitor                     Monitor
├─ limit-ladder                 LimitUpLadder
├─ indices                     Indices
├─ regime                       Regime
├─ market-lab                   MarketLab
├─ branding                     Branding
├─ settings                     Settings
├─ dev                          Dev(隐藏,仅调试)
└─ 旧路由兼容重定向
```

`OnboardingGuard` 仅挂根路由;`settings.isLoading` 时本地有缓存就放行,避免切页整屏 logo 闪烁;查询出错或字段缺失时不拦截,宁可放行。

### 7.2 数据层(`frontend/src/lib/`)

| 文件 | 职责 |
| --- | --- |
| `api.ts` | 统一 fetch 客户端与类型契约;组件禁止散落请求地址 |
| `queryKeys.ts` | TanStack Query 查询键集中维护 |
| `useSharedQueries.ts` | 跨页面共享查询 |
| `useSharedMutations.ts` | 共享 mutation |
| `useQuoteStream.ts` | 全局唯一 EventSource |
| `useStrategyPool.ts` | 策略结果池 |
| `useFinancials.ts` | 财务数据 |
| `indicator-formulas.ts` / `indicator-params.ts` | 前端浏览器内指标计算(纯函数,参数可持久化) |
| `screener-columns.ts` / `watchlist-columns.ts` / `list-columns.ts` / `stock-table.ts` | 列定义 |
| `signals.ts` | 信号库 |
| `board.ts` | 板块(概念/行业) |
| `storage.ts` / `theme.ts` / `format.ts` / `cn.ts` / `colors.ts` | 工具 |
| `voiceBroadcast.ts` / `notificationSound.ts` / `monitorBadge.ts` | UI 反馈 |

TanStack Query 默认 `staleTime 5s`,窗口重新聚焦不自动 refetch。401 或未初始化密码由全局 QueryCache/Mutation 拦截跳转登录。`quotes_updated` 按用户页面设置精确 invalidation。开发时 Vite 把 `/api` 代理到 3018;生产时 FastAPI 同源托管 dist。

### 7.3 组件(`frontend/src/components/`)

| 类别 | 组件 |
| --- | --- |
| 图表 | `CandlestickChart` / `EChartsCandlestick` / `EChartsIntraday` / `StockDailyKChart` / `StockIntradayChart` |
| 个股 | `StockPanel` / `StockInfoBar` / `StockPreviewDialog` / `LastStockChip` |
| 表格 | `stock-table/` / `virtual-list/` / `ListColumnCustomizer` / `ColumnCustomizer` |
| 通用 | `Modal` / `Toast` / `AlertToast` / `EmptyState` / `WarmupBadge` / `SealedBadge` / `DatePicker` / `PageHeader` / `Logo` |
| 板块 | `DimensionMembersDialog` / `RpsRotationDialog` |
| 数据 | `data/` / `ext-data/` / `EndpointTestDialog` / `ExtDimensionAnalysis` |
| 财务 | `financials/` |
| 监控 | `monitor/` |
| 选股 | `screener/` |
| 信号 | `signals/` |
| 个股分析 | `stock-analysis/` |
| 自选导入 | `WatchlistImportDialog`(含 OCR) |
| 布局 | `Layout` |

新增交互必须覆盖加载、空数据、错误、禁用、无权限五种状态(CONTRIBUTING.md §7)。

---

## 8. 如何在底座之上做分析

后续大量开发会落在这层。下面是从轻到重的四种接入方式,优先级从上到下递减。

### 8.1 方式一:用现成 API + 前端组件

最轻。直接调 REST/SSE,在前端用现成图表组件渲染。适合一次性展示、不引入新数据契约的场景。

例:新加一个「北向资金 Top10」卡片 → 调 `/api/overview/market` 已有字段,在 Dashboard 用 `StockPanel` 渲染。无需改后端。

### 8.2 方式二:直接读 Parquet(Polars / DuckDB)

适合脚本、Notebook、批处理,不进 Web 服务。这是底座最容易复用的能力。

Polars 读 enriched 最新日:

```python
import polars as pl
df = pl.read_parquet("data/kline_daily_enriched/date=2026-08-23/part.parquet")
# 仅 15 列窄表;需要完整指标调用 app.indicators.pipeline.compute_indicators
from app.indicators.pipeline import compute_indicators, compute_signals
df_full = compute_signals(compute_indicators(df))
```

DuckDB 查视图(进程外也行,只要装了 DuckDB):

```sql
-- 启动后的进程内视图由 repository.py:154-202 注册
SELECT symbol, date, close, volume FROM kline_daily
WHERE date >= '2026-01-01' ORDER BY symbol, date;

SELECT symbol, close, consecutive_limit_ups FROM kline_enriched
WHERE date = (SELECT max(date) FROM kline_enriched);
```

注意:**DuckDB 视图只在 TickFlow 后端进程内有效**。进程外查询需要自己 `read_parquet('data/kline_daily/**/*.parquet', union_by_name=true)` 注册视图(参考 `repository.py:_register_views`)。

### 8.3 方式三:复用 `KlineRepository` 写后端 service + API

适合需要进 Web 服务、要被前端调用的分析。这是最推荐的方式,因为自动复用缓存、能力门控、SSE、认证。

典型路径:

```text
新增分析
  └─ backend/app/services/xxx_analyzer.py    (业务逻辑,读 repo + provider)
  └─ backend/app/api/xxx.py                  (FastAPI router,薄层)
  └─ backend/app/main.py: include_router      (装配)
  └─ frontend/src/lib/api.ts                 (类型 + 调用)
  └─ frontend/src/pages/Xxx.tsx              (页面)
  └─ frontend/src/router.tsx                 (路由注册)
  └─ frontend/src/components/Layout.tsx      (菜单项)
```

service 通过 `KlineRepository` 拿数据:

```python
from app.tickflow.repository import KlineRepository
repo = app.state.repo  # 或构造时注入

# 最新日 enriched(含指标,来自内存缓存,毫秒级)
df = repo.get_enriched_latest(asset_type="stock")

# 完整历史(含指标,~100 万行,来自内存缓存)
hist = repo.get_enriched_history(asset_type="stock")

# instruments
inst = repo.get_instruments()

# DuckDB SQL(线程安全)
rows = repo.execute_all("SELECT symbol, close FROM kline_enriched WHERE date = ?", [today])
```

### 8.4 方式四:接入扩展数据(`ext_data`)

适合「把外部任意维度/标签/时序数据附着到标的,与内置数据同台分析」。这是 TickFlow 为「不修改核心代码就能加数据」预留的官方通道。

详见 §3.5 与 `docs/custom-data-source.md` / `docs/plugin-development.md`。接入后扩展数据有独立存储,可通过 `services/ext_data.py` 查询,并可在「设置 → 扩展页面」配置成动态菜单。

---

## 9. 如何新增功能

### 9.1 新增数据源

按复杂度递增三选一:

| 方式 | 适合 | 步骤 |
| --- | --- | --- |
| 自定义 HTTP(YAML) | REST API 取数 | 写 `data/data_sources/xxx.yaml` → `POST /api/settings/data-sources/reload` → 设置页切换 → 测试端点 → 小范围同步核对 |
| 数据源插件(Python/Node) | 复杂鉴权/分页/签名 | 在 `backend/app/plugins/<name>/` 放 `plugin.yaml` + `provider.py`(对齐 `GenericHTTPProvider` 签名)+ 可选 `bridge.py`(`check` 函数)→ 重启 → 设置页启用 |
| 扩展数据(CSV/JSON/HTTP pull) | 任意维度附着到标的 | 设置页 → 扩展数据 → 上传/配置 HTTP pull → 选 snapshot/timeseries → 可选配扩展页面 |

**铁律**:Provider 必须把供应商字段、单位、日期、代码格式转换为内部标准 schema(`schemas.py`)。缺少能力时 fail-closed,不静默换口径。

### 9.2 新增策略

三种方式(strategy.md):

| 方式 | 入口 | 落盘位置 |
| --- | --- | --- |
| 自定义信号(不写代码) | 选股页 UI `字段+操作符+阈值` | `data/user_data/custom_signals/*.json`(编译为 `csg_*`) |
| AI 生成 | 选股页「AI 策略生成器」 | `data/strategies/ai/*.py`(`ai_` 前缀) |
| 自定义编写/代码迁移 | 选股页「自定义编写」或手放文件 | `data/strategies/custom/*.py`(`custom_` 前缀) |

内置策略(贡献者):在 `backend/app/strategy/builtin/` 参照现有文件实现 `StrategyDef`,引擎自动发现。AI 生成的策略**不会**落入 `builtin/`。

策略文件结构(详见 `backend/app/strategy/prompts/strategy-guide.md`):

| 部分 | 作用 |
| --- | --- |
| `META` | 策略元信息(名称、参数、方向等),用户可在 UI 调整 |
| `basic_filter(df, params)` | 模式 A:单日过滤,返回 `pl.Expr` |
| `filter_history(df, params)` | 模式 B:历史窗口过滤,返回 `pl.DataFrame`(配 `LOOKBACK_DAYS`) |
| `scoring` | 评分权重,总和 = 1.0 |
| `ENTRY_SIGNALS` / `EXIT_SIGNALS` | 进出场信号列(回测用) |

AI 生成策略的安全措施:`ast.parse` → `META literal_eval` → `import/call/dunder` 白名单检查 → reload。**剩余风险**:AST 规则是模式拦截不是进程隔离,`StrategyEngine` 最终通过 `importlib` 的 `exec_module` 在 Web 服务进程执行策略文件。注释明确把「受限子进程执行」列为后续 P0,**只应运行可信或人工复核后的策略代码**。

### 9.3 新增指标/信号

修改 `backend/app/indicators/pipeline.py`。流程:

1. 在 `ENRICHED_COLUMNS` 字典里声明新列名 + 含义(分类:存储/基础/ma/ema/macd/boll/kdj/atr/量价/极值/动量/波动率/rsi/信号/JOIN)。
2. 在 `compute_indicators` / `compute_signals` / `compute_limit_signals` 里加 Polars 表达式,**`.over("symbol")` 每只标的独立计算**。
3. 若是信号(布尔),还要在 `compute_signals` 注册原子信号名,使其可被监控规则字段白名单引用。
4. 如果指标依赖历史状态,需同步改 `_build_live_agg` 的递推状态列(否则盘中口径会与历史不一致)。
5. 落盘列(`ENRICHED_STORAGE_COLS`)默认**不动**:落盘窄表越宽,每行越大,历史重算越慢。新指标默认走「读取时即时计算」路径,历史 Parquet 用 `union_by_name` 向后兼容。
6. 加固定样本数值断言测试,覆盖历史边界和降级路径(见 `backend/tests/`)。
7. 重跑盘后管道或调 `POST /api/pipeline/run` 让新指标在 enriched 缓存中生效。

### 9.4 新增 API endpoint

```text
backend/app/api/xxx.py        # 新 router
  └─ @router.get("/api/xxx/yyy")
  └─ 用 app.state.repo / app.state.strategy_engine / services

backend/app/main.py          # app.include_router(xxx.router)
frontend/src/lib/api.ts       # 加 fetchXxxYyy + TS 类型
frontend/src/lib/queryKeys.ts # 加 query key
```

薄层原则(`CONTRIBUTING.md §2.3`):

- API 只做参数校验、响应映射、SSE 包装。
- 重计算放 service,数据访问放 repo,指标放 indicators,策略放 strategy。
- 禁止 API 直接读 provider 或本地文件,绕过标准化。
- 能力缺失用 `capset.require(Cap.X)`,自动返回 403。
- 涉及 SSE:复用 `sse-starlette`,前端 `useQuoteStream` 模式。

### 9.5 新增通知渠道

修改 `backend/app/services/notify_adapter.py` 与 `webhook_adapter.py`,在 `monitor_rules` 的「推送渠道」枚举里加新选项,同步前端设置页与监控规则编辑表单。文案使用用户可理解的中文名称,不泄漏内部枚举名。

---

## 10. 如何新增面板

「面板」= 一个出现在左侧菜单、有独立路由、有数据来源的页面。TickFlow 提供两条路径:代码路径与零代码路径。

### 10.1 代码路径(完全自定义页面)

完整步骤:

**步骤 1 - 后端 API**(按 §9.4):

```python
# backend/app/api/momentum_grid.py
from fastapi import APIRouter, Request
router = APIRouter(prefix="/api/momentum-grid", tags=["momentum-grid"])

@router.get("")
def get_momentum_grid(request: Request, date: str | None = None):
    repo = request.app.state.repo
    # 业务逻辑放 service,API 只做参数校验与响应映射
    ...
```

在 `main.py` 装配:`app.include_router(momentum_grid.router)`。

**步骤 2 - 前端 API 客户端**:

```typescript
// frontend/src/lib/api.ts
export type MomentumGridRow = { symbol: string; name: string; score: number; ... }
export async function fetchMomentumGrid(date?: string): Promise<MomentumGridRow[]> {
  const q = date ? `?date=${date}` : ''
  return apiFetch<MomentumGridRow[]>(`/api/momentum-grid${q}`)
}

// frontend/src/lib/queryKeys.ts
export const momentumGridKeys = {
  all: ['momentum-grid'] as const,
  byDate: (date: string) => ['momentum-grid', date] as const,
}
```

**步骤 3 - 前端页面**(放 `frontend/src/pages/MomentumGrid.tsx`,默认导出或命名导出均可,router.tsx 用 `.then(m => ({ default: m.MomentumGrid }))` 适配):

```tsx
import { useQuery } from '@tanstack/react-query'
import { fetchMomentumGrid, momentumGridKeys } from '@/lib/api'

export function MomentumGrid() {
  const { data, isLoading } = useQuery({
    queryKey: momentumGridKeys.byDate(today),
    queryFn: () => fetchMomentumGrid(today),
  })
  // 加载/空/错/禁用/无权限 五态覆盖
  ...
}
```

**步骤 4 - 路由注册**(`frontend/src/router.tsx`):

```tsx
const MomentumGrid = lazy(() => import('./pages/MomentumGrid').then(m => ({ default: m.MomentumGrid })))
// children 里加:
{ path: 'momentum-grid', element: <MomentumGrid /> },
```

**步骤 5 - 菜单集成**(`frontend/src/components/Layout.tsx` + `settings` 菜单设置):

- 加菜单项,设置页「菜单设置」可拖动排序、显示/隐藏、配数字徽标。
- 隐藏菜单只影响导航显示,不删除页面数据或功能配置。
- 数字徽标可用 `monitorBadge.ts` 模式接入。

**步骤 6 - 可选:能力门控**

页面若依赖某项能力(如分钟 K、财务),在前端用 `capability-labels.tsx` 的能力检测显示灰显或引导,后端用 `capset.require(Cap.X)` 返回 403。

### 10.2 零代码路径(扩展页面)

适合「已接入扩展数据,想快速搭一个分析页」的场景。完全在设置页配置,无需写代码:

1. 接入扩展数据(§9.1 方式三)。
2. 进入「设置 → 扩展页面」。
3. 选择数据集、展示字段、筛选项、页面名称。
4. 保存后自动出现在左侧菜单,路由为 `/analysis/:menuId`(router.tsx 已内置 `AnalysisDetail`)。
5. 可在「菜单设置」拖动排序。

**边界**:扩展页面只负责展示已接入数据,**不会自动**把字段加入所有策略。需要在策略中使用扩展字段时,应确认该字段已进入对应策略数据链路或 enriched 数据。详见 `操作说明书.md §20.5`。

### 10.3 面板开发 Checklist

新增面板前自检(CONTRIBUTING.md §7 + §9):

- [ ] 后端业务逻辑在 service,API 是薄层。
- [ ] 后端契约变化已同步前端 `lib/api.ts` 类型与调用方。
- [ ] TanStack Query 查询键进入 `queryKeys.ts`,含所有影响结果的维度(资产类型/日期/周期/参数)。
- [ ] 切换股票/ETF/日期/策略后不把上一上下文的缓存结果当作当前结果。
- [ ] 实时刷新保留上一份有效数据直到新数据就绪,避免列、计数、列表闪烁消失。
- [ ] 弹窗打开和关闭正确重置临时表单状态;新建态与编辑态分离。
- [ ] 跨页面行为(个股详情、成分股、概念标签)用共享组件,不在多页面复制交互。
- [ ] 加载、空数据、错误、禁用、无权限 五种状态全覆盖。
- [ ] 桌面与窄屏尺寸下检查文字截断、遮挡、滚动区域、弹窗可操作性。
- [ ] 不用前端补丁掩盖后端单位或契约错误;契约问题在数据边界修正。
- [ ] `pnpm build` 通过。

---

## 11. 扩展方向建议

基于现有底座,以下是符合项目设计哲学、不破坏插件化与数据契约的扩展方向。

### 11.1 数据层

| 方向 | 价值 | 落地点 |
| --- | --- | --- |
| 本地财务源 | 绕过 TickFlow Expert 门槛 | custom provider 声明 `financial` 数据集,已支持;详见 `docs/system-integration-and-local-financials.md` |
| 分钟回测扩展 | 支持更精细的入场/出场 | `backtest/minute_trigger.py` + matrix minute 列 |
| Tick 级数据 | 高频研究 | 新数据集 `tick`,需先定义 schema 与 provider 契约,不能直接塞进 enriched |
| 跨市场(港/美) | 多市场研究 | 复用 `asset_type` 维度;新加 `asset_type="us"` 等,路由与维表独立 |
| 基本面快照扩展 | 估值/股东/研报 | 用 `ext_data` snapshot 模式附着到标的 |

### 11.2 业务层

| 方向 | 价值 | 落地点 |
| --- | --- | --- |
| 形态识别 | 头肩、双顶/底、三角 | 新增独立 pattern detector,输出证据点作为 ECharts marker/range;不能当缠论官方结果 |
| 信号面板 | 统一 BSP / 技术指标 / 策略信号 | 复用现有信号体系,保留 `source` / 时间 / 是否确认;**不**新增第二套互相矛盾的信号仓库 |
| BSP 回测 | 缠论买卖点回测 | 把 BSP 映射为现有 Backtest 策略输入,复用成本/停牌/涨跌停约束 |
| 多股扫描 | 形态/BSP 全市场扫 | 把 BSP/形态字段接入现有 Screener,基于已落地快照,避免页面逐股抓取 |
| 回放 | K 线逐 bar 重算 | ECharts 窗口截断逐 bar 重算,防未来函数;回测结果仍以后端为准 |
| 多周期 | 周/月线 | 由日线聚合;分钟质量取决于所选源 |
| 风险预算/Kelly/蒙特卡洛 | 仓位与模拟 | 已接入 MarketLab(`docs/prototype-integration.md §4`);可扩展为独立页面 |

### 11.3 前端

| 方向 | 价值 | 落地点 |
| --- | --- | --- |
| 画线/截图/快捷键 | 用户标注 | 复用 `ChartPriceLine` / `ChartRange` + 浏览器导出;用户标注与算法图层分开存储 |
| 自定义仪表盘 | 个性化 | 复用 `data/`、`stock-table/`、`virtual-list/`,卡片可拖拽 |
| 移动端适配 | 随时查看 | 现已支持窄屏,可进一步做 PWA |

### 11.4 不建议扩展的方向

- **不**对标同花顺 / 通达信(README 明确声明)。
- **不**内置 AI 荐股 / 涨停预测(README 明确声明)。
- **不**在未经验证的免费上游之上制造"可用"实现(`docs/prototype-integration.md §7`)。
- **不**为假设的未来需求设计抽象(CONTRIBUTING.md §1.2)。

---

## 12. 关键源码索引

按主题快速定位:

| 主题 | 文件 |
| --- | --- |
| 应用装配 | `backend/app/main.py` |
| 配置 | `backend/app/config.py`、`.env.example`、`docs/configuration.md` |
| TickFlow 客户端与能力 | `backend/app/tickflow/client.py`、`capabilities.py`、`policy.py`、`rate_limits.py`、`pools.py`、`scheduler.py` |
| 档位定义 | `tiers.yaml`(业务代码不读,只读运行时探测出的 CapabilitySet) |
| Provider 契约 | `backend/app/data_providers/base.py`、`schemas.py`、`registry.py`、`normalizer.py` |
| TickFlow provider | `backend/app/data_providers/tickflow_provider.py` |
| 自定义 HTTP | `backend/app/data_providers/custom/config.py`、`provider.py`、`mapper.py`、`loader.py`、`docs/custom-data-source.md` |
| stock-sdk 插件 | `backend/app/plugins/stocksdk/`、`docs/plugin-development.md` |
| 盘后管道 | `backend/app/jobs/daily_pipeline.py` |
| 仓库与缓存 | `backend/app/tickflow/repository.py`、`backend/app/parquet.py` |
| 指标与信号 | `backend/app/indicators/pipeline.py`、`levels.py` |
| 涨跌停 | `backend/app/price_limits.py` |
| 历史股本 | `backend/app/share_capital.py` |
| 策略引擎 | `backend/app/strategy/engine.py`、`scoring.py`、`composite.py`、`custom_signals.py`、`config.py` |
| 监控 | `backend/app/strategy/monitor.py`、`monitor_rules.py`、`intraday_signals.py`、`backend/app/services/sector_monitor.py` |
| 18 个内置策略 | `backend/app/strategy/builtin/` |
| 回测矩阵与撮合 | `backend/app/backtest/matrix.py`、`engine.py`、`strategy.py`、`minute_trigger.py`、`numba_runtime.py` |
| 参数优化与步进 | `backend/app/backtest/optimizer.py`、`walkforward.py`、`worker.py` |
| 因子回测 | `backend/app/backtest/factor.py` |
| 市场状态 | `backend/app/services/regime_builder.py` |
| 市场总览 | `backend/app/services/market_overview_builder.py` |
| 轮动 | `backend/app/services/rps_rotation.py`、`concept_rotation_analyzer.py` |
| 关键价位 | `backend/app/indicators/levels.py` |
| 实时行情 | `backend/app/services/quote_service.py` |
| AI provider | `backend/app/services/ai_provider.py` |
| 个股/财务/复盘 AI | `backend/app/services/stock_analyzer.py`、`financial_analyzer.py`、`market_recap.py`、`market_recap_reports.py`、`stock_reports.py`、`ai_reports.py` |
| 通知 | `backend/app/services/notify_adapter.py`、`webhook_adapter.py`、`wecom_bot_service.py` |
| 五档盘口 | `backend/app/services/depth_service.py` |
| 自选截图 OCR | `backend/app/services/watchlist_ocr/` |
| 扩展数据 | `backend/app/services/ext_data.py`、`ext_pull.py`、`ext_presets.py`、`backend/app/api/ext_data.py` |
| 同步 | `backend/app/services/instrument_sync.py`、`kline_sync.py`、`index_sync.py`、`financial_sync.py`、`repair_daily.py`、`extend_history.py` |
| API 汇总 | `backend/app/api/`(`routes.py` 装配 health/capabilities,其余各业务 router) |
| 缠论 | `backend/app/chanlun/`、`backend/app/api/chanlun.py`、`chanlun_analysis.py` |
| 市场实验室 | `backend/app/services/market_lab.py`、`backend/app/api/market_lab.py` |
| 前端路由 | `frontend/src/router.tsx` |
| 前端 API/SSE | `frontend/src/lib/api.ts`、`useQuoteStream.ts` |
| 前端查询键 | `frontend/src/lib/queryKeys.ts` |
| 前端布局 | `frontend/src/components/Layout.tsx` |
| 开发脚本 | `dev.ps1`(Windows)、`dev.sh`(*nix) |
| 部署 | `Dockerfile`、`docker-compose.yml`、`docs/deployment.md` |
| 贡献与审查规范 | `CONTRIBUTING.md` |
| AI 开发入口 | `AGENTS.md` |
| 独立审计结论 | `PROJECT_ANALYSIS.md` |
| 用户操作流程 | `操作说明书.md` |

---

## 13. 验证与开发流程

### 13.1 启动

```powershell
# Windows
cd prototypes\tickflow
cp .env.example .env       # 按需填 TICKFLOW_API_KEY(留空 = None 模式)
.\dev.ps1
```

```bash
# macOS / Linux
./dev.sh
```

`dev.ps1` / `dev.sh` 自动检查/安装依赖、释放端口、同时起前后端。后端 → http://localhost:3018,前端 → http://localhost:3011。

**已知安装缺陷**(`PROJECT_ANALYSIS.md §2.3`):`backend/pyproject.toml` 的 `readme = "../README.md"` 位于 backend 目录之外,Hatchling 拒绝,`uv sync` 会失败。绕过方式:`uv sync --no-install-project --extra dev` 安装依赖后直接从 backend 工作目录运行 `app` 包。如需长期使用,建议把 README 复制或链接进 backend,再让 pyproject 指向 backend 内部文件,并重建 `uv.lock`。

### 13.2 验证命令(CONTRIBUTING.md §9)

```bash
# 后端定向测试
cd backend
uv run pytest tests/path/to/test_x.py -q
uv run ruff check app/path.py tests/path.py

# 前端构建
cd frontend
pnpm build

# 提交前检查
git diff --check
```

验证矩阵(最低要求,不是上限):

| 改动类型 | 最低验证 |
| --- | --- |
| 后端纯函数/规则/bug 修复 | 对应定向 pytest,含复现用例和边界用例 |
| API 契约 | service 测试 + API 测试;成功/无数据/错误响应 |
| 数据源或插件 | provider 契约测试、缺能力、空数据、字段/单位标准化 |
| 指标/复权/换手率/涨跌停 | 固定样本数值断言,覆盖历史边界和降级路径 |
| 策略或监控 | 参数变更、缓存失效、资产切换、重启/并发 |
| 回测 | 信号日与成交日、T+1、费用、滑点、不可成交、数据缺口 |
| 缓存或性能 | 命中/失效测试、并发快照测试;必要时附前后基准 |
| 前端组件或页面 | `pnpm build`,并手工检查加载/空/错/切换/实时刷新 |
| 前后端契约同时变化 | 后端定向测试 + 前端构建 + 对应页面联调 |
| 文件/Docker/跨平台 | 正常路径、权限/能力缺失、目标不可用的失败路径 |

注意:

- 后端至少运行受影响模块的测试,不应只运行新加的单个测试。
- 新增文件和本次改动不得引入 Ruff 告警;不要为清理历史告警而在功能 PR 中全仓格式化。
- 前端任何 TypeScript/组件/样式/API 类型改动至少执行一次 `pnpm build`。
- 提交前必须运行 `git diff --check`,并检查最终 diff 不含调试代码和无关文件。
- 前端 `package.json` 声明 `pnpm lint` 但 devDependencies 没有 eslint,该命令无法执行(`PROJECT_ANALYSIS.md §16.1` 低严重度问题)。
- 后端全仓 Ruff 当前有 1,257 项历史告警,仓库不满足自身全量 Ruff 配置,不能把 lint 表述为"通过"。

### 13.3 PR 复审流程(CONTRIBUTING.md §11)

1. 确认问题(测试复现旧行为)
2. 检查边界(代码在正确模块,无反向依赖/平行实现/API 层重计算)
3. 核对数据契约(单位/复权/日期/时区/资产类型/空值/排序方向)
4. 核对插件化(是否依赖 provider 能力,非 TickFlow 数据源能否工作或明确降级)
5. 跟踪状态变化(写入→持久化→缓存→generation→SSE→前端查询失效)
6. 检查兼容性(历史配置/旧策略 JSON/旧 Parquet schema/缺字段数据)
7. 检查性能和并发(实时/列表/全量扫描热路径,锁和原子替换)
8. 检查失败路径(网络失败/无权限/空数据/能力缺失/部分写入)
9. 评估测试质量(测试必须断言业务结果,覆盖负例和边界,不能只断言 200)
10. 检查最终 diff(逐项确认必要性,排除无关格式化/敏感信息/临时文件)
11. 给出结论(可合并/修改后合并/不建议合并)

问题严重级别:`P0`(数据破坏/安全/严重错误交易结果,禁止合并)、`P1`(核心流程不可用/错误金融口径/未来函数/广泛回归,禁止合并)、`P2`(明确功能错误/兼容性/性能退化,修改后合并)、`P3`(维护性/局部体验/文档/测试建议,可不阻断)。

---

## 14. 已知风险与开发约束

### 14.1 安装与构建

- 标准 `uv sync` 因 README 越界失败(Hatchling)。
- `backend/uv.lock` 落后于 `pyproject.toml`:锁文件项目版本仍为 0.1.83,缺 pypinyin;不能把 `uv.lock` 当作当前依赖声明的完整镜像。
- README 声称 Docker 已内置 stock-sdk,但 Dockerfile 和 `docs/deployment.md` 明确默认 `INCLUDE_STOCKSDK=0`;实际默认镜像不含该插件依赖。

### 14.2 算法与描述偏差(改动前必看)

- **断板反包策略**:META description 写"连板>=2 后断板 1-2 天,出现放量反包",但 `compute_signals` 没有引用历史断板或前序连板,只看当日 `limit_up_locked`、`vol_ratio_5d`、`change_pct`。当前算法更接近"当日涨停且放量",不是严格的断板反包。
- **连板接力策略**:`ENTRY_SIGNALS` 写 `signal_limit_up`,但实际 entry 只检查 `change_pct` 和 `consecutive_limit_ups`,没有与当日 `limit_up_locked` 做 AND。
- **`high_60d/low_60d`**:历史用 close 极值,实时用 high/low 极值,口径不一致,盘中与盘后信号可能翻转。
- **因子回测**:`weight/fees_pct/slippage_bps` 进入响应 config 但计算函数未引用;UI 给出已配置的错觉,收益可能偏高。
- **enriched 列数**:源码注释称 14 列,实际 `ENRICHED_STORAGE_COLS` 有 15 列(含 `quote_ts`)。
- **关键价位**:README 称 9 类,源码 `LEVEL_TYPES` 实际有 11 类。

### 14.3 安全

- **AI/用户 Python 策略非进程沙箱**:AST 规则是模式拦截,不是进程隔离;`StrategyEngine` 最终通过 `importlib` 的 `exec_module` 在 Web 服务进程执行策略文件。源码注释明确把"受限子进程执行"列为后续 P0。**只应运行可信或人工复核后的策略代码**。
- **自定义 URL 外连**:自定义 HTTP 数据源、扩展数据测试、`detect-url`、手动拉取都会由后端访问用户提供的 URL,并允许跟随重定向。公网或多人部署必须启用访问认证并限制谁能操作数据源设置,否则形成内网 URL 探测面。
- **AI 数据边界**:AI 分析会把行情、财务、策略描述、用户输入发送给所配置的模型服务。涉及私有策略或敏感数据时,应使用可信服务并确认其存储政策。

### 14.4 数据与单位

- 改动跨边界映射时必须增加单位测试。**禁止**用"数值小于 1 就乘 100"一类启发式转换,这会掩盖真实数据错误。
- enriched 的 `open/high/low/close` 为前复权;`raw_close/raw_high/raw_low` 为不复权;`raw_open` **不存在**(历史已如此)。涨跌停判断使用 `raw_*`。技术指标和收益序列使用哪种价格必须与现有指标定义一致,不得在同一公式中混用。
- 窗口、前 N 日、批次回算均按实际交易日,不得用自然日直接替代。
- A 股交易时段统一按北京时间;服务器时区不能成为业务逻辑的隐式输入。
- 分钟 K 的股票、ETF、指数分开存储和路由,不得仅凭代码格式猜测资产类型。
- 历史换手率优先使用公告日不晚于目标交易日的历史股本;缺少时才降级到最新维表股本。当日维表、财务公告日、报表期是不同概念,不能用报表期提前泄露尚未公告的数据。

### 14.5 方法论风险(改动涉及指标/策略/回测时牢记)

- 18 个策略都是规则与横截面排名,**不是**机器学习预测模型。
- 策略 `score` 是候选集内相对分,**不是**收益概率。
- 多数策略没有 take-profit,退出主要靠 MA、MACD、止损或最长持有期。
- market regime 的阈值样本与校准脚本未随仓库提供;"2022-2026 p15/p85"只能视作作者声明。
- RPS 的"机构/游资"是排名稳定性标签,**不是**资金身份识别。
- 筹码分布使用区间均匀成交假设,**不是**交易所逐笔真实筹码。
- 回测虽处理 T+1/费用/滑点/涨跌停,但仍**没有**盘口冲击、排队成交、容量、真实撮合延迟和数据修订。
- 没有用真实样本独立复算任何策略收益,因此本指南不对 alpha、胜率或未来表现背书。

### 14.6 仓库协同(`docs/system-integration-and-local-financials.md`)

`quantall` 仓库内四个相关项目的源码边界:

| 项目 | 关系 |
| --- | --- |
| `prototypes/tickflow` | 本文档所在项目;A 股研究工作台 |
| `apps/quantx` | 每日市场数据采集、统一复盘报告、A 股深度研究 |
| `apps/quants` | 本地 A 股选股、策略分析、信号追踪(内部包名 `ppgu`) |
| `apps/quantt` | K 线训练、复盘、AI 点评 Web 应用 |

四者的源码边界、版本化 sidecar 契约、主线与形态交集评分、真实交易反馈回路详见 `docs/system-integration-and-local-financials.md`。后续在 TickFlow 之上做扩展时,如需与这三个兄弟应用协同,务必先读该文档,不要直接读取或写入它们的生产数据库。

---

## 附录:本文档的写作依据

本文档基于以下源码事实撰写,不引用未经验证的声明:

- 源码静态追踪:`backend/app/` 全模块、`frontend/src/` 主要文件、`docs/` 全部文档。
- `PROJECT_ANALYSIS.md`(2026-08-23 审计,提交 `9b9538a`,版本 0.1.88):给出无 API Key 启动、API 探测、Playwright 渲染、后端测试与前端构建验证结论。
- `CONTRIBUTING.md`、`AGENTS.md`、`操作说明书.md`、`docs/` 下 13 个文档。
- `data/` 目录实际结构(运行后)。

未覆盖的范围(改动前需独立验证):

- TickFlow 私有服务端如何生产、清洗、授权底层行情。
- `shy313.com` 概念/行业接口上游抓取、更新时间和授权链。
- 硬编码 regime 阈值的原始训练/校准样本。
- `stock-sdk` 第三方接口长期稳定性与正式授权。
- 在全 A 股多年数据上的真实峰值内存、回测耗时和告警延迟。

本文档不构成投资建议。TickFlow Stock Panel 用于数据分析和策略研究,历史表现不代表未来收益,实盘决策及其风险由使用者自行承担。
