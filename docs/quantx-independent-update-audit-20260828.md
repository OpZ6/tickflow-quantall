# QuantX 独立更新与渐进收口审计（2026-08-28）

> 文档角色：当前代码与本地数据的审计快照，不是架构权威入口。当前契约仍以 [`architecture.md`](architecture.md)、[`data-foundation.md`](data-foundation.md) 和 [`quantx-data-pipeline.md`](quantx-data-pipeline.md) 为准。
>
> 审计范围：只审计 QuantX 背后的确定性数据表格、采集、处理、存储、API、React 展示和调度；不包含 LLM 分析、Review Editor、研究报告、知识反思、HTML/PDF/PNG 报告流水线。

> **完成后增量结论（2026-08-28 17:05 CST）：** 下文第 1-12 节保留的是改造前审计快照，其中“未实证”“部分完成”和 958/962 数字不得再作为当前状态引用。后续执行已完成 20260828 无同日快照联网发布（job `d5e4c8c7d0`、run `20260828-f3cc36bd88fb`），12 个外部来源均为 fresh，13/13 当日事实已发布，单日 V2、多日和 catalog 可读取。公开 V1 JSON 回退已关闭；数据页已提供来源、事实、质量、血缘与刷新操作。纳入新日期后覆盖现为 972/975，剩余 3 个缺口均有 accepted-gap 原因，未接受缺口为 0。当前结论是：**TickFlow-Quantall 已通过独立更新实证，仍允许预期的第三方数据服务和本仓库运行时依赖，不存在旧 QuantX 目录或服务依赖。** 完整执行证据见 [`quantx-single-day-canonical-view-plan.md`](quantx-single-day-canonical-view-plan.md)。

## 1. 结论

不能把当前状态简单表述为“已经完全独立更新”。更准确的结论是：

| 能力 | 结论 | 当前证据 |
| --- | --- | --- |
| 旧 QuantX/retired 目录独立 | **通过** | 代码、配置和运行时模块均未引用旧目录；旧服务停止、旧目录主体移走后，前后端及单日/多日 API 仍返回 200 |
| 单日/多日读取与展示独立 | **通过** | `/api/quantx/review/20260827/data`、`/api/quantx-data/multiday/20260827` 可从本仓库数据读取 |
| 本地快照离线重算独立 | **通过** | pipeline、快照、事实发布和重算均位于 `D:\tickflow-quantall`；相关测试覆盖无网络重算和移除来源文件后的读取 |
| 主行情完成后自动触发 QuantX | **通过** | 手动 pipeline 与盘后 scheduler 都在主行情成功后调用同仓库 QuantX scheduler；17:30 另有恢复任务 |
| 当前进程全新联网采集 | **未通过验收/尚未实证** | 最新 20260827 发布的 12 个网络来源全部复用了本地快照；当前后端进程没有继承用户级 `TUSHARE_TOKEN` |
| Market Facts 统一权威底座 | **部分完成** | 多日能力已直接读 13 类事实；单日富图表以事实覆盖兼容 JSON，但仍保留展示字段和少量未正式分类字段 |
| 质量、血缘、刷新可观测 | **部分完成** | manifest、run/status、quality、source health API 已有；QuantX 页面尚未统一展示来源、覆盖率、降级原因和重试入口 |

因此，当前仓库已经实现了**文件系统和业务流水线上的独立性**，但“任何时候点击更新都能从外网完整采集新交易日”的运行验收尚未完成。独立不等于没有上游：Tushare、PyWencai、Eastmoney 等仍是预期的外部数据服务；真正应禁止的是读取旧项目文件、调用旧项目服务或把旧报告当数据源，目前没有发现这三类依赖。

## 2. 独立性的判定口径

本审计将依赖分为三类，避免混淆：

1. **禁止的遗留依赖**：旧 `apps/quantx`、retired/prototype、外部 QuantX 报告目录、旧 8766/3021/3031 服务或其生成文件。当前未发现。
2. **允许的系统运行时**：Python 基础解释器、仓库内 `.venv`、Windows Microsoft Edge、操作系统环境变量。它们不属于旧 QuantX 项目，但必须纳入部署清单。
3. **允许的上游数据服务**：Tushare、PyWencai、Eastmoney、Legulegu 等。QuantX 可以独立编排、存储和重算这些数据，但无法在断网或上游失效时凭空采集新事实。

“完整独立更新”必须同时满足：

- 所有业务代码、配置、暂存、发布和读取路径位于当前仓库或明确配置的 TickFlow `data_dir`；
- 不读取旧报告目录，不调用旧 QuantX 服务；
- 新交易日可以在没有同日快照的情况下完成必需来源采集；
- 原始证据、标准事实、兼容产物、manifest 和运行状态同时发布；
- 页面读取新的发布版本，并能显示降级、缺口和来源血缘；
- 失败不覆盖上一份有效发布，重试和重算可恢复。

前两项及发布事务已经满足；第三项在当前进程尚未通过真实新日期验收；第五项的页面可观测仍不完整。

## 3. 真实端到端调用链

```text
手动 POST /api/pipeline/run
或盘后 DailyPipeline scheduler
        │
        ▼
TickFlow 主行情/指数/enriched 更新
        │ 仅主任务成功后
        ▼
daily_pipeline._run_quantx_after_pipeline()
        │ data_root = repo.store.data_dir
        ▼
quantx_data.scheduler.run_scheduled(data_root)
        │ 交易日由 MarketFactRepository + 本地行情分区判断
        ▼
quantx_data.pipeline.run_pipeline(data_root, trade_date)
        ├─ SourceManager -> 12 个来源 adapter
        ├─ SourceSnapshotStore -> 原始来源快照
        ├─ normalize/compute/trends -> 确定性表格
        ├─ 13 类 Market Facts -> staging + 原子发布
        ├─ review_data.json -> 单日富图表兼容/展示缓存
        └─ multiday_snapshot.json + catalog -> 多日展示
        │
        ├─ /api/quantx/review/{date}/data -> QuantXReviewRepository
        │      └─ 先载入展示骨架，再用 Market Facts/Kline 覆盖权威字段
        └─ /api/quantx-data/multiday/{date}
               └─ 直接从 MarketFactRepository 计算
```

### 3.1 配置和数据根

- `backend/app/config.py` 负责 `settings.data_dir`。默认值解析到当前项目的 `data/`；相对覆盖值也相对当前项目根解析。
- `backend/app/main.py` 使用同一个 `DataStore`/`KlineRepository`，并以 `MarketFactRepository(store.data_dir)` 初始化市场事实仓库。
- QuantX API 的根目录由 `request.app.state.repo.store.data_dir / "quantx"` 派生，不硬编码旧路径。
- `backend/app/quantx_data/pipeline.py` 首先对 `data_root` 执行 `resolve()`，然后只在其下创建 `quantx`、source snapshots、staging、run 和发布目录。

### 3.2 采集层

`backend/app/quantx_data/collectors.py` 注册 12 个来源：

| 来源 | 角色 | 必需性 |
| --- | --- | --- |
| Tushare | 行情、交易日历、两融等基础事实 | 必需 |
| PyWencai | 涨跌停、题材、候选等结构化查询 | 必需 |
| AKShare | 补充市场/板块数据 | 可选 |
| THS Hot | 同花顺热榜/题材证据 | 可选 |
| Zhangtingke | 连板梯队证据 | 可选 |
| Zhangtingjun | 涨停相关补充 | 可选 |
| Duanxianxia | 短线情绪补充 | 可选 |
| DeepQ | 题材补充 | 可选 |
| Legulegu | 申万行业均线宽度 | 可选 |
| QuickTiny | 需登录态的补充证据 | 可选 |
| Dabanke | 需登录态的打板补充 | 可选 |
| Sector Fund Flow S4 | 行业资金流 | 可选 |

所有来源由 `SourceManager` 统一执行、分类错误、记录请求次数、决定复用同日快照或联网刷新。pipeline、Repository、API 和前端没有直接 import 单个 scraper。`legacy_scrapers` 仍是真实采集适配器的实现位置，但只允许被 `collectors.py`/`SourceManager` 包装调用；这里的 “legacy” 是实现来源，不代表运行时调用旧目录。

### 3.3 存储与发布层

同一 `data_root` 内的数据分为四类：

| 层 | 典型位置 | 权威性和用途 |
| --- | --- | --- |
| TickFlow 行情 | `data/kline_*`、指数和维表分区 | OHLCV、指数及主行情权威数据 |
| 原始来源快照 | SourceSnapshotStore 管理的分区 | 可追溯证据、同日复用、离线重算 |
| Market Facts | 13 类按交易日 Parquet 分区 | 可复用市场事实的权威来源 |
| QuantX 日期发布 | `data/quantx/YYYYMMDD/` | 原始/规范化副本、结构化表、manifest、状态和展示缓存 |

发布先进入 staging，事实批次和 QuantX 日期产物验证成功后再提交；失败时保留上一份有效发布。`_data_manifest.json` 记录来源状态、哈希、行数、产物和降级警告，`_pipeline_status.json` 记录阶段状态。这个机制已经具备失败隔离和重放基础。

### 3.4 处理层

QuantX pipeline 在采集后执行：

1. 原始响应持久化；
2. 交易日、证券代码和字段标准化；
3. 读取同仓库 `kline_daily_enriched` 聚合；
4. 计算单日宽度、成交、涨跌停、题材、行业、资金流、候选和市场信号；
5. 构建 13 类标准事实批次；
6. 质量校验和来源/产物对账；
7. 原子发布事实与 QuantX 日期目录；
8. 由事实仓库刷新多日快照和 catalog。

整个处理过程是确定性的，`backend/app/quantx_data/__init__.py` 明确不读取 `apps/quantx/output`，也不生成或消费 LLM 分析。

### 3.5 API 层

现有 API 已覆盖：

- 新运行、恢复、离线重算、单来源重试；
- 运行状态、质量结果和 catalog；
- 单日 overview/梯队/题材/情绪/资金流/候选结构表；
- 单日富图表聚合接口；
- 多日聚合接口；
- 数据源注册、路由、凭据状态和健康信息。

`GET` catalog 为只读扫描；全量重建必须显式 `POST`。主数据更新接口会把 QuantX 结果纳入同一个任务状态，不能在 QuantX 发布失败时把整次更新伪报为完整成功。

### 3.6 前端层

- `/quantx/:date` 通过 `QuantXReviewRepository` 聚合后的单日接口渲染富图表。
- `/quantx` 多日驾驶舱读取 catalog 和 multiday API；多日计算已直接依赖 Market Facts。
- QuantX 页面目前没有使用已经存在的 run/recompute/source retry API，也没有完整展示 `data_foundation`、来源降级和 reconciliation。
- 数据源管理页可以查看注册、路由和最近健康，但它与 QuantX 发布状态仍是两个入口。

### 3.7 调度层

- 手动 `POST /api/pipeline/run`：先运行主行情，再运行 QuantX，随后刷新 Repository/cache。
- 自动盘后任务：主 pipeline 成功后依赖触发 QuantX；主任务失败时不提前计算 QuantX。
- 工作日 17:30（Asia/Shanghai）：保留 QuantX 恢复任务，用于补偿主盘后触发遗漏。
- 交易日判断优先使用 `MarketFactRepository` 交易日历和本地 TickFlow 行情分区，不依赖旧项目的交易日服务。

## 4. 目录外和外部依赖审计

### 4.1 未发现的旧项目依赖

对 `backend/app`、`frontend/src`、`scripts` 和 `.github` 的静态搜索未发现：

- `D:\quantall\apps\quantx`、旧 prototype、retired、restore drill 或 backup 路径；
- 旧 QuantX HTML 报告、Review Editor 输出或旧日期报告目录读取；
- 3021、3031、8766 等旧 QuantX 服务地址；
- API、Repository、Service、pipeline 或前端直接 import 具体 scraper。

唯一关于 `apps/quantx/output` 的命中是 `backend/app/quantx_data/__init__.py` 中“永不读取”的边界说明。

运行时检查显示：

- Python 可执行文件为 `D:\tickflow-quantall\backend\.venv\Scripts\python.exe`；
- QuantX package、pipeline、collector 和 scraper 模块均解析到 `D:\tickflow-quantall\backend\app\quantx_data\...`；
- 数据根为 `D:\tickflow-quantall\data`；
- 旧目录主体移走且旧 Python 服务停止后，3011、3018、单日和多日接口仍正常。

本机另有一个任务外的 8766 Python 服务，但当前 TickFlow 源码和配置没有引用它，不能据此判定为依赖。

### 4.2 仍然存在的正常外部运行时

| 依赖 | 类型 | 是否旧项目依赖 | 说明 |
| --- | --- | --- | --- |
| 系统 Python 基础安装 | 运行时 | 否 | 仓库 `.venv` 仍基于系统 Python 标准库 |
| `backend/.venv` | 仓库内依赖 | 否 | Tushare、AKShare、PyWencai、Playwright 等由 lockfile 安装 |
| Microsoft Edge | 系统浏览器 | 否 | Windows 网页适配器使用 `channel="msedge"` |
| 用户环境变量 | 凭据注入 | 否 | Token 不得落入仓库文件 |
| 网站/API | 上游数据服务 | 否 | 必须联网，受鉴权、限流、反爬和字段变化影响 |

已识别的网络上游包括 Tushare、iWencai/同花顺、Eastmoney、Legulegu、QuickTiny、Duanxianxia、DeepQ、Zhangtingke、Zhangtingjun 和 Dabanke。它们是数据来源，不是目录外文件依赖。

### 4.3 当前凭据状态和关键阻塞

- 用户级 Windows 环境中已配置 `TUSHARE_TOKEN`，审计未读取或输出其值。
- 当前 Codex 进程及由其启动的后端进程中 `TUSHARE_TOKEN` 不可见。
- 根目录和 `backend` 下没有真实 `.env` 文件；这是正确的安全状态。
- Tushare adapter 直接从进程环境读取 Token，因此当前后端若对一个没有快照的新交易日强制采集，必需来源很可能因鉴权缺失而失败。
- QuickTiny 登录态当前未配置；它是可选来源，最新发布因此降级而非失败。

这说明“用户环境里已经保存 Token”和“正在运行的后端已经获得 Token”不是一回事。必须从刷新过用户环境的新终端启动后端，或由受控启动脚本显式继承用户环境，再做新日期验收。

另外有三项实现层风险：

1. `SourceSpec.timeout` 当前主要是声明/观测元数据，SourceManager 没有统一硬取消；底层 scraper 仍必须自行执行实际超时。
2. QuickTiny 的凭据声明已进入 SourceSpec；Dabanke scraper 虽读取 `DABANKE_LOGIN_STATE`，但其 SourceSpec 尚未完整声明该凭据，管理页可观测不一致。
3. 数据源 health 主要反映最近 manifest/快照状态，不等于一次实时鉴权探测；“最近成功”不能证明当前凭据可用。

## 5. 最新发布证据

审计时最新 QuantX 日期为 `20260827`，run id 为 `20260827-eb8085c6b1fa`：

- 状态：`degraded`；
- 阶段：pending → collecting → normalized → computed → trends → structured → quality → published；
- LLM：`false`；
- error：0；warning：1；
- warning：QuickTiny 为空，0 条；
- 12 个网络来源全部 `reused_snapshot=true`，TickFlow aggregate 为当前仓库分区读取；
- 输入路径均是日期相对路径或 `kline_daily_enriched/date=2026-08-27`，没有目录外绝对路径；
- `_data_manifest.json` schema version 2，包含 58 个产物和 13 个事实产物。

20260827 的 13 类事实行数为：

| 数据集 | 行数 |
| --- | ---: |
| `trading_calendar` | 38 |
| `market_breadth_daily` | 1 |
| `market_liquidity_daily` | 1 |
| `margin_daily` | 30 |
| `limit_event_daily` | 97 |
| `limit_ladder_daily` | 76 |
| `theme_observation_daily` | 40 |
| `theme_member_daily` | 77 |
| `sector_flow_daily` | 218 |
| `sector_breadth_daily` | 166 |
| `market_state_daily` | 1 |
| `market_signal_daily` | 11 |
| `screening_candidate_daily` | 131 |

这份发布能证明：本仓库可以从本地快照和行情聚合独立重算、发布并展示。它**不能证明**：旧目录移走后曾对一个没有同日快照的新交易日完成过全量联网采集。

## 6. Market Facts 权威覆盖

### 6.1 当前注册的 13 类事实

Market Facts 已覆盖：交易日历、市场宽度、市场流动性、两融、涨跌停事件、连板梯队、题材观察、题材成员、行业资金流、行业宽度、市场状态、市场信号、规则/观察候选。

这些事实已经承担多日驾驶舱，以及单日富图表中绝大多数可复用数值。指数/K 线历史继续由 TickFlow KlineRepository 权威提供，不应在 QuantX 私有事实中重复存储。

### 6.2 历史覆盖量化

2026-08-28 重新执行只读对账脚本的结果：

- 已发布 QuantX 日期：74；
- 数据集：13；
- 应有日期/数据集分区：962；
- 有效存在：958；
- 显式缺口：4；
- 权威覆盖率：`958 / 962 = 99.58%`；
- 事实集合指纹：`e227e718ff5c8e9aec2064d5f4941f7287fa368c6553c8a32fc96cca6892012a`。

四个缺口均被显式保留，没有用相邻日或零值伪造：

| 日期 | 数据集 | 状态 |
| --- | --- | --- |
| 2026-04-27 | `sector_breadth_daily` | missing partition |
| 2026-06-25 | `theme_member_daily` | empty partition |
| 2026-06-25 | `screening_candidate_daily` | empty partition |
| 2026-07-10 | `sector_breadth_daily` | missing partition |

99.58% 是“已发布历史日期 × 已注册事实”的分区覆盖，不代表所有外部来源、所有前端字段或未来交易日都具有同等完整性。

## 7. 日期 JSON 的兼容剩余范围

### 7.1 多日面板

多日 `multiday` 已直接从 `MarketFactRepository` 计算。测试覆盖“发布后移除兼容来源，仍只用 canonical facts 重建多日数据”。因此多日的 5/10/20 日矩阵、交易日历/窗口统计、题材生命周期、行业/个股雷达和行业资金连续性已经完成主要收口。

### 7.2 单日富图表

单日接口仍先读取 `review_data.json` 作为结构和展示骨架，再由 Repository 覆盖权威字段。20260827 的 `data_foundation` 声明：

- `read_mode = canonical_facts_with_presentation_cache`；
- `source_json_read = true`（当前仍读取 `review_data.json` 兼容骨架；V2 停止读取后才能改为 false）；
- 31 组字段由 Market Facts/Kline 权威覆盖；
- 5 个字段被正式声明为 presentation cache：
  - `sections.s0.diagnosis`
  - `sections.s0.risks`
  - `sections.s1.futures`
  - `sections.s4.institution`
  - `sections.s4.dx_strength`

其中 diagnosis/risks 是确定性展示文案；futures、institution 当前前端没有实际渲染；dx_strength 仅非空时渲染，当前为空。`llm_block` 只是区块标识字符串，不是 LLM 内容，前端也不渲染。

除上述正式清单外，审计还发现以下兼容骨架字段需要明确归类：

- 七个 section 的标题；
- `emotion_zones`；
- `emotion.height_trend` 中的摘要值，尽管 canonical `height_history` 已存在；
- `emotion.daily_summary`；
- 任何 Repository 没有覆盖、但因为深拷贝 JSON 骨架而被动保留的字段。

它们大多是展示结构或摘要，不一定都值得提升为事实；但必须列入显式白名单，避免“未声明的 JSON 兜底”长期存在。

### 7.3 表格 API 的兼容差异

结构化 table Repository 目前对 13 类事实中的 5 类执行 canonical overlay：宽度、流动性、涨跌停、题材观察、行业资金流。20260827 对账没有 legacy fallback dataset，但发现：

- `flat_count`：canonical 为 207，legacy JSON 为 308；
- concentration 字段：canonical 有值，legacy 缺失；
- 涨跌停、题材、行业资金流主要字段一致。

这直接证明 JSON 不能继续被视为业务权威数据；否则同一页面/接口可能出现两份事实值。

## 8. 可观测性缺口

当前后端已有运行、来源、质量、manifest 和对账信息，但用户还不能在 QuantX 页面完成“更新—观察—定位—重试”的闭环：

- 单日页面不显示当前 run id、是否复用快照、来源 warning、事实覆盖率或 reconciliation；
- 多日 catalog 只显示日期/窗口覆盖摘要，不能下钻到 13 类事实和来源；
- run、resume、recompute、source retry API 已存在，但 QuantX UI 没有调用；
- 数据源管理页与 QuantX 发布状态分离；
- 最近 health 不区分“快照成功”和“当前凭据实时可用”；
- 没有统一的刷新批次页把主行情、QuantX 来源、事实发布、兼容产物和页面 cache 串成一条 lineage。

## 9. 渐进收口优先级

### P0：完成一次真正的新日期独立采集验收

1. 从能读取用户级环境变量的新 PowerShell 启动后端，确认只显示 `credentials_configured=true`，不得输出 Token。
2. 选择一个已经收盘且当前没有同日来源快照的交易日，运行完整主 pipeline；不要用 `--recompute` 代替联网验收。
3. 验收 Tushare、PyWencai 等必需来源不是复用快照，并记录网络采集状态、原始快照、事实分区和 manifest。
4. 验证主行情 → QuantX → multiday/catalog → Repository cache refresh 的同批次结果。
5. 在不启动任何旧 QuantX 服务、不恢复任何旧目录的条件下，用单日和多日 API/Page 验收新日期。
6. 将这一批次的 run id、输入相对路径、事实指纹、warning 和页面截图作为“真正独立更新”的发布证据。

只有完成这一项，才可以把“当前环境完全独立更新”从“条件具备”升级为“实证通过”。

### P1：消除隐式 JSON 兜底

1. 为单日响应建立“canonical、presentation-only、deprecated”三类字段清单和 schema 测试。
2. Repository 组装新响应对象，不再深拷贝整份 `review_data.json` 后被动保留未知字段。
3. 将 `emotion_zones`、height summary、daily summary 逐项决定：提升为确定性派生字段，或明确保留为 presentation cache。
4. 删除当前前端未消费的 futures/institution 兼容字段前，先扫描所有 API 消费者并提供版本迁移。
5. 扩大 table Repository 对 13 类事实的覆盖，逐步取消两套值的 reconciliation。

### P2：统一质量、覆盖和刷新可观测

新增一个 QuantX 数据状态/刷新抽屉或页面，至少展示：

- 主 pipeline job id、QuantX run id、交易日和发布时间；
- 每个来源的 required/optional、fresh/reused、记录数、凭据状态、warning/error；
- 13 类事实的分区、行数、质量等级、覆盖率和缺口；
- canonical/presentation-cache/fallback/reconciliation 状态；
- 运行、恢复、离线重算、单来源重试按钮及幂等状态；
- multiday/catalog 和前端 cache 是否已刷新。

数据源管理页负责“来源能力”，QuantX 状态页负责“某次发布结果”；两者应互相链接，不能混成同一概念。

### P3：强化来源适配器契约

- 在 SourceManager 统一实现可取消的 wall-clock timeout；
- 为 Dabanke 补齐 credentials metadata，把登录态迁入明确的 `data/user_data` 或受控配置位置；
- 区分 manifest health、credential readiness 和 live probe；
- 为来源字段漂移、空结果、陈旧快照和限流建立独立指标；
- 在 CI 中保留“业务层禁止直接 import scraper”和“禁止旧路径/旧端口”的静态契约检查。

## 10. 验证记录

本轮已实际执行：

```text
GET http://127.0.0.1:3011/                                      -> 200
GET http://127.0.0.1:3018/openapi.json                           -> 200
GET http://127.0.0.1:3018/api/quantx/review/20260827/data        -> 200
GET http://127.0.0.1:3018/api/quantx-data/multiday/20260827      -> 200

python backend/scripts/audit_quantx_data_foundation.py --data-root data
-> 74 dates, 13 datasets, 958/962 present, 4 explicit gaps

backend/.venv/Scripts/python.exe -m pytest \
  backend/tests/test_quantx_data.py \
  backend/tests/test_quantx_source_manager.py \
  backend/tests/test_quantx_browser_runtime.py \
  backend/tests/test_market_facts.py -q
-> 39 passed
```

测试覆盖了确定性发布、幂等、失败保留旧发布、离线重算、单来源重试、SourceManager 故障隔离、Edge 运行时、Market Fact registry/发布回滚、多日只读 canonical facts、单日兼容覆盖以及读取时移除来源文件。

本审计没有执行一个“无同日快照的新日期强制联网更新”，原因是当前后端进程没有继承 Tushare 凭据，而且在盘中/数据未闭合时强制发布会污染验收结论。因此该项被明确标记为未实证，而不是伪报通过。

## 11. 清理边界

旧 restore drill 已进入 Windows 回收站；旧 retired 目录中的正常源码、数据、文档和配置也已进入回收站。剩余 `D:\r26` 仅为含失效 pnpm junction 的 `frontend/node_modules` 残留，按用户要求由用户自行处理，本审计不再修改。

`D:\tickflow-quantall-backups` 和 `D:\tickflow-data-audits` 是明确保留的备份/审计资产，不属于运行时依赖。当前应用不读取它们。

## 12. 最终判断

TickFlow-Quantall 已经摆脱旧 QuantX 文件目录、旧 HTML 报告流水线和旧服务，具备自己的采集编排、原始证据、事实存储、确定性处理、API、页面和调度链。多日能力已经基本建立在统一事实底座上；单日富图表仍处于受控兼容阶段，JSON 是展示骨架而非权威事实，但隐式剩余字段还应继续收口。

当前最重要的下一步不是继续声称“已独立”，而是刷新后端凭据环境并完成一次**无同日快照、无旧目录、无旧服务**的新交易日端到端采集验收；随后把 run/source/fact/cache 的质量和血缘直接展示到 QuantX 页面。完成这两个闭环后，独立更新才既有架构依据，也有运行证据和用户可见证据。
